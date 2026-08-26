#!/usr/bin/env python3
"""Quiet, bounded software curve for the Pi pwm-fan cooling device."""
import json
import os
import time
from pathlib import Path

CONFIG = Path(os.environ.get("ITUNER_FAN_CONFIG", "/var/lib/ituner-sdr/fan-curve.json"))
COOLING_STATE = Path("/sys/class/thermal/cooling_device0/cur_state")
CPU_TEMP = Path("/sys/class/thermal/thermal_zone0/temp")
# The application writes this JSON atomically and this service rereads it once
# per second. Temperature and minimum-speed changes therefore take effect live
# without a reboot or service restart.
DEFAULT = {"start_c": 56.0, "full_c": 75.0, "min_percent": 15.0}
STATE_DUTY = (0.0, 15.0, 40.0, 70.0, 100.0)
STOP_HYSTERESIS_C = 3.0
CHANGE_INTERVAL_SECONDS = 4.0


def curve_config():
    try:
        saved = json.loads(CONFIG.read_text())
    except (OSError, ValueError, TypeError):
        saved = {}
    try:
        start = min(65.0, max(45.0, float(saved.get("start_c", DEFAULT["start_c"]))))
        full = min(82.0, max(start + 8.0, float(saved.get("full_c", DEFAULT["full_c"]))))
        minimum = min(70.0, max(10.0, float(saved.get("min_percent", DEFAULT["min_percent"]))))
    except (TypeError, ValueError):
        return DEFAULT.copy()
    return {"start_c": start, "full_c": full, "min_percent": minimum}


def desired_state(temp_c, start_c, full_c, minimum_percent):
    if temp_c <= start_c - STOP_HYSTERESIS_C:
        return 0
    # At the start threshold, honor the operator's chosen minimum. The old
    # state-1 shortcut silently forced 15% here even when START SPEED was 70%.
    duty = minimum_percent if temp_c <= start_c else minimum_percent + (
        (100.0 - minimum_percent) * min(1.0, (temp_c - start_c) / max(1.0, full_c - start_c))
    )
    return min(range(1, len(STATE_DUTY)), key=lambda state: abs(STATE_DUTY[state] - duty))


def read_int(path, fallback=0):
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return fallback


def main():
    current = read_int(COOLING_STATE)
    filtered_temp = None
    last_change = 0.0
    while True:
        raw_temp = read_int(CPU_TEMP) / 1000.0
        filtered_temp = raw_temp if filtered_temp is None else filtered_temp * 0.78 + raw_temp * 0.22
        config = curve_config()
        target = desired_state(
            filtered_temp,
            config["start_c"],
            config["full_c"],
            config["min_percent"],
        )
        now = time.monotonic()
        observed = read_int(COOLING_STATE, current)
        if observed != current:
            current = observed
        # Move one hardware level at a time. The curve cannot make this
        # four-level fan physically continuous, but it never slams directly
        # from quiet to full or oscillates around a trip threshold.
        if target != current and now - last_change >= CHANGE_INTERVAL_SECONDS:
            next_state = current + (1 if target > current else -1)
            try:
                COOLING_STATE.write_text(str(next_state))
                current = next_state
                last_change = now
            except OSError as exc:
                print(f"fan curve write failed: {exc}", flush=True)
        time.sleep(1.0)


if __name__ == "__main__":
    main()
