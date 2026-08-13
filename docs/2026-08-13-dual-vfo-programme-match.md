# Dual VFO Programme Matching

## Purpose

Dual VFO can listen to two KiwiSDR receivers at the same frequency and mode.
The matcher decides whether the two paths carry the same programme even when
they have different gain, propagation, delay, fading, noise, or a co-channel
interferer.

It is observational: it never retunes a receiver, changes passband settings,
or changes the A/B audio mixer.

## Persisted VFO B Profile

VFO B is stored in the regular receiver-state file:

`~/.local/state/kiwi-gl-display-receiver.json`

`preferences.dual_vfo` records both VFO sources, location/name, frequency,
zoom, mode, passband, audio controls, selected VFO, and mixer position.

Leaving Dual VFO deliberately releases B's live Kiwi connection, but does not
discard this profile. Returning to Dual starts B from its saved receiver rather
than silently defaulting to Local Kiwi.

## Capture Path

The live SND workers make non-blocking copies of their mono PCM for a separate
matcher thread. Playback, tuning, and waterfall updates never wait for it.

Each side is reduced to a 12 kHz, 32-band log-mel feature frame every 100 ms.
The matcher keeps a rolling ten-second window and refreshes its decision every
second after the streams are stable.

## Multi-Signature Decision

No raw-waveform comparison is used. A programme can arrive at each Kiwi at a
different time and with radically different gain, noise, and filtering.

The matcher independently evaluates three delay-search signatures:

1. **Spectral motion**: moving narrow-band structure above the local spectral
   floor. This follows tones, voice formants, carrier-adjacent modulation, and
   other programme changes.
2. **Programme envelope**: detrended, gain-insensitive short-window energy.
   This preserves shared speech/music rhythm when a co-channel signal spoils
   part of one spectrum.
3. **Broad spectral shape**: the overall normalized log-mel profile, useful
   when both receivers have a clean copy.

Each signature scans possible inter-receiver delay and scores only the actual
overlap length. A short accidental edge overlap is therefore unable to beat a
sustained five-second programme segment.

A candidate requires:

- real modulation-bearing content on both VFOs;
- spectral motion plus at least one of the other two signature families;
- agreement on the same delay within one second;
- the same multi-signature result in three consecutive one-second windows.

That combination is the actual anti-noise protection. Two unrelated white-noise
floors may have a superficially similar average spectrum, but do not maintain
the same changing spectral and envelope timeline at one delay.

## Display States

- `WAITING` / `WAITING AUDIO`: streams are not yet comparable.
- `ANALYSING`: collecting the initial signature history.
- `VERIFY 1/3` through `VERIFY 3/3`: candidate evidence is accumulating.
- `MATCH nn%`: corroborated programme match.
- `MATCH 100%`: high-confidence result, latched until source, frequency, mode,
  or a genuine audio interruption changes.
- `WHITE NOISE`: both VFOs have stayed decisively noise-like for at least five
  seconds. The label is intentionally withheld for ambiguous weak signals.
- `NO MATCH`: insufficient shared evidence. It is not a claim that the
  stations are different, only that the UI has not proven they are the same.

`BEST VFO A/B` is shown only beside a confirmed match. It represents the
clearer structured programme copy, never a generic S-meter contest.

## Cost

The analysis is intentionally small: two 512-point FFT reductions per 100 ms,
plus a once-per-second comparison of a maximum ten-second history. It is
negligible beside OpenGL rendering, live PCM playback, and WSPR decoding.

## Files

- Main implementation: `UI/kiwi_gl_display.py`
- Pi service: `ituner-sdr-lcd-kms.service`
- Audio scheduling drop-in:
  `systemd/ituner-sdr-lcd-kms-audio-realtime.conf`
- Optional repeatable CPU stress probe: `scripts/cpu_load_probe.py`
