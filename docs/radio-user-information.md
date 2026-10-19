# Shared Radio / User Information

Open **Settings → Radio / User** on the touchscreen or `/settings` on either
Airspace (8090) or Signal Observatory (8092). These edit one profile,
`~/.local/share/ituner-sdr/radio-user.json` (mode 0600).

Identity includes station name, optional operator/callsign, site label,
timezone, and the URL identifying the local KiwiSDR. Location includes manual
latitude/longitude, ground elevation above sea level, antenna mounting height
above ground, and optional antenna height above WGS84 ellipsoid. These three
height quantities are distinct. Blank heights remain unknown. The grid locator
is calculated from effective coordinates.

ADS-B, its reception dome, VHF/UHF maps, satellite pass prediction/Doppler,
GLOBE/home distances and local HF identity consume the same profile. Both
existing decoder location APIs forward manual edits into it. Remote KiwiSDR,
OpenWebRX and FM-DX coordinates retain their source-specific values. The local
Kiwi URL associates the client application with its antenna; it does not write
the Kiwi device's admin configuration or replace its internal GPS settings.

The WeeWX driver reads `/api/station` locally every ten seconds and updates
station coordinates, elevation when known, label and timezone for subsequent
reports. Weather packet contents are never manufactured. Old archive records
are retained. Receiver-site metadata is not the location of a remote RF weather
sensor unless that sensor is physically colocated.

A saved callsign does not enable any upload or transmitter. Local WSPR reporting
uses the shared grid/callsign; identity changes pause existing local reporting
and require renewed confirmation. Remote receiver reporting profiles remain
separate. Hell report forms prefill the local identity only for the local Kiwi.

## Optional USB GPS / GNSS

Run `sudo scripts/install-station-info.sh` after installing the app. Debian gpsd
handles supported USB devices through udev. No arbitrary serial port or RTL-SDR
is opened by the app. Its read-only JSON WATCH client connects to local gpsd on
127.0.0.1:2947. Without hardware the profile remains usable manually and shows
"waiting for receiver / fix".

Enable monitoring and automatic location in Radio/User settings. Fresh TPV
2D/3D fixes with finite valid coordinates and timestamps no older than 15 seconds
are accepted. Reported horizontal error over 100 m is rejected. The RF antenna/GPS antenna height offset is configurable (0 m assumes they
are colocated). A 2D fix never invents altitude; 3D uses explicit `altHAE` and `altMSL` fields separately. Device,
fix age, accuracy and satellite status are visible. No fix, unplugging or loss
of gpsd retains the last known position and marks it stale. Selecting manual
mode immediately restores the saved manual coordinates.

Consumers receive position changes after 10 m cumulative motion and altitude
changes after 3 m. GPS observations persist at most once per 30 seconds; display
status updates independently. ADS-B maps move immediately with published fixes;
readsb's CPR reference restarts only after 25 km travel, avoiding repeated RF
interruptions from GPS jitter. Manual site edits retain normal receiver refresh
behavior.

Reception logs now include the receiver's coordinates. The dome includes only
observations taken within 100 m of the current receiving site. Other sites stay
stored and become visible again when returning there. Legacy observations are
anchored once to the saved pre-migration antenna location; GPS movement cannot
reinterpret them as observations from a new site.

No GPS fixes are simulated in the production profile. Tests use isolated files
and an isolated gpsd protocol fixture; a physical GNSS fix remains unverified
until a supported receiver is connected.
