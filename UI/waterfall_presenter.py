"""Pace real waterfall rows using measured arrivals, independently of audio."""
from collections import deque
import math
import queue


WATERFALL_PRESENTATION_RESERVE_SECONDS = 0.26


class WaterfallPresenter:
    def __init__(self, reserve_seconds=WATERFALL_PRESENTATION_RESERVE_SECONDS):
        self.reserve_seconds = max(0.0, float(reserve_seconds))
        self.reset()

    def reset(self, stream_key=None):
        self.stream_key = stream_key
        self.started = False
        self.next_row_at = 0.0
        self.source_fps = None
        self._hint = None
        self._pending = 0
        self._arrivals = deque(maxlen=256)
        self._measured = False
        self._last_measurement = None
        self._first_arrival = None
        self._report_at = None
        self.received_rows = self.presented_rows = self.underruns = 0

    def _observe(self, depth, now, hint):
        if hint != self._hint:
            self._hint = hint
            self.source_fps = hint
            self._arrivals.clear()
            self._measured = False
            self._last_measurement = None
            self._first_arrival = None
        arrived = depth - self._pending
        self._pending = depth
        if arrived <= 0:
            return
        self.received_rows += arrived
        if self._first_arrival is None:
            self._first_arrival = now
        # Do not interpret a disconnected/paused socket as a new slow rate.
        if self._arrivals and now - self._arrivals[-1][0] > 3.0:
            self._arrivals.clear()
            self._measured = False
            self._first_arrival = now
        if self._arrivals and now == self._arrivals[-1][0]:
            stamp, count = self._arrivals.pop()
            self._arrivals.append((stamp, count + arrived))
        else:
            self._arrivals.append((now, arrived))
        while len(self._arrivals) > 2 and self._arrivals[1][0] < now - 2.0:
            self._arrivals.popleft()
        elapsed = now - self._arrivals[0][0]
        if elapsed < 0.15:
            return
        # Exclude the first batch: its preceding arrival interval is unknown.
        count = sum(n for _, n in self._arrivals) - self._arrivals[0][1]
        measured = max(0.1, min(240.0, count / elapsed))
        blend = (1.0 if not self._measured else
                 1.0 - math.exp(-(now - self._last_measurement) / 0.6))
        self.source_fps += (measured - self.source_fps) * blend
        self._measured = True
        self._last_measurement = now

    def take(self, line_queue, now, source_fps, stream_key):
        """Return at most two real rows, with a small adaptive jitter reserve."""
        hint = max(0.1, float(source_fps))
        if stream_key != self.stream_key:
            self.reset(stream_key)
        depth = line_queue.qsize()
        self._observe(depth, now, hint)
        rate = self.source_fps
        reserve = max(1, math.ceil(rate * self.reserve_seconds))
        if not self.started:
            if depth < reserve:
                # Even a receiver much slower than its advertised speed must
                # show its first row, rather than wait indefinitely for six.
                waited = 0 if self._first_arrival is None else now - self._first_arrival
                if not depth or waited < max(0.35, self.reserve_seconds):
                    return ()
                if not self._measured:
                    self.source_fps = rate = min(rate, depth / max(waited, 0.1))
            self.started = True
            self.next_row_at = now
        # A newly measured faster stream must not inherit a slow stream's
        # long outstanding deadline, especially after an actual socket gap.
        self.next_row_at = min(self.next_row_at, now + 1.0 / rate)
        if now + 1e-9 < self.next_row_at:
            return ()
        # Drain excess latency gently after a delayed render/network burst.
        # Ordinary playback follows the measured rate, not the speed preset.
        excess = max(0, depth - reserve - 1)
        rate *= min(1.25, 1.0 + excess * 0.025)
        due = min(2, 1 + int(max(0.0, now - self.next_row_at) * rate))
        rows = []
        for _ in range(due):
            try:
                rows.append(line_queue.get_nowait())
            except queue.Empty:
                # Once timing is known, a transient empty queue must not
                # restart the initial batch threshold. Keep the clock near
                # now while the arrival estimator follows a slowing source.
                self.started = self._measured
                self.next_row_at = now if self.started else 0.0
                if not self.started:
                    self._first_arrival = None
                self.underruns += 1
                break
        self._pending -= len(rows)
        self.presented_rows += len(rows)
        if rows and self.started:
            # A UI stall must not leave a catch-up debt for subsequent frames.
            self.next_row_at = max(self.next_row_at, now - 1.0 / rate) + len(rows) / rate
        if self._measured and self._arrivals[-1][0] - self._arrivals[0][0] >= 0.5:
            if self._report_at is None or now >= self._report_at:
                print(f"gl waterfall pacing measured={self.source_fps:.2f} fps "
                      f"preset={hint:.2f} queued={self._pending} "
                      f"rows={self.presented_rows} underruns={self.underruns}", flush=True)
                self._report_at = now + 30.0
        return tuple(rows)
