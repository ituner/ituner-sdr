#!/usr/bin/env bash
set -Eeuo pipefail
for ((attempt=0; attempt<30; attempt++)); do
    for name in /sys/class/input/event*/device/name; do
        if [[ -r $name ]] && grep -q '1-005d Goodix Capacitive TouchScreen' "$name"; then
            exit 0
        fi
    done
    sleep 1
done
echo 'CM5 GT911 input device on I2C1 was not found.' >&2
exit 1
