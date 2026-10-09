#!/usr/bin/env bash
# Read-only checks after reboot. Does not reset the LCD or scan the I2C bus.
set -euo pipefail
export PATH="/usr/sbin:/sbin:$PATH"
fail=0
printf 'Kernel: %s\n' "$(uname -r)"
if modinfo panel_jadard_jd9365da_h3 >/dev/null 2>&1; then
    modinfo -F filename panel_jadard_jd9365da_h3
    modinfo -F vermagic panel_jadard_jd9365da_h3
else
    echo 'FAIL: Jadard module is missing.' >&2
    fail=1
fi
panel=/sys/bus/mipi-dsi/devices/1f00130000.dsi.0
if [[ -L "$panel/driver" ]] && [[ $(basename "$(readlink -f "$panel/driver")") == jadard-jd9365da ]]; then
    echo 'PASS: Jadard panel is bound on RP1 DSI1 (FPC2).'
else
    echo 'FAIL: expected FPC2 panel binding absent; inspect device tree and kernel log.' >&2
    fail=1
fi
if [[ -L /sys/bus/i2c/devices/0-005d/driver ]] && [[ $(basename "$(readlink -f /sys/bus/i2c/devices/0-005d/driver)") == Goodix-TS ]]; then
    echo "Touch driver: $(readlink -f /sys/bus/i2c/devices/0-005d/driver)"
else
    echo 'FAIL: no touch driver bound at I2C0 address 0x5d.' >&2
    fail=1
fi
found_touch=0
for name in /sys/class/input/event*/device/name; do
    if [[ -r "$name" ]] && grep -q '0-005d Goodix Capacitive TouchScreen' "$name"; then
        printf 'PASS: %s: %s\n' "$name" "$(cat "$name")"
        found_touch=1
    fi
done
if [[ $found_touch -eq 0 ]]; then
    echo 'FAIL: expected Goodix input device absent.' >&2
    fail=1
fi
for connector in /sys/class/drm/card*-DSI-*; do
    [[ -d "$connector" ]] || continue
    printf '\n%s\n' "$connector"
    for prop in status enabled modes; do
        [[ ! -r "$connector/$prop" ]] || { printf '%s: ' "$prop"; cat "$connector/$prop"; }
    done
done
echo 'Also check the visible image and touch alignment at all four corners.'
exit "$fail"
