# CM5 appliance splash

`ituner-sdr-native.png` is the shared 800x1280 image used by Plymouth and
the Wayland background. It is deliberately stored in the LCD's native portrait
buffer orientation; the mounted panel presents it as a 1280x800 landscape
image using the same counter-clockwise mapping as the OpenGL renderer.

Rebuild it after a design change with:

```sh
python3 scripts/build-boot-splash.py
```

The supplied logo, with blue/violet recolored silver (#C0C0C0), is stored as
`ituner-logo-color.svg` and is the only splash artwork, centered on
black at 350 px wide with its original proportions preserved. The build also
writes `ituner-sdr-preview.png` in the visible 1280x800 landscape orientation.
Rendering requires Pillow and librsvg's `rsvg-convert` (Homebrew: `brew install
librsvg`; Debian/Raspberry Pi OS: `sudo apt install librsvg2-bin`).

A centered 18 px version label (for example `v0.1.0`) appears below the logo.
The repository's `VERSION` file is the single source for the release number.
After changing it, rebuild and commit both splash images. Their embedded
version metadata is checked against `VERSION` by the boot tests.

This is a Linux Plymouth splash, followed by a matching Wayland background.
It appears after the kernel starts; it does not replace the pre-Linux firmware
screen. Boot configuration suppresses the standard firmware splash.
