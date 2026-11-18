# October 2026 V4 carrier profile

These sources capture the display, GPIO and USB configuration running on CM5,
verified against the live installation on 2026-11-18. They are **V4 only**.
The existing app-only installer preserves display drivers and boot overlays;
it does not automatically convert an older carrier to this wiring.

## Wiring

| Function | V4 connection |
| --- | --- |
| LCD | DSI1, YX80030ACT3 / JD9365, reset TCA9555 line 6 (P06) |
| Touch | I2C1 0x5d, reset TCA9555 line 5, interrupt RP1 GPIO17 |
| TCA9555 | I2C1 0x20, kernel `pca9555` compatible driver |
| Backlight | RP1 GPIO12 / PWM0 channel 0, 25 kHz, SY7201ABC EN |
| Amplifier enable | TCA9555 line 15 (P17), active high |
| Headphone detect | TCA9555 line 13 (P15), low when inserted |
| External USB power | GPIO42 high enables both external sockets |

The mechanical and optical encoder mappings are in `UI/cm5_encoder_input.py`;
button mappings are in `UI/cm5_button_input.py`. PTT remains unassigned.
GPIO13 is now an encoder input, not the amplifier enable used by the old board.
Python libgpiod 2.x is required (2.2.0 on the tested CM5).

## Display build and initial migration

The shared `../reference-display/panel-jadard-jd9365da-h3.c` uses sleeping GPIO
operations so reset works through the I2C expander. Build with headers matching
the running kernel; do not copy a binary from another kernel:

```sh
make -C hardware/cm5/reference-display modules
dtc -@ -I dts -O dtb -o /tmp/cm5-v4-display-touch.dtbo \
    hardware/cm5/v4/cm5-v4-display-touch-overlay.dts
```

For initial V4 bring-up, back up boot config, the deployed panel module, existing
DTBOs, and compositor files. Install the rebuilt module in the same kernel
updates location as the existing reference-display driver, run `depmod` and
refresh its initramfs. Install the V4 DTBO in `/boot/firmware/overlays/`.
Disable the old `cm5-main-fpc1-z80029`, `cm5-main-fpc2-yx80030`, and
`cm5-main-fpc2-gt911` overlays, and enable `dtoverlay=cm5-v4-display-touch`
in the CM5 section. Keep the working ES8316 audio overlay. Reboot is required.
See the reference-display README for kernel build/backup details.

The tested compositor configuration maps `1-005d Goodix Capacitive TouchScreen`
to `DSI-2`; kanshi enables DSI-2 at position 0,0. Verify the connector name on
other installations before changing their compositor files. The application
installer already accepts Goodix on either I2C bus; `touch-ready.sh` here is the
exact V4-specific helper captured from the device.

## Runtime controls on an already working V4 display/audio installation

After installing the application, install the captured support files from the
repository root. These commands change system configuration; they were not run
as part of preparing this PR.

```sh
sudo apt-get install python3-libgpiod
python3 -c 'from gpiod.line import Direction, Value; import gpiod; assert hasattr(gpiod, "request_lines")'
sudo install -m 0644 scripts/cm5_v4_gpio.py /usr/local/lib/ituner-sdr/
sudo install -m 0755 scripts/cm5-jack-monitor.py /usr/local/lib/ituner-sdr/
sudo mkdir -p /etc/systemd/system/ituner-sdr.service.d \
    /etc/systemd/system/cm5-headphone-monitor.service.d
for file in v4-audio.conf v4-buttons.conf v4-encoders.conf v4-optical.conf; do
    sudo install -m 0644 hardware/cm5/v4/$file /etc/systemd/system/ituner-sdr.service.d/
done
sudo install -m 0644 hardware/cm5/v4/v4-jack.conf \
    /etc/systemd/system/cm5-headphone-monitor.service.d/v4-audio.conf
sudo install -m 0644 hardware/cm5/v4/90-ituner-backlight.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=backlight
sudo systemctl daemon-reload
sudo systemctl restart cm5-headphone-monitor.service ituner-sdr.service
sudo bash scripts/enable-cm5-usb3.sh --v4
```

The USB helper backs up boot config and replaces the old marked active-low
workaround with active-high boot and service settings. It also detects an
already enabled V4 overlay. Older boards retain their existing behavior.
The audio installer preserves an existing V4 profile and installs its helper
without driving GPIO13.

Brightness is exposed in DISPLAY, saved in application preferences, and limited
to 5–100% so the UI remains visible. The udev rule grants the video group access
only to the V4 brightness attribute. The panel driver owns backlight sequencing.

Rollback requires restoring matching application/support files and system
configuration together. Do not restore the old GPIO13 amplifier or active-low
USB settings on V4 hardware. This revision does not alter fan power circuitry.
