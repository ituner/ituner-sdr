#!/usr/bin/env python3
"""Build the bundled globe from the same NASA GIBS product as its HD tiles.

Requires Pillow only when rebuilding assets, never at application startup.
Level 3 exactly covers the world with ten columns and five rows of 512px
tiles. Keeping the imagery product identical avoids ocean-color changes when
the renderer exposes its bundled fallback during a swipe or tile download.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import sys
from urllib.request import Request, urlopen

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "UI"))
from globe_tiles import TileKey, TILE_PIXELS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "UI" / "assets")
    args = parser.parse_args()

    def load(key):
        path = args.cache_dir / str(key.level) / str(key.row) / f"{key.col}.jpeg"
        if not path.exists():
            request = Request(key.url, headers={"User-Agent": "ituner-sdr-globe-assets/1"})
            with urlopen(request, timeout=30) as response:
                payload = response.read()
            # Validate before caching a response, including the expected size.
            with Image.open(io.BytesIO(payload)) as tile:
                assert tile.size == (TILE_PIXELS, TILE_PIXELS), key
                tile.load()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        with Image.open(path) as tile:
            assert tile.size == (TILE_PIXELS, TILE_PIXELS), key
            return key, tile.convert("RGB")

    keys = [TileKey(3, row, col) for row in range(5) for col in range(10)]
    world = Image.new("RGB", (10 * TILE_PIXELS, 5 * TILE_PIXELS))
    with ThreadPoolExecutor(max_workers=4) as workers:
        for key, tile in workers.map(load, keys):
            world.paste(tile, (key.col * TILE_PIXELS, key.row * TILE_PIXELS))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for width in (2048, 4096):
        path = args.output_dir / f"nasa-blue-marble-{width}.jpg"
        world.resize((width, width // 2), Image.Resampling.LANCZOS).save(
            path, quality=95, subsampling=0, optimize=True,
        )
        print(path)


if __name__ == "__main__":
    main()
