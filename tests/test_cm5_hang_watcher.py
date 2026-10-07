import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cm5_hang_watcher", ROOT / "scripts/cm5-hang-watcher.py"
)
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


class HangWatcherTests(unittest.TestCase):
    def sample(self):
        return {
            "mem_available_kb": 500_000,
            "root_free_mb": 2048,
            "temperature_c": 50,
            "throttled": 0,
            "ituner": {"pid": 10, "state": "S", "cpu_ticks": 100},
            "pressure": {"memory": {"some_avg10": 0}, "io": {"some_avg10": 0}},
        }

    def test_healthy_sample_has_no_warning(self):
        self.assertEqual(watcher.warnings(self.sample()), [])

    def test_detects_power_memory_and_blocked_process(self):
        sample = self.sample()
        sample.update(mem_available_kb=1000, throttled=0x50005)
        sample["ituner"]["state"] = "D"
        self.assertEqual(
            watcher.warnings(sample),
            ["low_memory", "power_or_throttle_0x50005", "ituner_state_D"],
        )

    def test_persistent_log_and_report_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch.jsonl"
            watcher.append_record(path, {"kind": "sample", "warnings": []})
            watcher.append_record(path, {"kind": "sample", "warnings": ["low_disk"]})
            self.assertEqual(watcher.report(path), 0)


if __name__ == "__main__":
    unittest.main()
