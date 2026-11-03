# Opt-in GT911 polling on the iTuner CM5

The affected CM5 enumerated its GT911 and opened input promptly but produced
no touch interrupts or input events for roughly 153–158 seconds after overnight
power-off. Rebinding at 10 seconds and again at 81 seconds did not restore
response. The cause of that delay is not yet proved. Controller configuration
readback had a valid checksum and the correct 800×1280 dimensions.

This candidate bypasses the interrupt-dependent event delivery path. It uses
the polling support from Raspberry Pi Linux `rpi-6.12.y`, pinned to revision
`2569533d6c33c15231fbc21704c87fcebc67173c`, without changing that driver source.
The installed 6.12.47 driver lacked polling support. The replacement is built
against the running kernel; source hashes are verified before installation.

The supplemental overlay empties the interrupt property only. Existing I2C,
reset, address-selection GPIOs, controller firmware/configuration, display and
orientation remain unchanged. A udev rule sets the native input poll interval
to 10 ms. Actual reporting cadence also depends on I2C and driver processing;
this does not promise 100 UI frames per second. The driver's normal contact
tracking and coordinate acknowledgement are retained.

## Installation

On the verified iTuner CM5 only, with matching kernel headers, a compiler,
`curl`, `make`, `dtc`, and the existing GT911 overlay installed:

```sh
sudo bash scripts/install-cm5-touch-polling.sh
sudo reboot
```

The installer backs up existing files, installs the replacement module in the
current kernel's `updates` directory, refreshes initramfs, and adds the overlay
after the existing display setup. It removes the ineffective boot-reset hook.
It does not install on other devices or change USB power/audio/encoder setup.

Check after boot:

```sh
modinfo -n goodix_ts
cat /sys/bus/i2c/devices/0-005d/input/input*/poll
systemctl is-active ituner-sdr
```

Expected: module from `updates`, poll interval `10`, app active. Confirm taps,
releases, drags and orientation physically. No `gt911` IRQ counter is expected
in polling mode. The passive boot recorder remains useful for input events.
A long-off cold start must still confirm that this bypass resolves the delay;
if the controller itself is not producing coordinates, polling cannot fix it.

## Rollback and kernel updates

Remove the `BEGIN ITUNER CM5 TOUCH POLLING` through `END ITUNER CM5 TOUCH
POLLING` block from `/boot/firmware/config.txt`. Remove the added udev rule and
`/lib/modules/$(uname -r)/updates/goodix_ts.ko`, restoring any preexisting copies
from the printed backup directory. Run `sudo depmod -a` and
`sudo update-initramfs -u -k "$(uname -r)"`, then reboot. The original packaged
module is never overwritten. Do not reinstate the failed reset hook by default.

This is not a DKMS package. Before switching kernels, confirm the new stock
Goodix driver supports polling, rebuild for that kernel, or roll back the
polling overlay. Loading a non-polling driver with this overlay will fail.

## Verification so far

On 2026-11-03 the upstream module compiled and loaded against
`6.12.47+rpt-rpi-2712`. Its native `poll` attribute appeared at 17 ms. The user
confirmed normal taps, releases and dragging and reported improved speed.
The interval was subsequently reduced to 10 ms at the user's request.
Overnight cold-start validation is still required.

Source: https://github.com/raspberrypi/linux/blob/2569533d6c33c15231fbc21704c87fcebc67173c/drivers/input/touchscreen/goodix.c

The final warm reboot loaded the replacement module automatically with
`poll=10`. Touch readiness completed at 4.96 seconds and iTuner signalled ready
at 16.88 seconds. The old boot-reset service remained inactive. USB power
service remained active. The readiness script and udev rule accept both the
old address-prefixed name and the newer unprefixed Goodix device name.
