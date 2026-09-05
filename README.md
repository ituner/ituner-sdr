# iTuner SDR for Raspberry Pi 5

iTuner SDR is a dedicated Raspberry Pi 5 touchscreen SDR console built around a native OpenGL interface and direct KiwiSDR WebSocket connections. It combines live waterfall/spectrum display, touch tuning, demodulated audio, passband control, receiver health/failover logic, WSPR monitoring/decoding, broadcast schedule identification, local speech recognition, and diagnostics in a self-contained embedded appliance.

The repository also contains the display/touch bring-up, installer, configuration tools, systemd integration, and macOS desktop-development modes.

## Highlights

- Native OpenGL/Pygame SDR UI designed for the 4.8-inch bar display.
- Direct KiwiSDR `W/F` and `SND` WebSocket clients; no embedded browser is used.
- Live GPU-resident waterfall plus optional spectrum/peak-hold view.
- Touch tuning, drag tuning, zoom, frequency ruler, S-meter, and real passband controls.
- AM, SSB, CW, FM, synchronous AM, IQ, DRM, and related Kiwi receiver modes.
- PipeWire audio playback with adaptive buffering and a direct-ALSA A/B test path.
- Persistent receiver, frequency, zoom, mode, filter, audio, and UI preferences.
- Conservative receiver-health probing for public KiwiSDR servers.
- Up to six concurrent WSPR monitor tiles with `wsprd` decoding, logging, waterfall history, and distance plots.
- Scheduled shortwave broadcast identification with receiver/transmitter geographic context.
- Optional local speech-recognition/caption engines.
- Experimental globe-based public-receiver picker and live diagnostics/test tools.
- One installer for display, touch, UI, configuration, dependencies, and boot services.

## Hardware connection

Use **only Raspberry Pi 5 CAM/DISP 1 (DSI1)**. The 22-pin FFC from the adapter board connects to CAM/DISP 1; do **not** move it to CAM/DISP 0.

The display overlay targets DSI1 and the bundled GT911 touch overlay targets the matching `i2c_csi_dsi1` controller (Linux I2C bus 11, address `0x5d`).

The Linux DRM/KMS framebuffer is **400x960**, not 320x960. The application maps that rotated framebuffer into the logical landscape SDR interface used by the panel.

## Architecture

```text
CAM/DISP 1 (DSI1)
  |-- ST7701 display overlay/module --> DRM/KMS framebuffer (400x960)
  |-- GT911 overlay -----------------> Goodix touch input

Goodix input --> OpenGL/Pygame SDR UI
                         |-- KiwiSDR W/F WebSocket --> waterfall + spectrum
                         |-- KiwiSDR SND WebSocket --> mode/filter/S-meter/audio
                         |-- PipeWire or direct ALSA --> USB audio output
                         |-- WSPR monitor workers --> wsprd + local logs/graphs
```

`UI/` contains two UI implementations:

- `kiwi_gl_display.py` is the active OpenGL/Pygame touchscreen radio and the production implementation.
- `kiwi_live_display_fb.py` is the earlier Python/Pillow framebuffer implementation kept as a protocol/behavioral reference and fallback.

Current development should target the **OpenGL implementation**.

## Radio interface

The main instrument view is intentionally closer to an embedded radio than a desktop application. Frequency remains the primary visual element and the waterfall uses most of the display area.

Current interface features include:

- Large monospaced frequency readout.
- Kiwi/ICOM-style segmented S-meter.
- Frequency ruler derived from the current center frequency and visible span.
- GPU-resident scrolling waterfall with automatic/manual level control.
- Optional live spectrum trace derived from the same Kiwi `W/F` stream.
- Peak-hold spectrum envelope.
- Waterfall Focus mode that fades nonessential controls after inactivity.
- Kiwi and Ice waterfall palettes.
- Persistent Home control and contextual configuration sheets.

The OpenGL waterfall is maintained as a texture ring and only new rows are uploaded, avoiding full-frame CPU redraws.

## Tuning and zoom

The normal radio view supports:

- Tap-to-tune on the waterfall.
- Continuous horizontal drag tuning.
- Pinch zoom.
- Dedicated `+` / `-` zoom controls.
- Coalesced frequency updates to the live Kiwi `W/F` and `SND` streams so fast gestures do not build a delayed command backlog.

Zoom is currently `0..14`:

```text
span_kHz = 30000 / 2^zoom
```

At zoom 14 the visible span is about 1.83 kHz, which is useful for narrow CW, FT8, and WSPR work.

## Receiver modes and passband

The Radio sheet exposes the Kiwi receiver mode catalogue used by the application, including:

```text
AM, AMN, AMW,
USB, LSB, USN, LSN,
CW, CWN,
NBFM, NNFM,
DRM, IQ,
SAM, SAU, SAL, SAS,
QAM
```

Filter edits are real receiver controls, not display-only graphics. The UI sends the selected low-cut and high-cut values to the active Kiwi `SND` session.

The filter sheet provides:

- Direct left/right edge dragging.
- Symmetric width adjustment.
- 50 Hz minimum passband width.
- CW, narrow voice, voice, wide voice, 6 kHz, 9 kHz, and Kiwi-max presets.
- Custom asymmetric filters.

The active passband is also shown over the waterfall while the instrument controls are awake.

## KiwiSDR integration

iTuner SDR talks directly to the KiwiSDR WebSocket interface.

### `W/F`

Used for:

- Live waterfall rows.
- Frequency/zoom control.
- Spectrum rendering.
- WSPR waterfall acquisition where a waterfall resource is available.

### `SND`

Used for:

- Demodulated mono PCM audio.
- Live S-meter data when supported by the receiver.
- Receiver mode and passband control.
- WSPR audio capture and decoding.

Some public KiwiSDR installations have different audio and waterfall capacity. The application therefore tracks receiver compatibility rather than assuming every server can supply both streams simultaneously.

A receiver can be treated as:

- Full `W/F + SND` capable.
- `W/F` only.
- Single-channel/capacity constrained.
- Temporarily unavailable/full/malformed.

Health checks are deliberately conservative because public KiwiSDRs are volunteer-operated and have finite client slots.

## Audio

The normal Raspberry Pi audio path is:

```text
Kiwi SND WebSocket
  -> BufferedAudioPlayer
  -> pw-cat
  -> PipeWire
  -> WirePlumber
  -> ALSA
  -> USB DAC / speaker
```

The player keeps an adaptive local reserve to absorb normal public-network packet variation without allowing an unbounded delay to accumulate.

`Home -> Audio` includes live listening controls such as:

- Speaker volume.
- Squelch.
- Audio filtering/processing controls.
- Output-backend selection.

### PipeWire / ALSA A/B path

`Home -> Audio -> OUTPUT` can switch between:

- `PIPEWIRE` — the normal production audio path.
- `ALSA DIRECT` — a diagnostic A/B path used to isolate rare audio-click behavior.

The selected path and volume are persisted with the receiver preferences.

## Receiver state and persistence

The UI remembers the active listening state across restarts, including receiver selection, frequency, zoom, and manually selected radio mode. Additional current preferences such as filter/audio selections are also persisted by the OpenGL application.

A manually selected mode remains global when changing receivers. With no explicit operator preference, the UI can still apply its normal automatic HF sideband convention.

## WSPR workspace

The OpenGL UI includes a multi-session WSPR monitoring workspace.

### Concurrent monitors

- Up to **six WSPR monitor tiles** can run concurrently.
- Each tile has its own Kiwi receiver and WSPR band.
- Startup is staggered to avoid a burst of simultaneous public-server connections.
- A tile can be edited, stopped, or deleted independently of the others.

### Views

Each tile can show:

- Live/narrow waterfall activity.
- Recent decoded spots.
- Compact distance/history information.

The full waterfall view uses an **800-row in-RAM history ring** and does not require opening a second Kiwi waterfall connection.

### Decoding

Each WSPR monitor:

- Captures approximately UTC-aligned two-minute PCM windows.
- Queues decode work to `wsprd`.
- Serializes decode jobs and uses low CPU priority to keep radio interaction responsive.
- Logs receiver, band, decoder state, and decoded spots locally.
- Defaults to `SWL` identity until an operator callsign/grid is configured.

Distance is calculated from the selected receiver's Maidenhead locator to the decoded transmitter locator.

The compact history visualization uses fixed WSPR-cycle bins so empty two-minute periods remain visible rather than being compressed out of the graph.

The WSPR code also understands that modern Kiwi configurations can advertise more audio receivers than waterfall channels. If a dedicated W/F stream is unavailable, audio/decode service can continue without aggressive waterfall retries.

## Broadcast schedule identification

The waterfall can show a `SCHEDULED BROADCASTS` overlay based on external schedule data and the current tuned frequency.

The matching behavior is data-driven through:

```text
UI/broadcast-identification-policy.json
```

The policy covers frequency tolerance, ambiguity handling, cache timing, and UTC schedule expectations.

The overlay intentionally identifies **scheduled broadcasts**, not verified RF content. When location data is available it can show receiver context and transmitter distance. A remote Kiwi with no usable GPS information remains explicitly unknown rather than silently substituting the Pi's location.

## Local speech recognition

The Audio/ASR interface supports selectable local caption engines, including:

- `OFF`
- `VOSK`
- `MOON`
- `PARA`
- `WHISPER`

These engines consume the normal Kiwi `SND` PCM path while receiver audio playback continues independently. Offline recognition is bounded so stale audio is dropped rather than accumulating delayed captions.

## Diagnostics and experimental tools

### DJ Tune

The live tuning test bench exercises the same selected receiver, `W/F` connection, and `SND` audio path used by normal listening.

It supports selectable tuning ranges, frequency steps, command rates, and repeatable sweep/jitter patterns for comparing responsiveness and audio behavior. State updates are coalesced so a slow receiver never receives a delayed backlog of obsolete retunes.

### Globe receiver picker

`Home -> Tests -> Globe` is an **experimental** geographic public-receiver picker.

It uses the public Kiwi map feed, draws an orthographic globe, and allows drag/zoom/tap selection of a geographic region. The app can select a small health-ranked receiver triangle and audition the best candidate first, using the others as geographic fallbacks.

It does **not** mix three receiver audio streams. The multi-site geometry is intended to remain compatible with possible future timing/IQ experiments.

## Install

Start with a clean Raspberry Pi 5 running current Raspberry Pi OS (Bookworm or newer), network access, and the adapter FFC firmly seated in **CAM/DISP 1**.

```bash
git clone https://github.com/ituner/ituner-sdr.git
cd ituner-sdr
sudo ./scripts/install.sh
sudo reboot
```

The installer is idempotent. It:

- Rebuilds the display module for the currently running kernel.
- Stores the original module under `/var/lib/ituner-sdr/`.
- Installs the display and touch overlays.
- Adds the required marked boot configuration.
- Installs Python/OpenGL/PipeWire dependencies.
- Installs configuration/test helpers.
- Enables the boot services.

To configure a receiver you are authorized to access:

```bash
sudo ituner-sdr-configure --server http://receiver-host:8073
```

Optional settings include:

```bash
sudo ituner-sdr-configure --frequency-khz 7075.794 --orientation flipped
```

## Run locally on macOS

The active OpenGL radio can run directly on a Mac for UI development and receiver testing. Desktop modes do not require the Pi, DSI display, or GT911 controller.

Use Python 3.9 through 3.12:

```bash
git clone https://github.com/ituner/ituner-sdr.git
cd ituner-sdr
python3 -m venv UI/.venv
source UI/.venv/bin/activate
python -m pip install pygame PyOpenGL sounddevice Pillow
```

If Anaconda shadows the desired interpreter:

```bash
/usr/bin/python3 -m venv UI/.venv
```

Available output modes:

| Output | Command | Layout |
| --- | --- | --- |
| Standard macOS desktop | `UI/.venv/bin/python UI/kiwi_gl_display.py --desktop --fps 30` | `960x320` SDR canvas |
| Wide macOS desktop | `UI/.venv/bin/python UI/kiwi_gl_display.py --desktop-1280 --fps 30` | `1024x480` SDR canvas plus `256x480` navigation rail |
| Raspberry Pi display | `UI/.venv/bin/python UI/kiwi_gl_display.py` | Fullscreen rotated `400x960` KMS/DRM framebuffer |

Desktop controls:

- Left-click and drag: touch-style tuning and UI interaction.
- Mouse wheel: zoom.
- Command-left-drag: move the borderless macOS window.
- `Esc` or `q`: close the application.
- `--no-audio`: run without desktop audio output.

## Boot services and status

After installation/reboot, the repository installs services for the active OpenGL radio, touch readiness, and receiver-health support.

The primary documented services are:

- `ituner-sdr-touch-ready.service`
- `ituner-sdr.service`
- `ituner-sdr-health.service`

Check them with:

```bash
systemctl status ituner-sdr.service ituner-sdr-touch-ready.service ituner-sdr-health.service
```

The UI reads the Goodix touch device automatically. PipeWire is configured so audio can work at boot without requiring an interactive desktop login.

## Touch test

Run the standalone installed touch test with:

```bash
sudo ituner-sdr-touch-test
```

It draws a circle following the current finger position. Press `Ctrl+C` to exit and restart the radio UI if needed:

```bash
sudo systemctl restart ituner-sdr.service
```

## Current limitations

Some interface areas remain intentionally incomplete or experimental:

- Decoder and Network sheets are not yet complete live subsystems.
- The normal public-receiver menu is still a curated shortlist rather than a full searchable directory.
- The Globe receiver picker is experimental.
- Direct ALSA output exists primarily as an engineering A/B diagnostic path.
- Public receiver capabilities vary; not every server supports simultaneous `W/F` and `SND` sessions or the same maximum waterfall zoom.

## Uninstall

The uninstall restores the saved display kernel module for the current kernel, removes the package's marked boot configuration and overlays, and disables/removes the installed services/files:

```bash
sudo ituner-sdr-uninstall
sudo reboot
```

The receiver configuration is preserved by default. To remove it too:

```bash
sudo ituner-sdr-uninstall --purge-config
sudo reboot
```

## Repository layout

- `display-driver/` — ST7701 panel module source and DSI1 display overlay.
- `touch-driver/` — GT911 DSI1/I2C overlay and touch test.
- `UI/kiwi_gl_display.py` — active OpenGL/KMS SDR interface.
- `UI/kiwi_live_display_fb.py` — earlier Pillow/framebuffer implementation and protocol reference.
- `UI/kiwi_station_health.py` — receiver health support.
- `UI/broadcast-identification-policy.json` — scheduled-broadcast matching policy.
- `UI/assets/` — menu icons, waterfall/map assets, and geographic data.
- `UI/docs/` — detailed radio-interface implementation notes.
- `docs/` — project notes including WSPR workspace behavior.
- `config/` — installed/application configuration material.
- `scripts/` — installation, configuration, deployment, and uninstall helpers.
- `systemd/` — boot/service integration.
- `display-driver/` and `touch-driver/` — Raspberry Pi hardware integration.
