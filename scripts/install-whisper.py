#!/usr/bin/env python3
"""Pinned CPU-only Whisper Base installation; no services or hardware changes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('runtime_bootstrap', ROOT / 'scripts/bootstrap-runtime.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def matches(destination, manifest):
    try:
        receipt = json.loads((destination / 'ituner-install.json').read_text())
        return (receipt['manifest'] == manifest
                and bootstrap.sha256(destination / 'build/bin/whisper-cli') == receipt['binary_sha256']
                and os.access(destination / 'build/bin/whisper-cli', os.X_OK)
                and bootstrap.sha256(destination / 'models' / manifest['model_name']) == manifest['model_sha256'])
    except (OSError, ValueError, KeyError):
        return False


def install(vendor, cache, manifest, verify_only=False):
    destination = vendor / 'whisper.cpp'
    if matches(destination, manifest):
        print('Verified Whisper Base Q5_1 and pinned native runtime.', flush=True)
        return
    if verify_only:
        raise RuntimeError('Whisper runtime/model missing or failed verification')
    vendor.mkdir(parents=True, exist_ok=True)
    print('Downloading/verifying pinned Whisper source and Base Q5_1 model.', flush=True)
    source = bootstrap.download(dict(id='whisper-source', url=manifest['source_url'],
                                     archive_sha256=manifest['source_sha256']), cache)
    model = bootstrap.download(dict(id='whisper-base-q5_1', url=manifest['model_url'],
                                    archive_sha256=manifest['model_sha256']), cache)
    with tempfile.TemporaryDirectory(prefix='.whisper-stage-', dir=vendor) as temporary:
        stage = Path(temporary)
        bootstrap.extract_archive(source, stage)
        tree = stage / ('whisper.cpp-' + manifest['commit'])
        build = tree / 'build'
        # Static project libraries avoid runtime dependencies on staging paths.
        subprocess.run(['cmake', '-S', str(tree), '-B', str(build),
                        '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=OFF',
                        '-DWHISPER_BUILD_TESTS=OFF', '-DWHISPER_BUILD_SERVER=OFF',
                        '-DGGML_CUDA=OFF', '-DGGML_VULKAN=OFF', '-DGGML_METAL=OFF',
                        '-DGGML_BLAS=OFF', '-DGGML_NATIVE=ON'], check=True)
        # One compiler at a time keeps installation safe on the 2 GB CM5.
        subprocess.run(['cmake', '--build', str(build), '--target', 'whisper-cli', '-j', '1'], check=True)
        import shutil
        shutil.copyfile(model, tree / 'models' / manifest['model_name'])
        binary = build / 'bin/whisper-cli'
        binary.chmod(0o755)
        result = stage / 'smoke'
        log = stage / 'smoke.log'
        print('Running Whisper speech transcription check.', flush=True)
        with log.open('w') as output:
            subprocess.run([str(binary), '-m', str(tree / 'models' / manifest['model_name']),
                            '-f', str(tree / 'samples/jfk.wav'), '-l', 'en', '-t', '2',
                            '-nt', '-np', '-otxt', '-of', str(result)],
                           stdout=output, stderr=output, timeout=180, check=True)
        text = result.with_suffix('.txt').read_text().lower()
        if 'country' not in text or 'ask' not in text:
            raise RuntimeError('Whisper speech smoke test failed; existing runtime preserved')
        (tree / 'ituner-install.json').write_text(json.dumps(dict(
            manifest=manifest, binary_sha256=bootstrap.sha256(binary)), indent=2) + '\n')
        for entry in tree.rglob('*'):
            if entry.is_dir():entry.chmod(0o755)
            elif entry.is_file():entry.chmod(0o755 if entry == binary else 0o644)
        tree.chmod(0o755)
        bootstrap.replace_directory(tree, destination)
    print('Installed Whisper Base Q5_1; real speech transcription passed.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', type=Path, default=Path('/opt/ituner-sdr/vendor'))
    parser.add_argument('--cache', type=Path, default=Path('/var/cache/ituner-sdr/models'))
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'config/whisper-runtime.json').read_text())
    install(args.vendor, args.cache, manifest, args.verify_only)


if __name__ == '__main__':
    main()
