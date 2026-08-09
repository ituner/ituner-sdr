#!/usr/bin/env bash
set -Eeuo pipefail

: "${ITUNER_SDR_SERVER:?Set ITUNER_SDR_SERVER in /etc/ituner-sdr.conf}"
: "${ITUNER_SDR_FREQUENCY_KHZ:=7075.794}"
: "${ITUNER_SDR_ORIENTATION:=flipped}"
: "${ITUNER_SDR_FPS:=24}"

exec /usr/bin/python3 /opt/ituner-sdr/UI/kiwi_gl_display.py \
  "$@" \
  --server "${ITUNER_SDR_SERVER}" \
  --freq-khz "${ITUNER_SDR_FREQUENCY_KHZ}" \
  --orientation "${ITUNER_SDR_ORIENTATION}" \
  --swap-x-y \
  --fps "${ITUNER_SDR_FPS}"
