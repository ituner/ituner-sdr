import math
import tempfile
import threading
import time
import unittest

import globe_tiles


class GlobeTileGeometryTests(unittest.TestCase):
    BOX = (0, 0, 1024, 800)

    @staticmethod
    def radius(scale):
        return 800 * 0.92 * scale

    def test_close_cm5_view_uses_verified_500m_tile_grid(self):
        keys = globe_tiles.visible_tiles(
            math.radians(26), math.radians(44), self.BOX, self.radius(1200),
        )
        self.assertLessEqual(len(keys), globe_tiles.MAX_VISIBLE_TILES)
        self.assertEqual(keys[0], globe_tiles.TileKey(7, 20, 91))
        self.assertEqual(keys[0].bounds, (24.75, 42.75, 27.0, 45.0))
        self.assertEqual(
            keys[0].url,
            "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/"
            "BlueMarble_NextGeneration/default/500m/7/20/91.jpeg",
        )

    def test_crossing_dateline_requests_both_sides_of_the_world(self):
        keys = globe_tiles.visible_tiles(
            math.radians(179.99), 0.0, self.BOX, self.radius(1200),
        )
        columns = {key.col for key in keys}
        self.assertIn(159, columns)
        self.assertIn(0, columns)
        self.assertLessEqual(len(keys), globe_tiles.MAX_VISIBLE_TILES)

    def test_fetch_happens_on_background_worker(self):
        caller = threading.get_ident()
        downloaded = threading.Event()
        worker_ids = []

        def loader(_key):
            worker_ids.append(threading.get_ident())
            downloaded.set()
            return b"\xff\xd8test\xff\xd9"

        fetcher = globe_tiles.GlobeTileFetcher(loader=loader, workers=1)
        key = globe_tiles.TileKey(7, 20, 91)
        fetcher.prefetch((key,))
        self.assertTrue(downloaded.wait(1.0))
        self.assertNotEqual(worker_ids, [caller])
        # The worker writes the cache just after signalling that it ran.
        for _ in range(100):
            if fetcher.ready(key) is not None:
                break
            time.sleep(0.001)
        self.assertEqual(fetcher.ready(key), b"\xff\xd8test\xff\xd9")

    def test_visited_tiles_survive_restart_without_another_download(self):
        key = globe_tiles.TileKey(7, 20, 91)
        with tempfile.TemporaryDirectory() as directory:
            first = globe_tiles.GlobeTileFetcher(
                loader=lambda _key: b"\xff\xd8cached\xff\xd9",
                workers=1, cache_dir=directory,
            )
            first.prefetch((key,))
            for _ in range(100):
                if first.ready(key) is not None:
                    break
                time.sleep(0.001)
            self.assertEqual(first.ready(key), b"\xff\xd8cached\xff\xd9")

            calls = []
            second = globe_tiles.GlobeTileFetcher(
                loader=lambda _key: calls.append(_key),
                workers=1, cache_dir=directory,
            )
            second.prefetch((key,))
            for _ in range(100):
                if second.ready(key) is not None:
                    break
                time.sleep(0.001)
            self.assertEqual(second.ready(key), b"\xff\xd8cached\xff\xd9")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
