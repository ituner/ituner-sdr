# Spectrum Survey

Open **http://cm5.local:8092/spectrum**. Signal Observatory and RTL433-UI link
to it. The app uses an exclusively leased SoapySDR receiver, and can use a free
dongle alongside the sensor pool. Starting a survey with one dongle explicitly
hands it off from its current decoder; no radio starts just by viewing the app.
A survey does not automatically resume after a reboot.

Select **FM benchmark · 87.5–108 MHz** for a quick continuous-signal reference,
or **Full survey · 25–1700 MHz** for an overview. Custom ranges, fixed gain,
frequency correction and bin width are supported. One pass releases USB when
finished; Repeat sweeps continues until stopped. Starting another decoder
stops the survey and waits for the process to release its USB lease.

The NESDR SMArt v5's ordinary tuner covers approximately 25–1750 MHz, per its
[manufacturer datasheet](https://www.nooelec.com/store/downloads/dl/file/id/111/product/342/nesdr_smart_rtl_sdr_v5_datasheet_revision_1.pdf).
The survey deliberately uses 25–1700 MHz and validates the range against the
selected receiver's SoapySDR-reported capabilities. It does not enable direct
sampling to extend into HF, and does not enable a bias tee or transmit.

## Measurements and comparisons

The chart plots uncalibrated received power density in **dBFS/Hz**, with a live
trace, peak hold and optional saved baseline average. Each 2.048 MS/s window
uses Hann-windowed 1024-point FFTs, averaged in linear power. The central 75%
of the passband is retained and near-DC bins are excluded. UI bins average
these power-density estimates; they are not calibrated antenna-input dBm.
Peak hold retains the highest measured density per UI bin across sweeps.

Each retune flushes SoapyRTLSDR's FIFO, then discards enough samples to exceed
both bounded USB and software queues before measuring. The stream stays open
to avoid repeated USB cancellation/control-write races. No stale-frequency
samples are intentionally used to fill the new frequency's bins. Unknown bins
remain null. A fixed 20,000-bin cap bounds RAM, JSON output and saved traces.

Scroll to zoom the plot, drag to pan, or use Zoom +/− and Full range. Hover or
press the chart to inspect a frequency, its latest level and matched-baseline
difference. At broad zoom, the highest UI bin in each screen column is retained
so the plot does not discard narrow peaks when drawing.

Save a completed sweep, change only the antenna or cable and repeat under
similar conditions. Saved overlays require the same receiver serial, tuning
range, fixed gain, PPM, sample rate, FFT size and bin width. Mismatched traces
are hidden. FM stations provide a useful reference around 100 MHz; they cannot
establish discone or coax performance at 433, 915 or 1090 MHz. Traffic levels,
propagation, interference, receiver response and overload also change a trace.

The ADC warning counts complex IQ samples where either component approaches
full scale (absolute value ≥0.98 in normalized CF32). An unclipped trace does
not rule out earlier analogue overload. Clipped measurements are flagged and
should not be treated as a clean antenna benchmark. The initial CM5 FM test
found substantial clipping even at 0 dB tuner gain; its saved reference label
records that limitation. This is evidence of strong received FM activity, not
an antenna efficiency measurement.

## Persistence and validation

The most recent trace, settings, receiver diagnostics and up to 20 saved
baselines are under `~/.local/share/ituner-sdr/vhf/spectrum/` on CM5.
JSON export includes receiver identity, all settings, timestamps, coverage,
linear-power averages, peak hold, sample counts and clipping counts. It stores
power statistics rather than raw IQ or demodulated audio.

`python3 -m unittest test_spectrum` checks range/work limits, cropped-window
coverage, FFT power normalization/frequency indexing, FIFO retuning, linear
averaging, immutable completed-sweep baselines, lease handoff and saved-trace
bounds. The browser is also tested against real USB samples on CM5.

## Automatic overload protection

Automatic gain is enabled by default. The gain control is the maximum permitted gain. If any tuning window has more than 0.1% clipped IQ samples, the driver lowers gain in 10 dB steps down to 0 dB and restarts the entire sweep. Old peak/average accumulators are cleared so gain settings are never mixed. Each completed sweep has one fixed, recorded actual gain; A/B overlays still require matching actual gain.

At minimum gain, a window that still exceeds the clipping threshold is excluded from all trace accumulators. Affected bins appear as orange shaded gaps with a frequency-specific hover explanation; unaffected frequencies remain available. Exclusion is conservative where neighbouring tuning windows overlap. Manual gain mode retains measurements with explicit clipping quality metadata instead. Raw clipping counts, per-window quality, masks, requested/actual gain and gain adjustments are included in JSON exports. Old saved surveys remain unchanged; run a new automatic survey to locate clipped windows.

Hardware validation on the Nooelec serial 78941732: FM benchmark stepped 28 → 18 → 8 → 0 dB automatically; clipping persisted at 0 dB and affected bins were excluded. Software cannot reduce this receiver's tuner gain below 0 dB.

## Run state and diagnostics

Start and Stop show immediate pending states, and Start is disabled until the initial receiver connection is ready. Concurrent Start requests are serialized by the supervisor. The green **RUNNING** indicator requires a live receiver subprocess and an IQ update from the current run within five seconds. Opening USB alone remains **STARTING**; an old trace cannot mark a new run as live. An overdue update shows **WAITING FOR DATA**. Finished runs show **COMPLETED**; failures show **FAILED** with their error retained instead of being overwritten by quality updates.

The activity panel records Start, first IQ measurements, completion, errors and explicit stops / decoder handoffs. A bounded `spectrum/activity.jsonl` also records lifecycle events. The receiver log is linked from the panel. A clean process exit without a completed sweep is treated as a failure.

Automatic protection is announced briefly (five seconds, once per run in the current page). The compact, expandable **Survey quality** panel retains excluded bandwidth and exact frequency ranges. Background polling does not extend the announcement. Opening retained survey data does not re-announce old clipping. Orange exclusions and hover explanations remain visible.


The frequency-bin control disables widths that would exceed 20,000 bins for the chosen span and automatically widens an unsupported selection. At 25 kHz, the span limit is 500 MHz; at 5 kHz it is 100 MHz. The full 25–1700 MHz survey uses 100 kHz (16,750 bins). The current bin count is displayed before Start. Select Repeat sweeps to keep surveying after a pass completes.

## Sweep waterfall

The waterfall saves each completed individual sweep in `waterfall.sqlite3`,
retaining up to 24 hours with a global 720-sweep cap. It survives page refreshes
and service restarts. History begins when this feature is installed; previous
averages cannot reconstruct individual swipes. A previously saved complete
latest sweep can seed a single genuine row. Partial/aborted sweeps are not archived.
The current partial sweep appears separately with a LIVE/PART label.

Newest sweeps appear at the top; scroll for older rows and choose 30, 120 or
720 sweeps. Zoom controls and frequency view are shared with the spectrum chart.
Move, tap, or use arrow keys (up/down for sweeps) to inspect frequency, level,
sweep start/end time and EU/US allocations. Each row is a sequential stepped
survey, not an instantaneous full-band frame, and rows are spaced by sweep
number rather than uniform elapsed time.

Only rows matching receiver ID, range, bin width, actual gain, PPM, sample rate
and FFT size appear together. Changing settings filters the view; it does not
relabel old rows. Power uses fixed adjustable colour limits, independent of the
line chart's automatic vertical scale. Colour limits fit the first saved history
once; Auto contrast refits them, and Floor/Ceiling sliders allow manual adjustment
without changing receiver gain. History is compacted to 1 dB steps,
with approximate column-peak tooltips. Clipped bins remain orange and unsampled
bins remain dark; neither is invented from nearby valid measurements.

`python3 -m unittest test_spectrum test_spectrum_history` checks history
persistence, deduplication, settings isolation, age/count bounds, clipping masks
and viewport downsampling. History HTTP responses fetch only new rows for the
current view, with at most 2048 columns per row; normal status polling stays small.

## Survey → Signals → Investigate

Both interfaces have three main destinations: **Scan**, **Signals** and **Tools**.
Scan shows one chart at a time (Spectrum or Waterfall), one Start/Stop action,
and Setup. Setup contains basic range/receiver choices; gain, resolution, PPM
and overload handling are behind Advanced. Investigation appears after selecting
a frequency. Activity, comparison, watchlists and reports are inside Tools:


- **Scan**: broad sweep, spectrum or recent individual-sweep waterfall, with shared zoom.
- **Signals**: groups of energy above an estimated local floor, ranked by strength,
  activity or recency. Select a result to investigate or add it to the watchlist.
  The web table pages 20 results; the touchscreen shows five large rows per page.
- **Activity**: sampled activity heatmap, 24-hour peak/mean archive, and recent
  spectrum persistence. Tap a frequency, zoom to it, or open a live investigation.
- **Compare**: save complete sweep A, change the cable/antenna, then receive B
  at identical settings. The difference graph uses **latest completed B minus
  saved A**, excluding missing and overloaded measurements. Running averages
  from before and after a change are never mixed into this difference.
- **Watchlist**: named frequencies, requested channel widths, latest valid levels
  and detected/appeared/disappeared/level-change events. Adding bookmarks does
  not change RF tuning until Watch mode is explicitly started.
- **Reports**: saved HTML, signal CSV, full JSON, waterfall PNG, optional difference
  CSV, and antenna/cable notes. Open HTML and use Print / save PDF in the browser.
  The native Reports workspace also exposes receiver lifecycle activity.

Investigation uses a fixed tuning window of at most 1.536 MHz, with 5 kHz display
bins. Its target is offset from the tuner DC notch. It consumes the continuously
streaming 2.048 MS/s IQ and averages FFTs into approximately five updates/second;
subsequent frames do not retune or flush the receiver. Real CM5 validation measured
nine frames in two seconds. This improves time resolution within the selected
band; it cannot monitor the entire 25–1700 MHz range simultaneously.

**Return to survey** restores the previous receiver, range, bins, gain limit,
PPM, repeat/protection settings and whether reception was enabled. The stack also
supports Survey → Watchlist → Investigate → Watchlist → Survey. Opening a
workspace or switching charts alone never claims USB. Configuring a fresh broad
survey deliberately starts a new workflow. Start/Stop, investigation, return and
watch mode all use the same serialized broker controls on web and touchscreen.

## Detection, heatmap and retention

A signal is a contiguous group at least **6 dB above a local 20th-percentile
floor**, with one measured quiet bin allowed between active neighbours. Widths
and peak frequencies are estimates at the acquired bin resolution; the analyzer
does not identify transmitters or automatically select a decoder. Regional
allocations describe permitted services rather than observed modulation.

Activity is **detected visits / valid sampled visits** at a frequency. Missing,
clipped and unsampled bins are excluded from both numerator and denominator.
Screen columns show the strongest bin's activity. This is sampled activity,
not continuous airtime: wide sweeps can miss short transmissions between visits.
Manual-mode clipped data remains visible on the raw chart but is excluded from
analytics and A/B differences. Watch measurements display their actual resolution;
normal surveys use their acquired bins, while explicit Watch mode measures FFT
channels at approximately 2 kHz resolution.

`insights.sqlite3` retains measured mean power (averaged in linear units), peak
power, valid and active counts in **one-minute buckets for 24 hours**. Fast live
frames therefore do not exhaust history after only a few minutes. Buckets retain
their actual first/last capture times and visit counts. Rows are recorded intervals,
not uniform elapsed time; gaps never become invented quiet measurements. Recent
detailed history remains capped at 720 individual sweeps globally. Persistence
shows up to 240 recent matching detailed sweeps in 3 dB level buckets, with colour
representing occurrence count rather than another peak-hold trace.

Archive safety bounds are 2,880 minute buckets across settings, 2,048 discovered
groups, 2,000 events and 64 watch frequencies. All history is separated by receiver,
range, actual gain, PPM, bin width, sample rate and FFT. Retained genuine raw rows
for the current settings are imported once at first startup; previous running
averages cannot reconstruct missing history. Future observations build the day
archive. Report bundles are retained separately, with an explicit 100-report limit.

Watch mode revisits only windows containing bookmarks, keeping the entire requested
channel in the usable cropped passband. The current list is captured when starting;
restart Watch mode after editing bookmarks. Nearby bookmarks can share one window.
Two quiet valid visits are required before a disappearance event. Invalid/clipped
visits do not imply disappearance, and measurements older than five minutes are
marked stale. Changing measurement settings resets transition comparisons. The
last bookmark's removal stops Watch mode and releases the receiver.

Reports are under `spectrum/reports/<id>/`; watch settings are in `watchlist.json`.
JSON records include measurement metadata and notes about the limits above.
Saved baselines and reports do not constitute calibrated antenna gain, SWR or
absolute input power measurements.

## Native CM5 touchscreen

Open **Decoders → Spectrum Analyzer**, the full-width tile above HF Decoders.
The native OpenGL interface uses full-width workspaces, large 21 px control labels,
large signal rows, and one main graph at a time. Survey → Signals → Investigate
provides the primary flow. Activity, Compare, Watchlist and Reports live behind
Tools, keeping only Scan / Signals / Tools in the primary navigation. It shares receiver leases, settings, watchlist, baselines, history and exports
with the web interface. There is no compressed web sidebar or embedded browser.

**Setup** opens a separate full-screen configuration workspace. Edit presets,
range, repeat and USB choice while stopped. Advanced contains gain, PPM, bins
and overload protection. **Apply**
saves without receiving; **Apply & Start** saves and starts through one serialized
backend action. Large numeric and text keyboards support frequency entry,
bookmark names and report notes. **Decoders** leaves the workspace while retaining
reception. **Return** in Survey restores the preceding survey/watch workflow.

Horizontal dragging pans; tap to select a frequency, then use **Investigate**.
Tap the selected-frequency readout for EU/US allocations and **Add to watchlist**.
Vertical swipes and Older page through real history. Activity offers heatmap, archived peak/mean and persistence.
Capture and event timestamps are explicitly UTC. Save/choose baseline and report
controls use the same measurements as the web app. Download and print native-created
reports from web Tools → Reports & exports.

Snapshots, SQLite reads and chart preparation run off the rendering thread.
Native OpenGL draws spectrum traces; a reusable GPU texture is reserved for
waterfalls and heatmaps. The native workspace launches no
independent radio process and does not stop reception when changing tabs.

## Validation

Run from `UI`:

```sh
python3 -m unittest test_spectrum test_spectrum_history test_spectrum_analysis test_spectrum_workspace
```

Tests cover FFT normalization, fixed-window retention, channel coverage, clipped
and missing counts, deduplication, minute history/restart, watch transitions,
matching A/B differences, report escaping/real values, broker handoffs, workflow
returns, touchscreen configuration and history rendering. CM5 tests additionally
cover VHF supervision and existing menu navigation. Hardware/browser checks use
real USB samples, including fixed-band live frames, multiplexed watch reception,
return-to-survey, comparison and every export route.

### Native rendering and responsiveness

The touchscreen consumes `native_snapshot()` directly in process. It does not
embed a browser or fetch its own HTTP endpoints. Spectrum and difference traces
are native OpenGL lines, with clipping bands drawn as native rectangles. Geometry
is prepared only after samples, viewport or display settings change. Unchanged
measurements do not trigger repeated chart rasterization or texture uploads.
Heatmaps/waterfalls use a cached GPU texture prepared from NumPy arrays, with a
raw history path that avoids base64 encoding and decoding locally.

Scan does not compute historical discoveries, the minute timeline or persistence.
Signals requests a lightweight signal summary; Activity requests only its chosen
history representation. NumPy reductions preserve the same partial-bin maxima,
clipped gaps, missing samples and valid-visit denominators as the original code.

On the CM5's retained airband dataset, cold full history analysis measured about
6.8 seconds before this change and 1.0 second afterward. The signal-only request
measured about 0.10 seconds and native spectrum geometry about 0.004 seconds.
These are data preparation timings, not a claim about display FPS or RF sensitivity.

## All-decoder mini SDR

Below the survey results, **Decoder activity · mini SDR** subscribes to the
shared decoder feed on port 8093. Its 1024-pixel / adaptive-height-marker waterfall covers
0–1.5 GHz, including HF, sensors, VHF/UHF and ADS-B. It shows actual decoded
outputs separately from this scanner's RF-energy detections. The decoder feed
never claims or retunes a radio. See [the shared activity model](decoder-activity.md).
