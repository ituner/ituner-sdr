"""Expose the application's existing GLOBE imagery, borders and HD tile cache."""
import json
import lzma
import math
from pathlib import Path
import threading
import globe_tiles
from adsb_traffic import MAP_ZOOM_MIN, MAP_ZOOM_MAX


class GlobeAssets:
    def __init__(self, assets=None):
        self.assets = Path(assets or Path(__file__).with_name('assets'))
        self.fetcher = None
        self.lock = threading.Lock()
        self.countries = None

    def country_data(self):
        with self.lock:
            if self.countries is not None: return self.countries
            payload = json.loads(lzma.decompress((self.assets/'ne_50m_admin_0_countries.geojson.xz').read_bytes()))
            countries = []
            for feature in payload.get('features', []):
                geometry = feature.get('geometry') or {}
                coordinates = geometry.get('coordinates') or []
                polygons = coordinates if geometry.get('type') == 'MultiPolygon' else [coordinates] if geometry.get('type') == 'Polygon' else []
                rings = []
                for polygon in polygons:
                    if not polygon or len(polygon[0]) < 3: continue
                    ring = polygon[0]
                    simplified = ring[::max(1, len(ring)//260)]
                    if simplified[-1] != ring[-1]: simplified.append(ring[-1])
                    rings.append([[float(lat), float(lon)] for lon, lat, *_ in simplified])
                prop = feature.get('properties') or {}
                countries.append(dict(name=prop.get('NAME_EN') or prop.get('NAME') or '', rings=rings,
                    lat=prop.get('LABEL_Y'), lon=prop.get('LABEL_X')))
            self.countries = json.dumps(countries, separators=(',', ':')).encode()
            return self.countries

    def view(self, query):
        def number(key, default, low, high):
            value = float(query.get(key, [str(default)])[0])
            if not math.isfinite(value) or not low <= value <= high: raise ValueError('Invalid globe view')
            return value
        yaw = number('yaw', 25, -180, 180)
        pitch = number('pitch', 45, -82, 82)
        scale = number('scale', 5, MAP_ZOOM_MIN, MAP_ZOOM_MAX)
        width = number('width', 1024, 1, 4096)
        height = number('height', 624, 1, 4096)
        keys = globe_tiles.visible_tiles(math.radians(yaw), math.radians(pitch), (0,0,width,height),
                                        min(width,height)*globe_tiles.GLOBE_RADIUS_FACTOR*scale)
        with self.lock:
            if self.fetcher is None:
                self.fetcher = globe_tiles.GlobeTileFetcher(memory_limit=32, workers=2, cache_dir=globe_tiles.default_cache_dir())
            self.fetcher.prefetch(keys)
            ready = [dict(id=f'{key.level}/{key.row}/{key.col}', bounds=key.bounds,
                url=f'/globe/tiles/{key.level}/{key.row}/{key.col}.jpg') for key in keys if self.fetcher.ready(key)]
        return dict(radius_factor=globe_tiles.GLOBE_RADIUS_FACTOR, drag_gain=globe_tiles.GLOBE_DRAG_GAIN, tiles=ready)

    def tile(self, path):
        # Only cached/wanted tiles are served; arbitrary requests cannot trigger downloads.
        parts = path.removeprefix('/globe/tiles/').removesuffix('.jpg').split('/')
        if len(parts) != 3 or not all(part.isdigit() for part in parts): raise ValueError('Invalid tile')
        key = globe_tiles.TileKey(*(int(part) for part in parts))
        if self.fetcher is None: return None
        return self.fetcher.ready(key)
