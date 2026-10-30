# Smart Seek prototype

On Home, connect a Kiwi receiver in AM, AMN or AMW and tap **SMART SEEK**
below Auto Tune. The RF canvas becomes a black station picker. Audio keeps
playing on the current station while the existing waterfall connection
surveys the broadcast band containing the listening frequency. Smart Seek is
offered only inside the defined LW, MW and shortwave broadcast bands. Outside
those bands it cannot start a survey; use the band navigator to select a
broadcast band first. There is no nearby-frequency fallback.

Candidates appear in a vertical list across the full RF canvas. Eight compact
rows fit in the viewport, showing frequency and relative strength. The playing
row expands to twice its normal height and shows country, transmitter site,
listed power, language and UTC schedule for up to two possible broadcasters.
Missing metadata is explicitly marked as not listed. More matches are counted
when present. The expanded row uses an extra slot, leaving seven visible rows.
The viewport scrolls only enough to keep the selected row visible; background
discoveries never reorder the rows.
Each row shows schedule matches as two columns of country flags and short
station names (up to four matches per frequency). Multiple matches stay
separate; **Unknown** means no active schedule match. The shared header
identifies the names as schedule matches, rather than repeating a disclaimer
on every row. Only visible rows receive online schedule lookups, with two
requests at most in flight. Lookup failure never prevents listening.

Tap a row to listen. There is no separate Listen button. Audio changes
immediately and the list stays open, so another row can be auditioned. The initial RF survey
continues while browsing; new rows append without reordering existing rows.
While the picker is open, the
RC-28 dial moves the selection and its push/Transmit control listens to the
selection; its normal Tune/Zoom behavior resumes when the picker closes.
Desktop mouse wheel and arrow keys move selection, Enter listens, and Escape
closes. The `toggle_smart_seek` input action is available for a future
dedicated hardware Seek button; this prototype adds no GPIO wiring.

**Minimum signal** is a draggable slider: **Weak** on the left includes more
candidates; **Strong** on the right keeps only stronger signals. It filters
the measured list without another survey and does not sort or retune it.
The remaining rows retain discovery order.
Refresh forces a new survey; Close restores the listening view. Results are
cached in memory for five minutes per receiver and broadcast band, including
partial results if the picker is closed early. Reopening uses the same list
without RF capture and shows its age. Opening the list does not extend its
expiry. A failed survey with no measured rows is not cached. The cache holds
at most 24 receiver/band combinations and clears when the application exits.
Touch actions are captured on press so incoming discoveries cannot change
what a release selects. Swipe vertically, use the up/down page buttons, or
turn the dial to reach more rows.

The survey uses raw, uncompressed 1024-bin W/F rows at zoom 8, limited by the
receiver's zoom cap. Overlapping windows cover the band independently of the
display zoom. At least eight rows and 600 ms are needed for the first candidate
list; a window normally observes for at least 1.5 seconds, with a three-second
timeout. Total duration depends on band width and incoming rows. Skipped
windows are explicitly reported as incomplete coverage. Receiver sampling
bandwidth metadata determines window geometry. Wrong-view, compressed,
duplicate and stale rows are ignored, including across sequence rollover.

Candidates require a persistent carrier plus broad sideband energy on both
sides between approximately 350 and 2200 Hz from it. Sideband energy must
vary over time relative to the surrounding noise floor. This rejects bare
carriers, stationary noise and one-sided signals in the regression fixtures.
The survey includes noise-reference context outside the band but publishes
only frequencies within its boundaries, bounding half-bin interpolation
uncertainty at the band edges. Weak, fading or briefly quiet AM stations can
be missed by this stricter heuristic; Refresh can measure them again.

These RF checks do not classify speech or music and do not guarantee
intelligible audio. Bars express the
carrier's prominence over its local spectral floor, not calibrated dBm or
audio SNR, and do not promise intelligibility. Surveying never retunes audio.
The current display waterfall pauses during measurement and restores its
original center, zoom and rate when capture finishes or is cancelled. Auto
Tune waits until the picker closes. Receiver, manual frequency, mode, filter,
connection, pause or audio-ownership changes cancel active capture. Explicit
station selections inside the picker preserve it. Cached measurements remain
available for their receiver/band until their original five-minute expiry.

Validation: `python3 -m unittest discover -s UI -p 'test_smart_seek.py'`,
the existing Auto Tune and navigation tests, and an actual OpenGL render of
the picker. Hardware reception and rotary input require a live CM5 check.
