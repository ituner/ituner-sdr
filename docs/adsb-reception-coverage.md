# ADS-B reception coverage

Open **ADS-B → Reception dome**, beside **Live** in the viewing row, on the
touchscreen or Airspace web page (`http://cm5.local:8090/#coverage`). The black view uses the same stored
observations on both screens, without claiming an SDR or starting ADS-B.

- **Sky cells** projects received directions onto an angular hemisphere, in
  4° azimuth × 2° elevation cells. Blue means received; grey means unknown.
- **Sky trails** shows received positions projected onto that hemisphere.
- **True 3D distance** preserves east/north/up distances, with 5 km horizontal
  rings and no vertical exaggeration. Drag to rotate; use sliders (web) or
  rotation/tilt buttons (touch). Tap a point to inspect it; on touch this also
  filters its aircraft. Reset restores all aircraft.
- **RX radius** is the maximum observed horizontal distance from the configured
  antenna. Diameter is twice that radius: a reference circle, not a claim of
  complete circular coverage. Maximum slant range includes vertical distance.
- **Maximum altitude** is the highest received aircraft altitude in the retained
  history, in feet and kilometres. Its label near the zenith is a statistic;
  that aircraft was not necessarily overhead. GNSS altitude is above the WGS84
  ellipsoid; barometric fallback is approximate. It is not height above antenna.

Set antenna latitude/longitude in **Settings → Radio / User**, shared by both
interfaces and local applications. The advanced antenna height used by Coverage
is **metres above WGS84 ellipsoid**, not height above street/roof.
Leave blank if unknown; geometry explicitly assumes 0 m. The address pin is an
approximation until the antenna itself is surveyed. Height updates are shared
with touch through the station profile, independently of receiver tuning.

`coverage.sqlite3` in the ADS-B data directory stores direct ADS-B positions
independently of the 24-hour traffic trails. Retention is up to 90 days and
250,000 positions, whichever limit is reached first. Startup imports retained
`flights.jsonl*` logs idempotently. New entries follow the normal five-second
flight logging cadence. SQLite reuses pages as older positions expire. Sky-cell
statistics and extrema use the full retained history. To bound UI payloads, dot
views are thinned above 20,000 positions, preserving maximum altitude/range.

The `/api/coverage` endpoint reads a cached snapshot built on the receiver
worker. The native renderer builds cached 3D geometry off the GL/touch thread, then
rotates vector arrays and submits batched OpenGL triangles and lines. No dome
bitmap is repainted or uploaded while dragging. Readouts sit beside the larger
dome as plain text. The web view caches its grid and trigonometry, avoids
resizing an unchanged canvas, and uses lower pixel density during a drag before
restoring full sharpness on release. Unknown sky uses a faint wire shell;
received cell boundaries and counts keep their original resolution. History
remains visible with ADS-B paused; the receiver state is shown separately.

Positions must be directly received ADS-B, with finite coordinates, a numeric
altitude and position age ≤10 seconds. Duplicates are removed. WGS84 ECEF→ENU
accounts for Earth curvature. GNSS altitude is preferred; a barometric fallback
uses open dots. RSSI is readsb's recent aircraft average in dBFS, not calibrated
antenna gain. Short trails connect observations no more than 15 seconds apart,
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
