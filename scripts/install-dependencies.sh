#!/usr/bin/env bash
# Application dependencies only: never install a display driver or upgrade the kernel.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python3 - <<'PY'
import platform, sys
if platform.machine() != 'aarch64' or sys.version_info[:2] != (3, 13):
    sys.exit('Use 64-bit Raspberry Pi OS Trixie / Python 3.13 for the tested dependency lock. No hardware files have been changed.')
PY

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg python3-pip python3-pygame python3-opengl python3-pil python3-scipy \
    pipewire-audio pipewire-bin wireplumber alsa-utils fontconfig \
    libspeexdsp1 libportaudio2 librtlsdr0 libairspyhf1 libgomp1 libatomic1 \
    cmake build-essential wsjtx tesseract-ocr tesseract-ocr-eng network-manager ca-certificates

python3 "$repo/scripts/bootstrap-runtime.py" "$@"

python3 "$repo/scripts/build-cw.py"
