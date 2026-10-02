#!/usr/bin/env python3
"""Add only the CM5 audio boot settings, or select its tested ALSA backend."""
import argparse
import json
from pathlib import Path


def boot_config(text):
    active = set()
    section = 'all'
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        elif section in ('all', 'pi5', 'cm5'):
            active.add(line)
    additions = [line for line in ('dtoverlay=cm5-main-es8316', 'gpio=13=op,dl')
                 if line not in active]
    if not additions:
        return text
    return text.rstrip('\n') + '\n\n[all]\n# CM5 carrier ES8316 audio (display settings preserved)\n' + '\n'.join(additions) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--boot-config', type=Path)
    group.add_argument('--preferences', type=Path)
    args = parser.parse_args()
    if args.boot_config:
        before = args.boot_config.read_text()
        after = boot_config(before)
        if before != after:
            args.boot_config.write_text(after)
    elif args.preferences.exists():
        settings = json.loads(args.preferences.read_text())
        preferences = settings.setdefault('preferences', {})
        if preferences.get('audio_backend') != 'alsa':
            preferences['audio_backend'] = 'alsa'
            args.preferences.write_text(json.dumps(settings, indent=2) + '\n')


if __name__ == '__main__':
    main()
