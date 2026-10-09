# Reproducing the tested CM5 application dependencies

A fresh application installation now installs the operating-system packages,
exact Python runtime and downloaded model files required by the tested CM5
baseline. It no longer relies on copying a hidden vendor folder from another Pi.
Display and touch drivers remain a separate hardware prerequisite.

## Supported platform and commands

Use **64-bit Raspberry Pi OS Trixie, CPython 3.13, aarch64**, with a working
desktop/display. This is the platform whose wheels and models were verified.
Other Python versions, 32-bit Pi OS, Windows and macOS are not covered by this
lock. The installer stops rather than silently choosing different packages.

```sh
git clone https://github.com/ituner/ituner-sdr.git
cd ituner-sdr
sudo bash scripts/install.sh --cm5-existing-display
```

That entry point calls `scripts/install-dependencies.sh` before installing the
application. The dependency helper never writes boot configuration, overlays,
kernel modules, display orientation or touch mapping. The separately selected
`--legacy-display` path still changes hardware and must not be used on the
verified CM5 or reference LCD.

To provision dependencies only (for example, without replacing LCD's launcher):

```sh
sudo bash scripts/install-dependencies.sh
python3 scripts/verify-runtime.py
```

The default destination is `/opt/ituner-sdr/vendor`. An application running from
another directory looks for its own adjacent `vendor` folder. For the reference
LCD checkout, explicitly use `--vendor /home/ituner/ituner-sdr/vendor` on both
commands instead. Do not copy the CM5 service or orientation onto LCD.

Allow approximately **0.6–0.8 GB of downloads and 3 GB free disk space** for
archives, installed data and staging. Existing verified models/packages are
reused. Old mismatching directories are retained with `.before-<timestamp>`
names for rollback; remove those only after accepting the new installation.

## Exactly what is installed

| Component | Version/model policy |
| --- | --- |
| Pygame, OpenGL, Pillow, PipeWire, ALSA, fonts, NetworkManager | Raspberry Pi OS packages; compatible security updates remain available |
| SpeexDSP, PortAudio, RTL-SDR, Airspy HF+ library, OpenMP, WSJT-X | OS libraries/tools used by DSP, local receivers and WSPR |
| Vosk | Engine 0.3.45; English model `vosk-model-small-en-us-0.15` |
| Moonshine English | Sherpa-ONNX 1.13.8; matching Base INT8 and Tiny INT8 fallback models |
| Parakeet English | Sherpa-ONNX 1.13.8; `parakeet_tdt_ctc_110m-en-36000-int8` |
| HF enhancement | ONNX Runtime 1.30.0; exact project-specific ONNX asset already tested on CM5 |
| Audio / cloud client | sounddevice 0.5.6; Deepgram SDK 3.11.0 (cloud use still needs your own key) |

`requirements/pi-cp313-aarch64.lock` pins the complete 40-package Python closure,
including transitive dependencies, and SHA-256 hashes of the permitted wheels.
Pip runs with `--require-hashes`, `--only-binary=:all:` and `--no-deps` into a
staging directory, then import checks run before replacement. It does not modify
the OS-managed Python environment or resolve newer dependencies implicitly.

`config/runtime-models.json` records upstream URLs, archive hashes and extracted
model-file hashes. The downloader verifies the archive before extracting it,
rejects unsafe archive paths/links, checks required files and only then replaces
a model directory. A changed upstream archive causes a clear failure; it is not
silently accepted as "latest". Models are not automatically upgraded at runtime
by this baseline installer. No project credentials or user settings are fetched.

The larger speech models come from the publishers:
[Vosk](https://alphacephei.com/vosk/models),
[Moonshine conversions](https://k2-fsa.github.io/sherpa/onnx/moonshine/models.html),
and [NeMo/Parakeet conversions](https://k2-fsa.github.io/sherpa/onnx/nemo/index.html).
Moonshine/Vosk license files shipped in their archives are retained. The compact
project-specific HF model is bundled under `assets/models` so it also has a
stable source; PyTorch/training data are not required to run this ONNX asset.

## Verification without touching the running application

```sh
python3 scripts/bootstrap-runtime.py \
  --vendor "$HOME/ituner-runtime-test/vendor" \
  --cache "$HOME/ituner-runtime-test/cache"
python3 scripts/verify-runtime.py --vendor "$HOME/ituner-runtime-test/vendor"
```

This starts with an empty application dependency directory; the OS packages must
already be installed. It downloads/install-checks the complete pinned Python and
model baseline and loads Vosk, both Moonshine models, Parakeet and HF enhancement
in separate processes to keep peak memory bounded. It does not play audio, tune
a receiver, open the display or modify the live app.

For an offline repeat, retain the model cache and supply `--wheelhouse PATH`
containing the exact locked wheels. `--verify-only` checks without installing;
`--models-only` omits Python provisioning for model-cache maintenance.

## Whisper and other native engines

Whisper Base Q5_1 and the pinned `whisper.cpp` runtime are now included by both
standard installers and by bootstrap verification. Their manifest is
`config/whisper-runtime.json`; see [Whisper setup](whisper.md). The earlier
CM5 baseline did not include Whisper.

RNNoise, Allosaurus/PyTorch and Moonshine Voice multilingual
or experimental streaming were **not installed by the tested CM5 baseline**.
They are not pulled into the standard installer or represented as ready by this
document. Their dedicated native builds/models need separate platform validation.
The application's experimental Allosaurus and non-English Moonshine paths may
fetch their own models if those optional engines are installed and selected;
those paths are outside this pinned baseline. Deepgram credentials stay local.
Physical Airspy/RTL hardware, audio-board repairs and display drivers are also
separate from installing their software libraries.

## Updating versions

Change the lock and model manifest deliberately on a branch, download the new
artifacts from their official sources, verify hashes and perform model-load and
on-device tests before merging. Preserve the previous source tag for rollback.
OS apt dependencies are deliberately not frozen to a historical distro snapshot,
so this is a repeatable application/model baseline, not a bit-identical OS image.
