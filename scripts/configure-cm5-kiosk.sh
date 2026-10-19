#!/usr/bin/env bash
# Run as the logged-in display user; keep the verified Wayland/touch session.
set -Eeuo pipefail
[[ $EUID -ne 0 ]] || { echo 'Run as the display user, without sudo.' >&2; exit 1; }
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
[[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]] || { echo 'No running Wayland session.' >&2; exit 1; }
command -v swaybg >/dev/null
# Raspberry Pi OS starts labwc with -m: both system and user autostart run.
pgrep -u "$(id -u)" -f '^/usr/bin/labwc -m$' >/dev/null || {
    echo 'This profile requires the Raspberry Pi labwc -m session.' >&2; exit 1;
}

python3 - <<'PY'
from pathlib import Path
import shutil
import time

home = Path.home()
target = home/'.config/labwc/autostart'
source = target if target.exists() else Path('/etc/xdg/labwc/autostart')
text = source.read_text()
marker = '# iTuner kiosk: desktop shell disabled; compositor and touch retained.'
if marker not in text:
    backup = home/'.local/state/ituner-sdr/kiosk'/time.strftime('%Y%m%d-%H%M%S')
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup/'autostart')
    (backup/'source.txt').write_text(str(source)+'\n')
    print('Original autostart saved in', backup)
# System autostart already supplies kanshi and XDG startup in merged mode.
# Retain unrelated custom user startup lines, without copying system commands.
remove = {'/usr/bin/lwrespawn /usr/bin/pcmanfm-pi &',
          '/usr/bin/lwrespawn /usr/bin/wf-panel-pi &',
          '/usr/bin/kanshi &', '/usr/bin/lxsession-xdg-autostart', marker,
          '/usr/bin/swaybg -c "#000000" >/dev/null 2>&1 &'}
lines = [line for line in text.splitlines() if line.strip() not in remove] if source == target else []
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(marker+'\n/usr/bin/swaybg -c "#000000" >/dev/null 2>&1 &\n'+'\n'.join(lines)+'\n')
target.chmod(0o755)
PY

# Preserve system startup for other users; gate only the two desktop programs
# on the per-user kiosk marker. Back up /etc before the first edit.
sudo python3 - <<'PY'
from pathlib import Path
import shutil
target = Path('/etc/xdg/labwc/autostart')
text = target.read_text()
marker = '# iTuner kiosk guard (merged labwc autostart)'
if marker not in text:
    backup = Path('/var/lib/ituner-sdr/kiosk')
    backup.mkdir(parents=True, exist_ok=True)
    if not (backup/'system-autostart').exists():
        shutil.copy2(target, backup/'system-autostart')
    commands = {'/usr/bin/lwrespawn /usr/bin/pcmanfm-pi &',
                '/usr/bin/lwrespawn /usr/bin/wf-panel-pi &'}
    if not commands.issubset({line.strip() for line in text.splitlines()}):
        raise SystemExit('Unrecognized system autostart; desktop startup was not changed.')
    lines = []
    for line in text.splitlines():
        if line.strip() in commands:
            lines.extend(['if ! grep -qF "# iTuner kiosk:" "$HOME/.config/labwc/autostart" 2>/dev/null; then', line, 'fi'])
        else:
            lines.append(line)
    target.write_text(marker+'\n'+'\n'.join(lines)+'\n')
PY

# Stop the restart wrappers first; otherwise they relaunch the desktop shell.
pkill -u "$(id -u)" -f '^/bin/sh /usr/bin/lwrespawn /usr/bin/(pcmanfm-pi|wf-panel-pi)$' || true
pkill -u "$(id -u)" -f '^pcmanfm --desktop$' || true
pkill -u "$(id -u)" -f '^/usr/bin/wf-panel-pi$' || true
pkill -u "$(id -u)" -f '^/bin/sh /usr/bin/pcmanfm-pi$' || true
if ! pgrep -u "$(id -u)" -f '^/usr/bin/swaybg -c #000000$' >/dev/null; then
    nohup /usr/bin/swaybg -c '#000000' >/dev/null 2>&1 </dev/null &
fi
echo 'Desktop wallpaper and taskbar stopped. SDR, Wayland, output mapping and touch remain running.'
