#!/usr/bin/env bash
# Install the upstream dashboard; SDR ownership stays with the iTuner VHF hub.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
revision=236910d4f0d4cbd687149f27f2d7698b50ee08bf
source=/usr/local/src/ituner-rtl433-ui
prefix=/opt/ituner-sdr/decoders/rtl433-ui
[[ -x /opt/ituner-sdr/decoders/vhf/bin/rtl_433 ]] || { echo 'Install the VHF decoder package first.' >&2; exit 1; }
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nodejs npm mosquitto
if [[ ! -d $source/.git ]]; then git clone --depth 1 --no-checkout https://github.com/dalekunce/rtl433-ui.git "$source"; fi
if ! git -C "$source" cat-file -e "$revision^{commit}" 2>/dev/null; then git -C "$source" fetch --depth 1 origin "$revision"; fi
git -C "$source" checkout --detach "$revision"
# A fresh staging directory makes repeated installations deterministic.
staging=$(mktemp -d /opt/ituner-sdr/decoders/.rtl433-ui.XXXXXX)
trap 'rmdir -- "$staging" 2>/dev/null || true' EXIT
cp -a "$source/rtl433-ui/." "$staging/"
python3 "$repo/integrations/rtl433-ui/patch.py" "$staging"
(cd "$staging" && npm ci --omit=dev --ignore-scripts --no-fund --no-audit)
printf '%s\n' "dalekunce/rtl433-ui $revision" > "$staging/versions.txt"
systemctl stop ituner-rtl433-ui.service 2>/dev/null || true
if [[ -d $prefix ]]; then mv "$prefix" "$prefix.backup-$(date -u +%Y%m%dT%H%M%SZ)"; fi
mv "$staging" "$prefix"
install -m 0644 "$repo/systemd/ituner-rtl433-ui.service" /etc/systemd/system/
backup=/var/backups/ituner-sdr/rtl433-ui-$(date -u +%Y%m%dT%H%M%SZ)
install -d "$backup"
for file in vhf_monitor.py vhf_workspace.py vhf_dashboard.js vhf_dashboard.html kiwi_gl_display.py sdr_broker.py spectrum_monitor.py spectrum_history.py spectrum_analysis.py spectrum_report.py spectrum_workspace.py spectrum_allocations.json soapy_survey.py spectrum.html spectrum.css spectrum.js spectrum_tools.js; do
    [[ ! -f /opt/ituner-sdr/UI/$file ]] || cp -a "/opt/ituner-sdr/UI/$file" "$backup/"
    install -m 0644 "$repo/UI/$file" /opt/ituner-sdr/UI/
done
systemctl daemon-reload
systemctl restart ituner-sdr.service
systemctl enable --now mosquitto.service ituner-rtl433-ui.service
printf '%s\n' 'RTL433-UI: http://cm5.local:8093/ — Start sensors hands off an occupied RTL-SDR.'
