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

For a plain black appliance screen without the desktop wallpaper or taskbar,
see [CM5 kiosk configuration](docs/cm5-kiosk.md). This keeps the verified
Wayland compositor, display and touch setup.

For the separately installed Ground Station and Satvisor evaluation dashboards,
addresses, setup and receiver ownership notes, see
[satellite application evaluation](docs/satellite-evaluation.md).

### Update, validate and run on the CM5

Run the following on the CM5 from its repository checkout. The compile check
and unit suite finish before the running application is replaced:

```sh
cd ~/ituner-sdr
git switch main
git pull --ff-only origin main
python3 -m compileall -q UI
python3 -m unittest discover -s UI -p 'test_*.py'
sudo ./scripts/install.sh --cm5-existing-display
```

The application-only installer copies the current UI and assets to
`/opt/ituner-sdr`, records the installed Git commit, and restarts the two CM5
services. It does not install an LCD module, overlay, kernel, orientation, or
touch mapping. Check the deployed revision and follow the live log with:

```sh
cat /var/lib/ituner-sdr/installed-commit
systemctl status ituner-sdr-touch-ready.service ituner-sdr.service
sudo journalctl -u ituner-sdr-touch-ready.service -u ituner-sdr.service -f
```

Useful service controls are:

```sh
sudo systemctl restart ituner-sdr.service
sudo systemctl stop ituner-sdr.service
sudo systemctl start ituner-sdr.service
```

The current CM5 interface uses the native **1280 × 800** landscape workspace
on the portrait 800 × 1280 JD9365DA-H3 panel and reads the GT911/Goodix touch
device directly. The same layout is used by desktop test mode. Current shared
features include the receiver list and full-width Globe, KiwiSDR, OpenWebRX,
LAN and FM-DX sources, retained sharp Globe tiles while dragging, editable
themes and S-meter selection, the three-column frequency keypad, and Dual RX.
Large square S-meters are hidden when the frequency is placed Left or Middle;
Middle is centered across the complete 1280-pixel display, and Dual RX always
uses the compact default meter so its controls remain visible.

Both installation paths use bounded local KiwiSDR name discovery for the main
radio and digital decoders, without HTTP status probes. If multicast discovery
fails, select a reserved LAN IP; stale cached addresses are not reused without
identity verification. See [local receiver discovery](docs/local-receivers.md).

For the custom CM5 carrier's **ES8316 codec / Class-D speaker amplifier**, add
`--cm5-audio` explicitly:

```sh
sudo ./scripts/install.sh --cm5-existing-display --cm5-audio
sudo reboot
```

This opt-in profile includes the verified audio
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

## ADS-B and VHF/UHF decoders

The Decode menu groups existing KiwiSDR modes under **HF DECODERS** and local
USB tools under **VHF/UHF DECODERS**. Airspace uses readsb and the shared GLOBE
map for live aircraft, trails, follow mode, traffic search, dongle assignment,
reconnection and on-screen flight/receiver/diagnostic logs. Its separate 978 UAT
slot is reserved for a future second receiver and decoder. Install
with `sudo ./scripts/install-adsb.sh` or add `--adsb` to the CM5 app installer.
See [ADS-B setup and custom-carrier USB power selection](docs/adsb.md).

Airspace now separates [Live, Since opened and History](docs/adsb-traffic-views.md),
with position/contact ages and a display-only Start fresh control. Its
[reception dome](docs/adsb-reception-coverage.md) accumulates received directions
and 3D positions. The [Spectrum Analyzer](docs/spectrum-survey.md), above HF in
the Decode menu, provides survey, signal investigation, heatmap, persistence,
watchlist and comparison/report tools on web and touchscreen.

**Settings → Radio / User** edits one [shared station profile](docs/radio-user-information.md)
for local SDR applications, satellite predictions and weather. Optional USB GNSS
can update the radio's location as it moves; enable support with
`sudo scripts/install-station-info.sh`. Remote receivers retain their own sites.

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

## Test the application on macOS, Windows or Linux

Desktop test mode runs the active OpenGL application in the same fixed
**1280 × 800** layout used on the CM5. It does not require the Pi, LCD driver,
touch controller, root access, or system service. Python **3.10–3.12** is
recommended; Python 3.12 retains the `audioop` module used by desktop volume
control. Run every command from the repository root.

The minimum desktop packages exercise the UI, live receiver, waterfall and
local audio. NumPy and SciPy enable the Python decoder paths. FFmpeg is needed
for FM-DX MP3 audio.

### macOS

Install Python and the native audio/decoder tools with Homebrew, then create a
repository-local environment:

```bash
brew install python@3.12 portaudio ffmpeg
git clone https://github.com/ituner/ituner-sdr.git
cd ituner-sdr
python3.12 -m venv UI/.venv
source UI/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pygame PyOpenGL Pillow sounddevice numpy scipy
python UI/kiwi_gl_display.py --desktop --fps 30
```

For a clean test that ignores the previously selected receiver:

```bash
python UI/kiwi_gl_display.py --desktop --fps 30 \
  --server http://21662.proxy2.kiwisdr.com:8073 \
  --no-remember-receiver
```

### Windows 10/11 (PowerShell)

Install 64-bit Python 3.12 from python.org, open PowerShell in the repository,
and run:

```powershell
git clone https://github.com/ituner/ituner-sdr.git
Set-Location ituner-sdr
py -3.12 -m venv UI\.venv
Set-ExecutionPolicy -Scope Process Bypass
UI\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install pygame PyOpenGL Pillow sounddevice numpy scipy
python UI\kiwi_gl_display.py --desktop --fps 30
```

Install FFmpeg before testing FM-DX streams:

```powershell
winget install --id Gyan.FFmpeg -e
```

Open a new PowerShell after that installation so `ffmpeg` is on `PATH`.

### Linux desktop (Debian/Ubuntu)

Install the native OpenGL, audio and FFmpeg libraries, then create the virtual
environment:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip libgl1 libportaudio2 ffmpeg
git clone https://github.com/ituner/ituner-sdr.git
cd ituner-sdr
python3 -m venv UI/.venv
source UI/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pygame PyOpenGL Pillow sounddevice numpy scipy
SDL_VIDEODRIVER=wayland python UI/kiwi_gl_display.py --desktop --fps 30
```

For an X11 session, replace the last command with:

```bash
SDL_VIDEODRIVER=x11 python UI/kiwi_gl_display.py --desktop --fps 30
```

The explicit SDL backend prevents the Linux desktop run from selecting the
Pi's fullscreen KMS/DRM backend.

### Desktop test controls and diagnostics

- Left-click and drag operates the touch UI, tuning, passband and Globe.
- Mouse wheel zooms the waterfall or Globe under the pointer.
- Command-left-drag on macOS, Windows-key-left-drag on Windows, or
  Super-left-drag on Linux moves the borderless window.
- `Esc` or `q` exits; the window intentionally has no native title bar.
- Add `--no-audio` to test rendering without opening an audio device.
- Add `--duration 60` for a one-minute smoke test.
- Add `--server URL --no-remember-receiver` to start from a specific receiver
  instead of the locally remembered one.

Before opening the UI, a quick source and unit-test check is:

```bash
python -m compileall -q UI
python -m unittest discover -s UI -p 'test_*.py'
```

The receiver is a live remote service. A silent stream or missing waterfall can
mean that the selected server is full or blocks external clients; choose another
receiver before treating it as a local build failure.

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
- Receiver directories refresh at startup and every 24 hours while the app stays running. Daily updates run off the UI thread, fetch central directory feeds only, preserve cached data on failure, and never launch receiver health probes.
- Kiwi directory firmware modes (for example `rx8.wf3`) are saved in the catalog and shown as neutral `AUDIO 8` / `WF 3` badges. These are advertised total capacities, not tested health or free waterfall slots. Missing mode metadata remains unknown.
- Background receiver health scans are disabled. Installers stop and mask the retired `ituner-sdr-health.service`. Public receiver listings use cached directory metadata, without `/status`, audio or waterfall probes. No receiver, including local receivers, is queried through `/status`. Connected Kiwi receivers supply live occupancy using `SET GET_USERS` / `MSG user_cb` on existing authenticated WebSockets, shared at a 5-second cadence per receiver address. Disconnected receivers use directory snapshots. WSPR reporting locations remain configured separately.

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

The receiver browser is one catalog of KiwiSDR, OpenWebRX, LAN, and FM-DX
receivers with a single source segment row (`KIWI`, `OPENWEBRX`, `LAN`,
`FM-DX`, `ALL`). KiwiSDR is the default and most complete receiver type.
OpenWebRX uses the same browser and adapts its controls to the active server
profile. LAN receivers show only controls implemented by the connected
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

## S-meter designs

Display → Themes → S-Meters offers 30 designs with moving previews, including
white and orange Vintage HD, Sliding Pointer Orange, OE3IDE and KE9NS faces,
six animated Magic Eye styles, and black, amber and copper instruments with
S, dBm and µV scales.
Tall square meters use the Home Bandpass panel's space only when the frequency
is on the right. They are hidden for Left and Middle frequency positions, and
Dual RX always uses the compact default meter.
Themes now has a preview-first gallery with a separate S-meter tab and quick
filters. **Save & Home** saves and returns directly to Home; **Cancel** leaves
saved settings untouched. Optional layout, text and color edits live under
Customize. See [Themes](docs/themes.md).
Flexible faces fill the rail width and use sharper resizing without an added
grey border. See [meter selection, calibration and artwork sources](docs/s-meters.md).

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

### VHF/UHF Signal Observatory

AIS, APRS, rtl_433, Meteor-M LRPT, CubeSat telemetry and RS41/DFM radiosondes are available under **Decoders → VHF/UHF**, with SoapySDR receiver assignment and shared ownership with ADS-B. The browser observatory is at [cm5.local:8092](http://cm5.local:8092/). See [setup, reception profiles and visible logs](docs/vhf-uhf.md). Install engines using `sudo bash scripts/install-vhf.sh` or the app-only installer's `--vhf` option.
