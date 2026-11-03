# iTuner SDR 0.3.0

This release combines the preserved CM5 development with the merged main
interface, retaining Smart Scan, offline station schedules and coverage work.

- Smart Scan continuously revisits broadcast bands, retains one-hour band
  counts and matches station names from downloaded EiBi and HFCC schedules.
  Older-season names remain useful with an explicit asterisk when no current
  match exists, while UTC time and weekday checks still apply.
- An optional continuous 100 kHz waterfall expands the playing row to four
  standard rows. It shows the actual tuned carrier and nearby RF activity,
  pauses scanning while enabled and resumes scanning when disabled.
- Full titles wrap to two lines in the expanded row. Country flags are larger
  with additional title spacing; the repetitive instruction line is removed.
- Display settings offers saved Waterfall Auto and Manual choices. Auto uses
  the visible frequency window and adapts after pan/zoom; Manual holds a fixed
  range. Palette changes preserve this choice, with Auto as the default.
- TUNE and SCAN join Favorite and Play/Pause in a square two-by-two control
  group using the shared theme styling.
- Receiver list and globe views offer manual directory refresh with data-age
  and failure feedback. A fresh upstream directory remains the source of truth.
- Preserved ADS-B development includes coverage, aircraft selection and
  persistence improvements, with the merged UI and keyboard changes retained.

The application update preserves receiver settings and display, touch, audio
and boot hardware profiles. No language detector or speech/music classifier
has been enabled. See [Smart Scan](smart-seek.md) and
[Waterfall display settings](waterfall-display.md).

Validation on the CM5: 1,058 UI tests passed for the combined implementation;
344 affected control, tuning, navigation and volume tests passed after the
button-group update. Auto/Manual selection and saving were verified in the
running UI, with native OpenGL layout checks for expanded station rows.
