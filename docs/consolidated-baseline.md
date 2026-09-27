# One application baseline for LCD and CM5

This is a consolidation candidate, based on LCD's running application captured
on 2026-09-27. The candidate is under test on CM5; GitHub main and the original
LCD installation remain unchanged. See `cm5-pr9-validation.md` for test results.

## What belongs in GitHub

- Shared application source, including the live OpenWebRX modules and local
  receiver changes. The renderer is byte-identical to the captured LCD file.
- UI assets and the exact Oxanium font used by LCD, with its OFL license.
- Reviewed UI defaults: compact instruments and Oxanium. No personal receiver
  history, credentials, API keys, or private saved settings.
- Separate machine startup profiles and reproducible dependency instructions.
- A version manifest with checksums: `config/lcd-baseline-manifest.json`.
- CM5 display source archived under `hardware/cm5/reference-display` for
  recovery. Application installation does not install or rebuild that driver.

The candidate starts from GitHub main and incorporates the actual live files.
It does not blindly merge the old LCD branch or reset LCD's dirty working tree.
Existing main Wi-Fi and HID support is retained. The historical uncompressed
country-map fallback is excluded: main's valid compressed map already matches
LCD byte for byte, as do all its tracked UI assets.

## Machine-specific settings

| Setting | Original LCD | CM5 |
| --- | --- | --- |
| App orientation | flipped | normal |
| Touch transform | swap axes, invert X | swap axes, invert Y |
| Rendering backend | existing direct KMS service | existing Wayland desktop |
| Display/touch drivers | preserve installed | preserve verified JD9365/GT911 |
| Audio backend | current ALSA setup | current PipeWire setup |
| Instrument layout | compact | compact after adopting the baseline |

Do not copy LCD's boot configuration, display driver, direct audio device,
system services, or entire user configuration onto CM5. CM5's onboard audio
repair remains a separate hardware task. Fan control is also optional and
requires validation of the machine's cooling device before enabling it.

## CM5 installation path

Keep the running kernel. Install application packages rather than upgrading the
whole OS; the external working panel module is tied to its kernel version.

```sh
sudo apt-get install --no-install-recommends python3-pygame python3-opengl python3-pil \
  pipewire-audio wireplumber fontconfig
sudo ./scripts/install.sh --cm5-existing-display
```

The CM5 application-only path installs all UI modules/assets and the matching
font, adds the NetworkManager helper and RC-28 access rule, and configures
application startup without writing boot settings, overlays, or kernel modules.
It preserves `/etc/ituner-sdr.conf` when present. A fresh CM5 configuration uses
normal orientation. A fresh user state gets the compact UI defaults; existing
user settings are preserved. Existing CM5 therefore still needs its saved
instrument layout changed from expanded to compact during the staged update.

The stock ST7701 hardware installer now requires explicit `--legacy-display`.
It must not be selected for this CM5 or the reference LCD. The old uninstaller
is not installed by the CM5 path because it manipulates display hardware files.

## Dependencies outside the base UI

Keep Python wheels isolated under `/opt/ituner-sdr/vendor/python`; do not replace
the OS-managed Python packages. `requirements-runtime.txt` describes PortAudio
Python support (also needs OS package `libportaudio2`). Optional ASR requirements
are separate; Deepgram is constrained to SDK 3.x to preserve the live API.

Speech engines also need their model data. Before tagging a complete release,
record the selected model download URLs/checksums and native-library versions,
including any enabled RNNoise, Whisper, Airspy HF+ and RTL-SDR support. Large
downloaded models and machine-built binaries belong in release assets or a
verified download manifest, not as undocumented files existing only on LCD.
Cloud API keys remain local. Installing a Python package alone is not proof its
feature is ready. WSJT-X supplies the external `wsprd` executable.

## Promotion and validation

1. Preserve LCD as the reference while reviewing this branch. Its source and
   settings were backed up privately on LCD and the development Mac.
2. Clone the candidate separately and validate the CM5 application installation.
   Back up application settings, preserve normal orientation, and select compact
   layout. Compare display, touch, receiver/Wi-Fi controls and enabled features
   with LCD. Preserve the previous application release for rollback.
3. Once validated, merge the reviewed changes to main and create an immutable
   release tag. Record the installed tag/commit and hashes on both devices.
4. Future work follows branch -> review/test -> merge -> tagged deployment.
   Any emergency on-device source edit must be captured back into GitHub before
   the next release. A dirty working folder is not a release identifier.

Local source/syntax/default-seeding checks do not replace the staged hardware
and feature checks above. CM5 now has the candidate application; its previous
application and settings are backed up for rollback. The original LCD remains
the unchanged reference.
