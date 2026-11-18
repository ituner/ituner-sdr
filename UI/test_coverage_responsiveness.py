"""Run on CM5 with its installed ADS-B dependencies; no live history is modified."""
import dataclasses
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CoverageTests(unittest.TestCase):
    def test_hidden_views_do_not_rebuild_but_visible_views_do(self):
        m = load('coverage_demand_test', ROOT / 'adsb_coverage.py')
        with tempfile.TemporaryDirectory() as directory:
            coverage = m.ReceptionCoverage(directory)
            site = {'lat': 37.66, 'lon': -121.87}
            with patch.object(coverage, 'build', wraps=coverage.build) as build:
                coverage.tick(site)
                self.assertEqual(build.call_count, 0)
                coverage.requested, coverage.key = True, None
                coverage.tick(site)
                self.assertEqual(build.call_count, 0)
                self.assertEqual(coverage.snapshot()['status'], 'LOADING')
                coverage.tick(site)
                self.assertEqual(build.call_count, 1)
                coverage.requested, coverage.key, coverage.next_build = True, None, 0
                coverage.full_used_at -= 13
                coverage.tick(site)
                self.assertEqual(build.call_count, 1)
                coverage.snapshot(time.time() - 60)
                coverage.tick(site)
                self.assertEqual(build.call_count, 2)
            coverage.close()
            self.assertTrue((Path(directory) / 'coverage.sqlite3').exists())

    def test_batched_geometry_preserves_history_and_statistics(self):
        from adsb_coverage import ecef
        new = load('coverage_cache_after', ROOT / 'adsb_coverage_cache.py')
        site = {'lat': 37.66, 'lon': -121.87}
        rows = [(1000 + i / 4, f'{i % 9:06x}', 37.66 + i * .00001,
                 -121.87 + i * .00002, 10000 + i, 1, -20 + i % 5, 'TEST')
                for i in range(1025)]
        origin = ecef(site['lat'], site['lon'], 0)
        a = new._project_rows_batch(rows, site, 10, origin)
        with patch.object(new.time, 'sleep') as sleep:
            b = new.project_rows(rows, site, 10, origin)
            self.assertEqual(sleep.call_count, 8)
        self.assertEqual([dataclasses.astuple(x) for x in a],
                         [dataclasses.astuple(x) for x in b])
        for batches in ((slice(0, None),), (slice(0, 700), slice(650, None))):
            before = new.CoverageAccumulator(site, 10, None)
            after = new.CoverageAccumulator(site, 10, None)
            for batch in batches:
                for record in a[batch]:
                    before.append([record])
                after.append(b[batch])
            self.assertEqual(before.snapshot({}, [], 1000), after.snapshot({}, [], 1000))


if __name__ == '__main__':
    unittest.main()
