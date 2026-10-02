#!/usr/bin/python3
"""Read the ES8316's volatile jack flag without changing codec registers."""
import json
import os
from pathlib import Path
import time

REGISTERS = Path('/sys/kernel/debug/regmap/1-0010/registers')
STATE = Path('/run/cm5-headphone/state.json')


def read_inserted():
    for line in REGISTERS.read_text().splitlines():
        address, _, value = line.partition(':')
        if address.strip() == '4f':
            # Bench verified on this carrier: 0x26 inserted, 0x22 removed.
            return bool(int(value.strip(), 16) & 0x04)
    raise ValueError('ES8316 jack flag missing')


def main():
    candidate = None
    count = 0
    stable = None
    reported = object()
    while True:
        try:
            value = read_inserted()
            count = count + 1 if value == candidate else 1
            candidate = value
            if count >= 3:
                stable = value
        except (OSError, ValueError):
            candidate = stable = None
            count = 0
        if stable != reported:
            print('Headphones: ' + {True: 'inserted', False: 'removed', None: 'unknown; speaker inhibited'}[stable], flush=True)
            reported = stable
        temporary = STATE.with_suffix('.tmp')
        temporary.write_text(json.dumps({'inserted': stable, 'monotonic': time.monotonic()}) + '\n')
        os.chmod(temporary, 0o644)
        temporary.replace(STATE)
        time.sleep(0.1)


if __name__ == '__main__':
    main()
