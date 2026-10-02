#!/usr/bin/env bash
# Disable this profile without removing codec support or touching the display.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
systemctl stop ituner-sdr.service
pinctrl set 13 op dl
rm -f /etc/systemd/system/ituner-sdr.service.d/cm5-audio.conf
systemctl disable --now cm5-headphone-monitor.service
systemctl daemon-reload
echo 'CM5 audio profile disabled; Class-D is off. Codec overlay remains installed.'
echo 'Select/configure another audio output before restarting ituner-sdr.service.'
