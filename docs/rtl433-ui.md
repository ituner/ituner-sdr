# RTL433-UI on CM5

Open **http://cm5.local:8093/**. The Sensor observatory at
`http://cm5.local:8092/#ism` also links to the dashboard when installed.
The native sensor screen shows the dashboard address in its footer.
In the web Sensor Observatory, **Open Intelligent Scan** sits above the band
controls and opens port 8093. Press **Start Intelligent Scan** there; the scan
results panel is expanded by default.

This is [dalekunce/rtl433-ui](https://github.com/dalekunce/rtl433-ui), pinned to
`236910d4f0d4cbd687149f27f2d7698b50ee08bf` (package version 0.1.6), with a small
adapter to the existing iTuner VHF hub. The upstream device cards, field plots,
labels, pins, ignored devices, filters, raw stream, MQTT mapping and Home
Assistant discovery remain available.

## Multiple dongles

**Use free dongles** is enabled by default. While Intelligent Scan is running,
newly discovered receivers with unique serials automatically join the sensor
pool, up to six. Separate SoapySDR/rtl_433 processes receive different survey
frequencies simultaneously. Each receiver listens to a different band; the complete band list rotates
across the available receivers. Six receivers cover six bands at any instant.
The receiver chips show each USB serial, actual frequency and status.

Automatic expansion never stops another decoder, even if ownership changes
between discovery and Start. A user-selected Primary USB can still perform an
explicit handoff. Disconnecting a dongle removes that slot; reconnecting a free
receiver lets it rejoin. Handing one sensor dongle to ADS-B leaves other sensor
receivers scanning. Handing off the last active sensor receiver stops scanning.
Turning **Use free dongles** off prevents further automatic additions.

**Hold frequency** freezes all current receiver frequencies. Manual frequency
buttons retune the first active sensor receiver while the other receivers keep
listening. **Stop sensors** (including native Stop) disables the entire pool.
Opening the dashboard never claims hardware. Each observation includes its
receiver slot, unique serial and actual frequency; auxiliary logs live in
`vhf/ism-2/` through `vhf/ism-6/` beside the primary `vhf/ism/` log. They can
also be downloaded through port 8092 `/api/log?mode=ism-2&kind=observations`.
The pool uses the existing broker; other decoders keep their leases.

Only one physical dongle was connected during initial deployment. Parallel
allocation, USB addition/removal, six-way frequency separation and handoff
races are verified with simulated receiver descriptors and real broker tests.

## Receiver controls

- Select **Primary USB** in dashboard **Settings** (or **USB RECEIVER** on
  the touchscreen), then **Start sensors**. Auto prefers an available
  uniquely identified RTL-SDR. A handoff stops the previous decoder and waits
  for it to release the device. With one dongle, sensors and ADS-B run in turn.
- **Stop sensors** releases the sensor receiver. Viewing/restarting the web
  dashboard does not claim hardware or interrupt a receiver.
- **Listen now** controls retune immediately from the main screen. The four
  quick buttons cover 433.92 MHz **US / EU**, 868.3 MHz EU, 915 MHz US and
  315 MHz US. The all-bands selector (touchscreen **MORE BANDS**) adds the
  remaining supported candidates below; there is no profile save/apply step.
  Retuning preserves USB assignment, gain and correction. A stopped receiver
  stays stopped; a running receiver retunes through the existing broker.
- **Intelligent Scan** runs on CM5, with the browser closed. It surveys every
  distinct frequency in the same catalog for at least 60 seconds of actual
  receiver listening per visit. USB setup and app downtime do not count.
  After the first survey, a productive band gets an extra visit after every
  three survey visits. A recent packet-rate score extends its next dwell up
  to 180 seconds; three quiet visits remove that preference. Every band stays
  in the survey rotation, including 915 MHz. This is receive time sharing,
  so a single dongle can miss bursts transmitted while listening elsewhere.
- The scan table shows total decoded packets, distinct sensor identities,
  actual listening time, packets per listening minute and last reception per
  frequency. These are supported decoded messages, not RF energy/noise scores.
  Totals persist across service restarts; restart begins a fresh survey.
- **Hold frequency**, the scan toggle, or a frequency button stops scanning
  and keeps sensor reception on that frequency. **Stop sensors** also releases
  the dongle. A handoff of the last active sensor receiver or manual retune from another
  interface cancels scanning. The scanner never reclaims another decoder's USB.
- Explicitly enabled scanning resumes after a dashboard restart only if the
  sensor receiver is still enabled. Scanning does not claim USB just because
  someone opens the page. 868.95 MHz uses 1.2 MS/s for M-Bus C/T; the other higher bands use 1 MS/s
  and lower bands use 250 kS/s,
  following [rtl_433 input guidance](https://github.com/merbanan/rtl_433/blob/master/docs/STARTING.md).
- An explicitly started sensor session resumes after a CM5/app restart while
  RTL433-UI is installed. Stopping it cancels that saved enabled state. It also
  reopens the native sensor view after restart.
- The receiver configuration editor supports `frequency`, `gain` (0–49.6 dB)
  and `ppm` (−150 to 150). USB assignment is managed above. Other rtl_433 config
  directives are rejected rather than bypassing the shared receiver manager.

### Listening bands and discovery

The shared catalog is `UI/rtl433_profiles.json`. Region labels describe typical
products; 433.92 MHz reception is shared by US and EU devices. These are discrete
listening centers, not continuous coverage of an entire regional allocation.

| MHz | Typical candidates |
| --- | --- |
| 433.92 | US / EU weather, TPMS, sensors and remotes |
| 868.3 | EU weather, energy sensors and M-Bus S |
| 868.95 | EU M-Bus C/T, Netatmo and Delta Dore |
| 869.67 | EU Cavius alarms |
| 315 | US TPMS, remotes and sensors |
| 345 | US Honeywell / 2GIG security sensors |
| 319.5 | US Interlogix / GE security sensors |
| 310, 390 | US Security+ remotes |
| 310.558 | US X10 security sensors |
| 303.875 | US Regency ceiling-fan remotes |
| 433.42 | EU Funkbus remotes |
| 433.55 | Efergy optical energy sensors |
| 433.71 | Kedsum temperature sensors |
| 434.052 | InFactory and grill thermometers |
| 912.6 | US ERT interval-data utility meters |
| 915 | US weather, soil sensors and meters |
| 917.2 | US Sharp SPC775 weather sensors |

The centers and sample rates follow the [rtl_433 device sources](https://github.com/merbanan/rtl_433/tree/master/src/devices).
Actual support depends on the installed rtl_433 version and enabled decoders.
Custom frequency entry remains available. Frequency-hopping products may need
other channels and longer observation; 915 MHz alone does not cover 902–928 MHz.

**Intelligent Scan** answers “where am I successfully decoding supported
sensors?” using decoded packet rate and distinct device identities. It keeps
exploring quiet bands and spends more time on productive ones. A zero packet
count means no successful decode during sampled listening, not an empty band.
For “where is unknown RF worth investigating?”, open **Spectrum Survey →
Signals → Investigate** to inspect measured activity and burst timing. That
workflow does not automatically identify arbitrary protocols. Upstream rtl_433
also offers [unknown-signal capture and pulse analysis](https://github.com/merbanan/rtl_433/blob/master/docs/ANALYZE.md)
(`-S unknown` / `-A`); these are not enabled by this dashboard's managed settings.

The dashboard never starts its own rtl_433 process. The existing iTuner sensor
session owns the decoder, dongle, retries, SoapySDR configuration and JSONL logs.
Incoming sensor events are delivered once per observation with their real time.
Radio messages without a supported sensor payload do not create fake devices.

## All-decoder mini SDR

Below the scan table, **Decoder activity · mini SDR** shows the shared 0–1.5 GHz
waterfall and central decoder counts, including HF and ADS-B. The same display
is below the Spectrum Survey results. See [the shared activity model](decoder-activity.md).

## Installation and service

After `scripts/install-vhf.sh`, run:

```sh
sudo scripts/install-rtl433-ui.sh
```

The installer uses Debian Node.js/npm and Mosquitto, installs the pinned upstream
source with its npm lockfile (`npm ci --ignore-scripts`), applies the adapter and
starts `ituner-rtl433-ui.service` on port 8093. It updates the native/browser links
and restarts the app. Previous dashboard directories and UI files are backed up.

Mosquitto is used for optional field publishing and Home Assistant discovery.
The default broker is local-only at `127.0.0.1:1883`; the sensor feed itself
arrives through the VHF hub, so it does not depend on MQTT reception.

- Application: `/opt/ituner-sdr/decoders/rtl433-ui`
- Settings, mappings, bounded device checkpoint: `/var/lib/ituner-rtl433-ui`
- Raw sensor logs: `/home/ituner/.local/share/ituner-sdr/vhf/ism/observations.jsonl`
- RF/decoder diagnostics: `/home/ituner/.local/share/ituner-sdr/vhf/ism/receiver.log`
- Dashboard service log: `journalctl -u ituner-rtl433-ui.service`
- Scan checkpoint and per-visit results:
  `/var/lib/ituner-rtl433-ui/intelligent-scan.json` and `intelligent-scan.jsonl`
  (rotated at 1 MiB, one backup). Sensor JSONL observations also include their
  actual receiving frequency, even while a retune is pending.

The device checkpoint retains up to 512 device cards with their real last-seen
ages. In-card sparklines follow updates in the current browser session; full
sensor observations stay in the existing rotated JSONL logs.

## Verification

`node --test tests/test_rtl433_ui.cjs tests/test_rtl433_scanner.cjs` exercises adaptive scan fairness, real listening time, 915 MHz visits, persistence, manual hold, broker handoff, no automatic
hardware takeover on page load/restart, external handoff, multi-device settings,
event deduplication, stale-event rejection and bounded receiver configuration.
The Python VHF suite also checks explicit sensor resumption and Stop persistence.
