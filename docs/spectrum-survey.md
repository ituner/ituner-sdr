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

## Native CM5 touchscreen

Open **Decoders → Spectrum Analyzer**, the full-width tile above HF Decoders.
This is a native OpenGL touch workspace; it shares `VHFHub.spectrum`, receiver
leases, settings, saved baselines and `waterfall.sqlite3` with the web app.
Opening or leaving the view does not start, stop or reassign a dongle. Start/Stop
and all configuration changes use the same broker-controlled survey backend.

Tap Scan Settings to choose a preset or edit range, gain, PPM, bins, repeat mode,
overload protection and USB receiver. Stop before applying changes; Apply does
not start reception. Zoom buttons and horizontal dragging change the display
viewport. Tap either chart for frequency, level and EU/US allocations. Capture and activity
timestamps are explicitly UTC. Vertical
swipes or Older/Newer page through 60 real sweeps at a time; History cycles
30/120/720 sweeps. Auto Contrast changes colours without changing RF gain.
Save Baseline and Baseline Overlay use the same saved sweeps as the web app.
The Logs tab exposes recent survey activity. Leaving with Back retains reception.

Native snapshots, SQLite reads and raster updates run off the rendering thread.
One reusable GPU texture keeps refreshes bounded; no browser or second radio
process is launched by the native workspace.
