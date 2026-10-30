# Smart Seek prototype

On Home, connect a Kiwi receiver in AM, AMN or AMW and tap **SEEK**
in the square group with Favorite, Play/Pause and **TUNE**. Smart Seek takes the full screen with a black station picker and a shared Back control. Audio keeps
playing on the current station while the existing waterfall connection
starts in the broadcast band containing, or nearest to, the listening
frequency. It only publishes candidates inside the defined LW, MW and
shortwave broadcast allocations; there is no arbitrary-frequency fallback.

Each opening starts with an empty station list and first measures the broadcast
band containing, or nearest to, the listening frequency. While the menu stays
open, a separate in-memory catalogue accumulates results for the other available
broadcast bands on this receiver. After the selected band's initial pass, two
steady broad views estimate activity across the receiver's spectrum. These are
scheduling hints, not station detections. Promising bands are checked first,
with nearby bands preferred for comparable activity; apparently quiet bands
remain at the end of the queue rather than being declared empty from the overview.

Two complete observations of the displayed band alternate with one background
observation. A background band advances one observation at a time, so even a wide
band cannot monopolize the waterfall. Each view remains steady for its normal
two-to-five-second dwell. The broad survey is refreshed after the background
queue completes and at least two minutes have passed. There is only one waterfall
connection and no automatic audio retuning.

Use **BAND** to choose a band. Each choice shows the last scanned RF candidate
count for that receiver and band, retained for one hour from measurement. A dash
means there is no unexpired measurement. Coarse peaks never contribute
to counts, and a frequency with several possible schedule identities counts once.
On switching, previously found rows appear dimmed with **Rechecking…** and keep
their original order. A fresh completed AM observation brightens each verified
row; rows not heard again remain visibly unqualified. Tapping a dimmed row can
still audition its last measured carrier. Other bands' results stay available.
Closing and reopening starts a fresh RF list, while each band's unexpired count
remains visible. **REFRESH** also clears only the current band's RF list. Neither
action, nor reading the counts, extends their measurement age. An incomplete
rescan keeps the previous count; a completed pass can replace it, including zero
when the full band was measured successfully and no candidates were confirmed.
Receiver changes cannot mix counts, and the minimum-signal filter still applies
to retained detections. This count cache lives in application memory and survives
menu reopening, but not application restarts. Switching bands does not change
audio until a station row is tapped.

The header shows the displayed band and station count, and identifies when
an overview or another band is being checked in the background. Technical window counts are hidden. A thin progress bar follows received
rows inside the current window. Each completed observation updates the thin progress bar. Closing the picker stops capture and restores the listening waterfall.

Candidates appear in a vertical list across the full RF canvas. Ten compact
rows fit in the viewport, showing frequency and relative strength. The playing
row expands to twice its normal height and shows country, transmitter site,
listed power, language and UTC schedule for up to two possible broadcasters.
Missing metadata is explicitly marked as not listed. More matches are counted
when present. The expanded row uses an extra slot, leaving nine visible rows.
The viewport scrolls only enough to keep the selected row visible; background
discoveries never reorder the rows.
Each row shows schedule matches as two columns of country flags and short
station names (up to four matches per frequency). Multiple matches stay
separate; **Unknown** means no active schedule match. The shared header
identifies the names as schedule matches, rather than repeating a disclaimer
on every row. All discovered rows receive local schedule lookups, with two
jobs at most in flight, allowing uncertain signals off screen to be revisited. Missing schedule data never prevents listening.

Tap a row to listen. There is no separate Listen button. Audio changes
immediately and the list stays open, so another row can be auditioned. The local RF survey
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
Refresh forces a new local survey; Close restores the listening view. Opening starts an empty catalogue. Refresh clears the displayed band; switching
bands retains dimmed earlier rows until new observations qualify them again.

Station names use a downloaded EiBi and HFCC index. There are no per-frequency
website queries, including the regular tuned-frequency identity display.
UTC times, operating weekdays and validity dates are evaluated locally;
current-season matches take priority. If there is no current match, an older-season
schedule can supply a name at the matching UTC time and weekday. A small asterisk
beside its flag is explained by **\* old schedule** in the header. The saved source
dates are retained; individually ended programmes in the current season do not
become fallback matches. The footer shows a simple offline-name or updating status.
Source seasons remain in the downloaded database metadata.
Bulk refresh is attempted at most daily after successful downloads, with a
one-hour retry interval after failures. Failed updates preserve the last good
source files. These are possible schedule matches, not decoded identities.
See [Offline broadcast schedules](offline-broadcast-schedules.md).
Touch actions are captured on press so incoming discoveries cannot change
what a release selects. Drag vertically to scroll the list without tuning.
**Scroll Up** and **Scroll Down** move the list without page counters; a narrow
scroll indicator shows position. The dial still moves the selection, and its
press listens. **BACK** closes Smart Seek and restores the listening screen.
Full-screen touch and rendering do not inherit the Home rail relocation.

**WATERFALL** is off by default and is available while a listed station is
playing. Turn it on to expand the playing row to four standard rows tall and
show a continuous 100 kHz RF waterfall in its right half. With the waterfall
off, the playing row returns to its normal two-row height. A gold marker shows the actual tuned frequency and nearby
frequency labels provide context. This temporarily gives the existing
W/F connection exclusively to the preview: all band scans and uncertain-signal
checks pause, with their observation deadlines preserved. Turn it off to resume
scanning. Tuning another row moves the preview to that station; closing Smart
Seek, Refresh, band selection and Research return the stream to scanning.
Home's zoom and RF tuning are not changed. The preview follows the current
waterfall palette and the Auto/Manual contrast choice in Display settings.
Auto adapts to this preview window independently. It buffers at most 32 source rows and keeps
a small GPU history. It opens no additional receiver connection.
The expanded card wraps full station titles onto two lines and separates
location, power/language and UTC schedule vertically beside the waterfall.

The survey uses raw, uncompressed 1024-bin W/F rows independently of display
zoom. One two-second wide overview of the selected band prioritizes promising
areas without publishing coarse peaks as stations. For a 30 MHz Kiwi, the 41 m
overview is zoom 6 (about 469 kHz) and the 49 m overview is zoom 5 (about 938 kHz).
Fine confirmation uses overlapping zoom 8 windows (about 117 kHz with 114 Hz
bins), limited by the receiver's zoom cap. Initial fine observations last two
seconds, repeated passes three seconds. Up to two uncertain signals per pass
receive a five-second zoom 10 observation, with a 30-second per-signal cooldown.
The rest of the band continues receiving coverage; opening starts fresh and selecting another
band starts requalification. Closing or changing receiver context stops every phase.

First candidates require at least eight rows and 600 ms; strong discoveries in
an observation append first, while later passes can add weaker or fading signals.
Existing rows retain their position. Their relative-strength meters update from
completed observations using a weighted average, rather than tracking every row.
No promise is made that every weak station will eventually be detected.
Wrong-view, compressed, duplicate and stale rows are ignored, including across
sequence rollover. Missing data times out rather than stalling the survey.

Candidates require a persistent carrier plus broad sideband energy on both
sides between approximately 350 and 2200 Hz from it. Sideband energy must
vary over time relative to the surrounding noise floor. This rejects bare
carriers, stationary noise and one-sided signals in the regression fixtures.
The survey includes noise-reference context outside the band but publishes
only frequencies within its boundaries, bounding half-bin interpolation
uncertainty at the band edges. Weak, fading or briefly quiet AM stations can
be missed by this stricter heuristic; subsequent passes can measure them again.

These RF checks do not classify speech or music and do not guarantee
intelligible audio. Bars express the
carrier's prominence over its local spectral floor, not calibrated dBm or
audio SNR, and do not promise intelligibility. Surveying never retunes audio.
The current display waterfall pauses while the picker observes RF data and restores its
original center, zoom and rate when the picker closes or capture is cancelled. Auto
Tune waits until the picker closes. Receiver, manual frequency, mode, filter,
connection, pause or audio-ownership changes cancel active capture. Explicit
station selections inside the picker preserve the current local scan.

Validation: `python3 -m unittest discover -s UI -p 'test_smart_seek.py'`,
the existing Auto Tune and navigation tests, and an actual OpenGL render of
the picker. Hardware reception and rotary input require a live CM5 check.

Station names use larger 28 px type and 42×28 flags without reducing the ten-row
capacity. When four schedule choices share a compact row, 24 px text and 36×24
flags preserve both lines. Single matches can use the whole name area.

An **Unknown** row has a separate **Research** button on the far right. This is
the only station-name action that requests online schedule pages. It queries
Shortwave DB and Shortwave.Live off the UI thread, admitting suggestions within
2.5 kHz and keeping ambiguous alternatives. A separate full-screen information
panel shows possible names, frequency, country, site, power, language, UTC
schedule and source when available. These suggestions do not replace offline
names or tune the radio. **Back** returns to the same list; tapping the main
part of an Unknown row still listens normally. Enter/encoder press cannot tune
while the research panel is open. Network errors leave browsing and listening
usable; Search Again is an explicit retry.

The frequency column uses the nominal schedule frequency when all displayed
matches agree. Unidentified shortwave signals close to a normal 5 kHz channel
show that rounded channel with an approximation sign. Ambiguous midpoint
signals retain their measured frequency. Redundant .000 decimals are removed.
The received carrier remains the listening target; an expanded playing row
shows its RF frequency when it differs from the displayed channel. Matching
tries a bounded channel-aware fallback before offering Research, while retaining
UTC/day/season checks and genuine off-channel schedules.

Strong AM sideband lobes are compared against nearby, stronger confirmed carrier
centers. Narrow clipped carrier plateaus are accepted, while genuine adjacent
5 kHz stations remain separate in the regression fixtures. The narrow follow-up
can correct a mis-centered row in place and refresh its local schedule matches.
If that row is currently playing off center, **Tap to center** offers an explicit
retune; background analysis never changes audio. Uncertain rows can show
**Carrier only** when a persistent line lacks the required varying sidebands, or
**Unconfirmed** when the longer observation cannot verify it. These are RF
classifications, not decoded station identities. Channel allocations and active
schedules guide which discrepancies to inspect; listed transmitter power or
proximity alone never establishes the identity or listening frequency.
