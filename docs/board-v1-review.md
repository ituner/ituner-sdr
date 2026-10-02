# board_v1 interface and receiver audit

Compared `board_v1` (b12c8dd, main + JD9365DA-H3 + upstream PR 11)
with `lucaiuli/fmdx-support` and `lucaiuli/knob-ui`, including
`19cfe10` (protocol-aware handoffs), `a2f5c64` (mode/sidebar navigation),
`c71268f` (menus), and the baseline FM-DX PR branch.

The PR 11 baseline port did not include all the work on the original fork.
A wholesale merge would also replace newer main functionality, including
OpenWebRX and local receiver integration. This update ports the relevant
behavior while retaining those newer paths.

## Corrected here

- Home instruments no longer render over Settings, Modes, or option drawers.
  Drawers cover the entire rail with an opaque background.
- Settings, Modes, Receivers, Network, Font Lab, local SDR, and expanded WSPR
  views use the same bottom-right Back target and arrow renderer as the
  existing Audio, Display, Filter, Apps, and Constellation drawers.
- Home mode buttons commit the selected demodulator before opening options.
  FM-DX keeps its server-controlled FM mode; local SDR validates supported modes.
- KIWI is the fresh-install and Reset Display waterfall palette. Existing
  saved palette choices are preserved.
- FM-DX waterfall rows retain their FM carrier coordinates rather than being
  clipped against Kiwi's 29.999 MHz display boundary. This is an audio-derived
  spectrum/waterfall, not a wideband RF spectrum supplied by the FM tuner.
- Kiwi receiver handoffs restore mode-specific strong-signal landing from
  19cfe10. Noise-only data times out after two connected seconds. Manual tuning,
  mode changes, and a replacement receiver invalidate the pending landing.
- FM-DX handoffs select the nearest cached station when available. RDS names
  continue to accumulate passively from live status and are persisted.
- The explicit FM-DX Scan command covers the entire supported FM band rather
  than only a capped group of presets. Stop restores the origin. Manual tuning
  and receiver changes take ownership so late scan work cannot retune them.

## Sidebar follow-up

All option rails use a shared screen-name header. FM-DX status, station
navigation, Scan/Stop, and tuning controls occupy separate rows. Manual FM-DX
tuning offers 50, 100 (default), and 200 kHz steps, saved independently from
Kiwi's step. FM dragging uses channel-sized detents rather than the audio
waterfall span. The RDS band scan retains its independent 100 kHz increment.

Settings no longer duplicates the receiver directory as KIWI. SYSTEM is now
the clearer INFO destination with its own icon. STATS has an explicit Close
target and its launcher toggles the graph. MODES opens the complete mode-family
and tuning drawer directly; WSPR remains available in that same drawer.

## Branch features not silently imported

The original fork also has a richer FM-DX audio scope/ruler, station shortcut
presentation, scan-progress presentation, and broader receiver-picker/map
refactoring. The knob branches have the separate three-knob input/controller,
focus navigation, and desktop knob simulation. Those are distinct feature
ports, not included wholesale in this CM5 bug-fix pass. CAD commits on the
local knob branch do not affect the runtime UI.

RDS discovery in the completed original implementation was passive during
listening, with an operator-started cancellable scan. It was not an automatic
background band sweep: sweeping retunes the shared FM-DX receiver and mutes
listening. This distinction is retained.

## Verification

Regression tests cover navigation spacing and shared Back rendering, hidden
compact readouts, immediate mode engagement, actual waterfall texture-strip
mapping above 30 MHz, and generation-safe landing/scan behavior. OpenGL renders
at the CM5's 1280x800 logical resolution are inspected for sidebar layout.
Physical touch and live server behavior still require a CM5 trial before PR.
