#!/usr/bin/env bash
set -Eeuo pipefail

: "${ITUNER_SDR_SERVER:?Set ITUNER_SDR_SERVER in /etc/ituner-sdr.conf}"
: "${ITUNER_SDR_FREQUENCY_KHZ:=7075.794}"
: "${ITUNER_SDR_ORIENTATION:=flipped}"
: "${ITUNER_SDR_FPS:=30}"

exec /usr/bin/python3 /opt/ituner-sdr/UI/kiwi_gl_display.py \
  --server "${ITUNER_SDR_SERVER}" \
  --freq-khz "${ITUNER_SDR_FREQUENCY_KHZ}" \
  --orientation "${ITUNER_SDR_ORIENTATION}" \
  --fps "${ITUNER_SDR_FPS}" \
  --wf-row-pixels 1 \
  --swipe-slow-sensitivity 1.15 \
  --swipe-fast-sensitivity 2.4 \
  --swipe-fast-px-s 420 \
  --swipe-repeat-window-s 1.4 \
  --swipe-repeat-boost 0.65 \
  --swipe-repeat-max 3 \
  --swipe-inertia-strength 0.0

