#!/usr/bin/env bash
# Install a local-only decoder and web map. Run after the app installer.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
install -d /usr/local/src/ituner-adsb /opt/ituner-sdr/decoders/adsb
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  git build-essential pkg-config libusb-1.0-0-dev librtlsdr-dev libncurses-dev zlib1g-dev libzstd-dev rtl-sdr
fetch() {
    local name=$1 revision=$2
    local target=/usr/local/src/ituner-adsb/$name
    if [[ ! -d $target/.git ]]; then git clone --depth 1 --no-checkout "https://github.com/wiedehopf/$name.git" "$target"; fi
    if [[ $(git -C "$target" rev-parse HEAD) != "$revision" ]]; then
        git -C "$target" fetch --depth 1 origin "$revision"
    fi
    git -C "$target" checkout --detach "$revision"
}
fetch readsb 8afcc22de2de81be38231695285070603af78ef4
fetch tar1090 e784ee5ae82948f41efe3ef5c235ade0943ab8ff
fetch tar1090-db 17679e257733ad808a417cf4a5d52f3b00238887
make -C /usr/local/src/ituner-adsb/readsb -j2 RTLSDR=yes
install -m 0755 /usr/local/src/ituner-adsb/readsb/readsb /opt/ituner-sdr/decoders/adsb/readsb
install -d /opt/ituner-sdr/decoders/adsb/tar1090
cp -a /usr/local/src/ituner-adsb/tar1090/html /opt/ituner-sdr/decoders/adsb/tar1090/
install -d /opt/ituner-sdr/decoders/adsb/tar1090/html/db2
cp -a /usr/local/src/ituner-adsb/tar1090-db/db/. /opt/ituner-sdr/decoders/adsb/tar1090/html/db2/
install -m 0644 /usr/local/src/ituner-adsb/readsb/LICENSE /opt/ituner-sdr/decoders/adsb/readsb.LICENSE
install -m 0644 /usr/local/src/ituner-adsb/readsb/COPYING /opt/ituner-sdr/decoders/adsb/readsb.COPYING
install -m 0644 /usr/local/src/ituner-adsb/tar1090/LICENSE /opt/ituner-sdr/decoders/adsb/tar1090.LICENSE
# Retain default config for local mapping; no feeders or external control ports.
cat >> /opt/ituner-sdr/decoders/adsb/tar1090/html/config.js <<'EOF'
// iTuner local receiver defaults.
DefaultCenterLat = 45;
DefaultCenterLon = 25;
DefaultZoomLvl = 6;
SiteShow = false;
EOF
# A decoder must be permitted to claim USB; librtlsdr supplies plugdev udev rules.
app_user=${SUDO_USER:-ituner}
id "$app_user" >/dev/null
usermod -a -G plugdev "$app_user"
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb
install -m 0644 "$repo"/UI/adsb_*.py "$repo"/UI/adsb_*.js "$repo/UI/adsb_map.html" "$repo/UI/adsb_map.css" "$repo/UI/globe_tiles.py" /opt/ituner-sdr/UI/
cat > /opt/ituner-sdr/decoders/adsb/versions.txt <<'EOF'
readsb 8afcc22de2de81be38231695285070603af78ef4
tar1090 e784ee5ae82948f41efe3ef5c235ade0943ab8ff
tar1090-db 17679e257733ad808a417cf4a5d52f3b00238887
EOF
systemctl restart ituner-sdr.service
printf '%s\n' 'ADS-B installed. Open Decoders > VHF/UHF > ADS-B, assign USB and Start.'
