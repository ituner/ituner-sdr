#!/usr/bin/env bash
# ONLY for the iTuner custom CM5 carriers. V4 uses active-high USB power;
# the earlier board uses the complementary active-low USB3 workaround.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
grep -aq 'Compute Module 5' /proc/device-tree/model || { echo 'CM5 required.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
boot=/boot/firmware/config.txt
v4=0
if [[ ${1:-} == --v4 ]]; then
    v4=1
    shift
elif grep -q '^dtoverlay=cm5-v4-display-touch\(,\|$\)' "$boot"; then
    v4=1
fi
[[ $# -eq 0 ]] || { echo 'Usage: enable-cm5-usb3.sh [--v4]' >&2; exit 2; }
if ((v4)); then
    python3 "$repo/scripts/configure-cm5-usb-host.py"
    cp -a "$boot" "$boot.before-ituner-usb3-$(date -u +%Y%m%dT%H%M%SZ)"
    python3 - "$boot" <<'PYCONF'
from pathlib import Path
import re
import sys
path = Path(sys.argv[1])
text = path.read_text()
block = '# BEGIN ITUNER CM5 USB3\n[cm5]\n# V4 TPS2561: high enables both external USB sockets.\ngpio=42=op,dh\n[all]\n# END ITUNER CM5 USB3'
pattern = r'(?ms)^# BEGIN ITUNER CM5 USB3\n.*?^# END ITUNER CM5 USB3$'
if re.search(pattern, text):
    text = re.sub(pattern, lambda _: block, text)
else:
    text += '\n' + block + '\n'
path.write_text(text)
PYCONF
    install -m 0644 "$repo/hardware/cm5/v4/ituner-cm5-usb3.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable ituner-cm5-usb3.service
    systemctl restart ituner-cm5-usb3.service
    pinctrl get 42
    lsusb
    exit 0
fi
if ! grep -q '^# BEGIN ITUNER CM5 USB3$' "$boot"; then
    cp -a "$boot" "$boot.before-ituner-usb3-$(date -u +%Y%m%dT%H%M%SZ)"
    cat >> "$boot" <<'EOF'

# BEGIN ITUNER CM5 USB3
[cm5]
# Custom carrier: low selects USB3 socket power (USB2 socket loses power).
gpio=42=op,dl
[all]
# END ITUNER CM5 USB3
EOF
fi
install -m 0644 "$repo/systemd/ituner-cm5-usb3.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ituner-cm5-usb3.service
pinctrl get 42
lsusb
