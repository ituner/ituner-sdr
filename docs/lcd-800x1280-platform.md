# 800x1280 Waveshare LCD platform

The active iTuner SDR target is the **Waveshare 8-DSI-TOUCH-A** on a Raspberry
Pi 5. Its native DSI framebuffer is `800x1280` portrait. The panel is mounted
landscape, so the SDR UI is a `1280x800` logical canvas. The application
rotates the framebuffer and maps Goodix touch through the same transform.

Older `400x960`, `320x960`, and `480x1280` layouts are retired. Do not add new
UI work to them.

## Run

On the LCD, the UI runs directly on the KMS framebuffer. No desktop
environment or Wayland compositor is required. The installer enables the
native service automatically:

```bash
sudo systemctl status ituner-sdr.service
```

This frees the memory otherwise used by the compositor, desktop panel, file
manager, onscreen keyboard, and desktop portals. The service uses KMSDRM and
`--swap-x-y` for the native Goodix `800x1280` coordinates; the default
inverted X mapping completes the physical flipped/landscape transform.

On macOS, `--desktop` opens the exact same `1280x800` logical interface in a
mouse-driven window:

```bash
UI/.venv/bin/python UI/kiwi_gl_display.py --desktop --fps 30
```

Open **RECEIVERS**, then tap **GLOBE** for the full interactive receiver map.
It loads the current receiver directory, supports drag/pinch navigation, and
cycles Borders / Atlas / Satellite with the map's `VIEW` control. The separate
**TESTS → CONSTELLATION** view remains available for the live listener/scout
visualization.

Tap the large frequency readout to open the on-screen MHz keypad.

## Required packaged runtime

The installer supplies the Pi graphics stack through APT and installs
`requirements-runtime.txt` into `/opt/ituner-sdr/vendor/python`:

- `python3-pygame`, `python3-opengl`, `python3-pil`
- `pipewire`, `pipewire-audio`, `wireplumber`, `libportaudio2`
- Python `sounddevice`
- `nasa-blue-marble-4096.jpg` and a validated
  `ne_50m_admin_0_countries.geojson.xz` for the globe

## ASR and AI voice cleaning

The standard installer now installs and verifies the complete local AI bundle:

- Vosk Small English;
- Sherpa-ONNX Moonshine Base INT8 and Parakeet TDT-CTC 110M INT8;
- Moonshine Voice, for its selectable language profiles;
- Whisper.cpp with the Tiny multilingual model;
- Deepgram's client (an operator API key is still required for its cloud
  service); and
- RNNoise with SpeexDSP resampling for the local neural voice-clean control;
  and
- the local HF Enhance EPOCH 1 and EPOCH 8 ONNX listening models.

All Python wheels live in `/opt/ituner-sdr/vendor/python`; model files and
native AI binaries live in `/opt/ituner-sdr/vendor/`. The installer uses the
same `aarch64`/Python 3.13 wheels verified on the LCD target. To repair or
refresh only this bundle after installation, run:

```bash
sudo ITUNER_SDR_PREFIX=/opt/ituner-sdr /usr/local/lib/ituner-sdr/install-ai-runtime.sh
```
