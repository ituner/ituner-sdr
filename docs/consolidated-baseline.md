# Official shared application baseline for LCD and CM5

The official repository is `https://github.com/ituner/ituner-sdr`, branch `main`.
PR #9 is merged. A fresh CM5 application/settings installation from main passed,
and the owner accepted the display tests on both machines on 2026-09-27.
PR #8 remains excluded. See `cm5-pr9-validation.md` for evidence and scope.

The shared runtime source matches both running machines. This does not mean
LCD's historical dirty Git checkout was reset, or that both operating systems,
drivers, private preferences and optional dependencies are identical.

## What belongs in GitHub

- Shared application source, including the live OpenWebRX modules and local
  receiver changes. The renderer is byte-identical to the captured LCD file.
- UI assets and the exact Oxanium font used by LCD, with its OFL license.
- Reviewed UI defaults: compact instruments, Oxanium, spectrum on, Classic
  waterfall palette, fixed floor 142 / ceiling 245, speed 4, auto levelling off. No personal receiver
  history, credentials, API keys, or private saved settings.
- Separate machine startup profiles and reproducible dependency instructions.
- A version manifest with checksums: `config/lcd-baseline-manifest.json`.
- CM5 display source archived under `hardware/cm5/reference-display` for
  recovery. Application installation does not install or rebuild that driver.

The consolidated baseline incorporates the actual live LCD files on top of main.
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
| Instrument layout | compact | compact |

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
normal orientation. A fresh user state gets the validated compact UI and fixed waterfall defaults;
existing user settings are preserved. Both running machines were explicitly
matched to these waterfall settings after finding auto levelling on only on CM5.

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

## Accepted validation and future changes

- PR #9 application installed, then removed with its services and saved UI
  settings backed up. CM5 rebooted and installed from a fresh main checkout.
- Compact layout, Oxanium, normal orientation and touch mapping were generated
  automatically. All 51 tracked UI/assets matched main byte for byte.
- Final reboot started app and health services, detected GT911 and connected
  Kiwi sound/waterfall streams. All eight protected display hashes stayed intact.
- Waterfall settings were subsequently matched on both machines and accepted
  by the owner; they are now included in fresh-install defaults.
- The source baseline tag identifies an application/configuration snapshot,
  not a reproducible full OS image or validation of every optional feature.

Future application changes should originate in this repository, be reviewed and
validated before merging to main, and be deployed by a recorded commit/tag.
Capture emergency on-device source changes in GitHub before the next deployment.
Keep hardware profiles separate; never copy one machine's boot setup to the other.
