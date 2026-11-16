# Waterfall contrast

Display uses compact half-row Spectrum and Waterfall cycle buttons, with
Speed and Reset on the next row. Advanced sits directly above Back. Spectrum and Waterfall each cycle
OFF → ON (manual) → ON (AUTO) → OFF. Waterfall OFF only hides the main image:
reception, listening, row collection and background scans continue. Speed
cycles Slow, Medium and Fast. Waterfall visibility and the explicit contrast
mode are saved across restarts; old settings default to visible Auto.

The three waterfall color presets sit below the level sliders on the main
page, using Audio’s 64 px squares and 16 px gaps. STD (Standard, formerly
Classic), Kiwi and GQRX keep their existing saved palette identities. The top
four controls also use 16 px gaps. Advanced holds Themes and Readout Position. The
last option moves the frequency readout and meter left, middle or right;
it does not move the tuned station within the RF view. Back returns to the
main Display page before closing the drawer.

Auto measures the visible window's noise and upper signal levels, seeds the
range from the first row and smooths subsequent adjustments. Panning, tuning,
zooming or changing receiver starts a fresh measurement. Local magnification
estimates contrast from the visible slice of the source FFT, excluding signals
outside the view. Main Kiwi, OpenWebRX, FM-DX audio FFT, USB and Smart Scan use
the same contrast rule with independent ranges for their current views.

Manual starts from the live range and holds fixed floor and ceiling settings.
In Auto, both sliders show the actual live levels with AUTO labels and are
dimmed, read-only instruments. Select Waterfall ON (manual) to edit them.
Returning to Auto clears the previous estimate and seeds from the next row.
Both slider scales stay fixed. Dragging one edge clamps at the 30-unit minimum
contrast gap without pushing the other edge or moving its thumb. Choosing another color palette
preserves the contrast mode; Reset Display returns to Auto. The spectrum's
existing Auto control remains independent of the waterfall mode.

The range estimation changes display mapping, not receiver tuning. There are
no new network connections or speech models. Existing waterfall history is retained while newly arriving rows use the
selected settings; hiding the image does not discard its rows.

## Five-minute scrollback

On HOME, drag upward on the waterfall to inspect older traces; drag downward
for newer traces. The floating LIVE button shows how far the top row is behind
reception and returns immediately to the newest trace. Incoming reception and
audio continue while browsing. A historical trace tap does not tune; a horizontal
drag returns to live tuning. Hold-then-drag still resizes the spectrum.
TUNE and SCAN stay in place with disabled styling while reviewing history or
when unavailable; touching a disabled action does not tune or start a scan.
After five seconds without interaction, the waterfall automatically resumes
LIVE. Touching or dragging restarts this timer. Both manual and automatic
returns show LIVE ENABLED in the Zoom notification's position, style and fade.

History is RAM-only and expires after five minutes, including during stream
pauses. Changing receiver clears it. Each captured row retains its frequency
mapping and original palette. The buffer stores one byte per column at up to
30 distinct rows/second; repeated presentation rows are not duplicated. At
1,280 columns the maximum pixel payload is about 11.5 MB, plus row metadata.
Slower sources retain fewer rows. History becomes scrollable once it exceeds
the visible waterfall height. This is visual history, not audio replay.

The live GPU texture stays small. A separate viewport texture is allocated only
when reviewing history, and rebuilt only after scrolling, expiry, or resizing;
changes to the theme recolour only that viewport. Incoming rows do not trigger
historical uploads. Drag uploads are capped at 30 Hz. Hidden waterfall views continue collecting rows when the
source supplies them; sources suspended by a full-screen workspace have gaps.
