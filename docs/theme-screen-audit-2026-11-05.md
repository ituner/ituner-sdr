# Theme screen audit — 5 November 2026

Two independent read-only UI agents inspected the native main screens and
auxiliary workspaces. This is a source audit; it does not certify every screen
through hardware interaction. Theme coverage is not yet complete.

## Changes completed with this audit

- General Cantarell labels now follow the selected font. Dedicated frequency
  faces and explicitly monospaced numeric instruments remain unchanged.
- ADS-B dashboard labels and the VHF title follow the selected font; Current
  preserves their original Oxanium face.
- INFO and Fan Curve descriptive text consume theme palette roles.
- Shared HOME/settings rail separators consume the theme border palette.

## Screen inventory

| Screen group | Source coverage / remaining work |
|---|---|
| HOME | Shared buttons, mode controls, volume/passband, headings, footer labels and spectrum/waterfall colors are connected. |
| Theme list / Customize / Color | Live draft palette, corners, font, text size, brightness, borders and saturation are connected. |
| DISPLAY and AUDIO LCD rails | Shared controls and slider palette are connected. |
| SYSTEM / Network / INFO / Fan Curve | Shared controls largely connected; INFO/Fan Curve text and separators corrected in this batch. Network table rows intentionally use square, quiet styling and need a consistency decision. |
| RECEIVERS list | Shared row/action colors, fonts and stateful outlines are connected through its palette adapter. |
| RECEIVERS Globe | **Remaining:** fixed-color map callouts, help/status/notice panels and reticle in `draw_receiver_map()` in `UI/kiwi_gl_display.py`. Keep geographic imagery distinct from UI chrome. |
| SSTV / Hell / QRSS / CW | Shared workspace palette, panels and buttons are connected. Received/captured images retain their actual pixel colors. |
| WSPR / history | Shared palette and controls connected. **Review:** ordinary chart headings using `mono=True` bypass font style. |
| Spectrum survey / compare | Shared DecoderStyle and spectrum palette connected; theme revision participates in chart caches. Series/exclusion colors retain data-category meanings. |
| VHF | Shared chrome connected; title font corrected in this batch. |
| ADS-B / native Coverage / Weather / Comparison | Shared DecoderStyle and dashboard controls connected; dashboard label font corrected in this batch. Radar and signal-scale colors retain their data meanings. |
| Station / Dongles / saved-log search / Apps rail | Shared live palette and components largely connected; no major native chrome gap found by the agents. |
| Legacy non-LCD Audio / Display / Apps-Test | **Remaining:** fixed backgrounds/text in `draw_audio_panel()`, `draw_display_setup_panel()`, and `draw_tests_panel()` in `UI/kiwi_gl_display.py`. |
| Browser companions | **Remaining:** separate fixed HTML/CSS palettes for galleries and ADS-B, VHF, Spectrum, Station and Dongles dashboards. Need a theme endpoint/CSS variable bridge; native palette changes alone cannot update these pages. |

## Follow-up work

- [ ] Theme Receiver Globe overlay chrome and validate dark/light themes.
- [ ] Theme legacy alternate layouts and validate their text contrast.
- [ ] Review nonnumeric monospaced chart headings and square network rows.
- [ ] Add a theme bridge for browser companions and their rendering caches.
- [ ] Visually exercise each affected screen on Mac and CM5.

Global saturation applies to theme palette colors and the spectrum/waterfall.
It does not recolor received images, satellite imagery, archived captures, or
data-category legends; changing those requires corresponding legend treatment.
