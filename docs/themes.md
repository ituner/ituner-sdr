# Themes

Open **Display → Themes**. The current saved appearance is selected when the
page opens. The page has three tabs and one common action bar:

- **Themes** previews a built-in palette or a saved theme. Choosing a built-in
  palette keeps the S-meter you have just chosen. Choosing a saved theme restores
  that theme's complete appearance.
- **S-Meters** shows an enlarged, animated preview. Use All, LED / Slider, Analog,
  or Magic Eye to narrow the gallery. The original meter is **LED Bar**, under
  **LED / Slider**. Browsing pages and filters does not change the selection.
- **Customize** contains optional name, sidebar, corners, text size, units, and
  color controls. These are not required to choose a theme or meter.

**Apply & Home** saves the preview, applies it, and returns directly to Home.
It works from every tab. **Cancel** discards the preview and returns to Home.
There is no second Save screen or nested Back sequence. Neither choosing a card
nor browsing the gallery changes saved settings or the active UI. Save failures
stay on the page with an inline error and retain the preview for retry.

The preview uses the selected palette, sidebar side, text size and actual
S-meter renderer. Tall meters hide the Bandpass area as they do on Home.
The Home preview uses an unchanged capture of the user's actual CM5 SDR
frontend at 17.6832 MHz, including the spectrum, ruler, waterfall and footer.
Candidate themes recolor the captured pixels; no generated RF image is used.
The enlarged S-meter uses a demonstration signal. Color controls preserve
opacity when adjusting RGB.

Changing a saved theme updates it in place. Customizing a built-in creates an
automatically named copy, such as **Default Custom**; further copies receive an
unused suffix. **Make a Copy** preserves the original. Renaming is optional.
Saved themes can be deleted only after confirmation; built-ins are protected.

Paint and touch targets come from `theme_screen_boxes`. Gallery controls use a
stable appearance and size while candidate themes stay inside the preview.
The theme page disables global sidebar input relocation until it closes.
