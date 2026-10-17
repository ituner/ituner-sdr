#!/usr/bin/env bash
# Optional USB GNSS support for the shared Radio / User Information profile.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends gpsd
# Debian's gpsd udev rules attach supported USB GNSS devices. Preserve devices
# and receiver options; no arbitrary serial device or SDR is probed here.
python3 - <<'PY'
from pathlib import Path
import re
p=Path('/etc/default/gpsd');text=p.read_text() if p.exists() else ''
if re.search(r'^USBAUTO=',text,re.M):text=re.sub(r'^USBAUTO=.*$', 'USBAUTO="true"',text,flags=re.M)
else:text+='\nUSBAUTO="true"\n'
p.write_text(text)
PY
install -m 0644 "$repo"/UI/station*.py "$repo"/UI/station.{html,css,js} /opt/ituner-sdr/UI/
udevadm control --reload-rules
systemctl enable --now gpsd.socket
printf '%s\n' 'GPS support ready. Settings > Radio / User Information shows USB GPS status and location source.'
