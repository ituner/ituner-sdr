# S-meter designs

Open **Display → Themes → S-Meters**. Choose a thumbnail to see that meter
inside a complete, live Home preview. **Full-screen Preview** shows all of Home
at normal size; **Continue Choosing** returns without saving. **Save & Home**
saves the choice and returns directly to Home. **Cancel** discards the draft.
Use **LED / Slider** for the original **LED Bar**, Analog for needles, or Magic
Eye for valve designs. Meter choice is saved separately from themes, and theme
switching preserves it. See [Themes](themes.md) for the complete flow.

The original six vector faces are LED Bar, Sliding Pointer (a vertical pointer
moving horizontally), Classic Ivory, Precision Dark, Aviation Black and Aviation
Brass. The aviation designs use round dials inside rectangular metal housings.
Gallery thumbnails use a demonstration signal, independent of the receiver.
LED Bar retains its original flat Home-rail background and wide segment track,
without a metal frame or inset bezel. LED and sliding-pointer scales follow the theme palette; analog faces retain
their cream, dark or brass instrument colours.

The gallery has 29 designs, up to four thumbnails per page. Next and Previous
browse pages, and tapping a thumbnail previews it in the real Home layout.
Category filters retain a selected meter that belongs to that category;
otherwise they preview its first design. These actions do not save settings or
modify themes. The live meter in Home uses actual receiver readings; thumbnail
signals are illustrative.
Eight entries use the actual PNG backgrounds from the Flexible S-Meter download
bundles: DX101, ICOM, Orange, Dark, Neon, Transparent, Vintage HD White and Vintage HD Orange. Their background files are retained
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
divider or inset padding. Orange retains its approved proportions. The other
Flexible faces expand to the full image area, with unused source margins trimmed
from ICOM and Dark. Separate horizontal and vertical calibration transforms keep
the needle aligned with the enlarged artwork. Preview cards use a coloured title
and selection lamp instead of a grey frame; RF Lab faces also have no metal bezel. Skin
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

The preferences file saves one top-level `smeter_style`, separately from the
appearance-only theme entries. Existing files migrate the active theme's meter
selection; inactive legacy themes cannot override it. Unknown style identifiers
default to LED Bar. The normal installer
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

## Community faces and Magic Eye

Seven designs use unchanged source images from the OE3IDE and KE9NS
downloads: FTDX-5000, FTDX-9000, Matrix, Star Trek, High Vis and Drake TR7, plus
Magic Eye Plain Black. The other five round-eye variants were removed; old
selections migrate to Plain Black. Gallery titles
include **OE3IDE** or **KE9NS** credits. Flexible titles credit **HB9HSJ** as their
collection publisher; individual artists for those faces have not been verified.
Titles shrink as needed to keep the callsign visible.

Analog faces fill the available width; unused source padding is cropped at
render time. The original scales and OE3IDE watermark remain intact. TR7 uses a
vertical pointer on its horizontal ruler. Magic Eye preserves the artwork's
aspect ratio and distinctive housing, filling the available height without an
added grey frame. Its shadow closes continuously from S0 to S9; the phosphor
brightens above S9. Missing signal turns the phosphor off and displays missing
readings. Original transparent glass is cached above the dynamic glow. All
bitmap faces are filtered once with Lanczos at final resolution.

The tall round Eye Plain reclaims the Bandpass area like other tall meters. Their
phosphor follows the receiver's existing smoothed RSSI; numeric S, dBm and 50 Ω
RMS voltage readouts use the same signal. The source transmit-power/SWR
cross-needle faces are retained in the download record, rather than shown as
S-meters without corresponding telemetry. Artwork source and license status
are documented in `UI/assets/smeters/community/SOURCE.md`.

Vintage HD White and Vintage HD Orange remain separate choices alongside
Transparent and Sliding Pointer Orange. Both HD versions share the publisher's
1920 × 1110 source and calibration: White shows the original face; Orange uses
a palette matching Flex Orange (255, 154, 0), with dark ink and preserved scale
geometry. Orange adds a static incandescent backlight with a broad lower-left
hotspot, weaker reflected light and softly uneven amber intensity. The light
field also fills the readout area so there is no added border or colour seam.
It is baked once at display size after Lanczos filtering; scale lettering and
needle calibration remain unchanged. White retains its original artwork.
The lower-resolution Vintage option remains removed; its saved selections
migrate to orange HD.
Flexible faces fill the rail width, with outer margins cropped at runtime and
no added frame. Transparent keeps its alpha channel so the UI background shows
through the scale. Titles credit HB9HSJ as the collection publisher.

Sliding Pointer Orange is an additional original procedural face, with an
orange background with the same cached, uneven incandescent light field as
Vintage HD Orange, dark scale/readout and a dark red vertical pointer moving
horizontally. It shares the standard Sliding Pointer calibration and retained
peak, has no added bezel, and stays 80 pixels tall so the Bandpass remains
visible. The standard Sliding Pointer and LED Bar keep their existing designs.

The linked Groups.io discussion confirms Jan / HB9HSJ as the application's
creator and includes an older ICOM download and a VU-meter photograph shared
by NI0K. The photograph retains a fixed needle and VU markings and is not
bundled as an S-meter. Exact forum messages and sources are recorded in the
Flexible collection's SOURCE.md.


## Horizontal Magic Band and linear LED faces

**Magic Eye** contains the retained **Eye Plain · OE3IDE** and a new original
**Magic Band EM84**. The latter is a horizontal, pill-shaped glass window with
two green phosphor bands closing toward the centre. It reaches closure at S9
and brightens further above S9. Missing signal leaves only dark glass. S levels,
dBm and 50-ohm RMS voltage come from the same receiver measurement.

**LED / Slider** adds **Peppy Bar**, **Peppy Dash** and **Peppy Gas**, credited to
the PeppyMeter publisher **PROJECT-OWNER**. These use real upstream display
strips with a new S/dBm scale, not the original stereo/audio VU labels. Two
textures per size are cached; signal changes reveal the active strip without
rebaking artwork. All four new horizontal faces are 80 pixels tall on Home,
so Bandpass remains available. The original LED Bar is unchanged.

PeppyMeter sources, license and image checksums are retained in
`UI/assets/smeters/linear/`. Reference tube documentation and the investigated
SDR# plugin are linked in that directory's `SOURCE.md`.
