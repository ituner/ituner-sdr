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
black at 700 px wide with its original proportions preserved. The build also
writes `ituner-sdr-preview.png` in the visible 1280x800 landscape orientation.
Rendering requires Pillow and librsvg's `rsvg-convert` (Homebrew: `brew install
librsvg`; Debian/Raspberry Pi OS: `sudo apt install librsvg2-bin`).
