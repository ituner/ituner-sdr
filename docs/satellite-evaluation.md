# Satellite application evaluation on CM5

Existing Mac, GitHub main and CM5 sources were synchronized at
`493b01eab1dbf0712b1e2d1336c665e6f5f8a512` before installing either application.
The pre-sync CM5 working files are archived under
`/home/ituner/sync-backup-20261019/`; a named Git stash also retains that snapshot.

## Evaluation addresses

| Application | URL | Purpose |
| --- | --- | --- |
| Ground Station 0.8.19 | http://cm5.local:7000/ | SDR reception, satellite database, scheduled observations and supported decoding |
| Satvisor | http://cm5.local:8095/ | Globe, sky view, pass predictions and rotator controls; no SDR decoder backend |

Both are web applications. They do not replace or autostart over the native
touchscreen app. Use a tablet or computer browser to evaluate them. No antenna
rotator or automatic RF observations are enabled by this installation.

Ground Station's local account is `ituner`. A generated password is stored in
`/home/ituner/.config/ituner-sdr/groundstation-evaluation.json` with mode 0600.
It is separate from the SSH password and is not stored in Git. The station
location and timezone are copied from Settings / Radio information during
bootstrap. Satvisor follows that shared location every 30 seconds through a
sanitized, read-only local endpoint; Ground Station currently receives an
initial copy, so update its Location settings if moving the receiver.

### Login mode (reversible)

At the user's request, Ground Station is configured for **no login prompt** on
the local network. Anyone who can reach port 7000 can operate the existing
`ituner` account. The account, password and normal upstream login implementation
are preserved. No credentials or session tokens are embedded in the frontend.
An external Python launcher supplies an internal session to HTTP and WebSocket
requests; the pinned upstream image is unchanged.

To require login again, run on CM5 from `/home/ituner/ituner-sdr`:

```sh
sudo bash scripts/set-groundstation-login.sh required
```

To return to no prompt:

```sh
sudo bash scripts/set-groundstation-login.sh open
```

The switch is stored in
`/var/lib/ituner-groundstation/configs/ituner_access.json` and survives reboot.
The helper restarts only Ground Station, dropping existing automatic-access
sockets. Missing settings default to requiring login. Existing legitimate
browser login sessions retain normal upstream behavior. The private credential
file above remains the login recovery reference; do not delete it.

For an older evaluation container, install the launcher mounts once with
`sudo bash scripts/start-groundstation-evaluation.sh --recreate`. The previous
container is retained stopped as `ituner-groundstation-backup-<timestamp>` with
automatic restart disabled. Both containers use the same persistent data.

## Ground Station

Pinned ARM64 image:

```text
ghcr.io/sgoudelis/ground-station@sha256:e71abef10c10207b3c7cddd9b81b01681c4cb2235395735b5205178aea0220eb
```

Registry layers total about 2.37 GB compressed. Docker reports 5,687,815,426
bytes (5.69 GB / 5.30 GiB) for the unpacked image. Data persists separately in
`/var/lib/ituner-groundstation`. Recorded IQ can consume substantial additional
space; recordings are not started automatically.

Debian `docker.io` and `docker-cli` are installed. The container is named
`ituner-groundstation`, with restart policy `unless-stopped`. The evaluation
starts the packaged Python application directly, skipping the stock launcher's
unneeded UHD firmware downloads and SDRplay/mDNS daemons. USB is passed through
without privileged mode or binding the entire host `/dev`. CPU quota is two
cores; the current CM5 kernel has no memory cgroup controller, so Docker cannot
enforce a RAM ceiling. No kernel or boot configuration was changed.

```sh
sudo docker pull ghcr.io/sgoudelis/ground-station@sha256:e71abef10c10207b3c7cddd9b81b01681c4cb2235395735b5205178aea0220eb
sudo bash scripts/start-groundstation-evaluation.sh
sudo python3 scripts/bootstrap-groundstation-evaluation.py
sudo docker logs --tail 80 ituner-groundstation
sudo docker stop ituner-groundstation
sudo docker start ituner-groundstation
```

The bootstrap helper is for initial setup: it creates a local account, copies
the shared receiver location, and restarts this container to refresh pooled
SQLite connections. It does not restart the SDR service. Sign in after startup.

The optional TinyGS orbital source is disabled in this evaluation because the
packaged parser rejects an Alpha-5 satellite ID (`A0960`) in that feed. The
CelesTrak Cubesats, Amateur, Space stations and Weather sources remain enabled.
Initial synchronization populated 249 satellites and 649 transmitters.
To repeat setup, open Satellite Data / Orbital Data, disable the TinyGS source
and synchronize the remaining sources. In Earth view, select a Group at the
top left (for example Space stations), then select ISS to see its details.
The evaluation verified catalog loading, upcoming passes, ISS tracking and
discovery of the connected RTL-SDR. RF recording/decoding was not started:
ADS-B retained ownership of the dongle throughout installation.

**One dongle can have only one owner.** Stop ADS-B/Meteor/other existing RF
reception through its normal controls before starting that dongle in Ground
Station. Stop Ground Station's receiver before returning it to the original
decoder. Its separate scheduler is not integrated with the existing USB broker.

## Satvisor

Upstream source: https://github.com/satvisorcom/satvisor at
`32ce6bb04fea6e08fb1e62d381edf1a70b04d0c5` (AGPL-3.0).
The local patch is `config/satvisor-evaluation.patch`. It removes optional
Bluetooth-feedback package dependencies hosted behind GitHub package
authentication, disables that feedback integration, selects Standard graphics,
defaults to 30 FPS, and follows the local shared station position. Satellite
tracking, database browsing, pass prediction and rotator features remain.

To rebuild from that checkout, apply the patch, install the public dependencies,
and run the production build (Node 20.19+):

```sh
git apply /path/to/ituner-sdr/config/satvisor-evaluation.patch
pnpm install --ignore-scripts --lockfile=false --registry=https://registry.npmjs.org
VITE_FEEDBACK_TOYS=false VITE_TEXTURE_QUALITY=lite pnpm run build
```

Deploy `dist/` to `/opt/ituner-satvisor`, install `scripts/satvisor-server.py` to
`/usr/local/lib/ituner-sdr/`, and install `systemd/ituner-satvisor.service`.
Orbital catalogs still update over the Internet; this is not a fully offline
data mirror. The local station endpoint excludes the SDR control token and
operator details. Altitude defaults to zero when unknown.

```sh
sudo systemctl enable --now ituner-satvisor
sudo systemctl stop ituner-satvisor
sudo systemctl start ituner-satvisor
```
