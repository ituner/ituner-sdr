#!/usr/bin/env python3
"""Configure the V4 internal hub's USB host, preserving unrelated boot settings."""
import argparse
from pathlib import Path
import re
import shutil
import tempfile


def host_config(text):
    section = 'all'
    lines = []
    host_found = False
    for line in text.splitlines(keepends=True):
        setting = line.split('#', 1)[0].strip()
        if setting.startswith('[') and setting.endswith(']'):
            section = setting[1:-1]
        if section in ('all', 'cm5', 'pi5') and re.match(r'^dtoverlay\s*=\s*dwc2(?:,|$)', setting):
            params = setting.split(',')[1:]
            params = [p for p in params if not p.strip().startswith('dr_mode=')]
            # Preserve optional FIFO/driver parameters on this overlay.
            updated = 'dtoverlay=dwc2,dr_mode=host' + ''.join(',' + p for p in params)
            if host_found and not params:
                lines.append('# V4 internal hub: duplicate/device-mode DWC2 override removed.\n')
            else:
                comment = ' #' + line.split('#', 1)[1].rstrip('\n') if '#' in line else ''
                lines.append(updated + comment + '\n')
                host_found = True
        else:
            lines.append(line)
    result = ''.join(lines)
    if not host_found:
        result = result.rstrip('\n') + '\n\n# V4 internal USB hub requires a host controller.\n[cm5]\ndtoverlay=dwc2,dr_mode=host\n[all]\n'
    return result


def host_cmdline(text):
    if len(text.strip().splitlines()) != 1:
        raise ValueError('cmdline.txt must contain one nonempty command line')
    # Remove only the obsolete serial gadget; retain other boot parameters.
    def modules(match):
        values = [v for v in match.group(1).split(',') if v != 'g_serial']
        return 'modules-load=' + ','.join(values) if values else ''
    return re.sub(r'(?<!\S)modules-load=([^\s]+)', modules, text)


def configure(config, cmdline):
    before = {config: config.read_text(), cmdline: cmdline.read_text()}
    after = {config: host_config(before[config]), cmdline: host_cmdline(before[cmdline])}
    if before == after:
        return None
    backup = Path(tempfile.mkdtemp(prefix='ituner-v4-usb-host-backup-', dir=config.parent))
    for path in before:
        shutil.copy2(path, backup / path.name)
    try:
        for path, text in after.items():
            if text != before[path]:
                path.write_text(text)
    except OSError:
        for path in before:
            shutil.copy2(backup / path.name, path)
        raise
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot-config', type=Path, default=Path('/boot/firmware/config.txt'))
    parser.add_argument('--cmdline', type=Path, default=Path('/boot/firmware/cmdline.txt'))
    args = parser.parse_args()
    backup = configure(args.boot_config, args.cmdline)
    if backup:
        print(f'V4 USB host configured; backup: {backup}. Reboot required.')
    else:
        print('V4 USB host boot settings already configured.')


if __name__ == '__main__':
    main()
