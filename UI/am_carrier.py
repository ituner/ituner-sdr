"""One-shot AM carrier acquisition from uncoloured Kiwi RF waterfall rows."""
import math
import statistics
import struct
from collections import deque

AM_MODES = frozenset(('am', 'amn', 'amw'))


def carrier_available(mode, receiver_type='kiwi'):
    return receiver_type == 'kiwi' and str(mode).lower() in AM_MODES


def rf_view_center_hz(requested_hz, bandwidth_hz, zoom):
    """Kiwi clamps its RF window at DC and the upper sampling-band edge."""
    half_span = bandwidth_hz / (2 ** zoom * 2)
    return max(half_span, min(bandwidth_hz-half_span, requested_hz))


def carrier_peak(rows, first_hz, bin_hz, target_hz, radius_hz):
    """Require a narrow, prominent, persistent and unambiguous RF peak."""
    if len(rows) < 5 or bin_hz <= 0:
        return None
    size = len(rows[0])
    if size < 16 or any(len(row) != size for row in rows):
        return None
    values = [statistics.mean(column) for column in zip(*rows)]
    floor = statistics.median(values)
    peaks = []
    for i in range(4, size - 4):
        hz = first_hz + i * bin_hz
        if abs(hz - target_hz) > radius_hz:
            continue
        p = values[i]
        if p < floor + 12 or p >= 253 or p <= values[i-1] or p < values[i+1]:
            continue
        # A carrier is a narrow line above its neighbouring modulation.
        shoulders = max(statistics.mean(values[i-4:i-2]),
                        statistics.mean(values[i+3:i+5]))
        if p - shoulders < 8 or p - max(values[i-2], values[i+2]) < 6:
            continue
        if sum(max(row[i-1:i+2]) >= statistics.median(row) + 10
               for row in rows) < len(rows) - 1:
            continue
        peaks.append((p, i))
    if not peaks:
        return None
    peaks.sort(reverse=True)
    power, index = peaks[0]
    if any(power - p < 6 and abs(i-index) > 3 for p, i in peaks[1:]):
        return None
    left, middle, right = values[index-1:index+2]
    denominator = left - 2 * middle + right
    offset = (0.5 * (left-right) / denominator) if denominator < -0.01 else 0
    return first_hz + (index + max(-0.5, min(0.5, offset))) * bin_hz


class CarrierSearch:
    """A coarse acquisition followed by a finer measurement, on one W/F socket."""
    def __init__(self):
        self.status = ''
        self.until = 0.0
        self.active = False
        self.rows = deque(maxlen=7)
        self.context = None
        self.result_hz = None
        self.last_sequence = None
        self.geometry = None

    def start(self, frequency_khz, width_hz, context, now):
        self.__init__()
        self.context = context
        self.active = True
        self.status = 'TUNING…'
        self.deadline = now + 9.0
        self.center_hz = self.target_hz = frequency_khz * 1000
        self.radius_hz = min(2500, max(250, abs(width_hz) / 2))
        self.zoom = 11

    def finish(self, status, now):
        self.active = False
        self.status = status
        self.until = now + 2.5

    def poll(self, context, now):
        if self.active:
            if context != self.context:
                self.finish('', now)
            elif now >= self.deadline:
                self.finish('NO CARRIER', now)
        return self.active

    def feed(self, message, bandwidth_hz, zoom_max, zoom_cap, now):
        if not self.active or len(message) != 1040 or message[:3] != b'W/F':
            return None
        start, zoom_flags, sequence = struct.unpack_from('<III', message, 4)
        zoom, flags = zoom_flags & 0xffff, zoom_flags >> 16
        expected_zoom = min(self.zoom, zoom_cap, zoom_max)
        if flags & 3 or zoom != expected_zoom or zoom < 8:
            return None
        if self.last_sequence is not None and ((sequence-self.last_sequence) & 0xffffffff) >= 0x80000000:
            return None
        if sequence == self.last_sequence:
            return None
        first_hz = start * bandwidth_hz / (1024 * 2**zoom_max)
        bin_hz = bandwidth_hz / (1024 * 2**zoom)
        center_hz = first_hz + bin_hz * 512
        # Server pan is quantized to its native start-bin grid. Queued rows
        # from the old view must never be measured against our new frequency.
        expected_center_hz = rf_view_center_hz(self.center_hz, bandwidth_hz, zoom)
        if abs(center_hz-expected_center_hz) > max(2 * bin_hz, 3):
            return None
        geometry = start, zoom
        if geometry != self.geometry:
            self.rows.clear()
            self.geometry = geometry
        self.last_sequence = sequence
        self.rows.append(message[16:])
        candidate = carrier_peak(self.rows, first_hz, bin_hz, self.target_hz, self.radius_hz)
        if candidate is None or not math.isfinite(candidate):
            return None
        if self.zoom == 11:
            self.center_hz = self.target_hz = candidate
            self.radius_hz = max(100, bin_hz * 3)
            self.zoom = 14
            self.rows.clear()
            self.geometry = None
            return None
        self.result_hz = round(candidate)
        self.finish('TUNED', now)
        return self.result_hz / 1000
