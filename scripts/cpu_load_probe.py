#!/usr/bin/env python3
"""Bounded, adjustable CPU-load probe for SDR audio diagnostics.

This intentionally has no dependency on the display service. It creates a
repeatable duty-cycled load and exits automatically, making it useful for
separating audio/network jitter from local scheduling pressure.
"""

import argparse
import multiprocessing as mp
import os
import signal
import time


def worker(stop_event, duty, period):
    """Burn CPU for a fraction of each period, then yield for the remainder."""
    # The controller terminates workers by setting the shared Event. Keep the
    # child signal disposition conventional so an emergency SIGTERM is also
    # immediate and cannot leave an orphaned stress worker behind.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    while not stop_event.is_set():
        started = time.monotonic()
        busy_until = started + period * duty
        value = 0x13579BDF
        while time.monotonic() < busy_until and not stop_event.is_set():
            value = (value * 1664525 + 1013904223) & 0xFFFFFFFF
        remaining = started + period - time.monotonic()
        if remaining > 0:
            stop_event.wait(remaining)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=2, help="load processes (default: 2)")
    parser.add_argument("--duty", type=float, default=0.5, help="per-worker duty cycle, 0.0..1.0")
    parser.add_argument("--duration", type=float, default=180.0, help="automatic stop time in seconds")
    parser.add_argument("--period-ms", type=float, default=20.0, help="load/yield period in ms")
    args = parser.parse_args()

    workers = max(1, min(int(args.workers), os.cpu_count() or 1))
    duty = max(0.0, min(float(args.duty), 1.0))
    duration = max(1.0, float(args.duration))
    period = max(0.001, float(args.period_ms) / 1000.0)

    stop_event = mp.Event()

    def stop(_signal, _frame):
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    processes = [mp.Process(target=worker, args=(stop_event, duty, period), daemon=True) for _ in range(workers)]
    for process in processes:
        process.start()
    print(
        f"cpu-load-probe started: workers={workers} duty={duty:.0%} "
        f"duration={duration:.0f}s pid={os.getpid()}",
        flush=True,
    )
    try:
        stop_event.wait(duration)
    finally:
        stop_event.set()
        for process in processes:
            process.join(timeout=1.0)
            if process.is_alive():
                process.terminate()
        print("cpu-load-probe stopped", flush=True)


if __name__ == "__main__":
    main()
