# KiwiSDR Radio Interface Notes

Last updated: 2026-07-30

This is the working record for the custom KiwiSDR frontend on the Raspberry Pi 5 bar LCD. It covers the original Pillow/framebuffer implementation and the current OpenGL implementation, including the display geometry, touch model, live KiwiSDR connection, deployment, and the design decisions that are meant to remain in place.

## Current State

- **Current renderer:** `tools/kiwi_gl_display.py`
- **Current Pi service:** `kiwi-gl-display.service`
- **Pi working directory:** `/home/ituner/codex-sdr-display`
- **Logical interface:** `960x320`, landscape
- **Physical DRM framebuffer:** `400x960`, portrait
- **Display orientation:** flipped by the renderer with `--orientation flipped`
- **Renderer target:** 30 fps, one-pixel waterfall rows
- **Live source:** a public KiwiSDR `W/F` WebSocket stream
- **Receiver preference:** the last manually selected demodulation mode is global and persists across receiver changes and restarts
- **Current observed process footprint on Pi:** about 134 MB RSS and 7% CPU; this varies with receiver traffic and the active UI.

The OpenGL service is enabled at boot and should be considered the production baseline. The direct-framebuffer implementation remains in the repository as a functional reference and fallback.

## Interface Intent

The interface is deliberately an embedded radio instrument, not a desktop web UI:

- Frequency is the first visual priority.
- The waterfall stays persistent and uses most of the display height.
- The S-meter is compact but legible, with a Kiwi-like scale.
- Most controls are quiet/translucent and fade after four seconds of inactivity.
- The first touch wakes the controls; the following touch performs the action.
- Larger configuration surfaces are contextual sheets over the waterfall, rather than permanent rows of small controls.
- Touch targets are sized for a 4.8-inch display.
- Avoid decorative borders, thick top bars, gradients, and dense "desktop menu" layouts.

## Display and Touch Geometry

The LCD is physically a `960x320` landscape bar display driven through a rotated `400x960` DRM framebuffer. The panel has an active physical scan height of 400 pixels, of which the upper 320 visible rows are useful. The bottom 80 physical rows are inactive/hidden.

The driver and panel bring-up are documented in [yx45011a-pi5-display-bringup.md](yx45011a-pi5-display-bringup.md). The key operational facts are:

| Item | Value |
| --- | --- |
| Linux framebuffer | `400x960`, 32 bpp, 1600-byte stride |
| Logical UI canvas | `960x320` |
| Physical active scan | `960x400` |
| Visible physical region | rows `0..319` |
| Hidden physical region | rows `320..399` |
| Touch controller | Goodix GT911, normalized to `960x320` |
| Current visual orientation | 180 degrees from the original panel orientation |

`tools/kiwi_gl_display.py` has the authoritative mapping in `logical_to_native()`. In the current `flipped` orientation, logical point `(x, y)` maps to native framebuffer point `(y + 80, 960 - x)`. This intentionally applies the vertical offset for the panel's hidden area and the 180-degree visual rotation in the same rendering pass.

The Linux boot console rotation is a separate driver/framebuffer concern. The application still must retain its own `flipped` mapping so touch coordinates and the rendered application agree.

## Evolution of the Renderer

### 1. Static mockup and framebuffer writer

`tools/render_sdr_frontend_mockup.py` was the visual design tool and first on-panel implementation. It is now historical only: the current user interface is rendered by `tools/kiwi_gl_display.py`.

To view the exact current Pi display from the Mac, use:

```sh
/Users/andreibulucea/Documents/Pi4/P5/p5-RX/r2d2/KIWI-SDR-UI/tools/capture_p5_live_display.sh
open /Users/andreibulucea/Documents/Pi4/P5/p5-RX/r2d2/KIWI-SDR-UI/renders/p5-live-reference-960x400.png
```

This asks the live OpenGL service for a framebuffer screenshot, so it includes the actual receiver, waterfall, controls, and any active overlay rather than a separate mockup.

For a continuously refreshing Mac window of that same framebuffer, use:

```sh
python3 /Users/andreibulucea/Documents/Pi4/P5/p5-RX/r2d2/KIWI-SDR-UI/tools/p5_live_preview.py
```

It refreshes at 2 fps by default, which is gentle on the Pi while remaining useful for live UI work. Use `--fps 3` through `--fps 5` when a faster preview is needed.

### Local Desktop Development

The OpenGL receiver can also run entirely on the Mac, without the Pi or its framebuffer:

```sh
cd /Users/andreibulucea/Documents/Pi4/P5/p5-RX/r2d2/KIWI-SDR-UI
/opt/miniconda3/bin/python3 -m pip install --upgrade pygame PyOpenGL sounddevice vosk sherpa-onnx moonshine-voice
/opt/miniconda3/bin/python3 tools/kiwi_gl_display.py --desktop --fps 30
```

Use Python 3.10 or newer when you want the full local ASR feature set. `--desktop` opens the same interface in a native `960x320` landscape window, matching the SDR canvas rather than the Pi's rotated framebuffer. It connects directly to the selected KiwiSDR receiver and uses CoreAudio for normal receiver audio. Left-click and drag is the touch gesture; the mouse wheel changes zoom; `Esc` or `q` closes the window. Use `--no-audio` for silent visual-only testing. If the remembered public receiver is unavailable, choose another one with `Home -> RX`.

#### Matching Desktop ASR

The Mac simulator uses the same public receiver directory as the Pi; it reads
the live KiwiSDR directory first and caches the complete result locally. Its ASR
models are intentionally portable rather than Pi-only. To give the desktop the
same `VOSK`, `MOON`, and `PARA` choices as the Pi, run this once in macOS
Terminal while `p5` is reachable:

```bash
cd /Users/andreibulucea/Documents/Pi4/P5/p5-RX/r2d2/KIWI-SDR-UI
chmod +x tools/bootstrap_macos_asr_from_p5.sh
tools/bootstrap_macos_asr_from_p5.sh p5
```

It installs the Mac Python ASR runtime and mirrors the portable Vosk, Moonshine,
and Parakeet model data into `vendor/` beside the project. The launcher prefers
the installed Miniconda Python 3.13 when available, because Moonshine Voice's
language profiles require a modern Python runtime. The renderer finds that local
directory automatically; `ITUNER_VENDOR_DIR` may point it at an external model
disk instead.

The `MOON` selector opens an eight-language profile menu: English, Spanish,
Arabic, Japanese, Korean, Chinese, Ukrainian, and Vietnamese. English uses the
local Sherpa-ONNX Base model; selecting another language downloads Moonshine's
official Base profile once into `vendor/moonshine-voice/` and retains it for
later use. `WHISPER` is automatic-language mode. It uses the multilingual
`ggml-tiny.bin` model when installed, and intentionally falls back to the
English-only model only until that model is available. The bootstrap script
builds the native macOS Whisper executable and copies that multilingual model,
so the completed simulator matches the Pi rather than exposing a dead button.

It uses Pillow to compose a full `960x320` SDR image, then converts it to the native rotated framebuffer layout and writes `/dev/fb0` through `mmap`. It established the principal visual language:

- A large centered mono-spaced frequency readout.
- Compact mode/digital/step annunciation.
- Kiwi/ICOM-inspired segmented S-meter.
- Frequency ruler generated from the current center frequency and span.
- Waterfall beginning directly below the ruler.
- Compact lower status strip.

Useful commands:

```sh
python3 tools/render_sdr_frontend_mockup.py
python3 tools/render_sdr_frontend_mockup.py --fb
```

The first command creates PNG previews in `renders/`; the second writes a static image to the Pi framebuffer. This is still the fastest way to test layout changes without networking or touch.

### 2. Live Pillow/framebuffer Kiwi client

`tools/kiwi_live_display_fb.py` evolved the mockup into a direct framebuffer client.

It includes:

- A minimal manual WebSocket client, `KiwiWebSocket`.
- KiwiSDR `W/F` waterfall connection and command handling.
- Waterfall color mapping and automatic/manual levels.
- A ring/queue of incoming waterfall lines and 1- or 2-pixel scroll options.
- Goodix touch-event parsing.
- Tap-to-tune, swipe tuning, pinch zoom, zoom controls, station selection, and a settings picker.
- Optional `SND` stream/audio support and S-meter support.

This version composes frames on the CPU with Pillow, copies each completed frame to `/dev/fb0`, and is therefore both a good behavioral reference and the less efficient rendering path. The legacy service file in `systemd/kiwi-live-display.service` launches this renderer; it is not the current active service.

The preserved pre-OpenGL baseline is also stored under:

```text
baselines/kiwi-basic-20260728-235830/
```

### 3. Current OpenGL renderer

`tools/kiwi_gl_display.py` is the current active implementation. It retains the Kiwi protocol and touch helpers from `kiwi_live_display_fb.py`, but moves display composition to Pygame plus OpenGL running through KMS/DRM.

Important parts:

| Component | Role |
| --- | --- |
| `setup_gl()` | Opens a fullscreen `kmsdrm` Pygame OpenGL surface at native `400x960`. |
| `logical_to_native()` | Maps the logical landscape UI to the flipped, offset physical framebuffer. |
| `TextCache` | Rasterizes Pygame fonts once and uploads cached text surfaces as OpenGL textures. |
| `WaterfallTexture` | Maintains a `960x256` OpenGL texture ring; new lines are uploaded with `glTexSubImage2D()`. |
| `waterfall_worker()` | Receives and maps live Kiwi waterfall data on a worker thread. |
| `SharedState` | Thread-safe frequency, zoom, S-meter, waterfall settings, selected station, and radio-mode state. |
| main event/render loop | Reads Goodix events, resolves gestures, draws the UI, and presents with `pygame.display.flip()`. |

The renderer uses straightforward OpenGL immediate-mode geometry plus textures, not shaders. The important performance win is that the waterfall stays resident on the GPU and only new scan lines are uploaded. Static text is also texture-cached rather than rasterized every frame.

## Current UI Layout

### Top instrument band

- **Home icon:** opens the compact main command band.
- **Radio summary:** the current RF mode and digital/IQ state. Touching it opens the Radio sheet.
- **Frequency:** prominent mono-spaced display in `MHz.kHz.Hz` format. The `MHz` suffix was removed because the receiver is fixed to 0-30 MHz.
- **S-meter:** right-hand Kiwi-style segment meter. Its scale is `S1`, `S3`, `S5`, `S7`, `S9`, then `+20`, `+40`, `+60`; `S9 = -73 dBm`, with 6 dB per S-unit below S9 and dB-over-S9 above it. Scale labels and ticks are mathematically aligned. The active segments use a strong blue before S9 and red above S9.

### Ruler and waterfall

- The ruler chooses a sensible 1-2-5 major frequency step from the current span.
- Major labels are rounded aligned frequencies rather than arbitrary current-frequency decimals.
- Tick positions and labels use the same frequency calculation.
- **Spectrum mode:** an optional 64-pixel amplitude-versus-frequency trace appears above the waterfall. It is a solid white filled amplitude silhouette with a white crest, backed by a muted gray-blue Icom-style peak-hold envelope. The peak window is 10 seconds, matching the default `10s Hold` behavior documented for the IC-7610 and IC-705. Its frequency ruler moves to a 30-pixel, low-opacity overlay at the very bottom of the waterfall, replacing the lower telemetry row and leaving the spectrum unobstructed. It is derived from the live `W/F` bins with peak-preserving downsampling and light smoothing, so it adds no second KiwiSDR connection. It defaults on and is controlled through `Home → DISP → SPECTRUM`.
- The waterfall is Kiwi-inspired, with the `kiwi` palette as the default and `ice` as an alternate display palette.
- A center filter/marker band was deliberately removed. The waterfall should remain visually close to KiwiSDR rather than look like a generic spectrum analyzer.
- **Passband overlay:** when the instrument view is awake, the live SND demodulator passband is shown as a fine translucent amber window. Its two vertical edges are the actual low-cut and high-cut points relative to the tuned frequency, rather than a decorative center marker. At a waterfall span where the true width is under 10 pixels, it becomes a compact bracket rather than a falsely widened band. It fades out with Waterfall Focus.

### Persistent and quiet controls

- Home remains available; it does not fade away.
- View controls are separated by purpose: a subtle transparent `−/+` zoom group on the left, and a separate Spectrum/Passband group at the right edge. The trace icon toggles Spectrum and is cyan when active; the passband icon opens the Filter sheet. Keeping the passband control out of the center preserves unobstructed signal tuning gestures.
- Tapping `+` or `-` shows a large temporary green zoom OSD, with scale bars for levels `0..14`, then fades.
- **Waterfall Focus:** after four seconds without touch, the frequency ruler and lower status strip fade over 650 ms, while the live waterfall expands from `y=90..292` to `y=66..320`. The large frequency readout and S-meter remain fixed. This uses the existing OpenGL waterfall texture without clearing or rescaling its history.
- The first touch during Waterfall Focus restores the full instrument view and is deliberately consumed. The following touch tunes, swipes, or operates a control.
- With Spectrum enabled, the lower status/telemetry row returns as a translucent HUD at the physical bottom while controls are awake. The bottom frequency ruler sits immediately above it; both fade with Waterfall Focus.
- Settings is overlaid rather than consuming permanent waterfall area.

### Passband Filter

- The passband icon in the transparent waterfall control group opens a full-width filter sheet over the waterfall. Filter setup is deliberately not a Home sub-menu or a permanent status readout.
- The large center strip is direct manipulation: touch nearer the left or right handle and drag horizontally to reshape that filter edge. Its scale automatically tightens around the active passband so the handles remain comfortably separated. The edges cannot cross; they stop at a 50 Hz minimum width.
- A large `- / preset / +` width stepper provides fast, symmetric changes around the current filter center. Edge dragging produces a `CUSTOM` asymmetric filter; the next `-` or `+` tap deliberately re-centers it around that same center frequency.
- The cyclic width presets are `CW` (500 Hz), `VOICE NARROW` (1.2 kHz), `VOICE` (2.4 kHz), `VOICE WIDE` (3 kHz), `WIDE 6k`, `WIDE 9k`, and `KIWI MAX` (12 kHz). Fine `-`/`+` changes remain symmetric 100 Hz adjustments around the current center.
- Filter edits update the active KiwiSDR SND connection with real `low_cut` and `high_cut` values. The SND stream also supplies the preferred live S-meter data.

### Context sheets

The Home command band is centered over the lower waterfall area. It exposes a limited number of actions at once and can scroll horizontally.

- **RX:** station picker sourced from `STATIONS` in `kiwi_live_display_fb.py`.
- **RADIO:** two pages of Kiwi receiver modes plus `DIG`/`IQ` and 10/100/1000/5000 Hz step controls.
- **DISP:** Auto Scale; waterfall floor and ceiling; slow/medium/fast waterfall rate; Kiwi/Ice palette.
- **DEC, NET, INFO:** currently visible navigation placeholders. They are intentionally not presented as finished controls until wired to live behavior.

The Radio mode catalogue currently shown is:

```text
AM, AMN, AMW, USB, LSB, USN, LSN, CW, CWN, NBFM,
NNFM, DRM, IQ, SAM, SAU, SAL, SAS, QAM
```

The selected mode is reflected in the top summary and radio sheet. The active OpenGL service passes the selected mode and passband to its live `SND` worker whenever the radio mode or filter changes. Audio samples are not played by the renderer.

### Global radio-mode preference

The receiver state file at `~/.local/state/kiwi-gl-display-receiver.json` stores a `radio_mode` only after the operator selects a mode manually. That makes the preference global to the last view rather than per-station:

- A manual selection from the visible Kiwi mode catalogue is retained when changing public receivers and after a restart.
- A later manual selection immediately replaces the saved preference.
- A fresh state file, or one with no manual selection, still follows the normal HF convention: LSB below 10 MHz and USB at or above 10 MHz.
- The app never writes an automatic band-derived choice as though it were an operator preference.

## Gestures and Tuning

| Gesture | Behavior |
| --- | --- |
| First waterfall touch while controls are quiet | Wakes overlays only. |
| Tap waterfall | Tunes to the tapped frequency. |
| Horizontal swipe | Begins after a 4-pixel drag and tunes continuously. Finger distance maps directly to the active zoom span, so a given travel covers the same fraction of the visible spectrum regardless of how fast it is dragged. Left moves toward higher frequency and right toward lower frequency in the current configuration. |
| Live Kiwi delivery | The custom client coalesces touch updates and sends only the latest requested tune to both Waterfall and SND streams at up to 50 Hz. A fast drag cannot build a delayed command queue; a slow drag produces each selected frequency detent. |
| Slow glide after fast travel | Immediately fades repeat-swipe acceleration back to the normal constant positional mapping at the current view span. |
| Repeated fast swipes | Applies a capped, conservative acceleration/zoom-out behavior only after the current swipe itself proves fast, so a slow follow-up drag remains precise. |
| `+` / `-` | Changes zoom one level at a time. |
| Pinch | Remains supported, but the dedicated zoom controls are the dependable way to reach the maximum zoom. |

Completed zoom/tune animations are explicitly cleared before a new touch begins, so they cannot overwrite live drag feedback between touch events.

Zoom is `0..14`, with:

```text
span_kHz = 30000 / 2^zoom
```

Thus zoom 13 is about 3.66 kHz and zoom 14 is about 1.83 kHz. Zoom 14 is the current maximum because it is the practical limit of the current Kiwi waterfall data and `960` display samples. It is useful for FT8, WSPR, and narrow CW work; adding nominal zoom values above 14 would mostly magnify existing pixels rather than provide more receiver resolution.

## KiwiSDR Integration

The client does not embed or automate a browser. It speaks directly to the KiwiSDR WebSocket interface.

- `W/F` stream: live waterfall lines and waterfall commands; this is the stream used by the current OpenGL renderer.
- The OpenGL spectrum trace uses that same `W/F` stream, not a browser or a separate spectrum/audio connection.
- `SND` stream: receiver-level messages and live mono PCM audio. The OpenGL service decodes compatible raw PCM and feeds PipeWire's current default sink, normally the Pi USB-audio output.
- Station changes reset the visible waterfall texture/queue and reconnect the worker to the new server.
- The station list is a curated list of public receivers, not the full Kiwi directory.
- The selected receiver, tuned frequency, zoom, and any manually selected radio mode are persisted at `~/.local/state/kiwi-gl-display-receiver.json` on the Pi. Startup restores the full view before the first WebSocket connection; changing receiver keeps the same frequency/zoom and manual radio mode. Use `--no-remember-receiver` only when a deliberate default-server boot is wanted.

### Public receiver health checks

The receiver picker currently uses a curated static `STATIONS` list. It does **not** yet run or display an automated health check. The following is the established operational health model for public KiwiSDR stations and should guide any future receiver-list work.

| Result | Meaning | UI / operational treatment |
| --- | --- | --- |
| `W/F` healthy | The waterfall WebSocket completes Kiwi setup and delivers waterfall data within a short timeout. | Receiver is usable for the live waterfall view. |
| `W/F` plus `SND` healthy | The waterfall remains stable while a second SND session accepts the selected frequency, mode, and cuts, and yields meter data. | Full current experience: waterfall, passband control, and receiver-derived S-meter. |
| `W/F` only | Waterfall is healthy, but SND is unavailable, refused, or yields no useful meter data. | Keep the receiver selectable; use the visual waterfall-derived S-meter fallback and do not imply audio is available. |
| `SND` destabilizes `W/F` | A public receiver accepts one connection but drops, refuses, or interferes with the other. | Treat it as a single-channel-compatible receiver; do not continuously retry the second stream against it. |
| Unreachable / full / malformed | DNS, HTTP/WebSocket connection, Kiwi setup, or first-data timeout fails. | Mark unavailable and skip it in automatic selection until a later probe. |

Health probes should be conservative because these are volunteer-operated public receivers with finite client slots:

- Probe one receiver at a time with short connect and first-data timeouts.
- Open `W/F` first; test `SND` only after a healthy waterfall session is established.
- Close both sockets immediately after the result is known; do not poll continuously or consume a receiver slot while the picker is closed.
- Keep the active listener out of bulk checks. A background check must never retune, clear, or interrupt the currently displayed waterfall.
- Cache results with a timestamp and back off failures. The station list should remain usable even when no health information is available.
- A receiver passing `W/F` is still useful. Do not reject it solely because the optional SND/meter path is incompatible.

The future picker can show a small state indicator only when useful: available, waterfall-only, or unavailable. It should avoid verbose diagnostics on the 4.8-inch display; detailed error text belongs in logs or a diagnostics view.

### Receiver GPS map

In the `480x1280` desktop layout, `RECEIVERS -> MAP` opens a full-height
`1024x480` equirectangular GPS map backed by the public Kiwi map feed. Drag to
pan and pinch (or use the desktop mouse wheel) to zoom. It is now an
orthographic `RADIOGARDEN` globe, not an unfolded coordinate chart: the center
reticle stays fixed while the globe moves underneath it. Clicking a visible
dot locks that station into the center and starts the ordinary live Kiwi
audio/waterfall connection. Clicking the reticle tunes the receiver nearest to
the current geographic focus. Desktop handling bypasses the synthetic touch
bridge for direct, reliable mouse/touchpad dragging, hover preview, and click;
the Pi uses the same gesture semantics through touch. Released globe drags
coast briefly to a stop, while a selected receiver smoothly locks into center.

The map starts near edge-to-edge and supports `192x` regional zoom. It switches
from Natural Earth's 50 m outlines to an anti-aliased 10 m coastline layer at
close view, preserving coast and small-island detail without magnifying a
coarse source. At regional zoom it changes from fragmented boundary segments
to complete Natural Earth country polygons with restrained country labels. This
makes national borders, including Romania at a Balkan close-up, read as closed
political shapes instead of thin river-like line fragments.
The compact `VIEW` control on the map rail cycles the built-in styles:
`CLEAN` (receiver-first coastlines), `BORDERS` (international boundaries),
`ATLAS` (boundaries plus a restrained latitude/longitude grid), and `SAT`
(NASA Blue Marble physical/satellite-style imagery with the political-boundary
overlay). `SAT` uses a 2048x1024 texture on Pi and a 4096x2048 texture in the
desktop simulator. It also applies a UTC-driven day/night terminator with a
subtle twilight transition. The styles are native OpenGL layers and need no
network tile service.
The map is only a visual receiver selector for now: signal comparison,
heatmaps, and multiple neighboring receiver streams are deliberately separate
later work.

### S-meter and SND behavior

The OpenGL service now starts a `SND` worker alongside the waterfall connection. It sends the active frequency, radio mode, and filter cuts to KiwiSDR and uses `SND` meter messages when available. The waterfall percentile remains a visual fallback while a receiver is unavailable or reconnecting.

Some public Kiwi receivers can limit concurrent `W/F` and `SND` connections. The worker reconnects after an error, but receiver compatibility remains the main reason to verify a newly added public station before relying on its meter or audio behavior. Unsupported compressed/stereo `SND` data is safely ignored rather than sent to the PCM device.

### Home > Audio and Tests

`AUDIO` is the listening-control sheet. Its `SPEAKER VOLUME` slider reads and writes the real PipeWire default-sink volume, while squelch and Audio Filter control the live SND path.

The lower-right `ASR` readout is also a touch control. It opens a seven-choice
caption-engine selector: `OFF`, `VOSK`, `MOON`, `PARA`, `WHISPER`, `DEEP`, and
`D-HAM`.
`DEEP` is Deepgram Nova-3 live transcription. It uses the same live Kiwi `SND`
PCM lane as every local engine, so audio playback and waterfall rendering are
unchanged. The selection is
remembered with the receiver preferences. `VOSK` uses the lightweight live
Kaldi model, `MOON` uses Moonshine Base INT8 through sherpa-onnx (falling back
to Moonshine Tiny if Base is unavailable) and is the preferred local option on
the 2 GB Pi 5. `PARA` uses NVIDIA Parakeet TDT-CTC 110M INT8 through
sherpa-onnx in short bounded windows, and `WHISPER` uses Whisper.cpp Tiny
English in the same bounded-batch style. All engines use the normal Kiwi `SND`
PCM path and USB-audio playback continues independently. Offline engines drop
stale audio rather than accumulating delayed captions.

`D-HAM` is a separate Deepgram Nova-3 profile for amateur-radio listening. It
adds a focused static vocabulary for Q-codes, signal reports, common QSO
phrases, and short callsign-adjacent language, then passes Deepgram's three
final alternatives to the existing local callsign scorer. The visible caption
remains the normal Deepgram transcript. The callsign pane highlights a call
only when it is locally verified, repeated across alternatives, or explicitly
appears in a high-confidence QSO-shaped result; it can also summarize observed
behavior such as `CQ`, `calling`, `QSL`, `QTH`, a report, or `73`. It is a
context profile, not a trained ham model, so uncertain noisy speech stays in
the normal caption stream instead of being promoted to a callsign.

### Deepgram setup

Deepgram is deliberately optional. Install its Python SDK for the service user:

```sh
sudo -H -u ituner /usr/bin/python3 -m pip install --user 'deepgram-sdk>=3,<4'
```

On the display, tap the `ASR` annunciator, choose `DEEP` or `D-HAM`, then enter the key
in the large on-screen keypad and tap `OK`. The renderer saves it locally as
`~/.config/ituner-sdr/deepgram.env`, with an owner-only `0700` directory and
`0600` file. It never writes the key to the repository, receiver-state JSON,
screenshots, or normal logs. Tapping the active `DEEP` choice again reopens
the sheet for a deliberate key replacement.

The credentials file is read directly by the renderer, so no systemd
`EnvironmentFile` line is required. Optional model and language overrides may
still be added through the service environment:

```ini
Environment=ITUNER_DEEPGRAM_MODEL=nova-3
Environment=ITUNER_DEEPGRAM_LANGUAGE=en-US
```

The defaults are `nova-3` and `en-US`. They can be overridden without changing
source using `ITUNER_DEEPGRAM_MODEL` and `ITUNER_DEEPGRAM_LANGUAGE`. Selecting
`DEEP` without a key opens the local setup sheet; receiver audio remains
unaffected throughout setup and transcription.

`TESTS` is a separate, extensible diagnostics sheet. `DJ TUNE` is the live finger-driven tuning bench: it uses the **same** selected receiver, `W/F` waterfall connection, and `SND` audio path as normal listening.

- Drag the dedicated strip left or right to issue real tuning changes in 100 Hz detents. It starts at the current frequency, has a bounded `+/-5.0 kHz` working range, and shows the live offset from centre.
- `STEP` cycles 50 Hz, 100 Hz, and 250 Hz detents. `RANGE` cycles `+/-2.5`, `+/-5.0`, and `+/-10.0 kHz`. `RETURN`, touching outside the workspace, or returning Home restores the exact starting frequency.
- `LINK RATE` cycles from 10 Hz through 100 Hz in 10 Hz increments. It controls the coalesced live-command rate for both Kiwi Waterfall and SND streams, allowing a direct audio-versus-responsiveness comparison with the same finger gesture.
- The UI sends only the current desired frequency to the shared state, rather than building a command backlog. This makes it a direct test of the normal live waterfall and USB-audio tuning path.

- Tap the pattern tile to cycle `GENTLE`, `FAST`, `JITTER`, `AM SLOW`, `AM MED`, `AM FAST`, `SCAN +/-50k`, `SSB 50Hz 2s`, and `SCAN +/-25k 4s`.
- `RUN TEST` begins the selected short sweep; it becomes an unambiguous `STOP` control while active.
- The patterns contain respectively 16, 20, 11, 32, 32, 32, 48, 100, and 200 scheduled tuning steps. The first seven remain below 50; `SSB 50Hz 2s` and the intentional high-resolution `SCAN +/-25k 4s` use 100 and 200. The AM variants each reach `+6.4 kHz`, enough to make an AM broadcast station audibly fade at the normal filter edge before returning; they differ only in slow, medium, and fast cadence. `SCAN +/-50k` uses four two-second legs: `+50 kHz`, centre, `-50 kHz`, centre. `SSB 50Hz 2s` reaches `+2.5 kHz` in fifty 50 Hz increments, then returns through fifty matching increments in two seconds. `SCAN +/-25k 4s` crosses `0 -> +25 -> -25 -> 0 kHz` in four seconds at 20 ms state intervals; receiver workers coalesce only stale updates so a slow public receiver never receives a delayed backlog.
- The sweep produces direct state updates, not a queue; a slow receiver cannot later play back stale retunes. Any stop or unrelated new touch restores the exact starting frequency.
- Finishing normally also ends at the starting frequency. The visual waterfall follows the same retunes as the audible `SND` stream.

## Deployment on the Pi

The active service is:

```ini
# /etc/systemd/system/kiwi-gl-display.service
[Unit]
Description=KiwiSDR OpenGL display
After=network-online.target sound.target
Wants=network-online.target
Conflicts=kiwi-live-display.service

[Service]
Type=simple
User=ituner
WorkingDirectory=/home/ituner/codex-sdr-display
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=PYGAME_HIDE_SUPPORT_PROMPT=1
ExecStart=/usr/bin/python3 /home/ituner/codex-sdr-display/tools/kiwi_gl_display.py --orientation flipped --freq-khz 7075.794 --zoom 13 --fps 30 --wf-row-pixels 1 --swipe-slow-sensitivity 1.15 --swipe-fast-sensitivity 2.4 --swipe-fast-px-s 420 --swipe-repeat-window-s 1.4 --swipe-repeat-boost 0.65 --swipe-repeat-max 3 --swipe-inertia-strength 0.0
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

The working deployment routine from the development machine is:

```sh
python3 -m py_compile tools/kiwi_gl_display.py
scp -i ~/.ssh/id_ed25519_p4 -o IdentitiesOnly=yes -o BatchMode=yes \
  tools/kiwi_gl_display.py \
  ituner@p5:/home/ituner/codex-sdr-display/tools/kiwi_gl_display.py
ssh -i ~/.ssh/id_ed25519_p4 -o IdentitiesOnly=yes -o BatchMode=yes ituner@p5 \
  'cd /home/ituner/codex-sdr-display && \
   python3 -m py_compile tools/kiwi_gl_display.py && \
   sudo systemctl restart kiwi-gl-display.service && \
   systemctl --no-pager --full status kiwi-gl-display.service'
```

If mDNS for `p5` is unavailable, use its current LAN address instead. The observed address on 2026-07-30 was `10.0.0.151`:

```sh
scp -i ~/.ssh/id_ed25519_p4 -o IdentitiesOnly=yes \
  tools/kiwi_gl_display.py \
  ituner@10.0.0.151:/home/ituner/codex-sdr-display/tools/kiwi_gl_display.py
```

Useful Pi checks:

```sh
systemctl status kiwi-gl-display.service
journalctl -u kiwi-gl-display.service -f
ps -C python3 -o pid,%cpu,%mem,rss,cmd --sort=-%cpu
vcgencmd measure_temp
```

The service is configured with `Restart=always`, so the interface should return automatically after reboot or a transient failure.

## Current UI Contract

The production layout is frequency-first and designed for the 960 x 320 logical
surface on the 4.8 inch panel:

- Home is the single persistent left-side affordance. It opens and closes the
  Home workspace; there is no timeout and no separate Exit tile.
- Home is a semi-opaque, waterfall-scale, two-row/five-column touch grid. Its
  eight current functions are left-justified, with the lower status/ruler area
  intentionally covered while it is open.
- The remaining top instrumentation is right-aligned as one cluster: mode and
  digital annunciators, frequency, then the S-meter. The frequency readout
  uses Liberation Sans Bold at 50 px and a subdued gray-cyan rather than pure
  white.
- Zoom and Scope/Filter retain subdued translucent charcoal controls. Their
  touch-safe exclusion zone is 32 logical pixels, and a control gesture never
  falls through into waterfall tuning.
- Waterfall tuning is deliberate horizontal drag only: at least 14 px and
  horizontally dominant. A stationary waterfall tap does not retune.
- The tuned center is marked by an amber dashed guide and small top tick. The
  gaps preserve visibility of a faint carrier directly at center.
- The S-meter uses saturated royal blue for S1-S9 and deep red for the upper
  range. Its peak holds for 2 seconds, then decays at 9 dB/s.

## Globe Experiment

`Home > Tests > Globe` opens an experimental spatial public-receiver picker.
It fetches the public Kiwi map feed, which includes receiver GPS coordinates
and stream URLs, then caches the result locally. The Globe is an orthographic
view: drag to rotate, pinch to zoom, and tap a region to choose a nearby
three-receiver triangle. The app auditions only the best health-ranked member
through the normal waterfall and USB-audio path. The other two vertices are
shown as geographic fallbacks; if the first receiver fails/retries after five
seconds, the app tries the remaining triangle members in order. It never mixes
three audio streams. A future TDoA version can use that same triangle for
IQ/capture work, which requires timing-capable IQ data rather than audio.

## Dependencies

The simple framebuffer path requires at least:

```text
python3
Pillow
```

The OpenGL path additionally requires:

```text
pygame
PyOpenGL
KMS/DRM access through the `video`/`render` groups
```

The old framebuffer service includes `video input audio render` supplementary groups. The current OpenGL service runs as `ituner`; access has been working on the deployed Pi. If the service later cannot open DRM or touch input, check the user's group membership and the device permissions first.

## Known Limitations and Sensible Next Steps

- Decoder and Network sheets are not live yet. Audio has live speaker-volume, squelch, and filter controls; Tests is reserved for bounded diagnostics.
- The public receiver menu is a hand-maintained shortlist, not a searchable public directory.
- The GL renderer uses compatibility-style immediate OpenGL. It is already efficient enough for the current screen; shaders are an optional future refinement, not a prerequisite for good waterfall motion.
- Touch swipe travel uses conservative capped auto-zoom behavior. A fast gesture can widen by up to five zoom levels total, then it caps. Slowing the finger afterwards provides fine tuning at the widened view; tune these parameters only after physical-display testing.

Recommended order for future work:

1. Make the mode/digital/step sheet drive one verified live Kiwi receiver connection.
2. Replace the static receiver list with a compact searchable/station-favorite data source.
3. Wire useful Decoder and Network sheets one at a time.
4. Profile again only after behavior is complete; baseline OpenGL performance is already healthy at 30 fps.

## Key Files

| File | Purpose |
| --- | --- |
| `tools/render_sdr_frontend_mockup.py` | Original static frontend renderer and framebuffer writer. |
| `tools/kiwi_live_display_fb.py` | CPU/Pillow live Kiwi client; protocol, touch, audio/SND, and fallback reference. |
| `tools/kiwi_gl_display.py` | Current OpenGL/KMS renderer and active UI. |
| `systemd/kiwi-live-display.service` | Legacy framebuffer service template. |
| `baselines/kiwi-basic-20260728-235830/` | Preserved direct-framebuffer baseline. |
| `docs/yx45011a-pi5-display-bringup.md` | Panel driver, physical geometry, touch overlay, and driver rebuild instructions. |
