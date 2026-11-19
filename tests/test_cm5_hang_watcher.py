import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cm5_hang_watcher", ROOT / "scripts/cm5-hang-watcher.py"
)
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)


class HangWatcherTests(unittest.TestCase):
    def test_core_ticks_exclude_aggregate_and_double_counted_guest(self):
        proc = "cpu 999 0 0 0 0\ncpu0 100 10 20 800 30 4 5 6 50 5\ncpu1 0 0 0 100 0 0 0 0 0 0\nintr 123\n"
        with patch.object(watcher, "read_text", return_value=proc) as read:
            self.assertEqual(watcher.cpu_core_ticks(), {
                "cpu0": {"total": 975, "idle": 800, "iowait": 30},
                "cpu1": {"total": 100, "idle": 100, "iowait": 0},
            })
            read.assert_called_once_with("/proc/stat")

    def test_missing_or_invalid_core_counters_are_omitted(self):
        for proc in ("", "cpu0 bad 0 0 0 0", "cpu1 1 2", "cpu2 -1 0 0 1 0"):
            with self.subTest(proc=proc), patch.object(watcher, "read_text", return_value=proc):
                self.assertEqual(watcher.cpu_core_ticks(), {})

    def test_task_names_with_spaces_and_parentheses(self):
        fields = ["0"] * 37
        fields[0], fields[11], fields[12], fields[19], fields[36] = "S", "80", "20", "123", "3"
        with patch.object(watcher, "read_text", return_value="42 (a ) worker) " + " ".join(fields)):
            self.assertEqual(watcher.task_stat("unused"), {
                "name": "a ) worker", "cpu_ticks": 100, "start_ticks": 123, "last_cpu": 3})
        with patch.object(watcher, "read_text", return_value=""):
            self.assertIsNone(watcher.task_stat("gone"))

    def test_attribution_deltas_pid_reuse_and_bounded_ranking(self):
        monitor = watcher.CPUAttribution()
        monitor.hz = 100
        def tasks(ticks, start=1):
            return {("process", i): {"name": "worker", "cpu_ticks": ticks * i,
                    "start_ticks": start, "last_cpu": i % 4} for i in range(1, 21)}
        self.assertEqual(monitor.summarize(tasks(0), 10, 1)["top_processes"], [])
        result = monitor.summarize(tasks(10), 20, 1)["top_processes"]
        self.assertEqual(len(result), 8)
        self.assertEqual(result[0]["pid"], 20)
        self.assertEqual(result[0]["cpu_percent"], 20)
        self.assertEqual(result[0]["leader_last_cpu"], 0)
        self.assertEqual(monitor.summarize(tasks(100, start=2), 30, 1)["top_processes"], [])
        self.assertEqual(monitor.summarize({}, 40, 1)["top_processes"], [])
        self.assertEqual(monitor.previous, {})

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
