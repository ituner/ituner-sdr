#!/usr/bin/env bash
set -Eeuo pipefail

# The bundled GT911 overlay binds the controller on Pi 5 CAM/DISP 1's I2C bus.
for _ in $(seq 1 30); do
  if [[ -d /sys/bus/i2c/devices/11-005d ]] && compgen -G '/dev/input/event*' >/dev/null; then
    exit 0
  fi
  sleep 1
done

echo 'GT911 touch controller was not found at I2C bus 11 address 0x5d.' >&2
exit 1
