"""Bounded, asynchronous NASA Blue Marble tiles for the CM5 Globe.

GIBS's geographic 500 m matrix starts at (-180, 90) with 512 px tiles. Its
level-zero tile spans 288 degrees; each subsequent level halves that span.
The padded matrix extends beyond the world, so requested columns and rows are
limited to geographic coordinates before a URL is constructed.
"""

from collections import OrderedDict
from dataclasses import dataclass
import math
import os
from pathlib import Path
import queue
import threading
import time
from urllib.request import Request, urlopen


GIBS_TILE_URL = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/"
    "BlueMarble_NextGeneration/default/500m/{level}/{row}/{col}.jpeg"
)
GLOBE_RADIUS_FACTOR = 0.92
GLOBE_DRAG_GAIN = 1.0
TILE_PIXELS = 512
MAX_LEVEL = 7
MAX_VISIBLE_TILES = 24
DISK_CACHE_LIMIT_BYTES = 64 * 1024 * 1024


def default_cache_dir():
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return root / "ituner-sdr" / "blue-marble-500m"


@dataclass(frozen=True)
class TileKey:
    level: int
    row: int
    col: int

    @property
    def span(self):
        return 288.0 / (1 << self.level)

    @property
    def bounds(self):
        west = -180.0 + self.col * self.span
        north = 90.0 - self.row * self.span
        return west, north - self.span, west + self.span, north

    @property
    def url(self):
        return GIBS_TILE_URL.format(level=self.level, row=self.row, col=self.col)


def _screen_to_geo(x, y, center_lon, center_lat, box, radius):
    """Inverse orthographic projection in unwrapped degrees near the centre."""
    nx = (x - (box[0] + box[2]) / 2.0) / radius
    ny = ((box[1] + box[3]) / 2.0 - y) / radius
    rho2 = nx * nx + ny * ny
    if rho2 > 1.0:
        return None
    depth = math.sqrt(max(0.0, 1.0 - rho2))
    latitude = math.asin(max(-1.0, min(1.0,
        ny * math.cos(center_lat) + depth * math.sin(center_lat)
    )))
    longitude = center_lon + math.atan2(
        nx, depth * math.cos(center_lat) - ny * math.sin(center_lat)
    )
    return math.degrees(longitude), math.degrees(latitude)


def _view_level(box, radius):
    angular_width = math.degrees(2.0 * math.asin(min(1.0,
        (box[2] - box[0]) / (2.0 * radius)
    )))
    degrees_per_pixel = angular_width / max(1.0, box[2] - box[0])
    return max(2, min(MAX_LEVEL, math.ceil(math.log2(
        288.0 / (TILE_PIXELS * max(1e-6, degrees_per_pixel))
    ))))


def visible_tiles(center_lon, center_lat, box, radius):
    """Choose tiles covering the visible map, capped for CM5 GPU/network use."""
    samples = [
        _screen_to_geo(
            box[0] + (box[2] - box[0]) * ix / 8.0,
            box[1] + (box[3] - box[1]) * iy / 8.0,
            center_lon, center_lat, box, radius,
        )
        for iy in range(9) for ix in range(9)
    ]
    samples = [point for point in samples if point is not None]
    if not samples:
        return ()
    west = min(lon for lon, _lat in samples)
    east = max(lon for lon, _lat in samples)
    south = max(-90.0, min(lat for _lon, lat in samples))
    north = min(90.0, max(lat for _lon, lat in samples))
    level = _view_level(box, radius)
    while level >= 2:
        span = 288.0 / (1 << level)
        # A small overdraw margin prevents seams appearing during a slow pan.
        col_first = math.floor((west + 180.0 - span * 0.1) / span)
        col_last = math.floor((east + 180.0 + span * 0.1) / span)
        row_first = max(0, math.floor((90.0 - north - span * 0.1) / span))
        row_last = min(math.ceil(180.0 / span) - 1,
                       math.floor((90.0 - south + span * 0.1) / span))
        if (col_last - col_first + 1) * (row_last - row_first + 1) <= MAX_VISIBLE_TILES:
            break
        level -= 1
    world_columns = int(round(360.0 / span))
    keys = {
        TileKey(level, row, col % world_columns)
        for row in range(row_first, row_last + 1)
        for col in range(col_first, col_last + 1)
    }
    centre_lon = math.degrees(center_lon)
    centre_lat = math.degrees(center_lat)

    def distance(key):
        west, south, east, north = key.bounds
        lon_delta = ((west + east) / 2.0 - centre_lon + 180.0) % 360.0 - 180.0
        lat_delta = (south + north) / 2.0 - centre_lat
        return (lon_delta * math.cos(center_lat)) ** 2 + lat_delta ** 2

    return tuple(sorted(keys, key=distance))


def download_tile(key):
    request = Request(key.url, headers={
        "User-Agent": "iTuner-SDR/1.0 (Globe Blue Marble imagery)",
        "Accept": "image/jpeg",
    })
    with urlopen(request, timeout=5.0) as response:
        data = response.read(1_000_001)
    if len(data) > 1_000_000 or not data.startswith(b"\xff\xd8"):
        raise ValueError("NASA GIBS did not return a JPEG tile")
    return data


class GlobeTileFetcher:
    """Never fetch or decode imagery on the OpenGL rendering thread."""

    def __init__(self, loader=download_tile, memory_limit=32, workers=2,
                 cache_dir=None):
        self.loader = loader
        self.memory_limit = max(1, int(memory_limit))
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._disk_writes = 0
        self._lock = threading.Lock()
        self._queue = queue.Queue(maxsize=48)
        self._tiles = OrderedDict()
        self._pending = set()
        self._wanted = set()
        self._retry_at = {}
        for index in range(max(1, int(workers))):
            threading.Thread(target=self._worker, name=f"globe-tile-{index}",
                             daemon=True).start()

    def prefetch(self, keys):
        now = time.monotonic()
        with self._lock:
            self._wanted = set(keys)
            for key in keys:
                if key in self._tiles or key in self._pending or self._retry_at.get(key, 0.0) > now:
                    continue
                try:
                    self._queue.put_nowait(key)
                except queue.Full:
                    break
                self._pending.add(key)

    def ready(self, key):
        with self._lock:
            data = self._tiles.get(key)
            if data is not None:
                self._tiles.move_to_end(key)
            return data

    def _load_tile(self, key):
        path = (self.cache_dir / str(key.level) / str(key.row) / f"{key.col}.jpeg"
                if self.cache_dir is not None else None)
        if path is not None:
            try:
                cached = path.read_bytes()
                if cached.startswith(b"\xff\xd8") and len(cached) <= 1_000_000:
                    return cached
            except OSError:
                pass
        data = self.loader(key)
        if path is not None:
            temporary = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(data)
                os.replace(temporary, path)
                self._disk_writes += 1
                if self._disk_writes == 1 or self._disk_writes % 32 == 0:
                    self._prune_disk_cache()
            except OSError:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return data

    def _prune_disk_cache(self):
        try:
            files = [path for path in self.cache_dir.rglob("*.jpeg") if path.is_file()]
            files.sort(key=lambda path: path.stat().st_mtime)
            total = sum(path.stat().st_size for path in files)
            for path in files:
                if total <= DISK_CACHE_LIMIT_BYTES:
                    break
                size = path.stat().st_size
                path.unlink()
                total -= size
        except OSError:
            pass

    def _worker(self):
        while True:
            key = self._queue.get()
            with self._lock:
                wanted = key in self._wanted
            if not wanted:
                with self._lock:
                    self._pending.discard(key)
                continue
            try:
                data = self._load_tile(key)
            except Exception:
                # A malformed response must not kill the background worker.
                with self._lock:
                    self._retry_at[key] = time.monotonic() + 20.0
                    self._pending.discard(key)
                continue
            with self._lock:
                self._pending.discard(key)
                self._retry_at.pop(key, None)
                if key not in self._wanted:
                    continue
                self._tiles[key] = data
                self._tiles.move_to_end(key)
                while len(self._tiles) > self.memory_limit:
                    self._tiles.popitem(last=False)
