# Bakelite Square and Bakelite Round

Adapted on 2026-10-15 from the two VU-meter photographs supplied by the user in
this chat. The references show a square glossy black case with a pale yellow
face, and a circular black case with an amber face and a curved lower cover.
The photographers/authors and their callsigns were not identified; no callsign
credit or third-party open-source licence is claimed for these references.

The built-in image generation tool prepared `square.png` and `round.png`:
the physical shape, paper, glass and material character are retained, while
audio markings, manufacturer names and fixed needles are removed. True alpha
is preserved around both housings. Full prompts are recorded in `PROMPTS.md`.
These are photo adaptations, not original manufacturer replacement faces.
The original clipboard photographs are not separately distributed.

At runtime the original VU print treatment is recreated with slender, angled
sans-serif numerals, long/short ticks, inner dots and a broad red high-range arc.
The scale is regraduated to S1–S9 and S9+20/+40 dB, with an inner dBm scale.
Geometry and receiver calibration are shared between printed marks and the
thin dark tapered live needle. Calibration is the same as the existing radio
meters: S1 = -121 dBm, S9 = -73 dBm, +20 = -53 dBm and +40 = -33 dBm.
The red region begins at S9. The digital footer reports S, dBm and RMS µV
at 50 ohms; the artwork never represents received signal strength as audio VU.

`calibration.json` records pivot, radii, sweep, colours and the round cover's
front edge. The pointer emerges from behind that cover; the square face's
photographed pivot cap stays in front of its live needle. Static print is
supersampled separately, composited once at native dimensions and cached.
Signal updates move the pointer without reloading or repainting the housing.

Bakelite Square now fills the full 236 × 236 Home rail width. Its live reading
sits on a subtle dark label below the adjustment screw, inside the housing.
The mode-grid gaps are reclaimed using the existing full-width case layout,
preserving the mode and Volume touch targets. Bakelite Round retains its
previous dimensions and separate readout.
