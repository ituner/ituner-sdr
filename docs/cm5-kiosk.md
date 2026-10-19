# CM5 appliance display

The current CM5 application uses SDL/OpenGL through labwc's Wayland session.
Keep labwc, LightDM login, kanshi output configuration and the existing touch
mapping. The Raspberry Pi desktop wallpaper/icons (`pcmanfm --desktop`) and
taskbar (`wf-panel-pi`) are optional.

Run as the logged-in display user. The script requests sudo internally for
the system autostart guard:

```sh
bash scripts/configure-cm5-kiosk.sh
```

This saves the original autostart under `~/.local/state/ituner-sdr/kiosk/`,
creates a per-user labwc autostart for a plain black background. Raspberry Pi
OS uses `labwc -m`, which runs both system and user autostart files. A guard in
`/etc/xdg/labwc/autostart` skips desktop/taskbar startup only for users with the
kiosk marker. Its original is saved in `/var/lib/ituner-sdr/kiosk/system-autostart`.
Other system startup commands, including kanshi and XDG startup for input/session
services, are retained once. The running SDR
and RF decoders are not restarted. Subsequent app installations preserve this
per-user configuration. Brief black gaps during app initialization are expected.

To restore, consult `source.txt` in the saved backup: if the source was the
system `/etc/xdg/labwc/autostart`, remove the generated per-user autostart;
otherwise copy the saved `autostart` back to `~/.config/labwc/autostart`.
Log out or reboot when convenient to restore the desktop processes.

This is a reduced desktop session, not a direct DRM/KMS conversion. Removing
the compositor requires separate validation of GPU initialization, display
ownership, panel orientation and touchscreen input on this custom carrier.

Live validation on CM5: wallpaper, taskbar and their restart wrappers stopped;
the same SDR service PID remained running and ADS-B messages continued arriving.
Those processes accounted for 48.89 MiB proportional set size (PSS); the black
background uses 1.76 MiB PSS, an estimated net reduction of 47.14 MiB. Private
resident memory decreased by 35.88 MiB. PSS apportions shared pages and is not
an exact measurement of system-wide free RAM. A subsequent reboot test exposed
system/user autostart merging; the system guard above corrected it. A second
reboot confirmed that the SDR starts automatically, with one kanshi process,
one black background, and no desktop, taskbar or desktop respawn wrappers.

## Touchscreen cursor

The CM5 app-only installer configures an invisible Xcursor theme for the
appliance user's Labwc session, including the boot background. The app also
hides its SDL cursor in touchscreen mode; desktop mode keeps it visible.
Touch mapping is unchanged. To restore the compositor pointer, remove
`~/.config/labwc/environment.d/99-ituner-cursor.env` and run `labwc --reconfigure`.
