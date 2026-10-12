"""Daily directory refresh while running; no receiver connections or timers at import."""
import threading
import time

DIRECTORY_REFRESH_SECONDS = 24 * 60 * 60


class DailyDirectoryRefresh:
    def __init__(self, jobs, clock=time.monotonic):
        self.jobs = tuple(jobs)
        self.clock = clock
        # Startup downloads are already performed by the application.
        self.next_at = clock() + DIRECTORY_REFRESH_SECONDS
        self.worker = None

    def poll(self):
        now = self.clock()
        if now < self.next_at or (self.worker is not None and self.worker.is_alive()):
            return False
        # Advance before starting; failures never create a rapid retry loop.
        # A long suspend results in one refresh, not a backlog of missed days.
        self.next_at = now + DIRECTORY_REFRESH_SECONDS
        self.worker = threading.Thread(target=self._run, name="daily-directory-refresh", daemon=True)
        self.worker.start()
        return True

    def _run(self):
        for job in self.jobs:
            try:
                job()
            except Exception as exc:
                print(f"gl daily directory refresh failed; keeping saved data: {exc}", flush=True)
