#!/usr/bin/env bash
set -Eeuo pipefail
for ((attempt=0; attempt<30; attempt++)); do
    for name in /sys/class/input/event*/device/name; do
        # Older kernels prefix the I2C address; newer kernels omit it.
        if [[ -r $name ]] && grep -Eq '^([0-9]+-005d )?Goodix Capacitive TouchScreen$' "$name"; then
            exit 0
        fi
    done
    sleep 1
done
echo 'Existing Goodix GT911 input device was not found.' >&2
exit 1
