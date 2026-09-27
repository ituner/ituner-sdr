# Verified CM5 display sources (reference only)

These are the sources used for the working CM5 JD9365 30-pin display and GT911
configuration verified on 2026-09-26. They are archived here for recovery and
future kernel-porting work, NOT installed by the application installer.

The application-only installer must never rebuild these modules, replace boot
overlays, alter config.txt, or alter labwc/kanshi touch/output settings.

FPC2 uses DSI1, four lanes, GPIO26 active-low reset, 800x1280 at approximately
60 Hz. Desktop connector DSI-2. The verified sequence is yx80030act3_init,
compatible yousee,yx80030act3. Timing 70.012 MHz; H800/40/20/20,
V1280/30/12/4. Controller readback 93 65 04. GT911 uses I2C0 address0x5d,
GPIO0/1, interrupt GPIO12 and reset GPIO16. U8 backlight enable is physically
wired to 3.3 V. These source files do not undo or automate that hardware change.

Verified kernel: 6.18.50+rpt-rpi-2712. A kernel change needs separate driver
validation. The application uses normal orientation and the CM5 launcher swaps
axes and inverts Y. LCD's original machine uses different hardware settings.
