"""One aggregate budget for retained ADS-B data, separate from installed software."""
from pathlib import Path
import re
import threading

MIB = 1024*1024
STORAGE_LIMIT = 250*MIB
WRITE_HEADROOM = 16*MIB


class StorageBudget:
    def __init__(self, root, limit=STORAGE_LIMIT, headroom=None):
        self.root = Path(root)
        self.limit = limit
        self.headroom = min(WRITE_HEADROOM, limit//10) if headroom is None else headroom
        self.lock = threading.Lock()
        self.state = dict(limit_bytes=limit, used_bytes=0, headroom_bytes=self.headroom,
                          removed_files=0, coverage_pruned_before=None)

    def files(self):
        result = []
        for path in self.root.rglob('*'):
            try:
                if path.is_symlink() or not path.is_file():continue
                s = path.stat()
                result.append((path, max(s.st_size, getattr(s, 'st_blocks', 0)*512), s.st_mtime))
            except FileNotFoundError:pass  # Atomic writers may replace a file during accounting.
        return result

    def usage(self):
        files = self.files()
        used = sum(size for _, size, _ in files)
        with self.lock:self.state['used_bytes'] = used
        return used

    def snapshot(self):
        with self.lock:return dict(self.state)

    def database_budget(self, required=0):
        """Discard oldest expendable files before shortening position history.

        required is the anticipated database size, not an additional allocation.
        Settings, active logs, trails, comparison and received weather survive.
        """
        files = self.files()
        database = self.root/'coverage.sqlite3'
        other = sum(size for path, size, _ in files if path != database)
        target = self.limit-self.headroom
        candidates = sorted(((path, size, modified) for path, size, modified in files
                             if (path.parent == self.root and re.fullmatch(r'(flights|receiver)\.jsonl\.\d+', path.name))
                             or (path.parent == self.root/'aircraft-details' and path.suffix in ('.jpg', '.json'))),
                            key=lambda item: item[2])
        removed = 0
        for path, size, _ in candidates:
            if other+required <= target:break
            try:path.unlink();other -= size;removed += 1
            except FileNotFoundError:pass
        with self.lock:self.state['removed_files'] += removed
        return max(0, target-other)
