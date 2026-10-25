#!/usr/bin/env bash
# Add FlightAware's UAT decoder to the existing ADS-B workspace; no feeders.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
revision=f40aa9a0d2d0a0067c0c628b44ba316f7049b8ce
target=/usr/local/src/ituner-adsb/dump978
destination=/opt/ituner-sdr/decoders/adsb
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  git build-essential libboost-program-options-dev libboost-regex-dev \
  libboost-filesystem-dev libsoapysdr-dev soapysdr-module-rtlsdr
install -d /usr/local/src/ituner-adsb "$destination"
if [[ ! -d $target/.git ]]; then git clone --depth 1 --no-checkout https://github.com/flightaware/dump978.git "$target"; fi
git -C "$target" fetch --depth 1 origin "$revision"
git -C "$target" checkout --detach "$revision"
patch_file="$repo/config/dump978-geometric-altitude.patch"
if git -C "$target" apply --check "$patch_file" 2>/dev/null; then
    git -C "$target" apply "$patch_file"
else
    git -C "$target" apply --reverse --check "$patch_file"
fi
make -C "$target" -j2
install -m 0755 "$target/dump978-fa" "$target/skyaware978" "$destination/"
install -m 0644 "$target/LICENSE" "$destination/dump978.LICENSE"
printf 'dump978-fa + skyaware978 %s + geometric-altitude correction\n' "$revision" > "$destination/uat-version.txt"
install -m 0644 "$repo"/UI/adsb_*.py "$repo"/UI/adsb_*.js "$repo"/UI/adsb_*.css "$repo/UI/adsb_map.html" "$repo/UI/adsb_weather.html" "$repo/UI/adsb_compare.html" /opt/ituner-sdr/UI/
if [[ ${ITUNER_UAT_SKIP_RESTART:-0} != 1 ]]; then systemctl restart ituner-sdr.service; fi
printf '%s\n' 'UAT installed. Settings > Receiver & dongles > 978 UAT: assign a second unique RTL-SDR and Start.'
