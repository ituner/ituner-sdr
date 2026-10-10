"""Live channel counts from already-open Kiwi WebSockets; no HTTP or sockets here."""
import json
import threading
import time
from urllib.parse import unquote

# Occupancy is informational; refresh more slowly than the official 2.5 s UI.
INTERVAL = 5.0
MAX_AGE = 15.0


class OccupancyCache:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.last_request = {}
        self.values = {}

    @staticmethod
    def key(endpoint):
        return str(endpoint).rstrip('/')

    def request_due(self, endpoint):
        key = self.key(endpoint)
        now = self.clock()
        with self.lock:
            if now - self.last_request.get(key, float('-inf')) < INTERVAL:
                return False
            self.last_request[key] = now
            return True

    def accept(self, endpoint, payload):
        try:
            rows = json.loads(payload)
        except (ValueError, TypeError):
            try:
                rows = json.loads(unquote(payload))
            except (ValueError, TypeError):
                return
        if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
            return
        # Official rx_users emits one row per channel. Busy rows have "n",
        # even if the user is anonymous/private; idle rows contain only "i".
        if any(not isinstance(row, dict) or type(row.get('i')) is not int for row in rows):
            return
        if {row['i'] for row in rows} != set(range(len(rows))):
            return
        used = sum('n' in row for row in rows)
        with self.lock:
            self.values[self.key(endpoint)] = (used, len(rows), self.clock())

    def snapshot(self, endpoint):
        with self.lock:
            value = self.values.get(self.key(endpoint))
            if value is None or self.clock() - value[2] > MAX_AGE:
                return None
            return value[:2]


occupancy = OccupancyCache()
