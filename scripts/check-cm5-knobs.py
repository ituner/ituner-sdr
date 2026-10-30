#!/usr/bin/env python3
"""Print raw logical knob clicks without tuning the receiver or grabbing input."""
import argparse
from collections import Counter
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'UI'))
from knob_input import LinuxKnobReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=120)
    args = parser.parse_args()
    reader = LinuxKnobReader()
    totals = Counter()
    previous = None
    deadline = time.monotonic() + args.duration
    try:
        while time.monotonic() < deadline:
            events = reader.poll()
            status = (tuple(sorted(name for _fd, name in reader.devices.values())), tuple(sorted(reader.errors.items())))
            if status != previous:
                print('Devices:', status[0], 'Errors:', status[1], flush=True)
                previous = status
            for event in events:
                if event.kind == 'turn':
                    totals[event.role] += event.value
                print(event.role, event.kind, event.value, 'net clicks:', totals[event.role], flush=True)
            time.sleep(.01)
    except KeyboardInterrupt:
        pass
    finally:
        reader.close()
        print('Net rotation totals:', dict(totals), flush=True)


if __name__ == '__main__':
    main()
