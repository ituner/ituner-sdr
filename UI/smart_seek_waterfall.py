"""Bounded RF rows for the optional listening preview; no sockets or GPU work."""
import math
import struct
from collections import deque

from am_carrier import rf_view_center_hz


class PreviewLeveler:
    """Expose local RF contrast promptly without altering Home's display levels."""

    def __init__(self):
        self.floor = self.ceiling = None

    def levels_for(self, samples):
        if not samples:
            return (0, 28) if self.floor is None else (self.floor, self.ceiling)
        ordered = sorted(samples)
        floor = max(0, ordered[len(ordered)//5]-5)
        ceiling = min(255, max(ordered[min(len(ordered)-1, int(len(ordered)*.98))]+4,
                               floor+28))
        floor = min(floor, ceiling-28)
        if self.floor is None:
            self.floor, self.ceiling = floor, ceiling
        else:
            self.floor = .82*self.floor+.18*floor
            self.ceiling = .82*self.ceiling+.18*ceiling
        return self.floor, self.ceiling


class SeekWaterfall:
    WIDTH = 512
    SPAN_KHZ = 100

    def __init__(self):
        self.enabled = False
        self.center = None
        self.context = None
        self.generation = 0
        self.rows = deque(maxlen=32)
        self.last_frame_at = None
        self.sequence = None
        self.geometry = None
        self.span = self.SPAN_KHZ
        self.zoom = 8

    def set(self, enabled, center=None, context=None):
        key = bool(enabled), center if enabled else None, context if enabled else None
        if key == (self.enabled, self.center, self.context):
            return
        self.enabled, self.center, self.context = key
        self.generation += 1
        self.rows.clear()
        self.last_frame_at = self.sequence = self.geometry = None

    def request(self, bandwidth_hz, zoom_cap):
        if not self.enabled:
            return None
        self.zoom = max(0, min(int(zoom_cap), 14,
                              math.floor(math.log2(bandwidth_hz/(self.SPAN_KHZ*1000)))))
        self.span = min(self.SPAN_KHZ, bandwidth_hz/(2**self.zoom*1000))
        return self.center, self.zoom

    def feed(self, message, bandwidth_hz, zoom_max, zoom_cap, now):
        if not self.enabled or len(message) != 1040 or message[:3] != b'W/F':
            return
        start, flags, sequence = struct.unpack_from('<III', message, 4)
        zoom = flags & 0xffff
        if flags >> 16 & 3 or zoom != min(self.zoom, zoom_max, zoom_cap):
            return
        if self.sequence is not None and not 0 < (sequence-self.sequence) & 0xffffffff < 0x80000000:
            return
        first = start*bandwidth_hz/(1024*2**zoom_max)
        bin_hz = bandwidth_hz/(1024*2**zoom)
        expected = rf_view_center_hz(self.center*1000, bandwidth_hz, zoom)
        if abs(first+512*bin_hz-expected) > max(3, 2*bin_hz):
            return
        lower = self.center*1000-self.span*500
        # Never stretch a partial/off-frequency frame into the listening view.
        if lower < first-bin_hz or lower+self.span*1000 > first+1024*bin_hz+bin_hz:
            return
        geometry = bandwidth_hz, zoom, self.span
        if self.geometry is not None and geometry != self.geometry:
            self.generation += 1
            self.rows.clear()
        self.geometry = geometry
        samples = message[16:]
        indices = (round((lower+(i+.5)*self.span*1000/self.WIDTH-first)/bin_hz)
                   for i in range(self.WIDTH))
        self.rows.append(bytes(samples[max(0, min(1023, i))] for i in indices))
        self.sequence = sequence
        self.last_frame_at = now

    def take(self):
        rows = tuple(self.rows)
        self.rows.clear()
        return self.generation, rows, self.center, self.span, self.last_frame_at
