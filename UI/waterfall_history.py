"""Bounded, UI-thread-owned waterfall scrollback; no audio or disk work."""
from dataclasses import dataclass
from functools import lru_cache
import time


@lru_cache(maxsize=16)
def _palette(channels):
    return channels


@dataclass(frozen=True, slots=True)
class CompactRow:
    pixels: bytes
    palette: tuple
    captured_at: float

    @classmethod
    def capture(cls, pixels, mapper):
        return cls(bytes(pixels), _palette(tuple(bytes(c) for c in mapper)), time.monotonic())

    def rgba(self):
        # bytes.translate maps whole rows in C, avoiding per-pixel Python work.
        result = bytearray(len(self.pixels) * 4)
        for channel, lut in enumerate(self.palette):
            result[channel::4] = self.pixels.translate(lut)
        result[3::4] = b'\xff' * len(self.pixels)
        return result


class WaterfallPixels(bytes):
    """RGBA upload bytes carrying their already-computed intensity row."""
    def __new__(cls, rgba, compact):
        result = super().__new__(cls, rgba)
        result.compact = compact
        return result


@dataclass(frozen=True, slots=True)
class HistoryRow:
    compact: CompactRow
    center_khz: float
    span_khz: float


class WaterfallHistory:
    """Five minutes, at most 30 distinct rows/sec, one byte per column.

    Absolute row IDs keep a reviewed window stationary as live rows arrive.
    A ring provides O(1) insertion and viewport lookup; duplicate presentation
    rows and bursts within one sampling bucket do not inflate RAM use.
    """
    def __init__(self, width, seconds=300, max_fps=30):
        self.width = width
        self.seconds = seconds
        self.max_fps = max_fps
        self.capacity = int(seconds * max_fps) + 1
        self.clear()

    def clear(self):
        self.rows = [None] * self.capacity
        self.first = self.next = 0
        self.anchor = None
        self.last_bucket = None
        self.last_interaction_at = None

    @property
    def reviewing(self):
        return self.anchor is not None

    def live(self):
        self.anchor = None
        self.last_interaction_at = None

    def resume_if_idle(self, now, touching=False):
        """Return to live after five idle seconds, never during a touch."""
        if not self.reviewing:
            return False
        if touching or self.last_interaction_at is None:
            self.last_interaction_at = now
        elif now - self.last_interaction_at >= 5.0:
            self.live()
            return True
        return False

    def expire(self, now):
        cutoff = now - self.seconds
        while self.first < self.next:
            if self.rows[self.first % self.capacity].compact.captured_at >= cutoff:
                break
            self.rows[self.first % self.capacity] = None
            self.first += 1
        if self.first == self.next:
            self.live()

    def append(self, compact, center_khz, span_khz, now):
        self.expire(now)
        if compact is None or len(compact.pixels) != self.width:
            return False
        bucket = int(compact.captured_at * self.max_fps)
        if (self.last_bucket is not None and bucket <= self.last_bucket
                or compact.captured_at < now - self.seconds):
            return False
        self.last_bucket = bucket
        self.rows[self.next % self.capacity] = HistoryRow(compact, center_khz, span_khz)
        self.next += 1
        self.first = max(self.first, self.next - self.capacity)
        return True

    def top(self, height):
        if self.first == self.next:
            return None
        newest = self.next - 1
        oldest_top = min(newest, self.first + max(1, int(height)) - 1)
        if self.anchor is not None:
            self.anchor = min(newest, max(oldest_top, self.anchor))
        return newest if self.anchor is None else self.anchor

    def scroll(self, older_rows, height, now=None):
        top = self.top(height)
        if top is None:
            return
        self.anchor = top - int(older_rows)
        self.top(height)
        if self.anchor == self.next - 1:
            self.live()
        else:
            self.last_interaction_at = time.monotonic() if now is None else now

    def window(self, height):
        top = self.top(height)
        if top is None:
            return ()
        return tuple(self.rows[i % self.capacity]
                     for i in range(top, max(self.first - 1, top - int(height)), -1))

    def age(self, now, height):
        top = self.top(height)
        return 0 if top is None else max(0, now - self.rows[top % self.capacity].compact.captured_at)
