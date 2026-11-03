"""Band-wide AM candidate survey using the listener's uncoloured W/F rows.

No audio tuning or network I/O lives here. The transport temporarily borrows
its existing waterfall connection and restores the displayed view afterward.
"""
import math
import statistics
import struct
import time
from collections import OrderedDict
from dataclasses import dataclass

from am_carrier import rf_view_center_hz
from scan_policy import coverage_windows


@dataclass(frozen=True)
class SeekCandidate:
    frequency_khz: float
    prominence: float
    carrier_khz: float = None

    @property
    def tuning_khz(self):
        return self.frequency_khz if self.carrier_khz is None else self.carrier_khz


def am_modulation_present(rows, values, index, bin_hz, hint=False):
    """Require broad, varying sidebands on both sides of a carrier.

    This is RF evidence of AM modulation, not a speech/music classifier.
    Subtract each row's nearby floor so a changing receiver/noise level alone
    cannot masquerade as programme modulation.
    """
    inner = max(2, math.ceil(350/bin_hz))
    outer = max(inner, math.floor(2200/bin_hz))
    left = list(range(max(0, index-outer), max(0, index-inner+1)))
    right = list(range(min(1024, index+inner), min(1024, index+outer+1)))
    ref_inner, ref_outer = math.ceil(3500/bin_hz), math.ceil(6500/bin_hz)
    reference = (list(range(max(0, index-ref_outer), max(0, index-ref_inner)))
                 + list(range(min(1024, index+ref_inner), min(1024, index+ref_outer))))
    if min(len(left), len(right)) < 3 or len(reference) < 8:
        return False
    noise = sorted(values[i] for i in reference)[len(reference)//4]
    # A strong wide AM station can fill the usual noise ring with its own
    # programme. Subtracting that ring would cancel the modulation we need
    # to recognise, leaving its narrow music lobes looking more convincing.
    far_inner,far_outer = math.ceil(10000/bin_hz),math.ceil(14000/bin_hz)
    farther = (list(range(max(0,index-far_outer),max(0,index-far_inner)))
               + list(range(min(1024,index+far_inner),min(1024,index+far_outer))))
    if len(farther)>=8:
        far_noise = sorted(values[i] for i in farther)[len(farther)//4]
        if noise-far_noise>=6:
            reference,noise = farther,far_noise
    for side in (left, right):
        # A single tone or the carrier's FFT skirt does not fill a sideband.
        if sum(values[i] >= noise+(1 if hint else 3) for i in side) < math.ceil(len(side)*(.2 if hint else .4)):
            return False
    envelopes = []
    for row in rows:
        row_noise = sorted(row[i] for i in reference)[len(reference)//4]
        power = statistics.median([row[i] for i in left+right])
        envelopes.append(power-row_noise)
    envelopes.sort()
    return envelopes[-2]-envelopes[1] >= (1 if hint else 2)


def narrow_carriers(rows, values, bin_hz):
    """Narrow persistent lines, including a small saturated carrier plateau."""
    peaks = []
    for index in range(5, 1019):
        power = values[index]
        if power <= values[index-1] or power < values[index+1]:
            continue
        end = index
        while end < 1019 and values[end+1] >= power-.5:
            end += 1
        if end-index > 3:
            continue
        local = values[max(0,index-24):index-4]+values[end+5:min(1024,end+25)]
        prominence = power-statistics.median(local)
        shoulders = max(statistics.mean(values[index-4:index-2]),
                        statistics.mean(values[end+3:end+5]))
        if (prominence < 6 or power-shoulders < 5
                or power-max(values[index-2],values[end+2]) < 4):
            continue
        persistent = sum(max(row[index-1:end+2])-statistics.median(
            row[max(0,index-24):index-4]+row[end+5:min(1024,end+25)]) >= 6 for row in rows)
        if persistent < math.ceil(len(rows)*.8):
            continue
        center = (index+end)/2
        if end == index:
            left,middle,right = values[index-1:index+2]
            denominator = left-2*middle+right
            if denominator < -.01:
                center += max(-.5,min(.5,.5*(left-right)/denominator))
        peaks.append(dict(index=round((index+end)/2), center=center,
                          power=power,prominence=prominence))
    return peaks


def mirrored_sideband_image(rows, peak, owner, peaks, bin_hz):
    """A shallow mirrored line following the parent's modulation, not fading.

    Geometry, relative power, a matching mirror line and temporal correlation
    must agree. Subtracting the owner's carrier level cancels shared receiver
    gain/fading. Correlation alone must never suppress another broadcaster.
    """
    distance = abs(peak['center']-owner['center'])*bin_hz
    if (len(rows)<8 or bin_hz>250 or not 4500<=distance<=8000
            or owner['power']-peak['power']<10):
        return False
    reflected = 2*owner['center']-peak['center']
    mirror = next((p for p in peaks if abs(p['center']-reflected)<=.75
                   and abs(p['power']-peak['power'])<=6 and p['prominence']>=8),None)
    if mirror is None:
        return False
    def level(row,p):
        return max(row[max(0,p['index']-1):min(1024,p['index']+2)])
    left = [level(row,peak)-level(row,owner) for row in rows]
    right = [level(row,mirror)-level(row,owner) for row in rows]
    a,b = statistics.mean(left),statistics.mean(right)
    aa = sum((value-a)**2 for value in left)
    bb = sum((value-b)**2 for value in right)
    if min(aa,bb)<len(rows)*4 or min(max(left)-min(left),max(right)-min(right))<6:
        return False
    if sum((x-a)*(y-b) for x,y in zip(left,right))/math.sqrt(aa*bb)<.95:
        return False
    # A fading parent alone can correlate two unrelated lines after the
    # shared carrier subtraction. Require agreement with its programme
    # sideband/carrier ratio as well; that ratio removes common fading.
    inner,outer = max(2,math.ceil(350/bin_hz)),max(2,math.floor(2200/bin_hz))
    bins = list(range(max(0,owner['index']-outer),max(0,owner['index']-inner+1)))
    bins += list(range(min(1024,owner['index']+inner),min(1024,owner['index']+outer+1)))
    if len(bins)<6:
        return False
    programme = [statistics.median(row[i] for i in bins)-level(row,owner) for row in rows]
    mean = statistics.mean(programme)
    variance = sum((value-mean)**2 for value in programme)
    if variance<len(rows)*2.25:
        return False
    return (sum((x-a)*(p-mean) for x,p in zip(left,programme))/math.sqrt(aa*variance)>=.8
            and sum((y-b)*(p-mean) for y,p in zip(right,programme))/math.sqrt(bb*variance)>=.8)


def detect_stations(rows, first_hz, bin_hz, low_khz, high_khz, unresolved=None, images_out=None):
    """Confirm AM centers, not independent peaks in a strong station's wings."""
    if len(rows) < 6 or bin_hz <= 0 or any(len(row) != 1024 for row in rows):
        return []
    values = [sum(column)/len(rows) for column in zip(*rows)]
    peaks = narrow_carriers(rows,values,bin_hz)
    anchors = [p for p in peaks if am_modulation_present(rows,values,p['index'],bin_hz)]
    images = {}
    for peak in peaks:
        owners = [owner for owner in anchors
                  if (0<abs(owner['center']-peak['center'])*bin_hz<4500 and owner['power']>=peak['power']+8)
                  or mirrored_sideband_image(rows,peak,owner,peaks,bin_hz)]
        if owners:
            images[peak['center']] = max(owners,key=lambda owner:owner['power'])
    context_bins = max(5,math.ceil(6500/bin_hz))
    found = []
    for peak in anchors:
        if peak['center'] in images:
            continue
        if not context_bins <= peak['center'] < 1024-context_bins:
            continue
        # DSB modulation can have persistent narrow music lobes. A much
        # stronger confirmed carrier within one channel's sideband region
        # owns those lobes. Keep genuine 5 kHz neighbouring stations.
        if any(0 < abs(other['center']-peak['center'])*bin_hz < 4500
               and other['power'] >= peak['power']+8 for other in anchors):
            continue
        frequency = (first_hz+peak['center']*bin_hz)/1000
        uncertainty = bin_hz/2000
        if low_khz-uncertainty <= frequency <= high_khz+uncertainty:
            candidate = SeekCandidate(round(max(low_khz,min(high_khz,frequency)),3),
                                      round(peak['prominence'],1))
            found.append(candidate)
    result = []
    for candidate in sorted(found,key=lambda p:-p.prominence):
        if all(abs(candidate.frequency_khz-p.frequency_khz) >= 2 for p in result):
            result.append(candidate)
    if images_out is not None:
        images_out.extend(((first_hz+center*bin_hz)/1000,
                           (first_hz+owner['center']*bin_hz)/1000) for center,owner in images.items())
    if unresolved is not None:
        for peak in peaks:
            frequency = (first_hz+peak['center']*bin_hz)/1000
            if not low_khz <= frequency <= high_khz:
                continue
            owned = peak['center'] in images or any(abs(other['center']-peak['center'])*bin_hz < 4500
                        and (abs(other['center']-peak['center'])*bin_hz < 750
                             or other['power'] >= peak['power']+8) for other in anchors)
            # A bare carrier is not, by itself, a reason to repeat a whole RF
            # region. Keep weak bilateral AM evidence as an uncertainty hint;
            # known stations missing from a wider view are checked regardless.
            if not owned and am_modulation_present(rows,values,peak['index'],bin_hz,hint=True):
                unresolved.append(frequency)
    return sorted(result,key=lambda p:p.frequency_khz)


class SmartSeek:
    TARGET_ZOOM = 8
    MAX_ROWS = 64
    OBSERVE_SECONDS = 1.5
    WINDOW_TIMEOUT = 3.0
    RESPONSE_MARGIN = .5
    MAX_ROW_INTERVAL = .5
    CACHE_SECONDS = 300
    CACHE_LIMIT = 24

    def __init__(self, policy=None):
        self.policy = policy
        self.policy_zoom = None
        self.policy_key = None
        self.policy_context = None
        self.pass_candidates = []
        self.pass_uncertain = []
        self.pass_skipped = 0
        self.refining = False
        self.refined_last_pass = False
        self.refinement_expected = []
        self.baseline_fallback = False
        self.fallback_targets = []
        self.frequency_resolution = {}
        self.open = False
        self.active = False
        self.candidates = []
        self.context = None
        self.windows = []
        self.index = 0
        self.skipped = 0
        self.selection = None
        self.rows = []
        self.last_sequence = None
        self.geometry = None
        self.started_rows_at = None
        self.last_rows_at = None
        self.observed_seconds = 0.0
        self.published_at = 0
        self.deadline = 0
        self.bandwidth_hz = 30000000
        self.zoom = 8
        self.label = ''
        self.cache = OrderedDict()
        self.cache_key = None
        self.measured_at = None
        self.cached = False
        self.adaptive = False
        self.worker = None
        self.worker_kind = ''
        self.overview_done = False
        self.pass_count = 0
        self.reviews_this_pass = 0
        self.next_pass_at = 0
        self.identities = {}
        self.evidence = {}
        self.reviewed_at = {}
        self.review_target = None
        self.suppressed = set()
        self.playing_khz = None
        self.zoom_cap = 14
        self.window_measured = False
        self.window_retries = 0
        self.retries = 0
        self.stale = set()

    def start(self, low, high, label, context, now, cache_key=None, refresh=False, adaptive=False, policy_context=None):
        self._remember()
        cache = self.cache
        policy = self.policy
        self.__init__()
        self.policy = policy
        self.cache = cache
        self.cache_key = cache_key if cache_key is not None else (context, low, high)
        for key in list(cache):
            if now-cache[key]['measured_at'] >= self.CACHE_SECONDS:
                del cache[key]
        self.open = self.active = True
        self.adaptive = adaptive
        self.low, self.high, self.label = float(low), float(high), label
        self.context = context
        self.policy_context = context if policy_context is None else policy_context
        if refresh:
            cache.pop(self.cache_key, None)
        elif self.cache_key in cache:
            saved = cache[self.cache_key]
            self.candidates = list(saved['candidates'])
            self.selection = saved['selection']
            self.windows = list(saved['windows'])
            self.index, self.skipped = saved['index'], saved['skipped']
            self.measured_at = saved['measured_at']
            self.bandwidth_hz, self.zoom = saved['bandwidth_hz'], saved['zoom']
            self.active = False
            self.cached = True
            cache.move_to_end(self.cache_key)
            return
        self.configure(30000000, 14, now)

    def _remember(self):
        # A close, tuning gesture or reopen never extends measurement age.
        # Partial results are useful too; a transport timeout with no measured
        # rows must not cache an empty failure as a completed survey.
        if self.cache_key is None or self.measured_at is None:
            return
        self.cache[self.cache_key] = dict(
            candidates=tuple(c for c in self.candidates if c.frequency_khz not in self.suppressed), selection=self.selection,
            windows=tuple(self.windows), index=self.index, skipped=self.skipped,
            measured_at=self.measured_at, bandwidth_hz=self.bandwidth_hz, zoom=self.zoom)
        self.cache.move_to_end(self.cache_key)
        while len(self.cache) > self.CACHE_LIMIT:
            self.cache.popitem(last=False)

    def configure(self, bandwidth_hz, zoom_cap, now):
        self.zoom_cap = zoom_cap
        if self.policy is not None:
            key = (self.policy_context,self.low,self.high,bandwidth_hz,int(zoom_cap))
            if key != self.policy_key:
                self.policy_zoom = None
                self.policy_key = key
            if self.policy_zoom is None:
                self.policy_zoom = self.policy.plan(key,bandwidth_hz,zoom_cap,self.low,self.high)
            zoom = self.policy_zoom
        else:
            zoom = min(self.TARGET_ZOOM, int(zoom_cap))
        if self.windows and self.bandwidth_hz == bandwidth_hz and self.zoom == zoom and not self.refined_last_pass:
            return
        self.refining = False
        self.refined_last_pass = False
        self.refinement_expected = []
        self.baseline_fallback = False
        self.fallback_targets = []
        changed_receiver_geometry = self.bandwidth_hz != bandwidth_hz
        self.pass_candidates = []
        self.pass_uncertain = []
        self.pass_skipped = self.skipped
        self.bandwidth_hz, self.zoom = bandwidth_hz, zoom
        span = bandwidth_hz / (2**zoom * 1000)
        # Include RF context outside the band for sideband/noise checks, but
        # publish carriers only inside its exact broadcast boundaries.
        low, high = max(0, self.low-8), min(bandwidth_hz/1000, self.high+8)
        if high <= low or span < 20:
            self.close()
            return
        # Overlap avoids losing carriers at the five-bin detection margins.
        previous_center = self.windows[-1] if self.windows else None
        self.windows = coverage_windows(bandwidth_hz,zoom,self.low,self.high)
        if self.policy is not None:
            self.windows = self.policy.order_windows(self.policy_key,self.windows,span,previous_center)
        self.index = 0
        if changed_receiver_geometry:
            self.candidates = []
        self._reset_window(now)

    def _reset_window(self, now):
        self.window_measured = False
        self.window_retries = 0
        self.rows = []
        self.geometry = None
        self.started_rows_at = None
        self.last_rows_at = None
        self.observed_seconds = 0.0
        self.published_at = 0
        self.deadline = now + self.response_budget()

    def response_budget(self):
        return max(self.WINDOW_TIMEOUT,self.dwell_seconds()+1.5)+self.RESPONSE_MARGIN

    def dwell_seconds(self):
        return (2 if self.pass_count == 0 else 3) if self.adaptive else self.OBSERVE_SECONDS

    def close(self):
        self._remember()
        self.open = self.active = False
        self.rows = []
        if self.worker:
            self.worker.close()
        self.worker = None

    def poll(self, context, now):
        if self.open and context != self.context:
            self.close()
        if self.worker:
            self.worker.context = self.context
            self.worker.poll(context,now)
            if not self.worker.active:
                self._finish_worker(now)
        elif self.active and now >= self.deadline:
            if self.policy is not None and self.window_retries<1:
                retry = self.window_retries+1
                self._reset_window(now)
                self.window_retries = retry
                self.retries += 1
            else:
                self.skipped += 1
                self._advance(now)

    def _advance(self, now):
        self.index += 1
        if self.baseline_fallback and all(any(abs(freq-c.tuning_khz)<.75 for c in self.pass_candidates)
                                          for freq in self.fallback_targets):
            # Wider coverage is already complete. Extra reference contexts
            # can stop once every specific uncertainty is positively resolved.
            self.index = len(self.windows)
        if self.index >= len(self.windows):
            if self.policy is not None:
                complete = self.skipped==self.pass_skipped and self.window_measured
                uncertain = tuple(freq for freq in self.pass_uncertain
                                  if not any(abs(freq-c.tuning_khz)<.75 for c in self.pass_candidates))
                if self.refining:
                    missing = [freq for freq in self.refinement_expected
                               if not any(abs(freq-c.tuning_khz)<.75 for c in self.pass_candidates)]
                    if complete and self.zoom>min(8,int(self.zoom_cap)) and missing:
                        zoom = min(8,int(self.zoom_cap))
                        span = self.bandwidth_hz/(2**zoom*1000)
                        grid = coverage_windows(self.bandwidth_hz,zoom,self.low,self.high)
                        windows = [center for center in grid
                                   if any(abs(center-freq)<=span/2-8+1e-8 for freq in missing)]
                        previous_center = self.windows[-1]
                        self.windows = sorted(windows or grid,key=lambda center:abs(center-previous_center))
                        self.index,self.zoom,self.policy_zoom = 0,zoom,zoom
                        self.baseline_fallback,self.fallback_targets = True,missing
                        self._reset_window(now)
                        return
                    self.policy.finish_refinement(self.policy_key,self.pass_candidates,complete,uncertain,now=now)
                    self.refining = False
                    self.refined_last_pass = True
                    retry = False
                else:
                    retry = self.policy.finish(self.policy_key,self.zoom,self.zoom_cap,
                                              self.pass_candidates,complete,uncertain,now=now)
                self.policy_zoom = None
                if retry:
                    windows,refinement_zoom = self.policy.refinement_plan(self.policy_key,self.pass_candidates,
                        self.pass_uncertain,self.bandwidth_hz,self.zoom_cap)
                    if windows:
                        self.refinement_expected = self.policy.refinement_targets(self.policy_key,
                            self.pass_candidates,self.pass_uncertain)
                        self.refining = True
                        self.policy_zoom = self.zoom = refinement_zoom
                        self.windows,self.index = windows,0
                        self.pass_uncertain = []
                        self._reset_window(now)
                    else:
                        # An unrecognised reference cannot justify a targeted
                        # absence claim; retain a complete narrow fallback.
                        self.configure(self.bandwidth_hz,self.zoom_cap,now)
                    return
            self.active = False
            self.rows = []
            self.next_pass_at = now if self.adaptive else now+2
        else:
            self._reset_window(now)

    def request(self, context, now, bandwidth_hz=30000000, zoom_cap=14):
        self.poll(context, now)
        self.zoom_cap = zoom_cap
        if self.adaptive and self.open:
            if not self.overview_done and self.worker is None:
                self.configure(bandwidth_hz,zoom_cap,now)
                self._start_overview(now)
            if self.worker:
                return self.worker.request(context,now,bandwidth_hz,zoom_cap)
            if not self.active:
                self._start_review(now)
                if self.worker:
                    return self.worker.request(context,now,bandwidth_hz,zoom_cap)
                if now >= self.next_pass_at:
                    self.pass_count += 1
                    self.reviews_this_pass = 0
                    self.pass_candidates = []
                    self.pass_uncertain = []
                    self.pass_skipped = self.skipped
                    self.index = 0
                    self.active = True
                    self._reset_window(now)
        if not self.active:
            return None
        self.configure(bandwidth_hz, zoom_cap, now)
        return (self.windows[self.index], self.zoom) if self.active else None

    def feed(self, message, bandwidth_hz, zoom_max, zoom_cap, now):
        if self.worker:
            self.worker.zoom_max = zoom_max
            self.worker.feed(message,bandwidth_hz,zoom_max,zoom_cap,now)
            if not self.worker.active:
                self._finish_worker(now)
            return
        if not self.active or len(message) != 1040 or message[:3] != b'W/F':
            return
        start, zoom_flags, sequence = struct.unpack_from('<III', message, 4)
        zoom, flags = zoom_flags & 0xffff, zoom_flags >> 16
        if flags & 3 or zoom != min(self.zoom, zoom_cap, zoom_max):
            return
        if self.last_sequence is not None and not 0 < ((sequence-self.last_sequence) & 0xffffffff) < 0x80000000:
            return
        first_hz = start * bandwidth_hz / (1024 * 2**zoom_max)
        bin_hz = bandwidth_hz / (1024 * 2**zoom)
        expected = rf_view_center_hz(self.windows[self.index]*1000, bandwidth_hz, zoom)
        if abs(first_hz + 512*bin_hz - expected) > max(3, 2*bin_hz):
            return
        if (start, zoom) != self.geometry:
            self.rows = []
            self.geometry = start, zoom
            self.started_rows_at = now
            self.last_rows_at = None
            self.observed_seconds = 0.0
            # Start a full observation budget only after the requested view arrives.
            self.deadline = now+self.response_budget()
        if self.last_rows_at is not None:
            self.observed_seconds += max(0,min(self.MAX_ROW_INTERVAL,now-self.last_rows_at))
        self.last_rows_at = now
        self.deadline = max(self.deadline,now+max(0,self.dwell_seconds()-self.observed_seconds)+self.RESPONSE_MARGIN)
        self.last_sequence = sequence
        self.rows.append(message[16:])
        self.rows = self.rows[-self.MAX_ROWS:]
        observed = self.observed_seconds
        if len(self.rows) >= 8 and observed >= .6 and now-self.published_at >= .3:
            self._merge(self._detect_capture(first_hz,bin_hz))
            self.measured_at = now
            self.published_at = now
        if len(self.rows) >= 6 and observed >= self.dwell_seconds():
            self._merge(self._detect_capture(first_hz,bin_hz,final=True),accumulate=True)
            self.measured_at = now
            self.window_measured = True
            self._advance(now)

    detect = staticmethod(detect_stations)

    def _detect_capture(self,first_hz,bin_hz,final=False):
        images = []
        options = {'images_out':images} if self.detect is detect_stations else {}
        if final and self.policy is not None:
            options['unresolved'] = self.pass_uncertain
        found = self.detect(self.rows,first_hz,bin_hz,self.low,self.high,**options)
        for ghost,carrier in images:
            self.pass_candidates = [c for c in self.pass_candidates
                                    if abs(c.tuning_khz-ghost)>=.75 or abs(c.tuning_khz-carrier)<.75]
            for index,old in enumerate(self.candidates):
                if (abs(old.tuning_khz-ghost)>=.75 or abs(old.tuning_khz-carrier)<.75
                        or old.frequency_khz in self.suppressed):
                    continue
                if self.playing_khz is not None and abs(old.tuning_khz-self.playing_khz)<.5:
                    # Keep the playing row and offer its existing Tap to Center
                    # action. Signal evidence must never retune listening.
                    self.candidates[index] = SeekCandidate(old.frequency_khz,old.prominence,carrier)
                    self.evidence.setdefault(old.frequency_khz,dict(hits=0,failures=0))['status'] = 'AM signal'
                    self.suppressed.update(c.frequency_khz for c in self.candidates
                        if c.frequency_khz!=old.frequency_khz and abs(c.tuning_khz-carrier)<2)
                else:
                    self.suppressed.add(old.frequency_khz)
        return found

    def _merge(self, candidates, accumulate=False, bin_hz=None):
        bin_hz = self.bandwidth_hz/(1024*2**self.zoom) if bin_hz is None else bin_hz
        if self.policy is not None:
            for candidate in candidates:
                previous = next((i for i,old in enumerate(self.pass_candidates)
                                 if abs(candidate.tuning_khz-old.tuning_khz)<2),None)
                if previous is None:
                    self.pass_candidates.append(candidate)
                elif self.refining and accumulate:
                    self.pass_candidates[previous] = candidate
        if self.adaptive:
            candidates = sorted(candidates,key=lambda candidate:-candidate.prominence)
        for candidate in candidates:
            duplicate = next((i for i, old in enumerate(self.candidates)
                              if old.frequency_khz not in self.suppressed
                              and abs(old.tuning_khz-candidate.tuning_khz) < 2), None)
            if duplicate is None and accumulate:
                # Suppression is evidence about an earlier observation, not
                # a permanent ban on a channel where a real station may start.
                duplicate = next((i for i,old in enumerate(self.candidates)
                    if old.frequency_khz in self.suppressed
                    and abs(old.frequency_khz-candidate.tuning_khz)<.75),None)
                if duplicate is not None:
                    old = self.candidates[duplicate]
                    self.candidates[duplicate] = SeekCandidate(old.frequency_khz,old.prominence,candidate.tuning_khz)
                    self.frequency_resolution[old.frequency_khz] = bin_hz
            if duplicate is None:
                if any(old.frequency_khz in self.suppressed and
                       abs(old.frequency_khz-candidate.frequency_khz)<.1 for old in self.candidates):
                    continue
                # Keep stable candidate keys; snapshots order the list by frequency.
                self.candidates.append(candidate)
                self.frequency_resolution[candidate.frequency_khz] = bin_hz
            elif accumulate or (not self.adaptive and candidate.prominence > self.candidates[duplicate].prominence):
                old = self.candidates[duplicate]
                strength = old.prominence*.65+candidate.prominence*.35 if accumulate else candidate.prominence
                resolution = self.frequency_resolution.get(old.frequency_khz,bin_hz)
                tuned = old.carrier_khz
                if bin_hz<resolution*.9:
                    tuned = candidate.tuning_khz
                    self.frequency_resolution[old.frequency_khz] = bin_hz
                elif accumulate and bin_hz<=resolution*1.1 and abs(candidate.tuning_khz-old.tuning_khz)*1000<2*bin_hz:
                    tuned = round(.65*old.tuning_khz+.35*candidate.tuning_khz,4)
                self.candidates[duplicate] = SeekCandidate(old.frequency_khz,round(strength,1),tuned)
            key = candidate.frequency_khz if duplicate is None else self.candidates[duplicate].frequency_khz
            if accumulate:
                evidence = self.evidence.setdefault(key,dict(hits=0,status='Checking',failures=0))
                evidence['hits'] += 1
                if not evidence['failures']:
                    evidence['status'] = 'AM signal' if evidence['hits'] >= 2 else 'Checking'
                self.suppressed.discard(key)
                self.stale.discard(key)

    def note_identity(self, frequency, known, nominal=()):
        self.identities[frequency] = (bool(known),tuple(nominal))

    def _start_overview(self, now):
        span = (self.high-self.low+16)*1000
        zoom = max(0,min(7,self.zoom_cap,math.floor(math.log2(self.bandwidth_hz/span))))
        self.worker = BandOverview()
        self.worker.TARGET_ZOOM = zoom
        self.worker.start(self.low,self.high,self.label,self.context,now,refresh=True)
        self.worker.configure(self.bandwidth_hz,self.zoom_cap,now)
        self.worker_kind = 'overview'
        self.active = True

    def _start_review(self, now):
        if self.reviews_this_pass >= 2:
            return
        choices = []
        for candidate in self.candidates:
            key = candidate.frequency_khz
            if key in self.suppressed or now-self.reviewed_at.get(key,-1000) < 30:
                continue
            identity = self.identities.get(key)
            mismatch = identity and any(abs(n-candidate.tuning_khz) > .35 for n in identity[1])
            if identity and (not identity[0] or mismatch):
                choices.append(candidate)
        if not choices:
            return
        target = max(choices,key=lambda c:c.prominence)
        self.review_target = target.frequency_khz
        center = target.tuning_khz
        self.worker = CarrierReview()
        self.worker.start(max(self.low,center-6),min(self.high,center+6),
                          self.label,self.context,now,refresh=True)
        self.worker.configure(self.bandwidth_hz,self.zoom_cap,now)
        self.worker_kind = 'review'
        self.reviews_this_pass += 1
        self.reviewed_at[target.frequency_khz] = now
        self.active = True

    def _finish_worker(self, now):
        worker,kind = self.worker,self.worker_kind
        self.worker,self.worker_kind = None,''
        self.skipped += worker.skipped
        if kind == 'overview':
            self.overview_done = True
            span = self.bandwidth_hz/(2**self.zoom*1000)
            self.windows.sort(key=lambda center:max((p.prominence for p in worker.candidates
                if abs(p.frequency_khz-center)<span/2),default=0),reverse=True)
            self.index = 0
            self.active = True
            self._reset_window(now)
            return
        self.active = False
        if not worker.window_measured:
            return
        target = next((c for c in self.candidates if c.frequency_khz==self.review_target),None)
        if target is None:
            return
        worker_candidates = worker.snapshot()['candidates']
        nearby = [c for c in worker_candidates if abs(c.tuning_khz-target.tuning_khz)<.75
                  or (abs(c.tuning_khz-target.tuning_khz)<4.5 and c.prominence>=target.prominence+8)]
        evidence = self.evidence.setdefault(target.frequency_khz,dict(hits=0,status='Checking',failures=0))
        if nearby:
            carrier = max(nearby,key=lambda c:c.prominence)
            index = self.candidates.index(target)
            self.candidates[index] = SeekCandidate(target.frequency_khz,
                round(.65*target.prominence+.35*carrier.prominence,1),carrier.tuning_khz)
            evidence.update(status='AM signal',failures=0,hits=evidence['hits']+1)
            self.identities.pop(target.frequency_khz,None)
            # Keep the corrected row in place, suppressing another row for
            # that same carrier. Never retune the listening VFO in the worker.
            for other in self.candidates:
                if other.frequency_khz!=target.frequency_khz and abs(other.tuning_khz-carrier.tuning_khz)<2:
                    if self.playing_khz is not None and abs(other.tuning_khz-self.playing_khz)<.5:
                        self.suppressed.add(target.frequency_khz)
                    else:
                        self.suppressed.add(other.frequency_khz)
        else:
            evidence['failures'] += 1
            evidence['status'] = 'Carrier only' if worker.stable_line(target.tuning_khz) else 'Unconfirmed'
        self._merge(worker_candidates,accumulate=True,bin_hz=worker.bandwidth_hz/(1024*2**worker.zoom))

    def snapshot(self, now=None):
        visible = tuple(sorted((item for item in self.candidates
                                if item.frequency_khz not in self.suppressed),
                               key=lambda item:(item.tuning_khz,item.frequency_khz)))
        if visible and self.selection not in [item.frequency_khz for item in visible]:
            self.selection = visible[0].frequency_khz
        elif not visible:
            self.selection = None
        measured = self.worker if self.worker else self
        return dict(open=self.open, active=self.active, candidates=visible,
                    selected=self.selection, label=self.label,
                    completed=min(measured.index,len(measured.windows)), total=len(measured.windows),
                    skipped=self.skipped, cached=self.cached,
                    window_progress=(min(.95,measured.observed_seconds/measured.dwell_seconds())
                                     if measured.active and measured.started_rows_at is not None else 0),
                    scanning_khz=(measured.windows[measured.index] if measured.active and measured.windows else None),
                    phase=('overview' if self.worker_kind == 'overview' else 'review' if self.worker else 'survey'),
                    continuous=self.adaptive,
                    stale=tuple(self.stale),
                    signal_status={key:value['status'] for key,value in self.evidence.items()},
                    age_seconds=(max(0, (time.monotonic() if now is None else now)-self.measured_at)
                                 if self.measured_at is not None else 0))

    def move(self, delta):
        snapshot = self.snapshot()
        candidates = snapshot['candidates']
        if not candidates:
            return
        index = next(i for i, item in enumerate(candidates) if item.frequency_khz == self.selection)
        index = max(0, min(len(candidates)-1, index+int(delta)))
        self.selection = candidates[index].frequency_khz


class BandOverview(SmartSeek):
    OBSERVE_SECONDS = 2

    @staticmethod
    def detect(rows,first_hz,bin_hz,low,high):
        values = [statistics.mean(column) for column in zip(*rows)]
        return [SeekCandidate(round((first_hz+p['center']*bin_hz)/1000,3),p['prominence'])
                for p in narrow_carriers(rows,values,bin_hz)
                if low <= (first_hz+p['center']*bin_hz)/1000 <= high]


class CarrierReview(SmartSeek):
    TARGET_ZOOM = 10
    OBSERVE_SECONDS = 5
    WINDOW_TIMEOUT = 8
    MAX_ROWS = 128

    def __init__(self):
        super().__init__()
        self.final_rows = ()
        self.zoom_max = 14

    def _advance(self, now):
        self.final_rows = tuple(self.rows)
        super()._advance(now)

    def stable_line(self, frequency):
        if len(self.final_rows)<8 or self.geometry is None:
            return False
        values = [statistics.mean(column) for column in zip(*self.final_rows)]
        first = self.geometry[0]*self.bandwidth_hz/(1024*2**self.zoom_max)
        bin_hz = self.bandwidth_hz/(1024*2**self.zoom)
        return any(abs((first+p['center']*bin_hz)/1000-frequency)<.6
                   for p in narrow_carriers(self.final_rows,values,bin_hz))
