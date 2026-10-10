# CW live waterfall and slot listening

The CW overview covers 200–3200 Hz above the USB dial. Slot markers and both waterfall sources share this RF scale. Selecting a marker selects its text; **Listen to slot** on the touchscreen or **Listen on CM5** on the web page explicitly plays that signal through the CM5 speaker/headphones. Web listening controls the CM5 output, not the browser speaker.

On the touchscreen, swipe left across the live waterfall to view the next saved CW receiver, or right for the previous one. This matches the < RX / RX > buttons and does not retune or switch listening audio. Up/down swipes continue to navigate live view and history.

## Waterfall sources

A W/F socket pairs with each CW receiver’s existing SND session timestamp. It requests zoom 13 and crops the returned rows using their actual starting-bin/zoom header. The Kiwi stream takes priority when available. No additional SND receiver is created. Waterfall hardware resources still depend on the Kiwi configuration and channel assignment.

If W/F is unavailable, malformed, refused, disconnected, or has produced no valid row for three seconds, the display uses the existing audio stream. Failed W/F connections retry after 30 seconds. An authenticated but stalled W/F socket stays open (closing it can also close its paired audio on Kiwi) and its setup is retried in place. Channels declared audio-only by Kiwi use fallback throughout. Audio decoding continues independently. Source changes clear the visual ring to avoid mixing differently scaled rows. The source label reports Kiwi or audio fallback.

The fallback uses a 4096-point Hann FFT at 12 kHz (2.93 Hz bin spacing) and a 600-sample hop, producing 20 rows per second. These overlapping windows improve frequency detail but smear very fast keying more than a short FFT. The acquisition and Morse engines retain their original timing. Both sources display a fixed 12-second ring. Kiwi rows may repeat if its native waterfall cadence is below 20 Hz; no extra information is invented.

The touchscreen uploads individual rows to a bounded GPU ring. The web page polls incremental row data separately from receiver/text metadata, then renders rows on animation frames. Hidden/offscreen web cards stop requesting rows and catch up when visible. Existing PNG endpoints remain available for stopped receiver views and compatibility.

## Audio behavior

Listening uses a continuous 300 Hz-wide bandpass centered on the selected track, with a short startup fade. The original audio pitch is retained. There is no gain boost. A bounded output queue prevents playback from delaying the decoding engines. All other tracks continue decoding.

Starting Listen temporarily hands the existing output device to CW. Stop Listening, decoder stop/delete, lost audio, or an expired track releases it and restores normal SDR listening. Listening is not persisted across restarts. The user’s volume, mute, headphone detection, display driver and touch mapping are retained. Another tool already using audio or dual listening must be stopped first.

## Validation and dependencies

`tests/test_cw_live.py` covers FFT detail, packet continuity, frequency alignment from Kiwi headers, stale/unavailable-source fallback and recovery, bounded row cursors, selected-slot filtering, command validation and audio-output handoff. SciPy is included in the application dependency installer for the slot filter. No new display dependencies are required.
