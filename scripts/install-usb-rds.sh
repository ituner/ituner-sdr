#!/usr/bin/env bash
# Build the pinned native RDS decoder; no boot, kernel, or USB configuration changes.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
version=v1.3.0
commit=abd793d989dd17327081e5d7064e7ef57475c9f2
marker=/var/lib/ituner-sdr/redsea-version
if [[ -x /usr/local/bin/redsea && -f $marker ]] && [[ $(cat "$marker") == "$commit" ]]; then exit 0; fi
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    git build-essential meson ninja-build libsndfile1-dev libliquid-dev nlohmann-json3-dev python3-scipy
build_dir=$(mktemp -d /tmp/ituner-redsea.XXXXXX)
trap 'rm -rf "$build_dir"' EXIT
git clone --depth 1 --branch "$version" https://github.com/windytan/redsea.git "$build_dir/source"
[[ $(git -C "$build_dir/source" rev-parse HEAD) == "$commit" ]] || { echo 'Unexpected redsea source revision' >&2; exit 1; }
meson setup "$build_dir/build" "$build_dir/source" -Dbuild_tests=false
meson compile -C "$build_dir/build" -j 2
install -m 0755 "$build_dir/build/redsea" /usr/local/bin/redsea
install -d /var/lib/ituner-sdr
printf '%s\n' "$commit" > "$marker"
