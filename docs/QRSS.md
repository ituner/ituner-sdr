# QRSS: waterfall and tentative Morse text

Open **Digital tools → QRSS** (CM5 PR12: **Modes → QRSS**) or
`http://cm5.local:8073/qrss`. Add a decoder and choose a Kiwi receiver and band.
A single 12 kHz audio connection feeds both outputs; no second receiver slot is
needed for text. Existing WSPR, SSTV and Hell receivers remain independent.

## Receiving

- The waterfall covers the selected span, with frequency increasing upwards and
  time running left to right. Tap a capture to enlarge it. The orange center tick
  marks the selected tone.
- For text, choose **CW** (on/off keyed) or **FSKCW** (frequency-shifted CW),
  set **3, 6, 10, 30 or 60 seconds per dot**, and tune **Mark tone** to the signal.
  Plain CW ignores Reverse. FSKCW assumes the space tone is below the mark tone
  by the configured shift; Reverse exchanges their interpretation.
- **Selected RF = USB dial × 1000 + audio tone** in Hz. Changing the tone changes
  the tracked RF frequency; compensate the dial if you want the same RF.
- The text decoder follows **one selected signal**, not all traces in the span.
  It does not automatically identify speed, callsigns, DFCW or arbitrary beacon
  patterns. Select **Visual only** for those; the image still contains them.
- FSK separation must be resolvable at the selected integration time. The editor
  rejects shifts below 2.5 FFT bins. Slower dots permit narrower shifts.
- Text is **tentative**. Fading, frequency drift, low SNR and overlapping stations
  can produce errors or no text. The detector uses narrow FFT bins; accurate
  tuning matters, especially with 30/60-second dots. Visual traces may remain
  readable below the automatic decoder's threshold. There is no CRC or reliable
  automatic confirmation of a callsign.

Preset RF centers: 80 m 3.500850 MHz, 40 m 7.000850 MHz,
30 m 10.140000 MHz, and 20 m 14.096900 MHz; each defaults to ±100 Hz,
6 s/dot FSKCW with 5 Hz shift and 10-minute captures. These are starting areas,
not a guarantee of continuous activity. Defaults do not automatically match
an unknown signal. The 30 m preset is selected initially.

Sources: [QRP Labs 80/40 m QRSS kit](https://qrp-labs.com/qrsskit.html),
[QRP Labs 20/30 m beacon frequencies](https://qrp-labs.com/flights/u4b10.html),
and [QRP Labs mode descriptions](https://www.qrp-labs.com/qrsskitmm.html).

## Galleries and persistence

The 1280 × 800 local gallery displays four captures with tentative text. Web
and local editors control the same saved sessions: Add, Edit, Start, Stop and
Remove. Web views can show all captures, latest per receiver, or captures with
some tentative text. Click an image to enlarge it or download its PNG.

Live images update approximately every five seconds. Choose 5, 10, 20 or 30
minutes per capture. Text timing continues across image boundaries. Audio gaps
close a partial capture and reset the text parser, avoiding invented characters
across a lost connection. Stop saves the partial image and its available text.

Images and their JSON metadata, including tentative text, are saved under
`~/.local/share/ituner-sdr/qrss/images`; `sessions.json` stores receivers and
paused states. Override with `ITUNER_QRSS_DIR`. The newest **300 captures** are
retained, including captures without recognized text. Removing a receiver or
stopping it does not erase its saved captures. Startup recovers interrupted live
captures as saved images. At most six QRSS receivers can be configured, subject
to actual Kiwi slot availability alongside other listeners.

No QRSS uploads or automatic station reports are sent. A visual capture or a
text guess is not treated as a confirmed reception report.

## Implementation, dependencies and attribution

`UI/qrss_decoder.py` adapts the periodic-Hann overlapping FFT approach in
[QrssPiG](https://gitlab.com/hb9fxx/qrsspig), Martin Herren / HB9FXX,
`src/QGProcessor.cpp`, commit `19bb36425053e0d179ddd9a309ed9b169f5858d8`.
Its GPL-3 license is included in `licenses/qrsspig-GPL-3.txt`.
This is a NumPy adaptation, not a bundled QrssPiG executable. Acquisition,
rendering and fixed-duration Morse tracking are integrated iTuner code.
It uses the app's existing NumPy and Pillow dependencies; no new driver,
external decoder executable or model download is needed.

Validation includes independently generated CW/FSKCW with all five dot speeds,
reversed FSK, random chunk boundaries, silence, noise, continuous carrier,
interrupted audio, image rollover, persistent settings/text and shared web/local
controls. Passing generated-signal tests is not evidence of an on-air station.

The main UI includes QRSS directly. On the existing PR12 CM5 UI, the incremental
compatibility patch is `hardware/cm5/sstv/qrss-ui.patch`, applied after
`hell-ui.patch`. Do not replace the CM5's display/touch/audio configuration.
