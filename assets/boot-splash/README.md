# CM5 appliance splash

`ituner-sdr-native.png` is the shared 800x1280 image used by Plymouth and
the Wayland background. It is deliberately stored in the LCD's native portrait
buffer orientation; the mounted panel presents it as a 1280x800 landscape
image using the same counter-clockwise mapping as the OpenGL renderer.

Rebuild it after a design change with:

```sh
python3 scripts/build-boot-splash.py
```
