# Theme preview capture

`home.png` is the original, unmodified screenshot copied from the user's CM5
Home screen on 15 October 2026 (Europe/Bucharest), after the user selected the
waterfall presentation. It shows reception at 17.6832 MHz on the local KiwiSDR.
The screenshot is stored in native portrait orientation; the UI rotates and
crops it at load time. `home.json` records the scene geometry, captured display
values, source palette and SHA-256 digest.

Theme previews use this actual spectrum trace, frequency ruler, waterfall and
footer. Candidate themes remap the captured colors; the RF patterns are retained.
The sidebar and selected S-meter remain independently rendered. No generated
waterfall or synthetic spectrum trace is used in the Home preview.
