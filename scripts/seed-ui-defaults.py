#!/usr/bin/env python3
"""Seed the LCD appearance on first install without replacing saved settings."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--defaults", type=Path, required=True)
    args = parser.parse_args()
    state = args.home / ".local/state/kiwi-gl-display-receiver.json"
    if state.exists():
        print("Preserved existing receiver and UI settings.")
        return
    settings = {}
    for line in args.config.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, separator, value = line.partition("=")
            if separator:
                settings[key.strip()] = value.strip()
    initial = {
        "server": settings["ITUNER_SDR_SERVER"],
        "freq_khz": float(settings.get("ITUNER_SDR_FREQUENCY_KHZ", "7075.794")),
        "zoom": 13,
        "preferences": json.loads(args.defaults.read_text()),
    }
    state.parent.mkdir(parents=True, exist_ok=True)
    try:
        with state.open("x") as stream:
            json.dump(initial, stream, indent=2)
            stream.write("\n")
    except FileExistsError:
        print("Preserved settings created by another process.")
    else:
        print("Seeded compact LCD layout and Oxanium font.")


if __name__ == "__main__":
    main()
