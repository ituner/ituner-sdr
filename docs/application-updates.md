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

Application files (`UI`, assets, licenses, version and update manifest) are
installed first. The candidate must present a frame and remain healthy before
fixed device steps declared in `app-update.json` run on Pi:

1. `pi-power-controls-v1` installs the root-owned REBOOT/SHUT DOWN helper and its
   two-command sudo rule, making the SYSTEM power controls usable.
2. `pi-network-controls-v1` installs the matching Wi-Fi/Ethernet helper and sudo
   rules so newly added settings work on existing images.
3. `cm5-quiet-halt-v1` applies `POWER_OFF_ON_HALT=0` only when the updater was
   installed with `--cm5-quiet-halt`. This opt-in is for the CM5 carrier whose fan
   needs quiet halt. Other Pi boards and Mac never receive this EEPROM change.

The confirmation screen describes the device steps. Keep power connected while
installing. The app restarts automatically; if EEPROM configuration was changed,
use SYSTEM → REBOOT before testing SHUT DOWN. Quiet halt stops the fan on the
verified carrier but retains standby power. It is not complete power removal.

The helper saves the original EEPROM configuration and version in
`/var/lib/ituner-sdr/updates/device-steps/`, preserves BOOT_ORDER and other settings,
and applies the override to an installed image matching the running firmware date.
It refuses to select an older default or automatically upgrade firmware. If the
matching image is absent, the update reports that the matching rpi-eeprom package
is required. The vendor EEPROM status check runs; unrelated firmware upgrades are
not scheduled. Completed writes are journaled to avoid reflashing before reboot.

Application recovery does **not** undo device steps or EEPROM changes. The error
message states this when relevant; the original EEPROM config remains available
for explicit recovery. Power controls are idempotent and remain compatible with
older app versions. Repository scripts are not general root install hooks: only
the named helper capabilities and specifically allowed payload files are used.

Display/touch overlays, audio configuration, kernel/OS, Python environments,
models, recordings and user settings are otherwise preserved. Runtime dependency
changes still require a separate runtime upgrade through `app-update.json`.

## Enable on an existing installation

The Pi installers install the updater automatically. **Previously installed
application-only helpers need a one-time privileged upgrade.** They cannot grant
themselves new EEPROM or power-control capabilities through an application-only
update. Use a trusted checkout containing this change (from upstream main after
merging; `lucaiuli/main` before merging). The app reports the upgrade requirement
instead of claiming device setup succeeded. For an existing Pi,
first deploy the application code including `app_update.py`, then run from the
matching repository:

```sh
sudo python3 scripts/install-updater.py --user ituner
# For the verified CM5 carrier quiet-halt workaround, use instead:
# sudo python3 scripts/install-updater.py --user ituner --cm5-quiet-halt
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

The source remains `ituner/ituner-sdr main`. Publishing to `lucaiuli/main` prepares
the changes for upstream merging; it does not change existing users' update source.
Merge tested changes into upstream `main` to make them available through **Check for updates**.
The short commit ID identifies the build even when VERSION has not changed.
Each check makes one GitHub API request; installation rechecks that commit
before downloading. If main changes in between, check again before installing.
No periodic background check or silent installation is performed.

For compatibility with already installed Pi helpers, the internal command uses
`development` to mean main. The helper still accepts legacy `stable` commands,
but the application UI always requests main regardless of old installed metadata.
