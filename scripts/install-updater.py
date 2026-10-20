#!/usr/bin/env python3
"""One-time updater setup, also called by both Pi installers.

Pi: sudo python3 scripts/install-updater.py --user ituner
Mac: UI/.venv/bin/python scripts/install-updater.py --root ~/Applications/ituner-sdr
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', default=os.environ.get('SUDO_USER'))
    parser.add_argument('--root', type=Path)
    parser.add_argument('--commit', default='')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(source / 'UI'))
    from app_update import atomic_json, PROTOCOL
    mac = sys.platform == 'darwin'
    if not mac and (os.geteuid() != 0 or not args.user or not re.fullmatch(r'[a-z_][a-z0-9_-]*', args.user)):
        parser.error('On Pi, run with sudo and --user APPLICATION_USER.')
    root = (args.root or (Path.home() / 'Applications/ituner-sdr' if mac else Path('/opt/ituner-sdr'))).resolve()
    if not mac and root != Path('/opt/ituner-sdr'):
        parser.error('The Pi updater only supports /opt/ituner-sdr.')
    if not (root / 'UI/kiwi_gl_display.py').is_file():
        parser.error('Install the application before installing the updater.')
    home = Path.home() if mac else Path(pwd.getpwnam(args.user).pw_dir)
    state = home / 'Library/Application Support/iTuner/updates' if mac else Path('/var/lib/ituner-sdr/updates')
    state.mkdir(parents=True, exist_ok=True, mode=0o700 if mac else 0o755)
    info = home / ('Library/Application Support/iTuner/update-runtime.json' if mac else '.local/state/ituner/update-runtime.json')
    info.parent.mkdir(parents=True, exist_ok=True)
    if not mac:
        user = pwd.getpwnam(args.user)
        os.chown(info.parent, user.pw_uid, user.pw_gid)
    cfg = dict(protocol=PROTOCOL, platform='darwin' if mac else 'linux', root=str(root),
               state=str(state), runtime_info=str(info), user=args.user or pwd.getpwuid(os.getuid()).pw_name,
               python=sys.executable if mac else '/usr/bin/python3')
    path = state / 'config.json' if mac else Path('/etc/ituner-update.json')
    atomic_json(path, cfg); path.chmod(0o600 if mac else 0o644)
    if not mac:
        helper = Path('/usr/local/sbin/ituner-update')
        helper.write_text('#!/usr/bin/python3\n' + (source / 'UI/app_update.py').read_text())
        helper.chmod(0o755)
        rule = state / 'sudoers-candidate'
        rule.write_text(f'{args.user} ALL=(root) NOPASSWD: /usr/local/sbin/ituner-update *\n')
        subprocess.run(['visudo', '-cf', str(rule)], check=True)
        shutil.copyfile(rule, '/etc/sudoers.d/ituner-update')
        Path('/etc/sudoers.d/ituner-update').chmod(0o440); rule.unlink()
        dropin = Path('/etc/systemd/system/ituner-sdr.service.d/updater.conf')
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text('[Service]\nExecStartPre=+/usr/local/sbin/ituner-update recover stable\n')
        subprocess.run(['systemctl', 'daemon-reload'], check=True)
    commit = args.commit
    if not commit:
        result = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True)
        commit = result.stdout.strip() if result.returncode == 0 else ''
    if commit and not re.fullmatch('[0-9a-f]{40}', commit):
        parser.error('Commit must be a full Git SHA.')
    version = (root / 'VERSION').read_text().strip() if (root / 'VERSION').exists() else 'unversioned'
    if not (root / '.ituner-installed.json').exists() or args.commit:
        atomic_json(root / '.ituner-installed.json', dict(version=version, commit=commit, channel='development'))
    print('Application updater installed:', path)


if __name__ == '__main__':
    main()
