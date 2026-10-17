# WeeWX + Belchertown

Separate weather function: **http://cm5.local:8094/**. Source selection: **/receiver**.

Install on CM5 with `sudo scripts/install-weather.sh`. WeeWX 5.5.2 is isolated in `/opt/ituner-sdr/weather/venv`; Belchertown 3.0.0 is pinned with its release SHA256. The installer configures the real driver before starting services. It disables simulator, station registration, external uploads, forecasts, earthquake content and browser MQTT. User data survives reinstall.

The weather feed reads existing sensor observations from the shared VHF hub; it never opens USB or changes receiver assignments. Leave RTL433-UI Sensors / Intelligent Scan receiving. All six available sensor slots feed discovery. Weather-compatible models and fields are accepted; TPMS, remotes, meters and security devices are excluded. Automatic selection locks to one identity (model, id, channel). Choose a different discovered station on the source page to change it.

WeeWX archives genuine packets every five minutes. Before the first real archive record, a waiting dashboard is shown; the stock Belchertown generators are deferred because they require archive history. No generated measurements or timestamps are inserted to work around an empty database. The page automatically opens Belchertown when its first report is ready. Source freshness is shown independently of archived history.

Temperature, humidity, wind, UV and solar radiation are mapped with validated units/ranges. Missing observations stay unavailable. Pressure corrections and rain totals require a verified station profile (and actual station altitude); they are intentionally not inferred from unknown hardware. Bucharest city coordinates are approximate. Configure the actual coordinates/altitude in `weewx.conf` before enabling altitude-dependent derivations.

Services: `ituner-weather-web.service` (8094), `ituner-weewx.service`. Both run as ituner with device access closed. Logs: `journalctl -u ituner-weewx -u ituner-weather-web`. Station configuration, source selection and SQLite archive: `/var/lib/ituner-weather/`; generated Belchertown files: `public_html/`. These private files are outside the HTTP document root.

Upstream: https://weewx.com/ and https://github.com/poblabs/weewx-belchertown.

Validation: weather-field tests cover TPMS rejection, bounds, unit conversion and multi-receiver deduplication. An isolated CM5 archive under `/home/ituner/vhf-build/weather-report-test` was populated with a clearly separate test fixture; Belchertown generated all 11 report files successfully. This test directory is outside the production document root. The production archive remained empty while waiting for a real station.
