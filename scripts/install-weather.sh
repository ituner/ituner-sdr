#!/usr/bin/env bash
# Separate WeeWX/Belchertown service; radio ownership remains with the VHF hub.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
prefix=/opt/ituner-sdr/weather
station=/var/lib/ituner-weather
archive=/usr/local/src/weewx-belchertown-3.0.0.tar.gz
checksum=25e7891b489e55a72a73ffc660c30f2ffceb069ced7dde9ee75853f75388a1af
id ituner >/dev/null
[[ -f /opt/ituner-sdr/UI/vhf_monitor.py ]] || { echo 'Install the shared VHF decoder hub first.' >&2; exit 1; }
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3-venv curl ca-certificates
install -d "$prefix" "$prefix/integration" /usr/local/src
systemctl stop ituner-weewx.service ituner-weather-web.service 2>/dev/null || true
python3 -m venv "$prefix/venv"
"$prefix/venv/bin/pip" install --disable-pip-version-check 'weewx==5.5.2'
curl -fL --retry 3 https://github.com/poblabs/weewx-belchertown/releases/download/weewx-belchertown-3.0.0/weewx-belchertown-3.0.0.tar.gz -o "$archive"
printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c -
# Configure everything before enabling either service. Preserve existing data.
install -d -o ituner -g ituner "$station"
if [[ ! -f $station/weewx.conf ]]; then
    "$prefix/venv/bin/weectl" station create "$station" --no-prompt --location='Bucharest · RTL-SDR weather' --latitude=44.4268 --longitude=26.1025 --altitude=0,meter --units=metricwx --register=n
fi
cp -a "$station/weewx.conf" "$station/weewx.conf.pre-install-$(date -u +%Y%m%dT%H%M%SZ)"
"$prefix/venv/bin/weectl" extension install "$archive" --config="$station/weewx.conf" --yes
install -m 0644 "$repo"/integrations/weewx/*.{py,html,js} "$prefix/integration/"
install -m 0644 "$repo/integrations/weewx/ituner_weather.py" "$repo/integrations/weewx/ituner_report.py" "$station/bin/user/"
"$prefix/venv/bin/python" "$repo/integrations/weewx/configure.py"
"$prefix/venv/bin/python" - "$station/weewx.conf" <<'PY'
import configobj,sys
c=configobj.ConfigObj(sys.argv[1]);assert c['Station']['station_type']=='ITunerWeather' and 'Simulator' not in c
assert c['ITunerWeather']['driver']=='user.ituner_weather'
PY
chown -R ituner:ituner "$station"
install -m 0644 "$repo/systemd/ituner-weather-web.service" "$repo/systemd/ituner-weewx.service" /etc/systemd/system/
# Navigation is static; no receiver restart is required.
backup=/var/backups/ituner-sdr/weather-$(date -u +%Y%m%dT%H%M%SZ)
install -d "$backup"
for file in vhf_dashboard.html vhf_dashboard.js spectrum.html spectrum.js spectrum.css; do
    [[ ! -f /opt/ituner-sdr/UI/$file ]] || cp -a "/opt/ituner-sdr/UI/$file" "$backup/"
    install -m 0644 "$repo/UI/$file" /opt/ituner-sdr/UI/
done
if [[ -d /opt/ituner-sdr/decoders/rtl433-ui/frontend ]]; then
    cp -a /opt/ituner-sdr/decoders/rtl433-ui/frontend/ituner-controls.js "$backup/" 2>/dev/null || true
    install -m 0644 "$repo/integrations/rtl433-ui/controls.js" /opt/ituner-sdr/decoders/rtl433-ui/frontend/ituner-controls.js
fi
systemctl daemon-reload
systemctl enable --now ituner-weather-web.service ituner-weewx.service
printf '%s\n' 'WeeWX + Belchertown: http://cm5.local:8094/ — waits for a real compatible rtl_433 weather station.'
