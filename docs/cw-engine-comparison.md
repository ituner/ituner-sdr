# CW engine comparison

This is an optional evaluation tool. GGMorse remains the default; live fldigi is now optional (see [CW setup](cw.md)). The comparison does not replace its backend, start receivers, alter
hardware drivers, or change speaker routing. It runs the actual upstream
fldigi decoder against files in its benchmark-only build.

## Initial CM5 results — 9 October 2026

[Full results table](benchmarks/cw-2026-10-09.md) and
[raw outputs/settings](benchmarks/cw-2026-10-09.json) cover ten deterministic
fixtures through three profiles (30 decodes). GGMorse had fewer errors on clean
samples; fldigi had fewer on the fading/noise sample (23.8% versus 107.1% CER)
and emitted no characters on the noise-only control, versus 47 from ungated
GGMorse. Both decoded the callsigns of the two mixed stations when given their
respective tones. Fldigi's ordinary and SOM profiles produced the same scores
in this small set. Scores include startup acquisition errors and trailing noise.
Do not generalize them to all operating conditions or the live receiver's gate.

A fresh local-Kiwi recording attempt returned no audio and was closed without
stopping existing receivers. Off-air comparison and live CPU/latency evaluation
therefore remain outstanding. These benchmark results predate the optional live integration.

## Repeat on CM5 / Debian

Install build/evaluation dependencies (separate from normal application setup):

```sh
sudo apt-get install --no-install-recommends build-essential pkg-config curl \
  libfltk1.3-dev libsamplerate0-dev libsndfile1-dev libpng-dev libudev-dev \
  libxft-dev portaudio19-dev xvfb xauth python3-numpy python3-scipy
bash scripts/build-fldigi-benchmark.sh
python3 scripts/build-cw.py
python3 scripts/decoder_bench.py --generate /tmp/cw-corpus \
  --fldigi "$HOME/.cache/ituner-sdr/fldigi-benchmark/fldigi-4.2.13/src/fldigi" \
  --output /tmp/cw-comparison.json
```

The builder downloads official fldigi 4.2.13, verifies its pinned SHA-256, and
compiles under a user cache directory. The builder also adds the receive-only PCM pipe used by the live adapter. Three upstream benchmark compatibility fixes are applied: qualify
`std::ofstream` in `src/misc/benchmark.cxx` for GCC 14, and guard the optional
signal-browser dialog pointer in `src/cw/cw.cxx` (it is absent in batch mode),
and synchronize the waterfall carrier with `--benchmark-frequency` so CW does
not retune itself to the default 1500 Hz.
The main CW decoding algorithm is unchanged. It does not run `make install` or start
a service. The official source is GPL-3.0-or-later; retain its license/source
when distributing built copies. The GitHub mirror was still at 4.1.23 when
this comparison was prepared, so it is not used as the current release.

`decoder_bench.py` creates both a JSON report with full decoded text and a
Markdown results table. Its two fldigi profiles differ only in whether SOM
character matching is enabled. Both track speed automatically over the same
5–55 WPM range; actual transmitted speed is not supplied per recording.
GGMorse also estimates speed automatically. Both receive the known target tone.
This isolates decoder quality from our own signal acquisition algorithm.

The fixtures cover 8, 20, 35 and 50 WPM; fading plus noise; irregular keying;
two simultaneous stations; and noise/unkeyed-carrier controls. They contain
no real transmissions. A SHA-256 in the manifest identifies the exact recording.
For GGMorse's existing wrapper, the same 8 kHz recording is resampled to 12 kHz
using a polyphase filter. fldigi consumes the original mono 16-bit 8 kHz WAV.
The upstream benchmark does not itself validate sample rate, so our adapter does.

## Interpreting results

Character error rate (CER) counts substitutions, insertions and deletions,
including word spaces, divided by reference length. Lower is better; insertions
can make it exceed 100%. Only case and repeated whitespace are normalized.
No startup characters are silently discarded. Noise-only cases report extra
characters instead of a meaningless percentage. Raw outputs are ungated, so
this measures raw decoder false text, not our live receiver's signal gate.

These are controlled synthetic tests, not evidence that an engine will win on
real stations. Do not compare the reported runtimes as CPU benchmarks: fldigi's
value includes process and virtual-display startup, while GGMorse's value is
in-process decoding only. CM5 load and latency need a separate streaming test.

## Off-air recordings and reuse

A manifest can reference existing mono 16-bit 8 kHz WAV recordings:

```json
[
  {
    "name": "40m-recording-1",
    "wav": "40m-recording-1.wav",
    "tone_hz": 700,
    "provenance": "Receiver, RF frequency, UTC time, recording method"
  }
]
```

Run with `--manifest path/to/manifest.json --fldigi /path/to/fldigi`.
Add `expected` only when someone has independently transcribed the recording;
without a reference the outputs are retained but no accuracy score is invented.
`sha256` is optional for externally supplied recordings and checked when present.

The `FldigiBatch` adapter separates modem selection, settings and decoded text
from the rest of the comparison. This is the first reusable boundary for other
fldigi modes. It currently validates 8 kHz inputs; modes with another sample rate
need explicit support. This class remains file-only; `UI/cw_fldigi.py` separately provides persistent live CW streaming.

Next evaluation stages:

1. Add independently transcribed off-air recordings with fading, interference
   and hand-sent timing, and compare the same audio through both engines.
2. Evaluate fldigi's existing [CW Signal Browser](https://www.w1hkj.org/FldigiHelp/signal_browser_page.html)
   alongside a wider receive slice and separate filters/frequency shifts per
   station. Its viewer has a separate CW implementation (`view_cw.cxx`), so
   results from the main CW decoder do not automatically establish viewer
   accuracy. Benchmark simultaneous decoding on CM5.
3. Choose a live backend based on accuracy, false detections, CPU and latency;
   reuse its process/audio/text interfaces for additional fldigi modes.

Primary references: [official release](https://www.w1hkj.org/files/fldigi/),
[CW controls](https://www.w1hkj.org/FldigiHelp/cw_configuration_page.html),
[GGMorse](https://github.com/ggerganov/ggmorse). The pinned source includes
`src/misc/benchmark.cxx`, `src/cw/cw.cxx` and `src/include/globals.h`; CW mode ID
1 and its 8000 Hz sample rate are verified there.
