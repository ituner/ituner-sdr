# CW Morse receiver

Open **Digital tools → CW Morse** in the standard UI, or **Modes → CW** in
CM5's PR12 drawer. The same receivers and settings are available at
`http://cm5.local:8073/cw`.

The layout takes inspiration from CW Skimmer's signal list and waterfall,
and fldigi's speed controls and separate receive text area. It is an iTuner
interface, not a copy of either application's UI or decoder.

## Receiving

Use **Add decoder** to select a KiwiSDR and a band. A receiver consumes one Kiwi
SND channel. Choose **GGMorse** for a 1 kHz window (200–1200 Hz audio),
or **fldigi** for a 3 kHz window (200–3200 Hz). Both are centered on the RF
frequency shown in the editor; switching engines preserves that center.
The USB dial is 700 Hz below center for GGMorse, or 1700 Hz for fldigi. Up to four automatically acquired signals share that one connection.
This is not an entire-band or IQ skimmer. Signals closer than approximately
85 Hz (GGMorse) or 150 Hz (fldigi) may not separate reliably. The strongest candidates acquire first;
inactive tracks release their slots after 15 seconds.

Presets cover 160, 80, 60, 40, 30, 20, 17, 15, 12 and 10 metres. They are starting
points within the [IARU Region 1 HF CW segments](https://www.iaru-r1.org/wp-content/uploads/2019/08/hf_r1_bandplan.pdf),
not promises of activity or transmit permissions. Edit **RF center** to follow
a conversation or find a busier segment. This tool only receives.

- **Auto scan** acquires up to four signals; select a signal to read its text.
- **Lock** decodes one chosen audio tone. The RF frequency is the USB dial plus the chosen tone; center is 700 Hz for GGMorse or 1700 Hz for fldigi.
- **Speed = 0** automatically estimates speed; optionally set 5–55 WPM manually.
- **Signal gate** defaults to 12 dB above the local spectral floor. Increase it
  to reduce false candidates, or lower it for weak signals. This value is not
  calibrated receiver SNR, and continuous carriers can still occupy a slot.
- The waterfall covers about ten seconds; newer audio appears at the bottom.
  Its labels remain native text and its display size stays fixed.
- Decoding needs several seconds of signal. Hand timing, overlapping stations,
  drift and fading can produce errors. The text is always tentative; there is
  no callsign correction or language-model completion.
- Web **Following live text** can be paused to inspect a conversation without
  stopping reception. Native **History**, or swiping upward, opens saved text.

## History

Text is appended to `~/.local/share/ituner-sdr/cw/history.sqlite3` using SQLite WAL.
Stopping, editing, restarting or deleting a receiver does not delete its history.
Tracks have separate IDs, frequencies, speed estimates, decoder engine, receiver identity and
UTC start/end times. UTC is the reception/decoder time, with several seconds
of decoder latency; it is not a measured QSO boundary. Long streams split at
8,192 characters. All history stays on disk; the interfaces show the latest 200
entries and the CSV export returns up to the latest 10,000. No automatic uploads
are made. Raw audio and waterfall recordings are not archived; the waterfall is
live only. `sessions.json` retains receiver settings and start/stop state.

## Engine choice and installation

[GGMorse](https://github.com/ggerganov/ggmorse) is a small native C++ library with
automatic speed estimation and an MIT license. It was selected for embedding
on ARM Linux without a desktop subprocess, external audio routing or downloaded
ML weights. It is not claimed to outperform every decoder. [CW Skimmer](https://www.dxatlas.com/CwSkimmer/)
is the interface reference but is proprietary Windows software; [RSCW](https://www.pa3fwm.nl/software/rscw/)
requires fixed speed and machine timing. [fldigi](https://www.w1hkj.org/FldigiHelp/cw_page.html)
is the optional second live engine. It uses an isolated persistent process per
acquired signal and shares one private virtual display. It never connects to
the system sound card or rig, and uses the same Kiwi channel as all other tracks
in that receiver. The main fldigi CW decoder is used, not its separate Signal Browser algorithm.

Sources are pinned to GGMorse commit
`7b4822a8cfdbb1addfe497f3ae8186f142a4ee79` under `UI/cw_vendor/`.
The MIT notice is in `licenses/ggmorse-MIT.txt`. Only upstream stdout printing
is suppressed; the decoder algorithm is unchanged. An iTuner FFT tracker assigns
fixed pitches to independent GGMorse instances, each estimating its own speed.

Application dependency installation installs `g++` and runs:

```sh
python3 scripts/build-cw.py
```

This builds the library for the current CPU, offline, from the vendored source.
No model, display driver, kernel, audio or touch changes are required. For
CM5 use `scripts/install-cm5-app-only.sh`, not the original LCD installer.
Development requires NumPy and Pillow, already used by the other decoders.

```sh
python3 scripts/build-cw.py
python3 -m unittest discover -s tests -p 'test_cw.py'
```

Tests synthesize Morse independently of GGMorse at 8/20/35/50 WPM, verify
known callsigns at independently acquired pitches, two simultaneous signals,
noise/fading, locked-tone exclusion, history persistence, and shared receiver
controls. Passing synthetic tests does not guarantee exact off-air copy.

## Comparing decoder engines

See [the repeatable fldigi/GGMorse comparison](cw-engine-comparison.md). This
optional file-based evaluation is separate from the installed live receiver.

## Optional live fldigi installation (CM5 / Debian)

```sh
bash scripts/install-fldigi.sh
```

This installs build dependencies, builds official fldigi **4.2.13** from a
SHA-256-verified archive, then places the executable in `UI/cw_vendor/fldigi`.
It is separate from the default GGMorse install and does not alter display,
touch, boot or audio configuration. Run from the deployed application checkout
(or copy the resulting executable and new CW modules to the installed UI).
`ITUNER_FLDIGI_BIN` may override the executable path for development.

Select **fldigi · 3 kHz** in **Add decoder / Edit** on either interface. Existing
receivers default to GGMorse. Both use the same history; the engine is recorded
in each new entry and CSV export. Switching or stopping keeps previous text.

The adapter adds continuous 8 kHz signed-16 PCM input to upstream benchmark
mode. A stateful FIR resampler converts the Kiwi's 12 kHz stream without packet
boundary discontinuities. Output is incremental; decoder timing is retained
throughout reception. Queues are bounded; a failed or overloaded process is
reported rather than silently losing audio. All processes close on receiver
stop/reset. Up to four signals per receiver and four fldigi signals total are
allowed to bound memory use. Receivers share this four-signal fldigi budget; the interface reports when all
slots are occupied. This is heavier than GGMorse on a 2 GB CM5.

The full-width native waterfall is 1240 × 338 display pixels. Four track buttons
and selected decoded text remain below it. The web view also uses a full-width
waterfall with fixed height, and responsive signal buttons. Labels are native
text, never stretched inside the raster.

To exercise actual streaming, wide acquisition and process cleanup on CM5:

```sh
ITUNER_TEST_FLDIGI=1 python3 -m unittest discover -s tests -p 'test_cw_fldigi.py'
```

The builder retains the upstream source/license and our adapter patch. fldigi
is GPL-3.0-or-later: distribute corresponding source and license with built
copies. Source and patch scripts are needed to reproduce this build.

Validation on CM5: the streaming test copied `KN6KEZ` at 600 Hz / 20 WPM and
`YO3ABC` at 2500 Hz / 28 WPM from the same synthetic PCM stream, with automatic
acquisition and speed estimation. Both worker processes (including additional
empty acquired tracks) and the shared virtual display were gone after closing
the decoder. Settings/history/resampler checks passed as well. These controlled
fixtures do not establish off-air accuracy.
