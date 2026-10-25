# Local ADS-B aircraft tracking

The VHF/UHF decoder section uses **wiedehopf/readsb** to decode local 1090 MHz
ADS-B/Mode S. The default **Airspace** interface uses the application's GLOBE
imagery, orthographic camera and HD tile cache on both touchscreen and browser.
The touchscreen uses the existing OpenGL renderer; the browser uses a WebGL
counterpart with the same sphere axes, camera constants, NASA Blue Marble
textures, Natural Earth country rings and Python tile selection/cache. No
aggregator feeding is configured. The optional tar1090 view remains at `/map/`.

## Install

Install the application normally, then run:

```sh
sudo ./scripts/install-adsb.sh
```

The CM5 application installer also accepts `--adsb`:

```sh
sudo ./scripts/install.sh --cm5-existing-display --adsb
```

The package is installed under `/opt/ituner-sdr/decoders/adsb/`, with pinned
readsb/tar1090 source revisions and a local aircraft database. Source checkouts
are retained under `/usr/local/src/ituner-adsb/`; installed revisions are recorded
in `versions.txt`. The database's upstream replaces commits periodically; retain
the installed source checkout when reproducing this version.

The app owns the decoder process and the web server; it must be running to use
the map. Existing installations retain the decoder binaries across app updates.
Optional environment variables are `ITUNER_READSB_BIN`, `ITUNER_ADSB_MAP`,
`ITUNER_ADSB_BIND` (default `0.0.0.0`) and `ITUNER_ADSB_PORT` (default `8090`).
The local web controls require a same-origin page token, matching the existing
LAN decoder control pattern. Use this on the trusted receiver LAN.

## Simultaneous 978 UAT

Run `sudo ./scripts/install-uat.sh` to add the pinned FlightAware dump978-fa
and skyaware978 binaries. A small pinned-source correction makes SkyAware
export geometric altitude from its GNSS value rather than its barometric value.
The app supervises both programs and connects them
only over an ephemeral loopback TCP port; there are no external feeds.

In Settings → Receiver & dongles, select **978 UAT**, assign the second RTL-SDR,
then Start. Both the native touchscreen and browser show independent band
status, assignment and Start/Stop controls. Auto uses a spare receiver and never
takes the 1090 dongle or another decoder's lease. A unique USB serial is required
for the SoapySDR driver; duplicate dongles can be renamed under Manage dongles.
Assignments and enabled state survive restart in `uat-settings.json`.

The decoder tunes 978 MHz at 2.083333 Msps using the tuner's maximum manual gain
(49.6 dB on R820T). **Listening** means the process is running with fresh JSON
but no recently decoded aircraft packets; **Receiving** requires new UAT packets.
Disconnected dongles, occupied receivers and decoder failures have separate
statuses. Losing UAT does not stop the 1090 receiver. Settings → Logs includes
UAT diagnostics (`uat.txt`), and shared flight logs identify each observation's
band and dongle.

Both bands share the map, 24-hour trails and saved reception geometry. Aircraft
heard on both frequencies appear once, using the freshest valid position and
its matching source/RSSI. UAT TIS-B relayed positions can appear on the map but
are excluded from the antenna reception dome and footprint, since their aircraft
locations do not describe the RF path from the ground transmitter.

The optional upstream `/map/` still shows the 1090 readsb feed; use the default
Airspace view for combined traffic. This integration displays UAT aircraft and
TIS-B traffic; a FIS-B weather-product viewer is not included.

## Custom CM5 carrier USB power

**Only for this iTuner custom CM5 carrier:** the USB2 and USB3 sockets have
complementary power selection. GPIO42 **low** enables the USB3 socket; GPIO42
high removes power from that socket. USB3 selection removes power from the USB2
socket. This is a carrier wiring property, not a generic CM5 setting.

The following explicit board-specific installer saves a boot configuration
backup, adds `gpio=42=op,dl` under `[cm5]`, and installs a oneshot service to
reassert that level after the USB controllers have initialized:

```sh
sudo ./scripts/enable-cm5-usb3.sh
```

Verified live on 2026-10-15: lowering GPIO42 enumerated USB `0bda:2838`, Nooelec
NESDR SMArt v5, serial `78941732`, R820T tuner, at USB path `1-1`. An RTL-SDR uses
USB2 signalling even when inserted in a powered USB3 socket, so enumeration on
a USB2 root hub is expected. Display, touch and audio settings are preserved.

To undo this power selection, disable `ituner-cm5-usb3.service`, remove the
`BEGIN/END ITUNER CM5 USB3` block from boot config, and restore the previous
GPIO42 alternate function (`sudo pinctrl set 42 a2`) or reboot. Disconnect the
SDR before changing the socket's power supply.

## Use

Open **DECODE → VHF/UHF DECODERS → ADS-B**. Choose **USB DONGLES** to assign a
specific dongle, or use **AUTO** to try available RTL-SDRs in turn. **START** and
**STOP** claim and release the dongle. The touchscreen Start/Stop control is at
the top of the right-hand rail and remains accessible in Map, USB, Traffic and
Logs. Opening the workspace or assigning a dongle does not start reception.
Other decoders cannot use the same tuner
concurrently. Busy devices are skipped in Auto mode. The selection and enabled
state are saved and restored when the application starts.

A unique dongle serial keeps the assignment stable across USB ordering changes.
Multiple dongles with identical factory serials are shown separately by slot;
a changed USB inventory requires reselecting the slot to prevent using the wrong
device. Programming unique EEPROM serials is optional and is never done by the
application. The receiver retries after disconnects and rejects stale positions.

Drag the map to pan, use Zoom +/−, and select an aircraft for callsign, ICAO
address, altitude, ground speed, heading and vertical rate. **FOLLOW** keeps the
selected aircraft centered as fresh positions arrive. Dragging cancels follow;
loss of position holds the camera at the last position and shows a waiting
state. **FIT ALL** (Center in the browser) fits current positioned traffic. The map starts over Romania as a display default; this does not set
an antenna location or create aircraft. Aircraft lacking a fresh position can
be decoded/logged without a map marker.

Tracking maps support digital zoom up to 12,000×, including the touchscreen
buttons and browser buttons, wheel and pinch gestures. Zoom continues beyond
the available satellite-image detail: cached imagery is enlarged while aircraft
and trail coordinates remain precisely positioned. The browser scale bar switches
to metres for close views. A manual zoom stays selected when a new aircraft arrives.

The CM5 touchscreen uses a native full-screen Airspace dashboard, styled like
its browser counterpart: 1090/978 receiver cards, map telemetry, floating touch
controls, an aircraft instrument card, sortable contacts and dedicated Logs /
Receiver views. Tap a map icon or contact to inspect it, then Follow or Locate;
Clear removes the selection. Labels can be toggled, and overlapping labels are
suppressed. Fit Traffic fits the selected viewing window, including saved
endpoints in History. Grey endpoints remain historical and cannot initiate Follow.
On restart, an enabled ADS-B receiver reopens Airspace unless the Meteor
workspace is active.

Open `http://cm5.local:8090/` on the LAN for Airspace. Its traffic list supports
callsign/ICAO search and sorting by recency, altitude or callsign. Selected targets
use gold, lower-altitude targets cyan and cruise-altitude targets blue. Satellite,
satellite + borders, and borders views are available. The browser also offers
label toggling, a nautical-mile scale and keyboard shortcuts (`+`, `−`, `F` for
follow, `L` for logs, Escape to dismiss drawers).

**Logs** opens Flights, Receiver and Diagnostics directly in both interfaces.
The browser provides a Download link for the selected log; no SSH is needed.
The viewer displays the latest 160 entries, including recent rotated files.
Touchscreen times are labelled UTC; browser flight/event times use the browser's
local timezone. New readsb diagnostic timestamps use UTC.

**Settings → Radio / User** on touchscreen, or `/settings` in the browser, edits
the shared antenna coordinates, optional callsign, height and GPS preferences.
The browser Receiver panel links to it. Range rings (50/100/200 NM), local
decoding and the reception dome use this position. No site is inferred from the
map's initial view. See [shared location and GPS behavior](radio-user-information.md).

Both interfaces open in **Live** with five-minute trails. **Since opened** shows
newly received samples from the current visit; **Start fresh** resets only that
viewing window. **History** defaults to 24 hours and offers Off, 5/15/30 minutes
and 1/3/6/12/24 hours. Optional Past trails adds a faint backdrop. Logging and
coverage collection continue in every view. See [traffic windows, freshness and
new-arrival counters](adsb-traffic-views.md).

The shared history keeps recent positions about four seconds
apart; positions older than 30 minutes are thinned to about one per minute,
preserving endpoints around reception gaps. Tracks expire after 24 hours and
are bounded to 1,024 aircraft, 2,048 positions per aircraft and 65,536 positions
in total; the least recently updated tracks are removed first if a limit is
reached. Gaps longer than two minutes are drawn as separate segments.

The compressed `trails.json.gz` checkpoint is written atomically once per minute
and at normal shutdown, so trails survive an application restart. Existing
recent flight logs seed history on first upgrade; positions that were already
discarded by the previous 30-minute history cannot be recovered. Aircraft which
disappear are removed from Live while their retained trail remains available in
History or the optional backdrop.

The central **Listening for aircraft** notice is shown only during the first
five seconds after the decoder starts, and is hidden sooner if a position is
received. The native footer and browser status line show the ages of the last
received message and last usable position separately. Message totals include
earlier packets and messages without coordinates; altitude, callsign and speed
reports cannot extend a map trail without a fresh latitude/longitude report.
The browser's Updated clock indicates a successful state refresh, not RF traffic.

The 1090 ES and 978 UAT band contract is defined in `adsb_traffic.py`. The 978 UAT
slot is explicitly **NOT INSTALLED**, with no fabricated targets, weather or
working controls. Simultaneous reception will require a second dongle, a UAT
decoder and the corresponding source adapter. A single RTL-SDR cannot receive
1090 MHz and 978 MHz simultaneously.

Bundled imagery and already cached tiles work offline. New HD imagery requires
internet access. Aircraft tracking requires valid position messages; USB
presence and message counts alone do not guarantee a positioned target.

## Logs and storage

The user's data directory is `~/.local/share/ituner-sdr/adsb/` (honours
`XDG_DATA_HOME`):

- `flights.jsonl`: fresh aircraft observations every five seconds with timestamp
  and assigned device identity. Rotates at 10 MiB with six backups (70 MiB max).
- `receiver.jsonl`: assignment, start/stop, release and error events. Rotates at
  2 MiB with three backups (8 MiB max).
- `readsb.txt`: current receiver diagnostics, truncated/reused on restart and
  capped at approximately 2 MiB while running.
- `settings.json`: selected dongle and desired enabled state.

Live JSON and temporary map data are kept under `$XDG_RUNTIME_DIR` in RAM,
falling back to the OS temporary directory. Stopping releases USB and clears the
current aircraft list; flight logs are retained. The browser download returns
the current JSONL file; rotated logs remain in the data directory.

## CM5 validation, 2026-10-15

- USB power polarity and RTL device enumeration verified on the live carrier.
- readsb compiled on CM5; USB tuner opened and samples processed without drops.
- Receiver tests cover selection persistence, busy-device fallback, unplug,
  stale positions, log generation, web control boundaries and map interaction.
- Touchscreen rendering and tar1090 basemap visually checked on the real CM5.
- An isolated readsb replay with known CPR frames and a known test reference
  location decoded aircraft `40621d` at approximately 52.266 N, 3.939 E and
  38,000 ft. Test aircraft were never inserted into the live receiver/map.
- FM survey found strong peaks near 101.3, 105.3, 94.3 and 98.3 MHz. Short WBFM
  captures at 101.3 and 105.3 MHz produced substantial audio levels.
- Live reception was sparse during initial checks. Subsequent saved observations
  include positioned WZZ9FW and WMT414 traffic, and THY7LA observations without
  position. These real flight logs are visible in the interface.
- 268 receiver, navigation, board and GLOBE tests passed on CM5. JavaScript model
  checks cover projection, follow, signal loss, retained tracks and date-line fit.
- Browser aircraft selection/follow/trails were additionally checked using an
  isolated fixture feed, labelled TEST DATA; it never wrote to production logs.
- All three native log views, the map, traffic list and USB page were rendered
  from the live data on the CM5 and visually inspected.

To add future VHF/UHF tools such as NOAA, extend `VHF_UHF_DECODER_ITEMS` in the
main UI and give the new tool its own receiver manager/workspace. The five
existing KiwiSDR decoder types are listed under `HF_DECODER_ITEMS`.

Upstream: <https://github.com/wiedehopf/readsb>,
<https://github.com/wiedehopf/tar1090>,
<https://github.com/wiedehopf/tar1090-db>.

## Design references

The traffic-focused instrument layout was informed by the Dynon SV-ADSB-472
traffic display and the history/selection controls of tar1090. The interface
does not copy Dynon artwork or imply that unsupported UAT/weather features are
installed.

- https://www.dynonavionics.com/adsb-dual-band-receiver-472.php/1000
- https://github.com/wiedehopf/tar1090

In History and Since opened, aircraft with stale positions remain as grey, selectable icons at retained trail endpoints within the chosen viewing window. Labels and selection details show the position age; they are excluded from live counts and cannot start Follow. They follow the selected trail duration (up to 24 hours), and disappear when trails are off. Live positions replace the historical icon. No position is extrapolated from speed reports. Callsign, heading and speed are saved with new trail points; older history uses the ICAO identifier.

The live map includes passive 1090 ES and 978 UAT readouts with receiver state,
packet count, fresh contact count, and last-heard age. The Receivers button
opens both bands' controls without entering Settings. UAT-origin aircraft carry
an UAT suffix on map labels and a 978 UAT source label in the aircraft list.
UAT's packet total and last-heard timestamp persist in `uat-reception.json`
across restarts and USB disconnects; they do not make old aircraft live again.
The UAT Receiver panel distinguishes saved totals from the current decoder run.

## UAT Weather

Install `sudo scripts/install-fisb.sh` after the UAT decoder. It pins
`rand-projects/fisb-decode` at `c3d3b0473429336b1a98672b2e8b276c24d49765`.
Only its pure Python capture/assembly/product layers are installed, plus its
license. No MongoDB, GDAL, cloud weather, feeders, or extra SDR stream is used.
The installer corrects an upstream assignment error in the north-of-60-degree
radar block split. `adsb_weather_worker.py` reads the existing private dump978
raw port. Its failure/restart does not stop either aircraft decoder.

Open **Weather** on the live map, or `/weather`. The native touchscreen has
Reports, Radar, and Ground stations tabs, with the shared Back/footer controls.
Received METARs, TAFs, PIREPs, winds and text advisories are assembled by the
upstream engine. Regional and CONUS NEXRAD blocks are placed on the same
GLOBE map as the traffic view. Report issue/receive/expiry times are shown.
Cancelled reports are removed. Each radar block retains its own issue/expiry
and geographical footprint. Regional zero (<5 dBZ) has a faint blue tint;
CONUS zero (unavailable) is transparent. Intensity seven (>=55 dBZ) is purple.
Unknown coverage is never filled as clear weather. Weather is delayed and
this is a hobby display.

The runtime `weather-live.json` publishes updates in RAM every five seconds;
`weather-state.json` is checkpointed every 30 seconds and on clean shutdown.
It stores at most 500 unexpired reports, 4,096 unexpired
radar blocks and 64 station records. A worker heartbeat distinguishes a live
connection from saved data. Ground uplinks have separate counters from
ordinary UAT aircraft packets; aircraft reception alone cannot set the
weather/ground-station status to Receiving. Weather collection pauses when
UAT stops or its receiver is used for comparison.

## Multi-receiver comparison

Open **Settings → Receiver comparison** in Airspace, or `/compare` on the web.
Start pauses UAT, remembers whether it should be restored, and runs a separate
copy of the same readsb executable on each connected spare receiver with a unique serial.
The receiver roster is saved at Start; a missing dongle never silently changes
a three-way test into a two-way test. Stop and Start to change the group.
All use `readsb_command()` for identical frequency, automatic gain policy,
sample-rate defaults, CRC policy and JSON cadence. The primary receiver stays
running. Built-in preamps/filters and automatic tuner gain differences remain
part of the hardware's practical performance; actual gain and relative
signal/noise are shown. RSSI is not an absolute sensitivity calibration.

Start also enables the primary 1090 receiver. If USB enumeration is delayed
at boot, the request stays queued using the saved serial assignments and
starts automatically once the receivers appear. The waiting status shows
the primary receiver's USB diagnosis rather than requiring a separate Start
on the main map.

All selected receivers run continuously. Live packet counts update every two seconds
in the browser and every second in the native view. A simultaneous five-minute
window records new valid packets, unique aircraft, positioned aircraft,
observed position updates, maximum range from the shared antenna location,
actual tuner gain and sample drops. Counts begin only after every decoder
output is fresh, subtract earlier lifetime totals, and reset together at
window boundaries. Loss/restart of any receiver marks the partial window
invalid; invalid/partial results are excluded from the comparison chart.

A five-minute line graph shows differential reception rates (new valid
packets per second) for each receiver, using a time-weighted rolling average that grows during startup to
30 seconds. Each new sample updates the curve; interpolating the counter at
the window edge handles irregular sample times without changing weighting.
The vertical scale automatically fits the highest rate in the selected view,
including low traffic below one packet/second, with 20% headroom and rounded
steps to reduce resizing. Old peaks outside the selected range or before Reset
do not hold the scale up. The colored legend shows each
receiver’s current rate; scorecards and saved windows retain total packets.
Choose **5 minutes**, **30 minutes**, **1 hour**, **12 hours**, or **24 hours** for a rolling graph.
Graph history continues across five-minute result boundaries. It is stored
separately in `comparison-rates.json`, with up to 24 hours of measured rates,
30-second checkpoints, and a final checkpoint on a clean shutdown. The latest
hour retains detailed samples; older data uses one-minute averages of those
samples. Outages and reset boundaries remain separate during compaction.
Storage and native drawing stay bounded. Receiver
changes start fresh graph history; interruptions and restarts create gaps.
The longer views fill as actual rate samples accumulate; completed packet
totals are never fabricated into detailed historical curves.
The native touchscreen renders this graph directly with OpenGL primitives;
it does not embed the web page. Historical bars and tables only show the
matching receiver group; two-way results are retained but never relabeled as
three-way results.

**Reset graphs** clears all displayed time ranges, the displayed completed-window
chart/table, and the current five-minute counters while the decoders keep running.
**Start comparison** also starts fresh graphs/counters. Retained measurements,
completed results and CSV exports are preserved; a saved reset timestamp keeps
older records hidden from the fresh view after a restart. New rate averages
build from samples collected after Reset.
Both interfaces briefly confirm **Graphs reset**. The web page fetches a fresh
control token for each action, so Reset continues working in tabs left open
across service restarts. Control errors remain visible until the next successful
action instead of disappearing on the next live-data refresh.

Completed results and chosen serials persist in `comparison.json` (576 windows,
about 48 hours). The browser shows a recent chart/table and provides
`/api/comparison.csv` for all retained results. Closing either interface leaves
the comparison running. Stop & restore UAT releases the extra 1090 processes and
restores its previous UAT enabled state. UAT assignment/start is blocked while
comparison owns that dongle. No receiver packets are fed to an external service.

Validation includes binary DLAC METAR and run-length radar APDUs through the
actual pinned engine, radar placement/row direction and extreme echoes,
report expiry/cancellation, native navigation, simultaneous packet deltas,
five-minute rollover and interrupted-window rejection. Test inputs use isolated
roots and never enter production receiver logs or weather products.
