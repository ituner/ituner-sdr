"""Share one waterfall between the visible band and an activity-led catalogue."""
import math
import statistics
import time

from smart_seek import SmartSeek


class SpectrumSurvey(SmartSeek):
    """Broad activity is only a scheduling hint, never a station count."""
    TARGET_ZOOM = 1
    OBSERVE_SECONDS = 2

    def __init__(self):
        super().__init__()
        self.bands = ()
        self.scores = {}

    def configure(self, bandwidth_hz, zoom_cap, now):
        zoom = min(1,int(zoom_cap))
        if self.windows and self.bandwidth_hz == bandwidth_hz and self.zoom == zoom:
            return
        self.bandwidth_hz,self.zoom = bandwidth_hz,zoom
        span = bandwidth_hz/(2**zoom*1000)
        self.windows = [span*(i+.5) for i in range(2**zoom)]
        self.index = 0
        self.scores = {}
        self._reset_window(now)

    def detect(self, rows, first_hz, bin_hz, low, high):
        values = [statistics.mean(column) for column in zip(*rows)]
        for low,high,label in self.bands:
            first = max(0,math.ceil((low*1000-first_hz)/bin_hz))
            last = min(1024,math.floor((high*1000-first_hz)/bin_hz)+1)
            if last <= first:
                continue
            radius = max(4,math.ceil(250000/bin_hz))
            context = sorted(values[max(0,first-radius):min(1024,last+radius)])
            floor = context[len(context)//4]
            score = max(values[first:last])-floor
            self.scores[label] = max(self.scores.get(label,0),score)
        return []


class SmartSeekCatalogue:
    """Keep band lists in this open menu; qualify each again on selection.

    A turn is one complete RF observation. Two foreground turns alternate
    with one background turn, so a wide quiet band cannot monopolize capture.
    The receiver still sees only a single waterfall request at any instant.
    """
    COUNT_CACHE_SECONDS = 3600

    def __init__(self, bands):
        self._bands = tuple(bands)
        self._engine = SmartSeek()
        self._models = {}
        self._current = None
        self._current_label = None
        self._token = None
        self._paused = {}
        self._queue = []
        self._scores = {}
        self._survey = None
        self._survey_at = None
        self._initial_done = False
        self._foreground_turns = 0
        self._count_cache = {}
        self._count_receiver = None
        self._count_completed = {}
        self._count_skips = {}
        self._capture_paused = False

    def __getattr__(self, name):
        return getattr(self._engine,name)

    def __setattr__(self, name, value):
        if name.startswith('_'):
            object.__setattr__(self,name,value)
        elif name in ('context','playing_khz','sensitivity'):
            for engine in self._models.values():
                setattr(engine,name,value)
            setattr(self._engine,name,value)
            if self._survey is not None:
                setattr(self._survey,name,value)
        else:
            setattr(self._engine,name,value)

    def start(self, low, high, label, context, now, cache_key=None, refresh=False, adaptive=True):
        self._remember_counts(now)
        source = cache_key if cache_key is not None else context
        receiver = source[0] if isinstance(source,(tuple,list)) and source else source
        continuing = self.open and self.context == context
        if not continuing:
            sensitivity = self.sensitivity
            counts = self._count_cache
            self.close()
            bands = self._bands
            self.__init__(bands)
            self._engine.sensitivity = sensitivity
            self._count_cache = counts
        self._count_receiver = receiver
        self._expire_counts(now)
        self._suspend(now)
        old_label = self.label
        previous = self._models.get(label)
        candidates = ([c for c in previous.candidates if c.frequency_khz not in previous.suppressed]
                      if continuing and previous and not refresh else [])
        selection = previous.selection if previous else None
        engine = SmartSeek()
        engine.sensitivity = self.sensitivity
        engine.start(low,high,label,context,now,cache_key=cache_key,refresh=True,adaptive=True)
        engine.candidates = candidates
        engine.selection = selection
        engine.stale = {candidate.frequency_khz for candidate in candidates}
        self._models[label] = engine
        self._count_completed.pop(label,None)
        self._count_skips.pop(label,None)
        self._engine = engine
        self._paused.pop(label,None)
        self._initial_done = False
        self._foreground_turns = 0
        self._queue = [entry for entry in self._queue if entry != label]
        if continuing and old_label != label and old_label not in self._queue:
            self._queue.append(old_label)

    def close(self):
        for engine in self._models.values():
            engine.close()
        self._engine.close()
        if self._survey:
            self._survey.close()
        self._current = None
        self._token = None
        self._capture_paused = False

    def set_capture_paused(self, paused, now):
        """Lend the W/F stream to the listener without expiring scan budgets."""
        paused = bool(paused)
        if paused and not self._capture_paused:
            self._suspend(now)
            for label in self._models:
                self._paused.setdefault(label, now)
            if self._survey is not None:
                self._paused.setdefault('spectrum', now)
        self._capture_paused = paused

    @staticmethod
    def _position(engine):
        worker = engine.worker
        return (id(worker) if worker else None,worker.index if worker else engine.index,
                engine.pass_count)

    def _suspend(self, now):
        if self._current is not None:
            self._paused[self._current_label] = now
        self._current = None
        self._token = None

    def _activate(self, engine, label, now):
        paused = self._paused.pop(label,None)
        if paused is not None:
            for capture in (engine,engine.worker):
                if capture is not None:
                    capture.deadline += max(0,now-paused)
                    if capture.started_rows_at is not None:
                        capture.started_rows_at += max(0,now-paused)
        self._current,self._current_label = engine,label

    def poll(self, context, now):
        if not self.open:
            return
        if context != self.context:
            self.close()
            return
        if self._capture_paused:
            return
        if self._current:
            self._current.poll(context,now)
            self._finish_turn(now)

    def _finish_turn(self, now):
        engine = self._current
        if engine is None or self._token == self._position(engine):
            return
        label = self._current_label
        if engine is self._survey:
            if not engine.active:
                self._scores = dict(engine.scores)
                self._survey_at = now
                self._rank_bands()
                self._foreground_turns = 0
        elif engine is self._engine:
            self._foreground_turns += 1
            if not engine.active and engine.index >= len(engine.windows):
                self._initial_done = True
        else:
            self._foreground_turns = 0
            if not engine.active and engine.index >= len(engine.windows):
                self._queue = [entry for entry in self._queue if entry != label]
        if engine is not self._survey:
            complete = not engine.active and engine.index >= len(engine.windows)
            self._remember_count(label,engine,now,complete=complete)
        self._suspend(now)

    def _expire_counts(self, now):
        for key,record in list(self._count_cache.items()):
            if not 0 <= now-record['measured_at'] < self.COUNT_CACHE_SECONDS:
                del self._count_cache[key]

    def _remember_count(self, label, engine, now, complete=False):
        stamp = engine.measured_at
        if stamp is None or not 0 <= now-stamp < self.COUNT_CACHE_SECONDS:
            return
        key = self._count_receiver,engine.low,engine.high
        candidates = tuple(c for c in engine.candidates
                           if c.frequency_khz not in engine.stale
                           and c.frequency_khz not in engine.suppressed)
        if complete:
            # Reviews after a pass must not rewrite its result or extend age.
            completed = id(engine),engine.pass_count
            if self._count_completed.get(label) == completed:
                return
            previous_skips = self._count_skips.get(label,0)
            self._count_completed[label] = completed
            self._count_skips[label] = engine.skipped
            if engine.skipped != previous_skips:
                return
        else:
            previous = self._count_cache.get(key)
            # Keep the last count while a fresh pass is incomplete. Real
            # new finds may raise it; only a complete pass can lower to zero.
            if not candidates or (previous is not None
                                  and len(candidates) <= len(previous['candidates'])):
                return
        self._count_cache[key] = dict(measured_at=stamp,candidates=candidates)

    def _remember_counts(self, now):
        self._expire_counts(now)
        for label,engine in self._models.items():
            self._remember_count(label,engine,now)

    def _available(self, bandwidth_hz):
        return tuple(b for b in self._bands if b[0] < bandwidth_hz/1000)

    def _rank_bands(self):
        available = self._available(self._engine.bandwidth_hz)
        labels = [band[2] for band in available]
        origin = labels.index(self.label)
        def priority(label):
            distance = abs(labels.index(label)-origin)
            score = self._scores.get(label,0)
            return score < 6,-score/(1+.2*distance),distance
        self._queue = sorted((label for label in labels if label != self.label),key=priority)

    def _choose(self, context, now, bandwidth_hz, zoom_cap):
        if not self._initial_done:
            return self._engine,self.label
        if self._survey is not None and self._survey.active:
            return self._survey,'spectrum'
        if self._survey_at is None or (not self._queue and now-self._survey_at >= 120):
            survey = SpectrumSurvey()
            survey.start(0,bandwidth_hz/1000,'Spectrum',context,now,refresh=True)
            survey.configure(bandwidth_hz,zoom_cap,now)
            survey.bands = self._available(bandwidth_hz)
            self._survey = survey
            return survey,'spectrum'
        if self._foreground_turns < 2 or not self._queue:
            return self._engine,self.label
        label = self._queue[0]
        engine = self._models.get(label)
        if engine is None:
            low,high,_ = next(band for band in self._bands if band[2] == label)
            engine = SmartSeek()
            engine.sensitivity = self.sensitivity
            engine.start(low,high,label,context,now,refresh=True,adaptive=True)
            engine.configure(bandwidth_hz,zoom_cap,now)
            self._models[label] = engine
        elif not engine.active and engine.index >= len(engine.windows):
            engine.stale = {candidate.frequency_khz for candidate in engine.candidates}
        return engine,label

    def request(self, context, now, bandwidth_hz=30000000, zoom_cap=14):
        self.poll(context,now)
        if not self.open or self._capture_paused:
            return None
        if self._current is None:
            engine,label = self._choose(context,now,bandwidth_hz,zoom_cap)
            self._activate(engine,label,now)
        request = self._current.request(context,now,bandwidth_hz,zoom_cap)
        self._token = self._position(self._current)
        return request

    def feed(self, message, bandwidth_hz, zoom_max, zoom_cap, now):
        if self._current is not None:
            self._current.feed(message,bandwidth_hz,zoom_max,zoom_cap,now)
            self._finish_turn(now)

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        self._remember_counts(now)
        result = self._engine.snapshot(now)
        current = self._current
        if current is not None:
            progress = current.snapshot(now)
            for key in ('completed','total','window_progress','scanning_khz','phase'):
                result[key] = progress[key]
            if current is self._survey:
                result['phase'] = 'spectrum'
            elif current is not self._engine:
                result['phase'] = 'background'
        result['scanning_band'] = self._current_label
        counts = {}
        for low,high,label in self._available(self._engine.bandwidth_hz):
            record = self._count_cache.get((self._count_receiver,float(low),float(high)))
            threshold = 24-.18*self.sensitivity
            counts[label] = (None if record is None else
                             sum(candidate.prominence >= threshold for candidate in record['candidates']))
        result['band_counts'] = counts
        result['active'] = self.open
        return result
