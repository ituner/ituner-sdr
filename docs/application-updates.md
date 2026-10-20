# Application updates (Raspberry Pi and macOS)

Open **SYSTEM → UPDATES**. Select **Stable** (published GitHub releases) or
**Development** (latest `main`), then **Check for updates**. Review the notes,
press **Install update**, and confirm. Checking is on demand; opening the screen
does not poll GitHub or contact receivers. The app restarts after installation.

The updater downloads from `ituner/ituner-sdr` at the exact commit shown. It
stages and imports the candidate using the existing Python environment before
stopping the app. It keeps one previous version and waits for the new process
to present a frame and remain running. Failed startup triggers restoration;
**Restore previous** also provides manual rollback.

Only application files (`UI`, assets, licenses, version and update manifest)
are installed. Display/touch overlays, audio configuration, kernel/OS, system
services, Python environments, downloaded models and user recordings are not
updated. User settings outside the application source remain in place.
Runtime requirements are versioned in `app-update.json`: a dependency change
must increment `runtime` and requires a separate runtime upgrade. This is an
application updater, not the full board installer. It does not run repository
installation scripts as part of an update.

## Enable on an existing installation

The Pi installers install the updater automatically. For an existing Pi,
first deploy the application code including `app_update.py`, then run from the
matching repository:

```sh
sudo python3 scripts/install-updater.py --user ituner
sudo systemctl restart ituner-sdr.service
```

On Mac, use the application's virtual environment and installed root:

```sh
UI/.venv/bin/python scripts/install-updater.py --root "$PWD"
```

Restart the app afterward. The desktop icon continues to launch the same
installed path. The updater restarts Python with the existing launch arguments
and selected receiver. It does not require Homebrew changes or administrator
access on Mac. The Mac checkout becomes a deployed application with modified
tracked files; use a separate clone for development rather than `git pull` in
this installation. Windows in-app installation is not implemented.

## Recovery and diagnostics

On Pi the fixed helper is `/usr/local/sbin/ituner-update`; its validated command
is the only update command allowed through sudo. A separate systemd job
survives application restart. A startup hook restores interrupted writes after
power loss. State and backups are in `/var/lib/ituner-sdr/updates`.

On Mac state and logs are in `~/Library/Application Support/iTuner/updates`.
A failed application startup is rolled back automatically while the worker is
running. After power loss during a Mac update, rerun the updater from Terminal
with the intended operation to recover its pending backup before proceeding.
Keep the one-time installer/source available if the application cannot open.
Normal quitting/reopening does not install updates.

## Publishing

Stable uses the latest non-prerelease GitHub release; Development uses `main`.
Publish release notes and tag the tested commit to make it available to Stable.
The installed commit is displayed alongside VERSION, so installations can be
distinguished even between numbered releases. A check makes one GitHub API call
for Development, or two for Stable. Installation rechecks that target before
downloading; if it changed, the user must check again. No periodic background
check or silent installation is performed.
