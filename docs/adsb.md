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

**Receiver** in the browser includes antenna latitude/longitude settings. Saving
a site restarts the assigned decoder with that reference position; range rings
(50/100/200 NM) use this saved site. Clearing the site removes the reference.
No site is inferred from the map's initial view. Native USB controls show site
status and direct the user to the browser for editing it.

Trails default to **24 hours**. Both interfaces offer Off, 5/15/30 minutes and
1/3/6/12/24 hours. The shared history keeps recent positions about four seconds
apart; positions older than 30 minutes are thinned to about one per minute,
preserving endpoints around reception gaps. Tracks expire after 24 hours and
are bounded to 1,024 aircraft, 2,048 positions per aircraft and 65,536 positions
in total; the least recently updated tracks are removed first if a limit is
reached. Gaps longer than two minutes are drawn as separate segments.

The compressed `trails.json.gz` checkpoint is written atomically once per minute
and at normal shutdown, so trails survive an application restart. Existing
recent flight logs seed history on first upgrade; positions that were already
discarded by the previous 30-minute history cannot be recovered. Aircraft which
disappear are removed from live traffic while their retained trail stays visible.

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

Aircraft with stale positions remain as grey, selectable icons at their saved trail endpoints. Labels and selection details show the position age; they are excluded from live counts and cannot start Follow. They follow the selected trail duration (up to 24 hours), and disappear when trails are off. Live positions replace the historical icon. No position is extrapolated from speed reports. Callsign, heading and speed are saved with new trail points; older history uses the ICAO identifier.
