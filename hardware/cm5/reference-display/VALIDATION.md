# Provenance and validation

## Working hardware baseline

- CM5 r2 main board, 30-pin YX80030ACT3 on FPC2 / RP1 DSI1.
- Visually accepted 2026-09-26: clear, steady colour bars, then desktop and touch.
- Live controller ID recorded during bring-up: `93 65 04`.
- SDR application orientation accepted 2026-09-27: `normal`, touch swap XY,
  no invert X, invert Y. Desktop mapping remains separate.
- LCD controller: Jadard JD9365DA-H3. Touch: Goodix GT911 at I2C0 / `0x5d`.
- Module derived from the Raspberry Pi
  [rpi-6.18.y Jadard driver](https://github.com/raspberrypi/linux/blob/rpi-6.18.y/drivers/gpu/drm/panel/panel-jadard-jd9365da-h3.c).
  Retains original copyright and GPL-2.0+ license. The added YX80030 profile
  uses the exact Waveshare 8-inch initialization tested on this panel, with
  host-first preparation. The supplied source is the version to build; the
  upstream branch link is provenance, not an instruction to download latest.

## Build-kit verification, 2026-09-29

Tested in a separate temporary directory on the working CM5 after its PSU-related
restart. No module was installed/unloaded, no overlay was applied to the live
device tree, and no boot/desktop configuration was changed during these checks.

- Kernel: `6.18.50+rpt-rpi-2712`, aarch64; matching installed kernel headers.
- Compiler/build: `make -j2` successfully built the external module and both
  FPC2 overlays. Device-tree compiler: Debian `1.7.2-2+b1`.
- Built module vermagic: `6.18.50+rpt-rpi-2712 SMP preempt mod_unload modversions aarch64`.
- Source SHA-256 matches the working CM5 source byte for byte.
- Both generated overlays match the installed working `.dtbo` files byte for byte.
- Offline `fdtoverlay` successfully merged both overlays into each installed
  CM5/CM5 Lite, CM4IO/CM5IO base DTB. This checks overlay references, not the
  electrical suitability of those other carrier boards.
- `bash verify.sh` passed against the running system: Jadard bound to
  `1f00130000.dsi.0`; Goodix-TS bound to `0-005d`; Goodix input device present;
  DSI-2 enabled with mode `800x1280` and the unused DSI-1 disabled.
- Local shell syntax and Git whitespace checks passed.

The newly built binary was not activated; these checks establish buildability
and correspondence with the already working configuration. A fresh OS install
using the new guide, other kernels, other panels and changed carrier wiring
have not been end-to-end tested.

## SHA-256 manifest

```text
cb2486d7546401117c77621b45114610399d449b4eba93de96d7820c92f36a6b  panel-jadard-jd9365da-h3.c
24f0cfb221ff75a6db1827634c8f37138ae117cdc8b435b619390313018dd18c  cm5-main-fpc2-yx80030.dtbo
b43c942a6366d4df5b80bbca2adcfac3e1bc17644811d8db9d98cee4e621a780  cm5-main-fpc2-gt911.dtbo
```

The overlay hashes above are outputs built with the tested compiler. A different
compiler may emit a different binary layout while describing the same hardware.
The module source is versioned; generated kernel binaries are deliberately not
committed because they must match the target kernel.
