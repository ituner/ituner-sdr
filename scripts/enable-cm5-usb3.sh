#!/usr/bin/env bash
# ONLY for the iTuner custom CM5 carrier with complementary USB2/USB3 power.
# Verified live: GPIO42 low enumerates the USB3 socket's Nooelec RTL2838.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
grep -aq 'Compute Module 5' /proc/device-tree/model || { echo 'CM5 required.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
boot=/boot/firmware/config.txt
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
