# USB TUNE and SCAN

HOME supports local RTL-SDR and Airspy HF+ signal search. The existing TUNE
and SCAN buttons and physical SCAN action use the active USB source, never a
parked network receiver.

- TUNE selects the nearest qualifying signal inside the visible RF range.
- SCAN sweeps the selected range from its lower to upper limit and collects all qualifying signals without stopping at each station.
  WFM uses 87.5–108 MHz; AM uses 531–1602 kHz on supported receivers. NFM uses a window of two capture spans either side of the starting frequency, clipped to the current hardware frequency interval. The green SCAN button means scanning.
- A second SCAN tap cancels and restores the original frequency. Exhaustion,
  timeouts, leaving HOME, pause, and history review also stop the scan.
  Manual tuning or a source/mode change cancels without overwriting that action.
- Results are signal candidates, not verified stations or proof of usable audio.
  WFM requires energy across a channel and rejects isolated narrow carriers.

Search reuses the waterfall's 2048-bin FFT and stores one current frame. The
UI samples at most every 70 ms during a scan and averages three settled frames
per tuning position. It opens no additional USB handle, creates no extra
thread, and performs no extra FFT. Idle search only checks an inactive flag.
The whole search times out after 60 seconds; absent fresh data stops it sooner.

Validation: `PYTHONPATH=UI python3 -m unittest UI.test_local_signal_search
UI.test_usb_home_stream UI.test_smart_seek UI.test_smart_seek_waterfall
UI.test_am_carrier UI.test_waterfall_history UI.test_encoder_feedback`.

## Station list and RDS

SCAN opens the USB station list. Each detected frequency can be selected for
listening after scanning; each complete sweep collects candidates. While listening in
WFM, decoded Programme Service (PS), PI, and RadioText populate that frequency.
No decoded identity means “Unnamed signal”; inactive rows label old messages
“Last decoded”. The list is bounded to 256 entries, stored locally, and separated
by receiver and frequency. BACK returns to HOME; no internet station name is
substituted for received RDS.

`usb-rds-mpx` prepares a 128 kHz FM multiplex from the existing IQ stream;
`usb-rds-json` reads the native redsea decoder. A six-block queue prevents the
RDS path from blocking audio. Retuning discards queued samples and resets the
decoder after a one-second settling interval. AM/NFM do not run RDS decoding.
The stream retains 57 kHz RDS data independently of the 32 kHz listening audio.

Install the pinned redsea 1.3.0 build with
`sudo bash scripts/install-usb-rds.sh`. The common dependency installer includes
this step for future installs/updates. Upstream: https://github.com/windytan/redsea
(MIT). The decoder cannot recover station names or messages from white noise.

## Automatic mode-selection band scan

Explicit AM/WFM selections start a full-band sweep once the local stream is
ready. WFM scans 87.5–108 MHz. Medium-wave AM scans 531–1602 kHz on receivers
whose declared tuning interval covers it (for example Airspy HF+). The RTL path now experimentally enables Q-branch direct sampling below 24 MHz,
with a 500 kHz lower software limit, and restores tuner sampling above that
threshold. Actual HF reception depends on dongle antenna wiring and remains
unconfirmed for generic devices. Switching uses the existing librtlsdr API;
no EEPROM or kernel changes are made.

Three settled FFT frames are averaged per position. Signal candidates are
ranked by channel energy above local noise; WFM rejects isolated narrow spikes.
At completion the listening frequency moves to the strongest qualifying signal.
A full-band sweep is not a guarantee of intelligible programme audio.

HOME keeps the live spectrum and waterfall within the receiver capture bandwidth.
No stitched full-band snapshot is displayed. Normal saved-session restoration
does not start an unsolicited new sweep.

The active SCAN button reads STOP SCAN and its border pulses in the theme focus color.
The list does not pulse. The tuned station has a 3 px theme selected-border outline.
A slim right-hand scrollbar uses dimmed theme slider-track and slider-thumb colors.
The animation stops immediately with the scan. Swipe vertically inside the
station rows to browse; movement never selects a station, including a drag
that returns to its starting point. PREVIOUS/NEXT remain available. Row taps
cannot interrupt an active sweep; stop SCAN or wait for completion first.

## Silent scanning

Scans temporarily suppress the CM5 codec output and gate both incoming USB PCM
and buffered output packets. User mute and volume settings remain independent.
Audio resumes only after the selected landing frequency has supplied fresh,
settled samples. A scan without a qualifying station stays silent until the
user tunes elsewhere or selects a receiver. Cancel restores the starting
frequency and resumes only after settling, respecting any user mute.

## Live waterfall width

Zoom-out stops at the widest live preset supported by the receiver capture.
The RTL-SDR capture is about 1.024 MHz, with a 937.5 kHz widest display preset.
Scanning can search the entire broadcast band, but cannot display that entire
band as a simultaneous live waterfall. Fixed full-band overviews are removed.

## Receiver handoff and scan results

Each explicit SCAN clears that USB receiver’s previous results and stale RDS
messages. The numbered, dim-prefixed list follows new discoveries, then centers
the playing station when scanning finishes. Manual browsing remains available.

Switching from USB to KiwiSDR releases local audio and scan ownership, selects
AM, and starts Kiwi’s band-limited strongest-signal landing. Delayed USB cleanup
cannot restore an old frequency over the new server. Landing still receives
fresh spectrum data when the spectrum display is hidden. Explicit USB selection
restores its remembered mode and scans; saved boot restoration does not rescan.
