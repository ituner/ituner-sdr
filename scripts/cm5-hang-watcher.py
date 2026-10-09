#!/usr/bin/python3
"""Persistent low-overhead flight recorder for CM5 lockups."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

DEFAULT_LOG = Path("/var/log/ituner-sdr/hang-watcher.jsonl")
DEFAULT_STATE = Path("/var/lib/ituner-sdr/hang-watcher-state.json")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
stopping = False


def read_text(path, default=""):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def command(*args, timeout=3):
    try:
        return subprocess.run(
            args, check=False, text=True, capture_output=True, timeout=timeout,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def key_values(path):
    values = {}
    for line in read_text(path).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key] = value.strip()
    return values


def pressure(kind):
    values = {}
    for line in read_text(f"/proc/pressure/{kind}").splitlines():
        fields = line.split()
        if not fields:
            continue
        for field in fields[1:]:
            key, _, value = field.partition("=")
            if key in ("avg10", "total"):
                try:
                    values[f"{fields[0]}_{key}"] = float(value) if key == "avg10" else int(value)
                except ValueError:
                    pass
    return values


def process_sample(pid):
    if pid <= 0:
        return {"pid": 0, "state": "missing"}
    stat = read_text(f"/proc/{pid}/stat").split()
    status = key_values(f"/proc/{pid}/status")
    try:
        fds = len(tuple(Path(f"/proc/{pid}/fd").iterdir()))
    except OSError:
        fds = -1
    return {
        "pid": pid,
        "state": stat[2] if len(stat) > 14 else "missing",
        "cpu_ticks": int(stat[13]) + int(stat[14]) if len(stat) > 14 else 0,
        "rss_kb": int(status.get("VmRSS", "0 kB").split()[0]),
        "threads": int(status.get("Threads", "0")),
        "fds": fds,
    }


def collect():
    mem = key_values("/proc/meminfo")
    load = read_text("/proc/loadavg").split()
    thermal = read_text("/sys/class/thermal/thermal_zone0/temp", "0")
    try:
        main_pid = int(command("systemctl", "show", "ituner-sdr.service", "-p", "MainPID", "--value") or 0)
    except ValueError:
        main_pid = 0
    throttled_text = command("vcgencmd", "get_throttled")
    try:
        throttled = int(throttled_text.rsplit("=", 1)[-1], 16)
    except ValueError:
        throttled = -1
    disk = shutil.disk_usage("/")
    drm = {}
    for path in Path("/sys/class/drm").glob("card*-DSI-*/status"):
        drm[path.parent.name] = read_text(path)
    return {
        "kind": "sample",
        "time": time.time(),
        "monotonic": time.monotonic(),
        "boot_id": read_text(BOOT_ID),
        "uptime_s": float(read_text("/proc/uptime", "0").split()[0]),
        "load": [float(value) for value in load[:3]] if len(load) >= 3 else [],
        "mem_available_kb": int(mem.get("MemAvailable", "0 kB").split()[0]),
        "swap_free_kb": int(mem.get("SwapFree", "0 kB").split()[0]),
        "temperature_c": round(int(thermal) / 1000, 1),
        "throttled": throttled,
        "root_free_mb": disk.free // (1024 * 1024),
        "pressure": {name: pressure(name) for name in ("cpu", "memory", "io")},
        "ituner": process_sample(main_pid),
        "usb_devices": max(0, len(command("lsusb").splitlines())),
        "alsa_cards": len(tuple(Path("/proc/asound").glob("card[0-9]*"))),
        "drm": drm,
    }


def warnings(sample, previous=None):
    found = []
    if sample["mem_available_kb"] < 150_000:
        found.append("low_memory")
    if sample["root_free_mb"] < 512:
        found.append("low_disk")
    if sample["temperature_c"] >= 80:
        found.append("over_temperature")
    if sample["throttled"] not in (0, -1):
        found.append(f"power_or_throttle_0x{sample['throttled']:x}")
    if sample["ituner"]["state"] in ("missing", "D", "Z"):
        found.append(f"ituner_state_{sample['ituner']['state']}")
    for kind in ("memory", "io"):
        if sample["pressure"].get(kind, {}).get("some_avg10", 0) >= 20:
            found.append(f"{kind}_pressure")
    if previous and sample["ituner"]["pid"] == previous.get("ituner", {}).get("pid"):
        if sample["ituner"]["cpu_ticks"] == previous.get("ituner", {}).get("cpu_ticks"):
            found.append("ituner_cpu_stalled")
    return found


def append_record(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def save_state(path, sample, clean=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"clean": clean, "sample": sample}) + "\n")
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def diagnostic_tail():
    return command(
        "journalctl", "-k", "--since=-45 seconds", "-p", "warning",
        "--no-pager", "-o", "short-monotonic", timeout=5,
    )[-12000:]


def report(path):
    records = []
    try:
        with path.open() as handle:
            for line in handle:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError as error:
        print(error)
        return 1
    for record in records[-30:]:
        if record.get("kind") != "sample" or record.get("warnings"):
            print(json.dumps(record, indent=2))
    samples = [record for record in records if record.get("kind") == "sample"]
    if samples:
        print("LAST SAMPLE")
        print(json.dumps(samples[-1], indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if args.report:
        return report(args.log)

    def stop(_signum, _frame):
        global stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    previous_state = {}
    try:
        previous_state = json.loads(args.state.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    now_boot = read_text(BOOT_ID)
    previous_sample = previous_state.get("sample", {})
    append_record(args.log, {
        "kind": "start", "time": time.time(), "boot_id": now_boot,
        "previous_clean": previous_state.get("clean"),
        "previous_boot_id": previous_sample.get("boot_id"),
        "previous_time": previous_sample.get("time"),
        "gap_s": round(time.time() - previous_sample.get("time", time.time()), 1),
    })
    previous = None
    while not stopping:
        started = time.monotonic()
        sample = collect()
        sample["warnings"] = warnings(sample, previous)
        if sample["warnings"]:
            sample["kernel_warnings"] = diagnostic_tail()
        append_record(args.log, sample)
        save_state(args.state, sample)
        previous = sample
        time.sleep(max(0.1, args.interval - (time.monotonic() - started)))
    save_state(args.state, previous or collect(), clean=True)
    append_record(args.log, {"kind": "stop", "time": time.time(), "boot_id": now_boot})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
