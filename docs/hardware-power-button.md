# Hardware power-button confirmation

The CM5's `pwr_button` Linux input opens the same shutdown confirmation as
SYSTEM → SHUT DOWN. A normal press never directly requests shutdown. Release,
autorepeat and contact bounce are ignored; another press while the confirmation
is open does not confirm it. Tap CONFIRM SHUT DOWN to proceed, or BACK to return
to the previous app view. Receiver playback is not stopped by opening the prompt.

`UI/hardware_power.py` discovers the named input rather than relying on event0,
exclusively claims it, and waits for events on a sleeping `power-button` thread.
The UI consumes pending requests on its existing frame loop. Missing hardware
leaves SYSTEM power controls available.

`sudo scripts/install-power-controls.sh ituner` also installs
`/etc/systemd/logind.conf.d/90-ituner-power-button.conf`, setting HandlePowerKey
and HandlePowerKeyLongPress to ignore, then reloads logind. This avoids Linux
shutting down before confirmation, including during app startup or restart.
The device's firmware-controlled forced-power behavior is not modified.

Verification: short press opens the prompt; release/repeated presses do not
shut down; BACK returns to the previous screen. Do not use a held press for this
test. Existing quiet-halt configuration and the confirmed shutdown helper remain
unchanged.
