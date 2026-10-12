#!/usr/bin/env bash
# Optional file/live PCM decoder; does not touch audio or display settings.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
set -euo pipefail
version=4.2.13
sha=a1e8d990359ce9c0cce3ceb5116fd0cf72c95528969766898640ca6ca2dba8d4
build_dir=${1:-${XDG_CACHE_HOME:-$HOME/.cache}/ituner-sdr/fldigi-benchmark}
mkdir -p "$build_dir"
cd "$build_dir"
archive="fldigi-$version.tar.gz"
if [[ ! -f "$archive" ]]; then
    curl -fL "https://www.w1hkj.org/files/fldigi/$archive" -o "$archive.tmp"
    mv "$archive.tmp" "$archive"
fi
printf '%s  %s\n' "$sha" "$archive" | sha256sum -c -
if [[ ! -d "fldigi-$version" ]]; then tar -xzf "$archive"; fi
cd "fldigi-$version"
# Upstream benchmark-only code omits std:: on ofstream (GCC 14 rejects it).
# No decoder algorithm changes; apply the exact, idempotent namespace fix.
python3 - <<'PYFIX'
from pathlib import Path
p=Path('src/misc/benchmark.cxx')
s=p.read_text()
s=s.replace('\t\tofstream out(benchmark.output.c_str());',
            '\t\tstd::ofstream out(benchmark.output.c_str());')
# Keep GUI carrier state in sync: CW's filter reset reads it even in batch mode.
if 'wf->carrier(benchmark.freq)' not in s:
    s=s.replace('\tprogStatus.afconoff = benchmark.afc;',
                '\tif (benchmark.freq) wf->carrier(benchmark.freq);\n\tprogStatus.afconoff = benchmark.afc;')
p.write_text(s)
# File-only mode does not create the optional signal-browser dialog.
p=Path('src/cw/cw.cxx')
s=p.read_text().replace('dlgViewer->visible() || progStatus.show_channels',
    '(dlgViewer && dlgViewer->visible()) || progStatus.show_channels')
p.write_text(s)
PYFIX
python3 "$script_dir/patch-fldigi-stream.py" "$PWD"
./configure --enable-benchmark --disable-flarq --without-pulseaudio \
    --without-hamlib --without-flxmlrpc --without-libmbedtls --without-asciidoc
make -j"${ITUNER_BUILD_JOBS:-2}"
printf 'Benchmark binary: %s/src/fldigi\n' "$PWD"
