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
Trails combine connecting lines with small dots at retained received positions.
Selected-aircraft dots are larger and gold; past-trail dots stay faint. Dots
that overlap at the current zoom are spaced visually to keep the map clear.
Reception gaps still break the line; dots never imply an interpolated position.
History starts with aircraft name labels, trail lines and dots hidden to reduce
clutter. **View → Labels**, **Aircraft icons**, and **History dots & trails**
(native: **Dots & trails**) switch these layers independently. Aircraft icons
start visible and can be hidden for a clear RX footprint view. Hidden symbols
do not leave invisible map click targets; aircraft remain in the list and logs.
Selecting a visible icon still identifies that aircraft. The choices stay in effect while
switching views during the current visit. Live keeps its own labels and normal
dots and trails. The RX footprint, dome and saved reception data are unaffected.

**History** defaults to all retained coverage, with shorter windows available in
View. Flight trails are retained for up to 24 hours. Coverage can include up to
90 days / 250,000 positions. The dome has an independent **Time** selector:
5 min, 15 min, 30 min, 1 hour (default), 3 hours, 6 hours, 12 hours, 24 hours,
7 days, 30 days and All recorded. Finite windows roll forward automatically;
cutoffs advance once per minute to reuse cached snapshots. All recorded uses
the retained positions at the current antenna site. The map's Live/History,
Start fresh and history window do not alter the dome. Distance and altitude
statistics use the dome's selected window. Filtering uses the full position database before display points
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
and trails on the aircraft map. It does not stop or restart the decoder or erase logs.
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

The 3D distance view fits the visible aircraft and ground disk to the viewport.
Height defaults to a clearly labelled expansion; Height display → True scale
(web) or the Height toggle (touch) restores equal horizontal and vertical units.
Sky trail links survive display thinning only across verified continuous original
reception. Actual reception gaps remain disconnected, and altitude values do not
change with visual height expansion.
