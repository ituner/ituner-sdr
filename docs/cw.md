# CW Morse receiver

Open **Digital tools → CW Morse** in the standard UI, or **Modes → CW** in
CM5's PR12 drawer. The same receivers and settings are available at
`http://cm5.local:8073/cw`.

The layout takes inspiration from CW Skimmer's signal list next to a waterfall,
and fldigi's speed controls and separate receive text area. It is an iTuner
interface, not a copy of either application's UI or decoder.

## Receiving

Use **Add decoder** to select a KiwiSDR and a band. A receiver consumes one Kiwi
SND channel. It receives a 1 kHz audio window (200–1200 Hz) centered on the RF
frequency shown in the editor. Internally the USB dial is 700 Hz below that
center. Up to four automatically acquired signals share that one connection.
This is not an entire-band or IQ skimmer. Signals closer than approximately
85 Hz may not separate reliably. The strongest candidates acquire first;
inactive tracks release their slots after 15 seconds.

Presets cover 160, 80, 60, 40, 30, 20, 17, 15, 12 and 10 metres. They are starting
points within the [IARU Region 1 HF CW segments](https://www.iaru-r1.org/wp-content/uploads/2019/08/hf_r1_bandplan.pdf),
not promises of activity or transmit permissions. Edit **RF center** to follow
a conversation or find a busier segment. This tool only receives.

- **Auto scan** acquires up to four signals; select a signal to read its text.
- **Lock** decodes one chosen audio tone. 700 Hz is exactly the displayed RF center.
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
Tracks have separate IDs, frequencies, speed estimates, receiver identity and
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
is a mature alternative but its full application/audio integration is heavier
than the embedded engine used here.

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
