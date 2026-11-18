"""Capture a bounded diagnostic when the render loop stops making progress."""
import gc
import logging
import sys
import threading
import time


class UIHeartbeat:
    def __init__(self, threshold=1.0):
        self.threshold = threshold
        self.thread_id = threading.get_ident()
        self.last_beat = time.monotonic()
        self.frames = 0
        self.max_gap = 0.0
        self._gc_started = {}
        gc.callbacks.append(self._gc_timing)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name='ui-heartbeat', daemon=True)
        self._thread.start()

    def _gc_timing(self, phase, info):
        generation = info["generation"]
        if phase == "start":
            self._gc_started[generation] = time.monotonic()
        else:
            duration = time.monotonic() - self._gc_started.pop(generation, time.monotonic())
            if duration >= 0.1:
                print(f"UI GC generation={generation} duration={duration:.3f}s thread={threading.current_thread().name}", flush=True)

    def beat(self):
        now = time.monotonic()
        self.max_gap = max(self.max_gap, now - self.last_beat)
        self.last_beat = now
        self.frames += 1

    def _watch(self):
        last_report = 0.0
        next_summary = time.monotonic() + 30.0
        while not self._stop.wait(0.25):
            now = time.monotonic()
            gap = now - self.last_beat
            if gap >= self.threshold and now - last_report >= 10.0:
                last_report = now
                frames = sys._current_frames()
                captured = {}
                for ident, frame in frames.items():
                    stack = []
                    while frame is not None and len(stack) < 8:
                        stack.append((frame.f_code.co_filename, frame.f_lineno, frame.f_code.co_name))
                        frame = frame.f_back
                    captured[ident] = stack
                del frames
                lines = []
                for thread in threading.enumerate():
                    stack = captured.get(thread.ident)
                    if stack:
                        lines.append(thread.name + ':\n' + '\n'.join(f'{filename}:{line} {name}' for filename, line, name in stack))
                logging.warning('UI stalled %.2fs; thread snapshots:\n%s', gap, '\n'.join(lines))
            if now >= next_summary:
                print(f'UI heartbeat frames={self.frames} max_gap={max(self.max_gap, gap):.3f}s', flush=True)
                next_summary = now + 30.0

    def close(self):
        if self._gc_timing in gc.callbacks:
            gc.callbacks.remove(self._gc_timing)
        self._stop.set()
        self._thread.join(timeout=1.0)
