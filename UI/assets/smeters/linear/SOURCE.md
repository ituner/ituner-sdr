# Linear LED and gas-display artwork

Publisher: **project-owner**, PeppyMeter project on GitHub (no callsign claimed).

- Repository: https://github.com/project-owner/PeppyMeter
- Commit: `2a64eb5156296b51c3baf403d92dacbe0aebde23`
- Gallery: https://github.com/project-owner/PeppyMeter.doc/wiki/Default-Meters
- Original folder: `800x480/`
- Retrieved: 2026-10-15
- License: GPL-3.0, full upstream text in `LICENSE.txt`.

The six PNGs retain their upstream bytes. `source.json` records source paths and
SHA-256 checksums; `upstream-meters.txt` preserves the original configuration.
The runtime uses pixel-aligned derivatives in `meter_artwork.py`, preserving
Bar's cyan/red segments and Dash's green/red blocks. Gas retains its crisp
luminous grid, recoloured to neon-green VFD phosphor with a pale green core,
dim green off-state, and matching green scale, readout and peak marker.
Cells and dark gaps are drawn directly at final display dimensions rather than
shrinking the originals' glow and fine grids, which became fuzzy at 228 × 30.
The original PNGs remain unchanged for provenance; their recorded crop bounds
are in `calibration.json`. Off/on states are cached at the same dimensions and
the active strip is revealed in proportion to receiver RSSI. Our S1–S9/+20/+40
and dBm readouts replace the audio VU labels. No second/stereo receiver channel
or audio level is implied, and no application code is imported from PeppyMeter.

# Original Magic Band EM84

The separate procedural `magic_band_em84` face is original application artwork.
The horizontal glass/pill view models the EM84's two phosphor bands approaching
the centre as signal grows. It closes at S9, with brighter phosphor above S9;
its S/dBm/50-ohm microvolt readouts share the existing receiver RSSI.

References (no images or code copied):

- Philips EM84 datasheet: https://www.r-type.org/pdfs/em84.pdf
- EM84 digital-replacement demonstration and operating description:
  https://retronics.no/2024/02/22/diy-digital-em84-magic-eye-replacement/
- BlackApple62's SDR# Magic Eye plugin also supports EM84, but supplies a Windows
  plugin without a source/artwork license in the repository. No DLL or other
  material from it is bundled:
  https://github.com/BlackApple62/SDRSharp-Magic-Eye-Plugin
