# CM5 JD9365DA-H3 LCD + GT911 touch build kit

This directory packages the **working 30-pin YX80030ACT3 panel on the r2 CM5
main board's FPC2 connector**. It is opt-in hardware setup, separate from the
SDR application installer. It is not a complete Raspberry Pi OS image.

The source was visually verified on CM5 on 2026-09-26 and its SDR orientation
on 2026-09-27. The controller returned `93 65 04`; the owner confirmed a clear,
steady image and working touch. Do not select an initialization sequence using
only the controller name: other JD9365 panels can require different sequences.

## Included files

- `panel-jadard-jd9365da-h3.c`: complete, GPL-licensed out-of-tree LCD module.
  The working profile is `yousee,yx80030act3`, function `yx80030act3_init`.
- `cm5-main-fpc2-yx80030-overlay.dts`: panel, power, reset and DSI wiring.
- `cm5-main-fpc2-gt911-overlay.dts`: touch I2C bus, interrupt and reset wiring.
  Touch uses the kernel's **Goodix-TS / goodix_ts** driver; no proprietary
  touch binary, firmware download, or separate Goodix source build is needed.
- `Makefile`: builds the module and these two overlays.
- `config/`: boot and desktop configuration fragments (merge, don't overwrite).
- `verify.sh`: read-only checks of module, panel binding, touch and DRM outputs.
- `VALIDATION.md`: provenance and build/check results.

`cm5-main-fpc1-z80029-overlay.dts` is retained only as an older 40-pin panel
reference. The Makefile does **not** build it. That panel's INX initialization
produced corrupted/flickering output on this 30-pin panel; do not enable it here.

## Hardware and OS requirements

| Item | Verified setting |
| --- | --- |
| Host | Raspberry Pi Compute Module 5, r2 custom main board |
| OS / kernel | 64-bit Raspberry Pi OS / Debian Trixie, `6.18.50+rpt-rpi-2712` |
| LCD | YX80030ACT3, JD9365DA-H3, 800 × 1280, approximately 60 Hz |
| DSI | FPC2 → RP1 DSI1, four data lanes, RGB888 |
| Pixel clock | 70.012 MHz requested |
| Horizontal active / front / sync / back | 800 / 40 / 20 / 20 |
| Vertical active / front / sync / back | 1280 / 30 / 12 / 4 |
| DSI flags | `0xc11`, with host-first preparation |
| Panel power / reset | 3.3 V; GPIO26 active low |
| Touch | GT911, RP1 I2C0, address `0x5d`, 100 kHz |
| Touch GPIOs | GPIO0 SDA, GPIO1 SCL, GPIO12 interrupt, GPIO16 reset |
| Backlight | U8 SY7201ABC EN physically connected to 3.3 V on the tested board |

The software cannot enable this board's backlight: U8 EN has no connected
control GPIO in the supplied schematic. The verified hardware modification is
required. Disconnect power before connecting/reseating display cables. A different
carrier board needs overlays adapted to its actual wiring.

## Build on CM5

Start with a 64-bit Raspberry Pi OS **Desktop** image for the documented labwc
setup. Lite users need to arrange their own compositor/session. The driver uses
Linux 6.18 DRM APIs; older or newer kernels may need source changes. Matching
headers alone do not guarantee source compatibility.

```sh
git clone --branch codex/JD9365DA-H3 https://github.com/ituner/ituner-sdr.git
cd ituner-sdr/hardware/cm5/reference-display
sudo apt update
sudo apt install build-essential device-tree-compiler kmod linux-headers-rpi-2712
uname -r
test -f /lib/modules/$(uname -r)/build/Makefile
make -j2
/sbin/modinfo -F vermagic ./panel-jadard-jd9365da-h3.ko
/sbin/modinfo goodix_ts
```

If the headers are for a newer kernel than `uname -r`, reboot into the matching
installed kernel or obtain headers for the running kernel before building. Do
not copy an old `.ko` to a different kernel release. Custom kernels need
`CONFIG_DRM`, `CONFIG_DRM_MIPI_DSI`, the Raspberry Pi RP1 DSI host, and
`CONFIG_TOUCHSCREEN_GOODIX=y` or `m`. If Goodix is built in, `modinfo` may not list
it; inspect the kernel configuration instead.

Outputs: `panel-jadard-jd9365da-h3.ko`, `cm5-main-fpc2-yx80030.dtbo`, and
`cm5-main-fpc2-gt911.dtbo`. To build just the overlays elsewhere, install `dtc`
and run `make overlays`. No generated kernel modules are distributed in Git.

## Install the hardware files

Run these commands **on the target CM5**, from this directory, after a successful
build. They stage the files for the next boot; they do not unload the live driver.
Keep an SSH connection available during initial setup.

```bash
kernel_release=$(uname -r)
backup_dir=/var/lib/ituner-sdr/display-backups/$(date +%Y%m%d-%H%M%S)
sudo mkdir -p "$backup_dir" /boot/firmware/overlays \
    "/lib/modules/$kernel_release/updates"
sudo cp -a /boot/firmware/config.txt "$backup_dir/"
# Save any earlier external modules and both earlier overlays.
sudo cp -a "/lib/modules/$kernel_release/updates" "$backup_dir/updates"
for overlay in cm5-main-fpc2-yx80030 cm5-main-fpc2-gt911; do
    if [ -f "/boot/firmware/overlays/$overlay.dtbo" ]; then
        sudo cp -a "/boot/firmware/overlays/$overlay.dtbo" "$backup_dir/"
    fi
done
sudo install -m 0644 panel-jadard-jd9365da-h3.ko \
    "/lib/modules/$kernel_release/updates/"
sudo install -m 0644 cm5-main-fpc2-yx80030.dtbo cm5-main-fpc2-gt911.dtbo \
    /boot/firmware/overlays/
sudo depmod -a "$kernel_release"
/sbin/modinfo -F filename panel_jadard_jd9365da_h3
printf 'Save this backup path: %s\n' "$backup_dir"
```

The selected module path must be the new file under `updates/`. If a previously
installed compressed copy or DKMS copy takes priority, resolve that conflict
before booting; do not leave multiple competing external versions installed.

Back up and edit `/boot/firmware/config.txt`, merging `config/boot-config.txt`.
Keep one `vc4-kms-v3d` entry. For this single-panel build, enable only the FPC2
LCD and touch overlays; disable old ST7701/YX45011, FPC1/Z80029 and legacy GT911
CAM/DISP overlays. Keep unrelated USB, network, audio and storage settings.
The example disables automatic display probing to make this explicit hardware
configuration deterministic; the historical working machine had probing enabled.
If using the OS's automatic initramfs, refresh it after installing the module:

```sh
sudo update-initramfs -u -k "$(uname -r)"
sudo reboot
```

## Desktop touch and orientation

In the logged-in desktop user's session, run `wlr-randr` to identify the actual
LCD output. The existing verified machine calls it **DSI-2**, because an unused
DSI0 panel was also enumerated. A fresh FPC2-only system may call it **DSI-1**.
Use the connected 800 × 1280 output consistently; the label is not the DSI bus
number. Do not enable the unused FPC1 overlay merely to reproduce a label.

Merge `config/labwc-touch.xml` into the root element of `~/.config/labwc/rc.xml`
(the working machine uses `openbox_config`; newer files may use `labwc_config`).
Change `mapToOutput` to the actual output. Preserve existing settings and map
this touch device only once. Check `/proc/bus/input/devices` if its name differs.

`config/kanshi.conf` reproduces the historical two-output configuration. For a
fresh system with **only DSI-1**, instead use:

```text
profile cm5_fpc2_only {
    output DSI-1 enable position 0,0
}
```

Merge the suitable profile into `~/.config/kanshi/config`, preserving other
profiles. Install `kanshi` and `wlr-randr` if missing. Ensure kanshi runs once in
the desktop session (on Raspberry Pi OS, check existing labwc autostart before
adding `kanshi &` to `~/.config/labwc/autostart`). Log out and in after editing.
Do not apply a second rotation or touch-axis transform to this desktop mapping.

For this repository's **SDR application**, return to the repository root and use
`sudo ./scripts/install.sh --cm5-existing-display`. Its CM5 configuration uses
`ITUNER_SDR_ORIENTATION=normal`; the launcher supplies
`--swap-x-y --no-invert-x --invert-y` for direct touch input. An existing
`/etc/ituner-sdr.conf` is preserved by the installer: check its orientation.
The application installer remains unchanged and never installs these hardware
files. **Do not run `--legacy-display` on this LCD.**

## Verify, update and recover

Run `bash verify.sh` after boot. Review `sudo journalctl -b -k` for Jadard,
Goodix, DSI and regulator errors. Test visible stability and all four touch
corners; successful compilation/binding alone does not prove a correct picture.
The verifier assumes the documented r2 CM5 buses; adapt it if changing the carrier.

This module is **not DKMS-managed**. After a kernel update, build and install it
against that kernel's headers, run depmod, and refresh its initramfs. Recheck
image and touch before treating another kernel as supported.

To roll back on the same kernel, restore the saved `config.txt`, restore earlier
FPC2 overlays if present (otherwise remove the newly added two overlays), and
restore the prior Jadard module from the backup's `updates/` directory. On a
fresh installation with no previous Jadard override, remove the new override
instead. Do not overwrite unrelated modules. Run `sudo depmod -a`, refresh the
initramfs for that kernel, and reboot. Restore backed-up per-user desktop files
if you changed them. An older kernel requires its own matching module.
