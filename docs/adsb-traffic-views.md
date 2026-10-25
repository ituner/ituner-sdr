# Airspace: map, views and receiver settings

The native touchscreen and browser map use the full available canvas. There is
no fixed aircraft sidebar. The main controls are **Live**, **History**, **Dome**,
**View**, and **Settings**. Zoom, Fit view and RX on/off float over the map.

**View** contains the optional aircraft list, base map, labels, range rings,
reception footprint, history window, Start fresh and Reset panel position.
**Settings** contains receiver/dongle assignment, shared Radio / User
Information (including location and GPS), and logs/diagnostics. Radio reception
continues while menus are closed or another display view is selected.

Tap an aircraft to show a compact translucent details card, including altitude,
speed, heading, vertical rate, freshness, Follow and Locate. Drag the card by its
header to move it without panning the map. The browser remembers its position;
the native view retains it while the app is running. Reset panel position
restores the corner placement. Without a selection, only a small hint remains.
The aircraft list is an optional overlay and closes when a target is selected.

Back returns to the parent screen. Settings → Receiver → Dongles returns through
those screens; Dome → Receiver returns to Dome. The native history picker has
Apply and Cancel, and Back cancels an unapplied choice. Browser Apply window and
Cancel have the same semantics. Only Back from the native main map leaves
Airspace. Shared navigation, theme and UTC/footer geometry remain in use.

## Live and saved reception

Both interfaces open in **Live 15 s**, with five-minute trails. The first Live
tap selects or confirms Live; further taps cycle aircraft visibility through
15 seconds, 30 seconds, 1 minute, 2 minutes and 5 minutes, then wrap to 15 seconds.
The button shows the selected duration. Switching back from History confirms
Live at its previous duration; another tap advances it. A new visit defaults to
15 seconds. Cycling does not clear selection or restart the radio.

Fresh contact and fresh position still use separate 15-second limits. Longer
Live windows retain last-known positions as muted symbols with age labels.
Speed or callsign messages never extend an old position's lifetime. Follow
continues to require a fresh position. ON MAP counts visible positions; LIVE
counts fresh radio contacts. Live trails remain five minutes.

**History** defaults to all retained coverage, with shorter windows available in
View. Flight trails are retained for up to 24 hours. Coverage can include up to
90 days / 250,000 positions. Live dome reception starts with the last five
minutes and then accumulates from a fixed starting point; it does not expire
samples as the clock advances. Start fresh establishes a new starting point.
History uses the selected reception window, including its distance and altitude
statistics. Filtering uses the full position database before display points
are thinned. Historical endpoints show Recorded age; the position archive does not establish the time of the last
non-position message.

## Accumulated RX footprint

The RX on/off control is available directly on the map and under View. It shows
the greatest observed range in each five-degree bearing sector at this antenna
site. Peaks are stored in SQLite separately from individual positions, so the
outline grows as farther receptions arrive and survives restarts and log/data
pruning. Live duration, History and Start fresh do not shrink or reset it.
Existing retained observations seed the peaks on upgrade. Receiver locations
more than 100 metres apart have separate accumulated footprints. Unobserved
bearings stay blank and are not claimed to be obstructions.

**Start fresh** begins a new Live viewing window and excludes earlier positions,
trails and coverage. It does not stop or restart the decoder or erase logs.
Saved observations remain available in History. Since opened and Past trails
are no longer separate controls. A view-change notice lasts five seconds; the
selected Live/History button continues to identify the active view.

Telemetry is passive, compact text without button borders. It distinguishes live
contacts, fresh map positions and new aircraft since this visit. Aircraft in the
initial snapshot form the baseline. An ICAO address first encountered afterward
is a new arrival; its row and symbol are highlighted for 12 seconds. Returning
aircraft are not counted again during the visit. Contact memory is bounded at
4,096 aircraft / 24 hours.

Server observation timestamps prevent cached replies from making traffic look
fresh. Browser time is aligned to the receiver for filtering; labels use the
browser's local time. These choices affect only the display. Reception, flight
logs and retained coverage continue independently. Other VHF maps share the
globe renderer without opting into ADS-B traffic filtering.

Dome refreshes keep the previous completed scene visible while a new window
loads. New reception samples glow briefly; rotation, filters and a pinned
inspection remain intact during ordinary updates. The browser caches the base
image and composites the new-sample glow over it; the native renderer caches
projected GL batches. Neither publishes an intermediate empty/loading scene.
