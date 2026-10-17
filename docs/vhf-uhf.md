# Signal Observatory: VHF/UHF decoders

Open **Decoders → VHF/UHF** on the touchscreen, or [Signal Observatory](http://cm5.local:8092/) in a browser. ADS-B remains in [Airspace](http://cm5.local:8090/); both pages link to each other.

## Included engines

| Workspace | Engine | Reception and output |
| --- | --- | --- |
| AIS / Maritime | [AIS-catcher](https://github.com/jvde-github/AIS-catcher) | AIS A + B, vessel identities, positions and reports; shared GLOBE map plus upstream viewer at port 8101 while running |
| APRS / Packet radio | [Dire Wolf](https://github.com/wb2osz/direwolf) | 1200 baud RF AX.25; positions, station comments, weather and packets; Europe, North America and ISS presets |
| rtl_433 / Sensors | [rtl_433](https://github.com/merbanan/rtl_433) | Protocol detection and sensor readings; 433.92, 868.3, 315 and 915 MHz presets |
| Meteor-M / Earth observation | [SatDump](https://github.com/SatDump/SatDump) | M2-4 LRPT, 137.1 MHz preferred preset, alternate profiles; images, dataset metadata and validated CADU frames |
| CubeSat / Orbital telemetry | [gr-satellites](https://github.com/daniestevez/gr-satellites) | Installed SatYAML satellite/downlink catalog; protocol-specific telemetry, raw frame hex and timestamped KISS files |
| Radiosonde / Upper atmosphere | [RS1729](https://github.com/rs1729/RS) | RS41 and DFM weather-balloon positions and telemetry on a chosen local 400–406 MHz channel |

Package choices prioritize maintained protocol implementations, ARM64 availability and resource use. AIS-catcher includes a mature dedicated web viewer. The common observatory supplies the interface for the other command-line engines, using the application's existing NASA Blue Marble / GIBS GLOBE imagery, country borders and tile cache.

### Listen

1. Choose the decoder and reception profile. Frequencies are starting points, not a promise of local traffic or an active satellite transmitter.
2. Select **Auto** or a particular USB receiver. Open **Frequency** on the touchscreen for a numeric keypad, or edit MHz, gain and ppm in the browser Receiver panel.
3. Press **Start**. Auto prefers an unused dongle. If all are occupied, starting a mode asks the previous application decoder to stop, waits for it to release USB, then claims the receiver. No external processes are killed.
4. Use Map, Data/Observations, Products and Logs. Select a positioned target to follow it. Maps support pan, zoom and trails.
5. Press **Stop** to release the receiver. For Meteor, allow image processing to finish before another mode claims it.

Each receiver supports one tuning/decoder session at a time; AIS A and B are a single simultaneous dual-channel exception within one capture. Multiple dongles with distinct USB serials can run independent sessions. Serial-based assignment survives USB index changes. SoapyRTLSDR identifies hardware by serial: receivers with duplicate or missing serials cannot be safely assigned through this driver and must first be given distinct serials outside the application. They are never silently substituted.

Start in the browser uses saved settings; press **Apply settings** after changing its form. The touchscreen profile/frequency/USB controls apply changes directly. Changing a running configuration restarts that session. New VHF sessions start stopped after an app restart, except an explicitly enabled continuous Meteor receiver; existing ADS-B enable/disable persistence is retained.

### Satellites

Set the shared antenna location in **Settings → Radio / User** on touchscreen or `/settings` in the browser; the old Station location button opens the same profile. **Update orbital data** retrieves a satellite's public TLE from CelesTrak and caches it locally. Your receiver coordinates stay on CM5. Local predictions show the next three passes, azimuth, elevation and range. Automatic receive Doppler correction uses range velocity and works through the Soapy input stream; orbital elements over 14 days old disable correction and are marked stale. Airspace, satellite predictions and local decoder maps use the same effective position, including automatic GPS updates when enabled. See [shared station settings](radio-user-information.md).

The CubeSat list comes from the installed engine, filtered to RTL tuning limits and downlinks up to 19.2 kbaud for the 48 ksample/s frontend. Catalog support does not imply current satellite activity. Select the appropriate downlink/profile and verify current mission status and frequency with its operator. The engine attempts its satellite-specific demodulators and parses supported telemetry; unknown telemetry is retained as raw frames.

Single-capture Meteor mode receives a maximum 15 minute pass, then finishes processing imagery. Continuous mode stays enabled overnight: it finalizes a received pass after 90 seconds without new frames (or 20 minutes of received data) and resumes listening. Waiting sessions stay open, with a 24 hour safety renewal. The preferred profile targets M2-4 at 137.1 MHz: the [SatDump-hosted reception status report](https://ub8qbd.satdump.org/wx_report_new.html), checked on 16 October 2026, lists this downlink as working and M2-3 LRPT as off. This is an observer report, not a live transmission guarantee; verify the current frequency and symbol rate before a long capture. The 137.9 MHz Auto 72k profile remains an alternate; it identifies M2-3/M2-4 from telemetry and follows the visible satellite for Doppler correction. Continuous reception resumes after an application restart; Stop or a receiver handoff cancels it. Stop also requests final processing. The interface distinguishes RF sampling, demodulator/Viterbi/deframer lock, validated CADU frames and completed image products. A zero-frame/no-lock session is not a successful image reception. CubeSat captures have a 30 minute limit. Live satellite or radiosonde validation requires a suitable antenna, local visibility and an actual transmission.

### Logs and captures

Data root: `~/.local/share/ituner-sdr/vhf/` for the service user (`/home/ituner`). Each mode has:

- `observations.jsonl`: decoded observations, UTC Unix timestamps and original protocol fields; 4 MiB × 5 files.
- `receiver.log`: startup, RF/decoder diagnostics and lifecycle events; 2 MiB × 3 files.
- `settings.json`: saved profile, dongle, frequency, gain, ppm and Doppler preference.
- `sessions/<UTC>/`: capture summary and engine products; KISS/telemetry for CubeSats, image/data products for Meteor. Satellite summaries include RF power/SNR ranges and whether Viterbi/frame lock was ever seen, including captures with zero frames. The browser Products tab opens/downloads these files.

Receiver log and decoded records are visible on the touchscreen and browser. Browser Logs provides downloads of the current receiver and observation files. Satellite sessions additionally save an RF spectrum/power, sample count, decoder statistics and orbital snapshot once per minute in `receiver.log`; summary extrema are updated each fresh measurement. Logs rotate independently of capture files. Capture cleanup retains at most 20 completed sessions per mode and targets a 512 MiB per-mode budget, preserving an active session until it finishes. High-rate IQ is streamed, not recorded to the SD card. Raw frames and imagery are retained. Full-rate RF status/spectra use temporary runtime files; minute diagnostics and decoded data are stored persistently.

The receiver is receive-only. APRS digipeating, beacons, transmit audio and APRS-IS gating are not configured. AIS sharing and gr-satellites online telemetry submission are not enabled.

## Installation

After installing the base application on Debian/Raspberry Pi OS ARM64:

```sh
sudo bash scripts/install-vhf.sh
sudo systemctl restart ituner-sdr.service
```

Or include `--vhf` in the app-only installer. Install ADS-B with its existing `--adsb` option when desired. `install-vhf.sh` uses Debian packages for SoapySDR, Dire Wolf, rtl_433, GNU Radio, gr-satellites and SatDump. AIS-catcher and RS1729 are built from pinned commits, including AIS-catcher's upstream web viewer. Engine entry points live in `/opt/ituner-sdr/decoders/vhf/bin`; version records and source licenses are alongside them. Source checkouts are retained for rebuilding.

The application owns child processes and exclusive USB leases. `soapy_rx.py` supplies filtered 48 ksample/s complex IQ to CubeSat decoding, 48 kHz mono FM audio to Dire Wolf, IQ to the sonde decoders, and a loopback RTL-TCP bridge to SatDump at 1.024 Msamples/s. AIS-catcher and rtl_433 use their built-in SoapySDR inputs. readsb retains its native RTL driver and participates in the same ownership broker. This does not change the verified CM5 USB power selection.

The observatory listens on LAN port 8092, Airspace on 8090 and the upstream AIS viewer on 8101 while AIS runs. Browser state changes use a per-process token and same-origin checks. SatDump status and input connections bind to loopback. No public receiver service or internet feed is created.

## Verification

```sh
cd UI
python3 -m unittest test_vhf test_adsb test_ui_navigation test_cm5_menu_status test_board_v1 test_globe_gpu test_globe_tiles test_globe_motion
```

The hardware check on CM5 uses the Nooelec NESDR SMArt v5, serial 78941732. A real RF APRS packet from YO3KXL-10 was decoded at 144.800 MHz, including its Bucharest position. AIS, rtl_433, Meteor, CubeSat and sonde startup/stream checks are separate from successful over-air protocol reception. The upstream [AO-73 sample recording](https://github.com/daniestevez/satellite-recordings/blob/master/ao73.wav) additionally verifies CubeSat demodulation, the complex-IQ pipe, a 256-byte validated frame, KISS transport and FUNcube telemetry parsing, without injecting sample data into the production receiver.
