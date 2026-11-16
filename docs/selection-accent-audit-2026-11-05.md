# Selected-option accent and HOME action row

Two UI/UX agents reviewed native choice controls. The implementation reuses
DISPLAY's Smart Button surface and 15 × 5 px accent indicator. The indicator
uses the theme's `ready` color and a dim version for unselected choices.
It is explicitly applied to persistent choices, not every `active=True` action.

| Screen | Change |
| --- | --- |
| DISPLAY → ADVANCED | LEFT / MIDDLE / RIGHT now match DISPLAY preset selection styling. |
| RECEIVERS | Source-category filters use the same selected indicator; server rows are unchanged. |
| MODES / FM-DX | Tuning-step options use the accent indicator, retaining numeric values and units. |
| Mode variant popup | Persistent mode choices use the shared selection renderer. |
| Dual RX mode picker | Keeps title and mode detail, adding the theme selection indicator. |
| WSPR Distance | Time-range choices use the shared renderer. |
| Long Scan | Setup and history duration options use the shared renderer. |
| ADS-B History Window | All nine time choices use the shared renderer. |
| ADS-B Dome Timespan | Time-window choices use the shared renderer. |
| DISPLAY presets, HOME/MODES families, AUDIO annunciators | Existing theme-ready indicators retained. |

HOME's TUNE, SCAN and BAND buttons now form a single row in that order,
below FAVORITE / PAUSE, aligned to the right edge of the RF canvas. Existing
square sizes and 10 px gaps are preserved. Drawing and touch handling use the
same box functions. HOME zoom retains its original symbol size and lower position.

Native previews checked HOME with LEFT, MIDDLE and RIGHT readout positions,
plus DISPLAY ADVANCED. Tests cover selection colors, selected states,
preserved decoder actions and button geometry. The full UI suite passed:
1,243 tests run, 3 skipped, no failures. Deployed to CM5 with 352 targeted
tests passing and app readiness, audio, waterfall and 10 ms polling verified.

Follow-up changes bottom-align DISPLAY ADVANCED above BACK, use the theme
accent on saved FAVORITE stars and spectrum/waterfall passbands, retain large
sidebar S-meters with LEFT/MIDDLE frequency positions, and remove the duplicate
top band label and its tap target. These updates were also deployed to CM5.
The final combined UI suite ran 1,244 tests with 3 skipped and no failures.
