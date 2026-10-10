# iTuner SDR — official application repository

**Official source:** [ituner/ituner-sdr](https://github.com/ituner/ituner-sdr),
branch **`main`**. The shared LCD/CM5 application baseline was consolidated in
PR #9 and accepted on both machines on 2026-09-27. PR #8 three-knob controls are
not included. See [the baseline guide](docs/consolidated-baseline.md) and
[validation results](docs/cm5-pr9-validation.md).

The subsequent board interface, FM-DX, digital decoders, callsign search and
local receiver recovery are consolidated in the shared source. See the
[October consolidation record](docs/consolidation-2026-10.md) for the older
PRs it incorporates or supersedes. Fresh builds do not need the historical
CM5 decoder compatibility patches.

For a CM5 with the verified working display, use:

```sh
sudo ./scripts/install.sh --cm5-existing-display
```

This installs the application while preserving the existing display/touch
drivers and boot settings. Fresh UI preferences use compact instruments,
Oxanium, Classic waterfall colours, fixed range 142–245, speed 4 and automatic
levelling off. Existing preferences are preserved. LCD and CM5 retain their
own orientation, touch mapping and audio backend.

Both installation paths include automatic local KiwiSDR address recovery for
the main radio and digital decoders. After the first successful connection,
the application remembers the receiver's address and checks its advertised
name before reusing it if `.local` discovery fails. No extra package or option
is needed. A DHCP reservation is recommended when using Wi-Fi extenders; see
[local receiver recovery and its limits](docs/local-receivers.md).

For the custom CM5 carrier's **ES8316 codec / Class-D speaker amplifier**, add
`--cm5-audio` to that command. This opt-in profile includes the verified audio
driver/overlay setup, high-quality sample-rate conversion, volume/mute controls
and automatic speaker shutdown when headphones are inserted. It preserves the
working display/touch drivers. See [CM5 audio setup and required board repairs](docs/cm5-audio.md).

The installer provisions the tested Python engines and Vosk, Moonshine, Parakeet,
Whisper Base Q5_1 and HF-enhancement models automatically, using fixed versions and verified
checksums. It requires 64-bit Raspberry Pi OS Trixie / Python 3.13. See
[dependency setup and version policy](docs/runtime-dependencies.md). This is an
application/model baseline, not a complete OS image; experimental engines and
hardware setup remain separate. The reference LCD's running source matches this
baseline, but its old dirty Git checkout has not been reset or replaced.

Whisper uses a pinned CPU-only `whisper.cpp` build and multilingual Base Q5_1,
including Chinese and Romanian transcription. Installation makes the engine
available; it preserves the selected ASR engine. See [Whisper installation](docs/whisper.md).

## CM5 / JD9365DA-H3 30-pin LCD hardware setup

For a fresh system using the r2 main board's **YX80030ACT3 on FPC2**, see the
[JD9365DA-H3 + GT911 build kit](hardware/cm5/reference-display/README.md).
It includes the verified LCD module source, LCD/touch overlays, Makefile,
boot and desktop configuration examples, installation and recovery steps.
Touch uses the kernel's Goodix driver. Hardware setup is separate from the
application installer; other panels using JD9365 may need different initialization.

## Legacy Raspberry Pi 5 / YX45011A hardware installation

The remaining hardware instructions describe the legacy 400×960 ST7701 setup.
**Do not apply that hardware installer to either verified LCD/CM5 installation.**

One self-contained installer for the YX45011A display, GT911 touch controller, and iTuner SDR radio interface on a Raspberry Pi 5 running 64-bit Raspberry Pi OS Trixie (Python 3.13). It installs the required packages, driver, overlays, UI, configuration, and systemd boot services.

## Hardware connection

Use **only Raspberry Pi 5 CAM/DISP 1 (DSI1)**. The 22-pin FFC from the adapter board connects to CAM/DISP 1; do **not** move it to CAM/DISP 0. The display overlay targets DSI1 and the bundled GT911 touch overlay targets the matching `i2c_csi_dsi1` controller (Linux I2C bus 11, address `0x5d`).

The display framebuffer is **400x960**, not 320x960. The panel is physically 960 pixels tall and is used in the installed flipped/portrait orientation.

## Architecture

```text
CAM/DISP 1 (DSI1) ── display overlay + rebuilt ST7701 panel module ── DRM/KMS framebuffer (400x960)
                    └─ GT911 overlay ── Goodix input event ── OpenGL SDR UI
                                                           └─ KiwiSDR WebSocket receiver + PipeWire audio
```

`UI/` contains two UI implementations:

- `kiwi_gl_display.py` is the active OpenGL/Pygame touchscreen radio. It is the service started at boot.
- `kiwi_live_display_fb.py` is the earlier Python/Pillow framebuffer skeleton/reference.

All current and future UI updates are made to the **OpenGL implementation**. The Python skeleton is included for reference and is not started or maintained as the active UI.

## Install

1. Start with 64-bit Raspberry Pi OS Trixie on a Raspberry Pi 5, network access, and the adapter FFC firmly seated in **CAM/DISP 1**.
2. Clone this repository and run:

   ```bash
   git clone https://github.com/ituner/ituner-sdr.git
   cd ituner-sdr
   sudo ./scripts/install.sh --legacy-display
   sudo reboot
   ```

The install is idempotent. It rebuilds the display module for the currently running kernel, stores the original module under `/var/lib/ituner-sdr/`, installs the display and touch overlays, configures the required boot settings in one marked block, installs Python/OpenGL/PipeWire dependencies, and enables all boot services.

The public receiver configured by default is the established working initial endpoint. To use a receiver you are authorized to access, configure it after reboot:

```bash
sudo ituner-sdr-configure --server http://receiver-host:8073
```

Optional settings:

```bash
sudo ituner-sdr-configure --frequency-khz 7075.794 --orientation flipped
```

## Run Locally on macOS

The active OpenGL radio can run directly on a Mac for UI development and receiver testing. Desktop modes use a fixed-size, borderless window with no macOS title bar or native close/minimize/fullscreen buttons. They do not need the Pi, DSI display, or touch controller.

Use Python 3.9 through 3.12:

```bash
git clone https://github.com/ituner/ituner-sdr.git
cd ituner-sdr
python3 -m venv UI/.venv
source UI/.venv/bin/activate
python -m pip install pygame PyOpenGL sounddevice Pillow
```

On macOS where Anaconda shadows the desired interpreter, use the system Python explicitly:

```bash
/usr/bin/python3 -m venv UI/.venv
```

Available output modes, run from the repository root:

| Output | Command | Layout |
| --- | --- | --- |
| Standard macOS desktop | `UI/.venv/bin/python UI/kiwi_gl_display.py --desktop --fps 30` | `960x320` SDR canvas |
| Wide macOS desktop | `UI/.venv/bin/python UI/kiwi_gl_display.py --desktop-1280 --fps 30` | `1024x480` SDR canvas plus a `256x480` navigation rail (`1280x480` total) |
| Raspberry Pi display | `UI/.venv/bin/python UI/kiwi_gl_display.py` | Fullscreen rotated `400x960` KMS/DRM framebuffer |

The Raspberry Pi command requires its KMS/DRM display and touch environment and is normally started by `ituner-sdr.service` rather than launched from macOS.

Desktop controls:

- Left-click and drag: touch-style tuning, menus, filter, and passband controls.
- Right-click and drag: does not move the window.
- Command-left-drag anywhere: move the borderless window.
- Mouse wheel: zoom.
- `Esc` or `q`: close the application.
- `--no-audio`: run without CoreAudio output.

Because desktop windows are borderless, use `Esc` or `q` instead of a macOS close button.

The receiver is a live public KiwiSDR connection. If the remembered receiver does not provide a waterfall, choose another from `Home -> RX`. Desktop mode is a development/runtime option only; it leaves the Pi's rotated framebuffer output untouched.

### FM-DX receivers

The receiver picker also includes available public FM-DX Webservers. Select
the **FMDX** route to see only those receivers. FM-DX tuning stays within the
band limits published by each server and is shown as the server-controlled
`FM-FMDX` mode; the saved Kiwi demodulator is retained for the next Kiwi
receiver.

FM-DX programme audio arrives as MP3 and is decoded locally with `ffmpeg` into
the existing audio, captions/callsign, scope, and audio-waterfall paths. The
Pi installer now installs `ffmpeg` automatically. For macOS development,
install it separately (for example with `brew install ffmpeg`) before opening
an FM-DX receiver. Live RDS programme-service names and server presets are
kept in the local receiver-state cache; they are not committed to the
repository.

## Boot services and status

After reboot, the following services are enabled:

- `ituner-sdr-touch-ready.service` verifies the GT911 touch device.
- `ituner-sdr.service` starts the active OpenGL radio UI.
- Background receiver health scans are disabled. Installers stop and mask the retired `ituner-sdr-health.service`. Public receiver listings use cached directory metadata, without `/status`, audio or waterfall probes. Your local receiver may still be queried through `/status` for capacity/location and address recovery.

Check them with:

```bash
systemctl status ituner-sdr.service ituner-sdr-touch-ready.service
```

The UI uses the Goodix touch event automatically. Audio is sent through PipeWire to its current default audio sink; the installer enables the selected user's persistent runtime so this works at boot without an interactive login.

## Touch test

Run the installed standalone touch check at any time:

```bash
sudo ituner-sdr-touch-test
```

It draws a green circle that follows your finger. Press `Ctrl+C` to exit, then restart the radio UI:

```bash
sudo systemctl restart ituner-sdr.service
```

## Receivers

The receiver browser is one catalog of KiwiSDR, OpenWebRX, local, and FM-DX
receivers with a single source segment row (`KIWI`, `OPENWEBRX`, `LOCAL`,
`FM-DX`, `ALL`). KiwiSDR is the default and most complete receiver type.
OpenWebRX uses the same browser and adapts its controls to the active server
profile. Local receivers show only controls implemented by the connected
hardware. FM-DX servers use a shared tuner: iTuner listens without retuning by
default, and any shared frequency control requires an explicit acknowledgement
for the current session only. See the [board_v1 changelog](docs/board-v1-changelog.md)
for the full list of browser and interface changes.

## Uninstall

The uninstall is explicit and restores the saved display kernel module for the current kernel, removes this package's marked boot-config block and overlays, then disables/removes its services and installed files:

```bash
sudo ituner-sdr-uninstall
sudo reboot
```

It preserves `/etc/ituner-sdr.conf` by default so an endpoint choice is not lost. To remove that configuration too:

```bash
sudo ituner-sdr-uninstall --purge-config
sudo reboot
```

## Repository layout

- `display-driver/` — verified ST7701 panel module source and DSI1 overlay.
- `touch-driver/` — verified GT911 DSI1/I2C overlay and circle-following touch test.
- `UI/` — OpenGL active UI, Python reference UI, and required texture assets.
- `UI/assets/menu-icons-svg/` — source SVG menu and Home icons.
- `UI/assets/menu-icons/` — `64x64` transparent PNG copies loaded by the OpenGL runtime.
- `scripts/` and `systemd/` — installation, configuration, uninstall, and boot integration.

## SSTV

Digital tools → SSTV adds continuous receiver decoders, a 1280 × 800 touch
gallery and LAN SSTV/WSPR pages with receiver selection and Add/Edit/Start/Stop controls. See [SSTV setup and supported modes](docs/sstv.md).

## WSPR history and reporting

WSPR spots survive decoder restarts and card removal. Browse sessions, dates
and receiver/band archives on the touchscreen or `/wspr`, export CSV, and
optionally upload new spots to WSPRnet with a separate identity per receiver.
See [history and reporting setup](docs/WSPR_HISTORY.md).

## Hell RX

Seven Hellschreiber receive variants, local/web live strips and optional manual
PSK Reporter spots: see [Hell RX setup and operation](docs/HELL.md).

## QRSS

Slow waterfall captures and tentative CW / FSKCW Morse text share one Kiwi
channel. AUTO follows up to six keyed signals with independent frequency, FSK shift and
Morse timing, with local and web receiver controls. See [QRSS setup and limits](docs/QRSS.md).

## CW Morse

Digital tools → CW Morse (CM5 Modes → CW) adds automatic Morse signal acquisition,
independent speed estimation for up to four signals on one Kiwi channel, a live
waterfall and persistent text history. Add/Edit/Start/Stop controls are shared
with `/cw`; history can be exported as CSV. The pinned GGMorse engine builds
locally during dependency installation without models or display-driver changes.
See [CW setup, engine choice and limits](docs/cw.md).

### Receiver client identity

Use the exact lowercase client label **`ituner`** for receiver connections and
all decoder modes, without mode suffixes. This is the user-selected project
default, centralized in `UI/client_identity.py`. Kiwi listener names, OpenWebRX
client identification and FM-DX receiver HTTP/WebSocket user agents share it.
Reporter callsigns and locations for spot uploads remain separate settings.
