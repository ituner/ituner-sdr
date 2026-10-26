#!/usr/bin/env bash
# FIS-B's pure Python capture/assembly engine; no MongoDB, GDAL or network feeds.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
revision=c3d3b0473429336b1a98672b2e8b276c24d49765
target=/usr/local/src/ituner-adsb/fisb-decode
destination=/opt/ituner-sdr/decoders/adsb/fisb-decode
install -d /usr/local/src/ituner-adsb "$destination"
if [[ ! -d $target/.git ]]; then git clone --depth 1 --no-checkout https://github.com/rand-projects/fisb-decode.git "$target"; fi
git -C "$target" fetch --depth 1 origin "$revision"
git -C "$target" checkout --detach "$revision"
cp -a "$target/fisb" "$destination/"
install -m 0644 "$target/LICENSE" "$destination/LICENSE"
printf '%s\n' "$revision" > "$destination/version.txt"
# Correct the upstream northern-block split assigning the second half to the first.
python3 - "$destination/fisb/level2/msgBlock.py" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
p.write_text(s.replace("newMsg['bins'] = bins[1]", "msgCopy['bins'] = bins[1]"))
PY
install -m 0644 "$repo"/UI/adsb_*.py "$repo"/UI/adsb_*.js "$repo"/UI/adsb_*.css "$repo/UI/adsb_map.html" "$repo/UI/adsb_weather.html" "$repo/UI/adsb_compare.html" /opt/ituner-sdr/UI/
if [[ ${ITUNER_FISB_SKIP_RESTART:-0} != 1 ]]; then systemctl restart ituner-sdr.service; fi
echo 'FIS-B weather installed. Airspace > Weather. Requires reception of an FAA ground uplink.'
