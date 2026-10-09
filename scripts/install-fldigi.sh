#!/usr/bin/env bash
# Optional CM5 CW engine. Does not change boot, sound, display or touch drivers.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
sudo apt-get update
sudo apt-get install -y build-essential pkg-config libfltk1.3-dev libsamplerate0-dev \
 libsndfile1-dev libpng-dev libudev-dev libxft-dev portaudio19-dev xvfb xauth \
 gettext autopoint autoconf automake libtool python3-scipy curl
build_dir=${1:-${XDG_CACHE_HOME:-$HOME/.cache}/ituner-sdr/fldigi-benchmark}
"$script_dir/build-fldigi-benchmark.sh" "$build_dir"
install -m755 "$build_dir/fldigi-4.2.13/src/fldigi" "$script_dir/../UI/cw_vendor/fldigi"
printf 'fldigi live CW engine installed. Select fldigi when adding or editing a CW receiver.\n'
