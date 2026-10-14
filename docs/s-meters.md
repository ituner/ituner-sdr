# S-meter designs

Open Display → Themes → S-Meters, or edit a theme and choose **S-Meter Design**.
Select a preview and tap **Save Theme** to apply it. Editing a built-in theme
creates a custom theme; name it in the Name section. An existing custom theme
is updated in place. Leaving without saving discards the meter selection.

The original six vector faces are LED Bar, Sliding Pointer (a vertical pointer
moving horizontally), Classic Ivory, Precision Dark, Aviation Black and Aviation
Brass. The aviation designs use round dials inside rectangular metal housings.
The gallery shows a moving demonstration signal, independent of the receiver.
LED and sliding-pointer scales follow the theme palette; analog faces retain
their cream, dark or brass instrument colours.

The expanded gallery has 14 designs across three pages. **More Designs** and
**Previous Designs** navigate without changing the selected preview or theme.
Five entries use the actual PNG backgrounds from the Flexible S-Meter download
bundles: DX101, ICOM, Orange, Dark and Neon. Their background files are retained
unchanged and credited in `UI/assets/smeters/flexible/SOURCE.md` and the third-party
notices. Original printed PO, SWR, COMP and TEMP scales are face artwork; iTuner
drives the S scale, rather than inventing readings for those transmit functions.

Three original **RF Lab** faces use Obsidian, Amber and Copper backgrounds, with
concentric S / dB, dBm and microvolt scales. All three scales and the three live
readouts derive from the same receiver RSSI. Voltage is RMS across a **50 Ω**
input: `µV = sqrt(0.001 × 50) × 10^(dBm / 20) × 10^6`. It represents the voltage
equivalent of the receiver's power reading, not an additional hardware sensor.
The faces keep units visible and use conventional HF S9 = −73 dBm, approximately
50 µV. Detailed faces are rendered into cached textures, leaving only the needle,
retained peak and numerical readings to change on each frame.

Flexible faces fill the available rail width without an added metal border,
divider or inset padding. Their original aspect ratios are preserved. Skin
images are composited against their face colour and resized once with Lanczos
filtering to their final pixel dimensions, then cached at 1:1 resolution.
Whole-pixel image placement and matching needle transforms keep the lettering
and ticks stable, including on the rotated CM5 display. The original PNGs remain
unchanged; enlargement is still limited by their source resolution.

Tall analog meters automatically hide the Home Bandpass panel and its touch
target on either side of the screen. Volume and mode controls move with the
layout and the navigation tiles remain available. The filter drawer is still
available through the existing radio controls. Choosing a short meter restores
the Bandpass panel. LEFT/MIDDLE frequency layouts retain a small meter in the
top instrument strip and show the full-size analog face in the Home rail.

`UI/smeter_styles.py` owns the shared calibrated drawing and needle geometry.
The vector styles use S1 = −121 dBm, S9 = −73 dBm, +20 = −53 dBm and +40 = −33 dBm,
matching the existing 36-segment display map. The Flexible skins use their author's
16 calibration points, from S0 through S9 and +10 through +60, corresponding to
−127 through −13 dBm. Interpolation follows those face coordinates, with a pivot
fitted to the supplied points and the needle stem clipped inside the image. Live meters retain the receiver's
existing attack/release smoothing and peak hold; each analog face specifies its
pivot, radius and angular sweep. Changing a dial's artwork alone is insufficient
if those geometry or scale parameters differ. No new receiver connection or
signal-processing worker is needed.

Themes save `smeter_style` alongside their other appearance settings. Older
themes and unknown style identifiers default to LED Bar. The normal installer
copies the new Python module with the rest of the UI.

## Visual references

- [OE3IDE's Thetis meter gallery](https://www.oe3ide.com/meter-graphics-thetis-2-9-0-8-and-newer/): rectangular Yaesu-inspired instruments and Aero styling.
- [F1jmm's S Meter 02 photograph](https://commons.wikimedia.org/wiki/File:S_Meter_02.jpg): classic radio dial proportions; the photograph is CC BY-SA 3.0 and is not bundled.
- [Mitchell Aircraft Products modular gauges](https://mitchellproducts.com/product/modular-gauges-voltmeters/): square aircraft instrument housings.
- [Flexible S-Meter](https://flexiblesmeter.svabi.ch/): original source of the five imported skin backgrounds and calibration points.
- [SDR-Radio S-meter documentation](https://www.sdr-radio.com/s-meter): multiple signal/peak pointers and HF reference levels.
- [IARU Region 1 S-meter reference](https://hamwaves.com/decibel/doc/iaru.region.1.s-meter.pdf): HF S units, dBm and RMS voltage at 50 Ω.

The vector designs are original procedural artwork. The Flexible backgrounds are
the original downloaded PNG skins with source attribution; their bundles contain
no separate license text and no license is inferred. Their source configuration
files and original calibration points are preserved in the research/deployment
record, with runtime geometry in `calibration.json`.
