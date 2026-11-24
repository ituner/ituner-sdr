# CM5 power controls and fan shutdown

SYSTEM contains **REBOOT** and **SHUT DOWN**. Each opens a confirmation screen;
BACK cancels. The root-owned helper accepts only `reboot` and `poweroff` and
requests an orderly systemd transition without force flags. The existing
SIGTERM handler saves the current receiver preferences before the app exits.
Desktop previews without the helper cannot issue a host power command.

Install the helper and its narrowly scoped sudo rule on the appliance:

```sh
sudo bash scripts/install-power-controls.sh ituner
```

The application-only CM5 installer also installs these controls. No bootloader,
GPIO, fan, display, or Ethernet settings are changed by this installer.

## Fan running after shutdown

Verified on 2026-11-24 at Wi-Fi address `192.168.12.97`: the preceding boot's
journal reaches `poweroff.target`, syncs filesystems and stops journald. The
bootloader is dated 2025-11-27, version `999d0ec96c451f74e3874c6f2d59025a2fab7182`.
Its configuration does not override `POWER_OFF_ON_HALT`, so the documented CM5
default of 1 applies. The running fan is exposed as the kernel `pwmfan` hwmon
device; no separate fan-curve service was installed. The current carrier's fan
supply circuit has not been verified against a matching schematic.

The user approved the quiet-halt workaround (`POWER_OFF_ON_HALT=0`). The EEPROM
configuration was written and verified using the installed matching 2025-11-27
image, preserving the firmware version and boot order. The original config is
saved on the CM5 at `/var/backups/ituner-sdr/before-quiet-halt-20261124-085246/`.
Power controls passed 55 focused tests on the CM5 and were deployed with a backup
at `/var/backups/ituner-sdr/before-system-power-20261124-085317/`.
Reboot completed and the live EEPROM reports `POWER_OFF_ON_HALT=0` with the
original firmware version. The app is ready with zero service restarts; audio
and waterfall are working over Wi-Fi (route metric 50). The user confirmed that SYSTEM → SHUT DOWN shut down the device and stopped
the fan. The user also confirmed that the physical power button starts the device
after this shutdown. The earlier reboot was verified successfully.

The CM5 datasheet, section 2.11, explicitly describes the fan PWM signal losing
power during shutdown while an externally powered fan can continue running.
It recommends switching the fan supply off with the module or an appropriate
hardware buffer. A running fan alone therefore does not establish that Linux
failed to shut down.

The bootloader's `POWER_OFF_ON_HALT=1` powers off the module's PMIC outputs; it
cannot remove the carrier's external input supply. On supported firmware,
`POWER_OFF_ON_HALT=0` can keep the fan stopped in a powered halt state, but that
is a **quiet-halt workaround, not complete power-off**. Do not silently substitute
it for the requested full shutdown or change fan-related GPIOs without tracing
the current carrier's circuit.

When the device is reachable:

1. Read `rpi-eeprom-config`, `vcgencmd bootloader_version`, and the previous boot's
   shutdown journal. Inspect any existing POWER OFF helper or physical-button
   action and the fan service's stop behavior.
2. Confirm the current carrier fan supply and control circuit against its exact
   schematic revision; the August 2026 carrier inventory is not sufficient.
3. If the module already enters PMIC standby but the fan has an unswitched supply,
   full fan power-off requires an existing controllable supply or a board fix.
4. Back up any configuration before changing it. Verify reboot, orderly shutdown,
   fan stop and physical-button restart with the user present. A silent fan must
   not be used as the only evidence of complete power removal.

Sources:

- [CM5 datasheet, fan control](https://pip-assets.raspberrypi.com/categories/944-raspberry-pi-compute-module-5/documents/RP-008180-DS-8-cm5-datasheet.pdf)
- [Raspberry Pi bootloader power settings](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#POWER_OFF_ON_HALT)
- [Bootloader release notes, 2024-12-19 fan fix](https://github.com/raspberrypi/rpi-eeprom/blob/master/firmware-2712/release-notes.md)

## USB discovery after quiet halt

On the subsequent hardware-button start, Linux enumerated RTL2832U serial
`00001000`, and ADS-B readsb was actively receiving samples without drops.
A missing HOME USB receiver row therefore did not indicate loss of USB power.
Discovery now uses USB descriptors for attached RTL devices instead of opening
them with rtl_test while another decoder owns the interface. No automatic
GPIO42 power cycle was added; it would interrupt both external USB sockets.

## Delivery through SYSTEM → UPDATES

The versioned GitHub update manifest now declares power-control installation and
the opt-in CM5 quiet-halt step. See [Application updates](application-updates.md)
for the one-time updater-helper upgrade required on existing images. Enable
`--cm5-quiet-halt` when installing that helper on this carrier. App rollback does
not reverse EEPROM settings; the original configuration is retained separately.
