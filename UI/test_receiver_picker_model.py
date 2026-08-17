import time
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from receiver_picker_model import (
    PickerFrameProfiler,
    ReceiverProjectionSnapshot,
    StationOrderCache,
    choose_nearby_receivers,
    closest_strong_spectrum_frequency,
    receiver_server_index,
    visible_station_range,
)


class StationOrderCacheTests(unittest.TestCase):
    def test_reuses_order_until_an_input_object_changes(self):
        now = time.time()
        stations = [("B", "B", "b"), ("A", "A", "a")]
        health = {"a": {"checked": now, "audio": True, "waterfall": True}}
        cache = StationOrderCache()

        first = cache.get(stations, health, "name")
        second = cache.get(stations, health, "name")
        refreshed = cache.get(stations, dict(health), "name")

        self.assertIs(first, second)
        self.assertIsNot(first, refreshed)
        self.assertEqual([station[2] for station in first], ["a", "b"])

    def test_visible_range_includes_partial_edge_rows_only(self):
        self.assertEqual(list(visible_station_range(840, 0.0, 1, 5)), [0, 1, 2, 3, 4])
        self.assertEqual(list(visible_station_range(840, 0.25, 1, 5)), [0, 1, 2, 3, 4, 5])
        self.assertEqual(list(visible_station_range(840, 835.0, 1, 5)), [835, 836, 837, 838, 839])


class ReceiverProjectionSnapshotTests(unittest.TestCase):
    def test_reuses_projection_for_lookup_and_spatial_hit_testing(self):
        receivers = [
            {"server": "left", "x": 10.0, "y": 20.0},
            {"server": "right", "x": 160.0, "y": 20.0},
        ]

        def project(receiver, _yaw, _pitch, _box, _scale):
            return receiver["x"], receiver["y"], 1.0

        snapshot = ReceiverProjectionSnapshot(receivers, 0.0, 0.0, (0, 0, 200, 100), 1.0, project)

        self.assertTrue(snapshot.matches(receivers, 0.0, 0.0, (0, 0, 200, 100), 1.0))
        self.assertEqual(snapshot.nearest(15.0, 20.0)["server"], "left")
        self.assertEqual(snapshot.receiver("right")["server"], "right")
        self.assertIsNone(snapshot.nearest(90.0, 90.0))

    def test_pointer_hits_do_not_reproject_the_directory(self):
        receivers = [
            {"server": str(index), "x": float(index), "y": 20.0}
            for index in range(840)
        ]
        projection_calls = 0

        def project(receiver, _yaw, _pitch, _box, _scale):
            nonlocal projection_calls
            projection_calls += 1
            return receiver["x"], receiver["y"], 1.0

        snapshot = ReceiverProjectionSnapshot(receivers, 0.0, 0.0, (0, 0, 840, 100), 1.0, project)
        for x in range(0, 840, 5):
            self.assertIsNotNone(snapshot.nearest(float(x), 20.0))

        self.assertEqual(projection_calls, len(receivers))

    def test_equal_distance_hit_preserves_directory_order(self):
        receivers = [
            {"server": "first", "x": 128.0, "y": 20.0},
            {"server": "second", "x": 64.0, "y": 20.0},
        ]

        def project(receiver, _yaw, _pitch, _box, _scale):
            return receiver["x"], receiver["y"], 1.0

        snapshot = ReceiverProjectionSnapshot(receivers, 0.0, 0.0, (0, 0, 200, 100), 1.0, project)
        self.assertEqual(snapshot.nearest(96.0, 20.0)["server"], "first")


class PickerFrameProfilerTests(unittest.TestCase):
    def test_reports_percentiles_at_the_requested_cadence(self):
        profiler = PickerFrameProfiler(enabled=True, report_every=2)
        self.assertIsNone(profiler.record("map", {"frame": 0.010}))
        report = profiler.record("map", {"frame": 0.020})
        self.assertIn("picker perf map", report)
        self.assertIn("p95:20.00", report)


class NearbyReceiverTests(unittest.TestCase):
    def test_finds_the_exact_highlighted_receiver_slot(self):
        candidates = (
            {"server": "strongest"},
            {"server": "tapped"},
            {"server": "third"},
        )

        self.assertEqual(receiver_server_index({"server": "tapped"}, candidates), 1)

    def test_prefers_proven_audio_within_the_local_pool(self):
        now = time.time()
        receivers = [
            {"server": "tap", "distance": 0, "used": 0, "total": 4},
            {"server": "ready", "distance": 2, "used": 0, "total": 4},
            {"server": "audio", "distance": 3, "used": 0, "total": 4},
            {"server": "unknown", "distance": 1, "used": 0, "total": 4},
        ]
        health = {
            "ready": {"checked": now, "audio": True, "waterfall": True},
            "audio": {"checked": now, "audio": True, "waterfall": False},
        }

        chosen = choose_nearby_receivers(
            receivers[0], receivers, health,
            lambda _anchor, receiver: receiver["distance"],
            limit=3, pool_size=4,
        )

        self.assertEqual([receiver["server"] for receiver in chosen], ["ready", "audio", "tap"])

    def test_skips_a_full_receiver_before_otherwise_equal_health(self):
        now = time.time()
        receivers = [
            {"server": "full", "distance": 0, "used": 4, "total": 4},
            {"server": "open", "distance": 1, "used": 0, "total": 4},
        ]
        health = {
            server: {"checked": now, "audio": True, "waterfall": True}
            for server in ("full", "open")
        }
        chosen = choose_nearby_receivers(
            receivers[0], receivers, health,
            lambda _anchor, receiver: receiver["distance"],
            limit=2, pool_size=2,
        )
        self.assertEqual(chosen[0]["server"], "open")


class SpectrumPeakTests(unittest.TestCase):
    def test_selects_the_strongest_peak_even_when_farther_from_center(self):
        values = [0.10] * 9
        values[1] = 0.95
        values[5] = 0.70
        self.assertAlmostEqual(
            closest_strong_spectrum_frequency(values, 1000.0, 90.0),
            970.0,
        )

    def test_returns_none_for_noise_without_a_clear_peak(self):
        self.assertIsNone(
            closest_strong_spectrum_frequency([0.20, 0.21, 0.20, 0.21, 0.20], 1000.0, 50.0)
        )


if __name__ == "__main__":
    unittest.main()
