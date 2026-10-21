# Application updates (Raspberry Pi and macOS)

Open **SYSTEM → UPDATES** and press **Check for updates**. Every Pi and Mac
checks the latest code on GitHub **main**, including changes pushed between
numbered releases. There is no Stable/Development selector.

The screen shows the installed build and either **Up to date** or **Update
available**. Review the latest change, press **Install update**, then **Confirm
install** (or **Cancel**). The app restarts automatically. **Recovery** contains
**Restore previous** if you need to undo an update.

Checking is on demand; opening the screen does not contact GitHub or receivers.

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

Push tested changes to `main` to make them available through **Check for updates**.
The short commit ID identifies the build even when VERSION has not changed.
Each check makes one GitHub API request; installation rechecks that commit
before downloading. If main changes in between, check again before installing.
No periodic background check or silent installation is performed.

For compatibility with already installed Pi helpers, the internal command uses
`development` to mean main. The helper still accepts legacy `stable` commands,
but the application UI always requests main regardless of old installed metadata.
