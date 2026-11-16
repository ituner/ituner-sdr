#!/usr/bin/env python3
"""Build the optional local Voice filter; never starts or changes the app."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen

URL = 'https://github.com/xiph/rnnoise/releases/download/v0.2/rnnoise-0.2.tar.gz'
SHA256 = '90fce4b00b9ff24c08dbfe31b82ffd43bae383d85c5535676d28b0a2b11c0d37'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path,
                        default=Path(__file__).resolve().parent.parent / 'vendor/rnnoise-install')
    parser.add_argument('--source', type=Path, help='Use a cached official release archive')
    args = parser.parse_args()
    if args.source:
        data = args.source.read_bytes()
    else:
        with urlopen(URL, timeout=30) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit('RNNoise source checksum does not match the pinned release')
    prefix = args.prefix.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix='ituner-rnnoise-') as folder:
        archive = Path(folder) / 'rnnoise.tar.gz'
        archive.write_bytes(data)
        with tarfile.open(archive) as source:
            source.extractall(folder, filter='data')
        root = Path(folder) / 'rnnoise-0.2'
        neon = root / 'src/vec_neon.h'
        # 0.2 retained Opus-only names in its ARM header. Use RNNoise's own
        # equivalent headers/clear macro; no model or DSP arithmetic changes.
        text = neon.read_text()
        text = text.replace('#include "os_support.h"',
                            '#include "opus_types.h"\n#include "common.h"')
        text = text.replace('OPUS_CLEAR(out, rows)', 'RNN_CLEAR(out, rows)')
        neon.write_text(text)
        for command in (['./configure', '--disable-static', '--prefix=' + str(prefix)],
                        ['make', '-j2'], ['make', 'install']):
            subprocess.run(command, cwd=root, check=True)
        shutil.copy2(root / 'COPYING', prefix / 'COPYING')
    print('RNNoise installed at', prefix)


if __name__ == '__main__':
    main()
