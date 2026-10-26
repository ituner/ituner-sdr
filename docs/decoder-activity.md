# Shared decoder activity

The RTL-433 dashboard (`:8093`) and Spectrum Survey (`:8092/spectrum`) show the
same **Decoder activity · mini SDR** below their result lists. The canvas has
1024 frequency pixels spanning 0–1500 MHz and a 256-pixel time axis. Rows
stay 8 pixels high. Marks start at 4 pixels wide for one decoded output in the
selected time interval and grow to 24 pixels as message intensity increases.
Each doubling adds 4 pixels: 1 / 2 / 4 / 8 / 16 / 32+ outputs produce widths
of 4 / 8 / 12 / 16 / 20 / 24 pixels. Intermediate counts interpolate on this
logarithmic scale. Width indicates decoded-output count, not RF bandwidth or
power. Frequency remains centered and rectangles stay inside the chart edges.
One-second cells are combined within the selected 1 / 10 / 30 / 60-second
interval, separately per frequency, decoder, receiver and quality. The tooltip
reports that combined count. Repeated frames never slow vertical movement.
Overlapping reports remain separate entries in the readout.
Zoom buttons and pointer-centered wheel zoom narrow the view to a minimum 1 MHz
span. Drag with a mouse or swipe with one finger to pan; two-finger pinch
zooms around the fingers while allowing simultaneous pan. Gestures work on both
the upper plot and waterfall. Touch gestures are captured only inside the chart;
the rest of the page scrolls normally. Arrows also pan. Tap or click a frequency
to focus button zoom, and use Full range to reset. Zoom changes only the display, never radio tuning.
It defaults to **1 second per row**; 10, 30 and 60 seconds are also available.
The time window is 32 seconds at the default speed. At 10, 30 or 60 seconds
per row it is 320, 960 or 1920 seconds. Rows move continuously at 8 pixels per
selected row interval. A monotonic animation clock follows the source clock
with bounded 2% speed corrections, so variable network latency never resets
positions. Timestamp ticks stay anchored to absolute eight-row boundaries.
Canvas motion follows display refresh; cached geometry, cached timestamp text,
and once-per-second summaries keep DOM layout work out of the animation loop.
Canvases use the display pixel ratio with interpolated subpixel rendering. A visible
clock makes progress clear even during a continuous carrier or an empty window.
Event storage uses one-second cells. Animation and polling pause when hidden
and resume on visibility changes or returning through the browser's page cache.
Narrow windows scale the canvas to fit. HF occupies about 20 frequency pixels.
The small upper plot shows recent output density, not RF power or RSSI.

All supported decoders stay visible above the plot, including stopped decoders
with zero outputs. Their labels show current state and link to the matching
receiver controls. The status banner distinguishes stopped decoders, retrying
receivers, an empty time window, and output outside the selected frequency span.

Color identifies the decoder. Filled squares represent successful decoded
outputs; outlined or dashed marks are tentative CW/QRSS text, Hell OCR guesses, or
partial SSTV images. A full SSTV image counts once as successful. Noise-only
Hell/QRSS raster captures do not create decode counts or markers. Hover or tap a
marker for frequency, receiver, count and observed time. Overlapping receivers
remain separate records and appear together in the readout.

**Central decoder counts** exposes named decoders, receiver state, successful
and tentative totals, and the counting unit. Frames, messages, characters,
spots and images are deliberately labeled separately. Totals begin when the
dashboard service starts; they are not lifetime totals or a success percentage.
The bounded in-memory waterfall retains at most 32 minutes / 4096 cells.

## Producers publish; views subscribe

`integrations/rtl433-ui/activity.cjs` owns the central model and its adapters.
The browser reads `/api/ituner/activity` on port 8093. It contains no radio
control token. Only the same hostname's ports 8092 and 8093 may read this feed
cross-origin. It never opens a radio, changes a lease, or starts a decoder.

The browser and live VHF / ADS-B adapters refresh every second; the slower HF
output APIs remain on a five-second cadence:

- VHF hub: all rtl_433 receiver slots, AIS, APRS, radiosonde, CubeSat and Meteor.
- Airspace: separate 1090 MHz and 978 MHz decoded-frame counters.
- HF: WSPR spots, CW text, SSTV images, Hell OCR and QRSS text.

The first counter sample establishes a baseline. Old device cards, retained
spots and aircraft snapshots are not replayed as new decodes. Counter resets
start a new sequence. The model counts actual counter differences; a message
with unavailable frequency may increase a total but cannot place a guessed
waterfall point. Sensor observations use their recorded receiving frequency,
including during retunes. Poll gaps do not imply RF silence. An unavailable
feed is labeled and does not create new activity. Satellite frame-counter and
ADS-B markers aggregate frames observed between polls, rather than claiming
individual frame timestamps. WSPR timestamps identify the received cycle.

Spectrum Survey's RF-energy discoveries remain its own measurements. A peak,
a running process, or received noise is not a successful protocol decode.

## Adding a packaged decoder

A downloaded decoder does not need to be modified. Its integration adapter can
read structured JSON/stdout, a local API, or host-side logs and translate actual
output into the same contract. A decoder without a compatible adapter cannot
contribute automatically. The adapter must register an ID and count unit:

```js
model.registerDecoder({id: 'my-decoder', name: 'My decoder', unit: 'frames'});
model.publish({
  decoder: 'my-decoder',
  receiver: 'USB serial / receiver ID',
  frequency: 433920000,       // Hz; null when genuinely unavailable
  timestamp: 1793000000,     // Unix seconds of the observation
  count: 1,
  quality: 'successful',     // or 'tentative'
  eventId: 'unique-frame-id',
  description: 'Decoded frame'
});
```

Registering a label is not evidence of decoding: only a validated, fresh output
may publish. `eventId` prevents duplicate reports. Frequency and timestamps
must describe the actual receiving run, not current settings applied to old
output. Register a receiver state separately when the adapter can establish it.
No count is inferred from signal energy, arbitrary raster previews, process
liveness, or stale files. Adapters for outputs without checksum validation
should identify tentative results explicitly.

## Verification

`node --test tests/test_decoder_activity.cjs tests/test_rtl433_ui.cjs tests/test_rtl433_scanner.cjs`
checks multi-receiver frequency attribution, counter baselines/resets,
deduplication, inactive decoders, all HF output types, tentative separation,
package registration, retention bounds, feed failures, sharing restrictions,
and the 1024-wide / 8-pixel geometry including HF and 1090 MHz.
