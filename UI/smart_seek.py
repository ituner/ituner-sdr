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


@dataclass(frozen=True)
class SeekCandidate:
    frequency_khz: float
    prominence: float


def am_modulation_present(rows, values, index, bin_hz):
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
    for side in (left, right):
        # A single tone or the carrier's FFT skirt does not fill a sideband.
        if sum(values[i] >= noise+3 for i in side) < math.ceil(len(side)*.4):
            return False
    envelopes = []
    for row in rows:
        row_noise = sorted(row[i] for i in reference)[len(reference)//4]
        power = statistics.median([row[i] for i in left+right])
        envelopes.append(power-row_noise)
    envelopes.sort()
    return envelopes[-2]-envelopes[1] >= 2


def detect_stations(rows, first_hz, bin_hz, low_khz, high_khz):
    """Find persistent narrow carriers, including multiple equally strong ones.

    Prominence is in native waterfall level units above the local noise floor,
    deliberately not presented as a calibrated RF meter or an audio SNR.
    """
    if len(rows) < 6 or bin_hz <= 0 or any(len(row) != 1024 for row in rows):
        return []
    values = [sum(column)/len(rows) for column in zip(*rows)]
    peaks = []
    for index in range(5, 1019):
        power = values[index]
        if power >= 253 or power <= values[index-1] or power < values[index+1]:
            continue
        local = values[max(0, index-24):index-4] + values[index+5:min(1024, index+25)]
        floor = statistics.median(local)
        prominence = power - floor
        if prominence < 6:
            continue
        shoulders = max(statistics.mean(values[index-4:index-2]),
                        statistics.mean(values[index+3:index+5]))
        if power - shoulders < 5 or power - max(values[index-2], values[index+2]) < 4:
            continue
        persistent = 0
        for row in rows:
            neighbourhood = row[max(0, index-24):index-4] + row[index+5:min(1024, index+25)]
            if max(row[index-1:index+2]) - statistics.median(neighbourhood) >= 6:
                persistent += 1
        if persistent < math.ceil(len(rows) * .8):
            continue
        if not am_modulation_present(rows, values, index, bin_hz):
            continue
        left, middle, right = values[index-1:index+2]
        denominator = left - 2*middle + right
        offset = .5*(left-right)/denominator if denominator < -.01 else 0
        frequency = (first_hz + (index + max(-.5, min(.5, offset))) * bin_hz) / 1000
        # A carrier at a band edge may interpolate slightly across it. Bound
        # that half-bin uncertainty to the edge; never publish out-of-band
        # frequencies or accept a peak a full bin beyond the allocation.
        uncertainty = bin_hz/2000
        if low_khz-uncertainty <= frequency <= high_khz+uncertainty:
            frequency = max(low_khz, min(high_khz, frequency))
            peaks.append(SeekCandidate(round(frequency, 3), round(prominence, 1)))
    # A single carrier can occupy neighbouring bins. Keep separate 5 kHz
    # broadcast channels, but never publish its shoulders as extra stations.
    result = []
    for candidate in sorted(peaks, key=lambda item: -item.prominence):
        if all(abs(candidate.frequency_khz-item.frequency_khz) >= 2 for item in result):
            result.append(candidate)
    return sorted(result, key=lambda item: item.frequency_khz)


class SmartSeek:
    OBSERVE_SECONDS = 1.5
    WINDOW_TIMEOUT = 3.0
    CACHE_SECONDS = 300
    CACHE_LIMIT = 24

    def __init__(self):
        self.open = False
        self.active = False
        self.sensitivity = 65
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
        self.published_at = 0
        self.deadline = 0
        self.bandwidth_hz = 30000000
        self.zoom = 8
        self.label = ''
        self.cache = OrderedDict()
        self.cache_key = None
        self.measured_at = None
        self.cached = False

    def start(self, low, high, label, context, now, cache_key=None, refresh=False):
        self._remember()
        sensitivity, cache = self.sensitivity, self.cache
        self.__init__()
        self.sensitivity, self.cache = sensitivity, cache
        self.cache_key = cache_key if cache_key is not None else (context, low, high)
        for key in list(cache):
            if now-cache[key]['measured_at'] >= self.CACHE_SECONDS:
                del cache[key]
        self.open = self.active = True
        self.low, self.high, self.label = float(low), float(high), label
        self.context = context
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
            candidates=tuple(self.candidates), selection=self.selection,
            windows=tuple(self.windows), index=self.index, skipped=self.skipped,
            measured_at=self.measured_at, bandwidth_hz=self.bandwidth_hz, zoom=self.zoom)
        self.cache.move_to_end(self.cache_key)
        while len(self.cache) > self.CACHE_LIMIT:
            self.cache.popitem(last=False)

    def configure(self, bandwidth_hz, zoom_cap, now):
        zoom = min(8, int(zoom_cap))
        if self.windows and self.bandwidth_hz == bandwidth_hz and self.zoom == zoom:
            return
        self.bandwidth_hz, self.zoom = bandwidth_hz, zoom
        span = bandwidth_hz / (2**zoom * 1000)
        # Include RF context outside the band for sideband/noise checks, but
        # publish carriers only inside its exact broadcast boundaries.
        low, high = max(0, self.low-8), min(bandwidth_hz/1000, self.high+8)
        if high <= low or span < 20:
            self.close()
            return
        # Overlap avoids losing carriers at the five-bin detection margins.
        count = max(1, math.ceil(max(0, high-low-span) / (span-16)) + 1)
        first = low + min(high-low, span)/2
        last = high - min(high-low, span)/2
        self.windows = [first + (last-first)*i/max(1, count-1) for i in range(count)]
        self.index = 0
        self.candidates = []
        self._reset_window(now)

    def _reset_window(self, now):
        self.rows = []
        self.geometry = None
        self.started_rows_at = None
        self.published_at = 0
        self.deadline = now + self.WINDOW_TIMEOUT

    def close(self):
        self._remember()
        self.open = self.active = False
        self.rows = []

    def poll(self, context, now):
        if self.open and context != self.context:
            self.close()
        if self.active and now >= self.deadline:
            self.skipped += 1
            self._advance(now)

    def _advance(self, now):
        self.index += 1
        if self.index >= len(self.windows):
            self.active = False
            self.rows = []
        else:
            self._reset_window(now)

    def request(self, context, now, bandwidth_hz=30000000, zoom_cap=14):
        self.poll(context, now)
        if not self.active:
            return None
        self.configure(bandwidth_hz, zoom_cap, now)
        return (self.windows[self.index], self.zoom) if self.active else None

    def feed(self, message, bandwidth_hz, zoom_max, zoom_cap, now):
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
        self.last_sequence = sequence
        self.rows.append(message[16:])
        self.rows = self.rows[-32:]
        observed = now - self.started_rows_at
        if len(self.rows) >= 8 and observed >= .6 and now-self.published_at >= .3:
            self._merge(detect_stations(self.rows, first_hz, bin_hz, self.low, self.high))
            self.measured_at = now
            self.published_at = now
        if len(self.rows) >= 6 and observed >= self.OBSERVE_SECONDS:
            self._merge(detect_stations(self.rows, first_hz, bin_hz, self.low, self.high))
            self.measured_at = now
            self._advance(now)

    def _merge(self, candidates):
        for candidate in candidates:
            duplicate = next((i for i, old in enumerate(self.candidates)
                              if abs(old.frequency_khz-candidate.frequency_khz) < 2), None)
            if duplicate is None:
                # Append rather than reorder: incoming discoveries cannot
                # move an existing touch target or encoder selection.
                self.candidates.append(candidate)
            elif candidate.prominence > self.candidates[duplicate].prominence:
                old = self.candidates[duplicate]
                self.candidates[duplicate] = SeekCandidate(old.frequency_khz, candidate.prominence)

    def snapshot(self, now=None):
        threshold = 24 - .18*self.sensitivity
        visible = tuple(item for item in self.candidates if item.prominence >= threshold)
        if visible and self.selection not in [item.frequency_khz for item in visible]:
            self.selection = visible[0].frequency_khz
        elif not visible:
            self.selection = None
        return dict(open=self.open, active=self.active, candidates=visible,
                    selected=self.selection, sensitivity=self.sensitivity, label=self.label,
                    completed=min(self.index, len(self.windows)), total=len(self.windows),
                    skipped=self.skipped, cached=self.cached,
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
