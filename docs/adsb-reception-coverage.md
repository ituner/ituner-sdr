# ADS-B reception coverage

Open **ADS-B → Coverage** on the touchscreen, or **Coverage** in the Airspace
web page (`http://cm5.local:8090/#coverage`). The black view uses the same stored
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
worker. The native renderer builds its image off the GL/touch thread. History
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
