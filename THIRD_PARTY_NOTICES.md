# Third-party artwork

The following navigation icons are distributed under the Flaticon Free
License, which permits personal and commercial use with attribution. The
copies in `assets/menu-icons/` and `UI/assets/menu-icons/` were converted to
the application's monochrome palette and resized to its 64 px icon canvas.

- **Technology** (`lan-home.png`), created by
  [Picons](https://www.flaticon.com/authors/picons), from
  [Flaticon](https://www.flaticon.com/free-icon/technology_15524790).
- **Global Network** (`globe-network.png`), created by
  [Vector Stall](https://www.flaticon.com/authors/vector-stall), from
  [Flaticon](https://www.flaticon.com/free-icon/global-network_8427394).

License: [Flaticon Free License](https://www.flaticon.com/license/license.pdf).

## Flexible S-Meter faces

`UI/assets/smeters/flexible/` contains original, unchanged DX101, ICOM, Orange,
Dark, Neon, Transparent and Vintage HD PNG backgrounds from [Flexible S-Meter](https://flexiblesmeter.svabi.ch/),
published by Jan Svabenik according to the site's [imprint](https://flexiblesmeter.svabi.ch/impressum/),
retrieved on 2026-10-14 from its published
[skin bundle](https://flexiblesmeter.svabi.ch/shared-files/83/?flexiblesmeter_skinbundle.zip)
and [Neon bundle](https://flexiblesmeter.svabi.ch/shared-files/148/?flexiblesmeter_skin_neon.zip).
The author's calibration coordinates are retained in `calibration.json`.
These bundles contain no separate license text; no license is inferred.
See `UI/assets/smeters/flexible/SOURCE.md` for provenance and integration details.

## OE3IDE and KE9NS meter artwork

`UI/assets/smeters/community/` contains five analog S-meter backgrounds and the Plain Black
Magic Eye glass/housing image published by Ernst, **OE3IDE**, in his
[Thetis meter graphics collection](https://www.oe3ide.com/meter-graphics-thetis-2-9-0-8-and-newer/),
and the TR7 tribute meter image explicitly credited to Darrin, **KE9NS**, on his
[PowerSDR/PowerMate page](https://www.ke9ns.com/flexpage.html).
Images retain their original download bytes. Titles credit these callsigns;
Flexible S-Meter titles additionally credit its publisher **HB9HSJ**, without
claiming verified per-face authorship. The Magic Eye animation is original
application code. No separate artwork license appears in these ZIP archives,
and no license is inferred. See `UI/assets/smeters/community/SOURCE.md` for exact
source files, download IDs, calibration and the scope of each credit.

Vintage HD has separate White and Orange choices sharing an unchanged source
PNG and printed scale geometry. Orange uses a palette filter at rendering time. The lower-resolution Vintage
option and its PNG have been removed.

## PeppyMeter linear meter strips

`UI/assets/smeters/linear/` contains unchanged Bar, Dash and Gas background and
indicator PNGs from [project-owner/PeppyMeter](https://github.com/project-owner/PeppyMeter),
commit `2a64eb5156296b51c3baf403d92dacbe0aebde23`, retrieved on 2026-10-15.
The upstream repository distributes them under GPL-3.0. Its complete license is
included as `UI/assets/smeters/linear/LICENSE.txt`, with original configuration,
source paths and SHA-256 checksums. See that directory's `SOURCE.md`.

The integration draws pixel-aligned derivatives of each display strip at native
size (preserving the original PNGs), with an independent S/dBm scale.
It does not display the source audio VU scale or pretend RSSI is an
audio level. No PeppyMeter application or signal-processing code is imported.
The EM84-style Magic Band is original procedural application artwork; it uses
no third-party photo, plugin binary or copied plugin source.

## Original aviation instrument housings

`UI/assets/smeters/aviation/black.png` and `brass.png` are original synthetic
photorealistic housings made with the built-in image generation tool. Museum
research links, generation prompts and calibration details are recorded in
that directory's `SOURCE.md` and `PROMPTS.md`. No museum photograph or historic
manufacturer artwork is bundled or claimed as an amateur-radio contribution.

## User-supplied vintage VU-meter references

The Bakelite Square and Round S-meters in `UI/assets/smeters/bakelite/` are
adaptations of two VU-meter photographs provided by the user. The built-in
image generation tool prepared blank, transparent housings; original runtime
print reproduces the VU typography/tick treatment with an accurately calibrated
S/dBm scale and a live pointer. Manufacturer markings and fixed needles were
removed. No author callsign or open-source licence is claimed for the supplied
references. See that directory's `SOURCE.md`, `PROMPTS.md` and calibration data.
