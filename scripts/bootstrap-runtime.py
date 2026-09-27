#!/usr/bin/env python3
"""Install the tested Pi runtime and verified model data without changing hardware."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parent.parent


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def model_matches(directory, model):
    return all(
        (directory / name).is_file() and sha256(directory / name) == digest
        for name, digest in model["files"].items()
    )


def replace_directory(staged, destination):
    """Retain the previous complete directory for rollback, including on failure."""
    backup = destination.with_name(destination.name + ".before-" + str(time.time_ns()))
    if destination.exists() or destination.is_symlink():
        destination.rename(backup)
    try:
        staged.rename(destination)
    except BaseException:
        if backup.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        print(f"Previous copy retained: {backup}", flush=True)


def download(model, cache):
    url = model["url"]
    if not url.startswith("https://"):
        raise ValueError("Model downloads must use HTTPS")
    archive = cache / (model["archive_sha256"] + "-" + url.rsplit("/", 1)[1])
    if archive.is_file() and sha256(archive) == model["archive_sha256"]:
        return archive
    cache.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="download-", dir=cache)
    partial = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            request = urllib.request.Request(url, headers={"User-Agent": "ituner-sdr-bootstrap/1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                shutil.copyfileobj(response, output, 1024 * 1024)
        if sha256(partial) != model["archive_sha256"]:
            raise ValueError(f"Checksum mismatch: {model['id']}; refusing installation")
        partial.replace(archive)
    finally:
        partial.unlink(missing_ok=True)
    return archive


def member_destination(root, name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive path: {name}")
    destination = root.joinpath(*path.parts)
    if not destination.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Archive member escapes staging: {name}")
    return destination


def extract_archive(archive, root):
    """Extract regular files only; reject links, devices and directory traversal."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                destination = member_destination(root, member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError("Archive links are not supported")
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as inp, destination.open("wb") as out:
                        shutil.copyfileobj(inp, out)
    else:
        with tarfile.open(archive, "r:*") as source:
            for member in source:
                destination = member_destination(root, member.name)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with source.extractfile(member) as inp, destination.open("wb") as out:
                        shutil.copyfileobj(inp, out)
                else:
                    raise ValueError(f"Unsupported archive member: {member.name}")


def install_model(model, vendor, cache):
    destination = vendor / model["id"]
    if model_matches(destination, model):
        print(f"Verified existing model: {model['id']}", flush=True)
        return
    print(f"Installing model: {model['id']}", flush=True)
    with tempfile.TemporaryDirectory(prefix=".model-stage-", dir=vendor) as temporary:
        root = Path(temporary)
        if "bundled" in model:
            staged = root / model["id"]
            staged.mkdir()
            for target, source in model["bundled"].items():
                shutil.copyfile(REPO / source, staged / target)
        else:
            extract_archive(download(model, cache), root)
            staged = root / model["id"]
        if not model_matches(staged, model):
            raise ValueError(f"Extracted model files failed verification: {model['id']}")
        # Staging is private; published model files must be readable by the app user.
        for entry in staged.rglob("*"):
            entry.chmod(0o755 if entry.is_dir() else 0o644)
        staged.chmod(0o755)
        replace_directory(staged, destination)


def locked_versions(lock):
    versions = {}
    for line in lock.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name, version = line.split()[0].split("==")
        versions[name.lower().replace("_", "-")] = version
    return versions


def packages_match(directory, lock):
    versions = {
        dist.metadata["Name"].lower().replace("_", "-"): dist.version
        for dist in importlib.metadata.distributions(path=[str(directory)])
    }
    return versions == locked_versions(lock)


def smoke_imports(directory):
    code = """
import sys
sys.path.insert(0, sys.argv[1])
from importlib.metadata import distributions
from packaging.requirements import Requirement
installed = {d.metadata['Name'].lower().replace('_', '-'): d
             for d in distributions(path=[sys.argv[1]])}
for dist in installed.values():
    for raw in dist.requires or []:
        req = Requirement(raw)
        if req.marker and not req.marker.evaluate({'extra': ''}):
            continue
        dependency = installed.get(req.name.lower().replace('_', '-'))
        if dependency is None or dependency.version not in req.specifier:
            raise RuntimeError(f'Incomplete/incompatible lock: {dist.metadata["Name"]} requires {raw}')
import numpy, vosk, sherpa_onnx, onnxruntime, sounddevice
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
print('Speech/audio runtime imports passed.')
"""
    subprocess.run([sys.executable, "-c", code, str(directory.resolve())], check=True)


def require_supported_python():
    if sys.platform != "linux" or platform.machine() != "aarch64" or sys.version_info[:2] != (3, 13):
        raise RuntimeError("The tested wheel lock requires 64-bit Raspberry Pi OS Trixie, Python 3.13 (aarch64). No automatic version substitution is allowed.")


def install_python(vendor, cache, lock, wheelhouse=None):
    require_supported_python()
    destination = vendor / "python"
    if packages_match(destination, lock):
        smoke_imports(destination)
        print("Verified existing pinned Python runtime.", flush=True)
        return
    with tempfile.TemporaryDirectory(prefix=".python-stage-", dir=vendor) as temporary:
        staged = Path(temporary) / "python"
        command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                   "--require-hashes", "--only-binary=:all:", "--no-deps",
                   "--target", str(staged), "--cache-dir", str(cache / "pip"), "-r", str(lock)]
        if wheelhouse:
            command += ["--no-index", "--find-links", str(wheelhouse)]
        else:
            command += ["--index-url", "https://pypi.org/simple"]
        subprocess.run(command, check=True)
        if not packages_match(staged, lock):
            raise RuntimeError("Installed Python package versions differ from lock")
        smoke_imports(staged)
        replace_directory(staged, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, default=Path("/opt/ituner-sdr/vendor"))
    parser.add_argument("--cache", type=Path, default=Path("/var/cache/ituner-sdr"))
    parser.add_argument("--models-only", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--wheelhouse", type=Path, help="Optional cache of the exact locked wheels")
    args = parser.parse_args()
    lock = REPO / "requirements/pi-cp313-aarch64.lock"
    models = json.loads((REPO / "config/runtime-models.json").read_text())["models"]
    if args.verify_only:
        if not args.models_only:
            require_supported_python()
            if not packages_match(args.vendor / "python", lock):
                raise RuntimeError("Python runtime missing or different from lock")
            smoke_imports(args.vendor / "python")
        for model in models:
            if not model_matches(args.vendor / model["id"], model):
                raise RuntimeError(f"Model missing or checksum mismatch: {model['id']}")
        print("All selected dependencies verified.")
        return
    if not args.models_only:
        require_supported_python()
    args.vendor.mkdir(parents=True, exist_ok=True)
    if not args.models_only:
        install_python(args.vendor, args.cache, lock, args.wheelhouse)
    for model in models:
        install_model(model, args.vendor, args.cache)
    print("Dependency installation complete.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"Dependency setup failed: {error}")
