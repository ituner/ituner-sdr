# ADS-B reception coverage

Open **ADS-B → Reception dome**, beside **Live** in the viewing row, on the
touchscreen or Airspace web page (`http://cm5.local:8090/#coverage`). The black view uses the same stored
observations on both screens, without claiming an SDR or starting ADS-B.

**Time** offers **1 min**, **5 min**, **30 min**, **1 hour** (default),
**6 hours**, **24 hours**, **7 days**, and **All recorded**. Selecting a duration
shows rolling history; it does not restart the clock. **Reset**, immediately to
its right, clears the displayed dome, aircraft selection and measurements and
accepts only positions received from that moment, keeping the selected duration.
After filling that duration it rolls rather than periodically clearing. Reset
can be pressed again at any time. Selecting a duration again returns to its
retained rolling history, and All recorded restores all retained site history.
The one-minute cutoff advances in ten-second steps; other windows use minute
steps. Neither control deletes logs, resets a decoder or changes the map window.

- **Sky cells** projects received directions onto an angular hemisphere, in
  4° azimuth × 2° elevation cells. Blue means received in sample-count mode;
  Signal uses the same blue-to-red strength scale as 3D distance. Grey means unknown.
- **3D distance** fits the ground disk and every displayed aircraft to the viewport.
  Height defaults to **Fit height**, with the expansion factor explicitly shown
  in the side readouts. **True scale · 1:1** (web Height display / touchscreen Height)
  restores equal horizontal and vertical units. Horizontal range, altitude
  readouts and point details always retain actual values. One graduated ground
  ruler and a height axis replace per-point distance labels. Maximum altitude,
  aircraft/source and scale notes stay beside the 3D plot, without central
  caption overlays. The wider native plot and tighter camera margins enlarge
  the projection while keeping compass and distance graduations readable. Entering this view
  uses a lower 25° camera tilt to reveal vertical separation. Drag to rotate; use sliders (web) or
  rotation/tilt buttons (touch). Tap a dot, any part of a trail, or an observed
  sky cell to open an aircraft information card without filtering the scene.
  After a tap, the card follows that aircraft's newest received position for
  RSSI, horizontal/slant range, azimuth and elevation. Its main altitude follows
  the latest actual report, independently of geometry updates. The prominent
  reception age resets on that aircraft's reports; there is no separate ageing
  clock anchored to the original tap. New recorded position evidence can update
  it even if a brief live report fell between web polls. Other aircraft, redraws
  and unchanged history cannot reset it. The compact age reads in seconds, then minutes/hours. No reports are
  extrapolated, and selecting another aircraft cannot reuse the previous one's
  telemetry. The web card refreshes once a second; the native card follows live
  application snapshots. Current speed/heading/squawk appear with reception age.
  A sky cell selects
  its latest retained sample; it can contain reception from several aircraft.
  Only this aircraft explicitly filters the display; Show all restores it.
  Close or Back (touch) / Escape (web) dismisses the card first. Reset restores
  all aircraft. Empty/unobserved sky does not fabricate an aircraft.
- **Map on/off** is directly on the main dome header in both interfaces.
  Turning it on from a sky mode opens **3D distance** and shows the satellite
  ground reference. Turning it off removes imagery without changing reception.
- **RX radius** is the maximum observed horizontal distance from the configured
  antenna. Diameter is twice that radius: a reference circle, not a claim of
  complete circular coverage. Maximum slant range includes vertical distance.
- **Maximum altitude** is the highest received aircraft altitude in the retained
  history, in feet and kilometres. Its side readout in 3D (zenith label in sky modes) is a statistic;
  that aircraft was not necessarily overhead. GNSS altitude is above the WGS84
  ellipsoid; barometric fallback is approximate. It is not height above antenna.

Set antenna latitude/longitude in **Settings → Radio / User**, shared by both
interfaces and local applications. The advanced antenna height used by Coverage
is **metres above WGS84 ellipsoid**, not height above street/roof.
Leave blank if unknown; geometry explicitly assumes 0 m. The address pin is an
approximation until the antenna itself is surveyed. Height updates are shared
with touch through the station profile, independently of receiver tuning.

`coverage.sqlite3` in the ADS-B data directory stores direct ADS-B positions
independently of the 24-hour traffic trails. Every reception is preserved for at least seven days. Older records may remain up to 90 days within a 250,000-position target; this target never deletes records younger than seven days. Startup imports retained
`flights.jsonl*` logs idempotently. New entries follow the normal five-second
flight logging cadence. SQLite reuses pages as older positions expire. Sky-cell
statistics and extrema use the full retained history. The selected window supplies up to 250,000 representative positions to both interfaces, so the current approximately 172,000-point week is loaded completely. Larger seven-day archives remain complete on disk while display sampling bounds the RAM and graphics workload. The previous 100,000-dot cap is removed. Received coordinates, altitudes, signal values and IDs are held in cached RAM snapshots and prepared geometry, while the source observations remain persistent in SQLite. Rotation uses those arrays without a disk read or network request.
Links between retained dots are built before thinning: a longer displayed segment
is only confirmed when all intervening original links pass the time, movement
and receiver-lifecycle checks. It does not invent continuity across a gap.

The `/api/coverage` endpoint reads a cached snapshot built on the receiver
worker. The native renderer builds cached 3D geometry off the GL/touch thread, then
rotates vector arrays and submits batched OpenGL points, triangles and lines. Dense stationary projections run on a separate worker; camera and history revisions reject outdated completions, so starting another drag never waits for a dense projection. Moving
frames use a cached overview of up to 1,800 real dots and 2,200 actual trail
segments; Sky Cells retains its complete bounded grid. Picking buffers are rebuilt
after motion settles, and stationary frames refine through 8,000, 30,000 and 100,000 dots to the complete saved set over about three seconds after release, using exactly the same camera bounds. A held finger stays in preview even when it pauses. The side readout shows the current and available dot counts. Sky Cells prioritizes speed with an 8° × 4° overview during interaction and fixed 4° × 2° reception cells at rest. It does not build a fine 1° mesh. Dense settled clouds use one logical-pixel dots; rotating previews use 2.4-pixel dots. Picking still accepts a wider touch radius. A cached convex support hull keeps camera fitting independent of history size. Native GNSS dots use one GPU point each instead of 24 triangle vertices, while approximate barometric dots retain open rings. History preparation is deferred during a native drag; the web avoids parsing history responses during a drag. No saved
points, statistics or reception continuity are removed by this display preview. No dome
bitmap is repainted or uploaded while dragging. Readouts sit beside the larger
dome as plain text. The web view caches its grid and trigonometry, avoids
resizing an unchanged canvas, and uses lower pixel density during a drag before
restoring full sharpness on release or a short slider pause. Web trails and dots
are batched by colour; dense histories use smaller markers to reduce overlap. Unknown sky uses a faint wire shell;
received cell boundaries and counts keep their original resolution. History
remains visible with ADS-B paused; the receiver state is shown separately.

Only **Sky Cells** and **3D Distance** are exposed as view choices. Both offer
**50–400% zoom**: native −/+ controls in 25% steps (up to 400%), and the web Zoom slider or
mouse wheel. Above 100%, the projection extends faintly behind the side controls
at 14% opacity; the central plot stays bright and controls/readouts remain on top.
Navigation and the status footer remain outside the drawing region.

**Signal** colours use a fixed −45 to −5 dBFS scale: blue → cyan → green → yellow
→ red. The same scale colours cells, dots and confirmed trail links (using their
endpoint average), without renormalizing when history grows. Missing RSSI uses a
muted neutral colour. The legend shows the scale; these are relative receiver
measurements, not calibrated power or an assertion that a closer aircraft must
be stronger. Statistics still use the complete selected history.

Positions must be directly received ADS-B, with finite coordinates, a numeric
altitude and position age ≤10 seconds. Duplicates are removed. WGS84 ECEF→ENU
accounts for Earth curvature. GNSS altitude is preferred; a barometric fallback
uses open dots. RSSI is readsb's recent aircraft average in dBFS, not calibrated
antenna gain. Trails connect original observations no more than 15 seconds apart,
with implausible jumps and receiver lifecycle boundaries split. Web optionally
shows dashed inferred links across 15–120 second position gaps.

Unobserved cells cannot establish an obstruction: there may have been no
transmitting aircraft in that direction, no decoded position, or no ADS-B
receiver running. A probability-of-reception obstruction map requires an
independent expected-position feed and synchronized receiver uptime.

CM5 benchmark, 18 October 2026, same 583 retained positions: former native
bitmap generation took 104.3 ms (cells), 65.9 ms (trails), 62.0 ms (3D). Cached
scene rotation takes 10.0 / 1.6 / 1.6 ms respectively, excluding GL submission
and screen presentation. These are processing timings, not measured FPS.

## Live-map reception footprint

**RX FOOTPRINT** adds a faint shaded background to the traffic map on web and
touchscreen. It defaults on; toggle it off to hide it. **FIT VIEW** frames both
the displayed aircraft and the enabled footprint. Changing Live / Since opened /
History or starting a fresh viewing window does not clear the reception history.
The reception dome is unchanged.

The overlay uses translucent violet shading with a bright lavender edge and dark
outline, so its extent stays distinct from terrain, cyan trails and aircraft.

The boundary uses the furthest directly received position in each 5-degree
bearing sector, over the full retained history (up to 90 days). Adjacent observed
sectors join; unobserved directions stay blank, including across north. This is
a historical maximum-range envelope, not a guarantee of continuous reception
inside it or proof of obstruction outside it. It combines aircraft at different
altitudes. No external aircraft feed or terrain prediction is used.

The compact `/api/footprint` endpoint exposes the cached sector counts and
geographic regions without transferring the detailed dome points. It is
refreshed every ten seconds in the browser. Native projection is cached until
the history or camera changes and drawn in two OpenGL batches below the trails
and aircraft. A footprint from a receiver site more than 100 m away is hidden
until history for the current site is ready.

### Aircraft identity in the dome popup

Tapping a received point or sky trail shows the aircraft manufacturer, model,
registration and ICAO type when known, alongside the selected sample's recorded
telemetry. The thumbnail sits beside the callsign in the header; aircraft identity uses
the full width below it instead of reserving a separate photo column.
The two-column card uses tight vertical spacing and a small thumbnail so it
leaves more of the globe visible. The native card is 316 pixels wide, with labels above values inside its two
columns, readable telemetry and unchanged 56-pixel touch controls. Reception age
is shown simply as “1 s ago”; the age row does not reserve a telemetry column. The native touchscreen
and browser share the same lookup cache.
The installed tar1090 aircraft database provides an offline fallback; opening a
card requests fuller identity from adsbdb (PlaneBase), with hexdb as fallback.
Only the six-digit aircraft ICAO address is sent, never the receiver location or
reception history. Identity describes the database's current registration and
can differ from the registration at the time of an old observation.

Where available, a small matched-aircraft thumbnail is supplied by Airport-Data
through adsbdb. The web thumbnail links to its original photo. Missing photos
stay hidden; no generic aircraft photograph is substituted. Internet lookups,
image decoding and thumbnail resizing run in one background worker, independently
of reception and dome rendering. Results persist for seven days; offline or
missing lookups retry after five minutes when that card is next opened. Memory
is limited to 128 identities and the persistent cache to 512 identities/photos.

### Optional geographic base in 3D distance view

Choose **Aircraft · 3D distance → Ground map → Satellite base** in the browser,
or **3D distance → Ground** on the touchscreen. The layer defaults to off. The
browser remembers its choice; the native choice lasts for the app session.
The map shares the GLOBE NASA Blue Marble imagery, regional GIBS tiles and disk
cache. It is aligned with the receiver's WGS84 east/north coordinates and rotates
with the aircraft scene. A selected sample gains a gold vertical guide to its
horizontal ground position. The map stays faint so trails and altitude cues are
readable. The ground map does not change reception, time windows or filters.

The base is a **flat reference map**. Relief shading in the imagery is not a 3D
terrain mesh, buildings or a measured obstruction survey. Aircraft positions and
height expansion retain the existing 3D geometry and labels. Imagery is rendered
on one background worker and uploaded once per patch/detail change; camera
rotation reuses the same texture. No image downloads or geographic reprojection
run on the touchscreen drawing thread. Missing regional tiles fall back to the
bundled world image. The renderer keeps at most two 512-pixel ground patches.

3D Distance shows received-position dots without connecting lines or a line toggle. Ground rulers, range rings and aircraft selection remain available. Pressing the plot immediately enters preview quality, before a swipe threshold is crossed; a tap still selects using the last completed picking geometry.

After the first web history download, a reference-keyed delta request sends only an overlapping 30-second tail plus current metadata. The browser merges it into its RAM history, preserving aircraft IDs, late observations, window expiry and receiver breaks. Changing to a larger time window or moving the antenna requires a new full snapshot. Sampled histories above the display budget refresh at most every 30 seconds. Rotation itself makes no history request.

Five-second reception samples are ingested into an in-memory SQLite working database. The on-card database is loaded once at startup. New/changed rows, footprint bookkeeping and pruning are committed incrementally every five minutes; the full database is not recopied for each save. Flight JSONL records are RAM-buffered on the same cadence, and traffic-trail persistence also uses five minutes. Live short windows, statistics, log tails and log downloads include the unsaved RAM data. A normal shutdown flushes pending data; abrupt power loss may discard the last five minutes. Receiver lifecycle/configuration logs can still write when settings or hardware change.

The native app suppresses covered Home instruments and waterfall FFT work while ADS-B is full screen, and requests 60 FPS during dome touch/zoom interaction. Preview begins at pointer-down, not after crossing a movement threshold. Picking stays in numeric arrays and is vectorized on demand; it does not rebuild hundreds of thousands of Python hit tuples each frame. Inactive history windows stop rebuilding after 12 seconds without a reader, and bulk WGS84 projection uses NumPy.
