# Plus/minus UI and UX audit — 2026-11-05

Three agents reviewed the native shared controls, decoder/browser workspaces,
and independent UX coverage. The change enlarges standalone minus/plus symbols
by 50%, following Theme Customize. Button rectangles, touch targets, positions,
colors, navigation, and labels are preserved.

## Screen report

| Screen or control | Result |
| --- | --- |
| HOME waterfall zoom | User exception: original 32 px signs and 4 px strokes restored. Buttons remain lowered, 10 px above the footer. |
| Dual RX waterfall zoom | Both receivers retain enlarged 48 px vector signs and 6 px strokes. |
| ADS-B native Map, Weather and Coverage/Dome | Standalone signs use 150% title size through the shared two-line button renderer. |
| Native VHF numeric keypad | Standalone minus receives the shared two-line renderer treatment. |
| Spectrum Analyzer numeric keypad | Standalone minus enlarged through DecoderStyle, including its explicit font size. |
| Shared single-line controls with explicit font sizes | Standalone minus/plus now receive the same scaling as default-size controls. |
| Theme Customize, Long Scan and existing default-size shared controls | Already enlarged; retained without applying the multiplier twice. |
| ADS-B browser Map | Zoom signs enlarged visually 50%; button dimensions and event targets preserved. |
| ADS-B browser Weather | Zoom signs enlarged visually 50%; button dimensions and event targets preserved. |
| VHF browser Map | Zoom signs enlarged visually 50%; button dimensions and event targets preserved. |
| Legacy framebuffer display | Reference renderer zoom signs enlarged from 32 to 48 px; not the active CM5 OpenGL renderer. |

Globe's labeled ZOOM IN/ZOOM OUT controls and composite captions such as
“Zoom +” retain their typography. Minus signs in measurements and ordinary
text are not controls and are unchanged. The browser ADS-B Dome uses a slider,
not standalone plus/minus buttons. External websites are outside this source
change.

## Validation

- Full UI suite: 1,240 tests run, no failures, 3 skipped.
- Regression coverage verifies scaling with default and explicit sizes,
  unchanged ordinary captions, and vector sign dimensions.
- Native OpenGL visual check across current, clean, instrument, classic and
  readable font styles at 120% theme text scale: symbols centered and fitting
  the tested 64 × 64 px buttons.
- Browser checks at 1280 × 800 and 390 × 800 confirm unchanged button width
  and height on ADS-B Map, ADS-B Weather and VHF Map, with a 1.5 symbol transform
  and pointer events delegated to the original buttons.

Deployed to CM5 on 2026-11-05. Follow-up correction keeps HOME zoom at its
original symbol size. Startup, audio, waterfall and 10 ms touch polling were
verified; physical touch acceptance remains a user check.

## Device acceptance checks

Check HOME and both Dual RX zoom pairs; ADS-B Map, Weather
and Dome; and the VHF/Spectrum numeric keypads. Confirm signs are clearer,
remain centered, and one tap still performs one action. Compare Theme Customize
to confirm its existing size has not increased again.
