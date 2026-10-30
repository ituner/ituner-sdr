"""Daily directory refresh while running; no receiver connections or timers at import."""
import threading
import time
from pathlib import Path

DIRECTORY_REFRESH_SECONDS = 24 * 60 * 60


class DailyDirectoryRefresh:
    def __init__(self, jobs, clock=time.monotonic):
        self.jobs = tuple(jobs)
        self.clock = clock
        # Startup downloads are already performed by the application.
        self.next_at = clock() + DIRECTORY_REFRESH_SECONDS
        self.worker = None
        self.completed = 0
        self.results = ()

    @property
    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def poll(self):
        now = self.clock()
        if now < self.next_at:
            return False
        return self.request()

    def request(self):
        """Refresh on demand without blocking the UI or overlapping downloads."""
        if self.busy:
            return False
        # Advance before starting; failures never create a rapid retry loop.
        # A long suspend results in one refresh, not a backlog of missed days.
        self.next_at = self.clock() + DIRECTORY_REFRESH_SECONDS
        self.worker = threading.Thread(target=self._run, name="daily-directory-refresh", daemon=True)
        self.worker.start()
        return True

    def _run(self):
        results = []
        for job in self.jobs:
            try:
                results.append(job() is not False)
            except Exception as exc:
                results.append(False)
                print(f"gl daily directory refresh failed; keeping saved data: {exc}", flush=True)
        self.results = tuple(results)
        self.completed += 1

    def result_message(self):
        if self.results and all(self.results):
            return "DIRECTORY UPDATED"
        if any(self.results):
            return "UPDATED; SOME SOURCES UNAVAILABLE"
        return "UPDATE UNAVAILABLE; SAVED LIST KEPT"


def cache_stamp(path):
    try:
        info = Path(path).stat()
        return info.st_mtime_ns, info.st_size
    except OSError:
        return None


def checked_refresh(job, cache_path):
    """Distinguish a fresh download from a loader's cached fallback."""
    before = cache_stamp(cache_path)
    job()
    after = cache_stamp(cache_path)
    return after is not None and after != before


def directory_age_label(path, now=None):
    stamp = cache_stamp(path)
    if stamp is None:
        return "No saved update"
    age = max(0, (time.time() if now is None else now) - stamp[0] / 1_000_000_000)
    if age < 60:
        return "Updated just now"
    if age < 3600:
        return f"Updated {int(age // 60)} min ago"
    if age < 86400:
        return f"Updated {int(age // 3600)} hr ago"
    return f"Updated {int(age // 86400)} days ago"
