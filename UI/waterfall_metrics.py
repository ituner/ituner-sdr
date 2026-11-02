"""Bounded live counters for actual view commands and first matching data."""
from collections import deque
import threading
import time


class WaterfallMetrics:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.changes = deque(maxlen=256)
        self.delays = deque(maxlen=30)
        self.pending = None
        self.lock = threading.Lock()

    def sent(self):
        with self.lock:
            now = self.clock()
            self.changes.append(now)
            self.pending = now

    @property
    def waiting(self):
        with self.lock:
            return self.pending is not None

    def first_row(self):
        with self.lock:
            if self.pending is not None:
                self.delays.append(max(0,self.clock()-self.pending))
                self.pending = None

    def cancel_wait(self):
        with self.lock:
            self.pending = None

    def snapshot(self):
        with self.lock:
            now = self.clock()
            while self.changes and self.changes[0] < now-30:
                self.changes.popleft()
            return dict(views_per_second=len(self.changes)/min(30,max(1,now-self.started)),
                        first_row_ms=1000*sum(self.delays)/len(self.delays) if self.delays else None)
