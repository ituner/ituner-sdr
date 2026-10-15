# Themes and S-meters

Open **Display → Themes**. The chooser shows a reduced view of the complete,
real-time Home screen: waterfall, spectrum, frequency, S-meter, mode controls,
volume and navigation. The wider gallery beside it has **Themes**, **S-Meters**
and **Customize** tabs. Selecting a candidate updates the whole preview.

Tap **Full-screen Preview**, or the preview image, to inspect that same complete
Home screen at its normal size. The picker disappears. The two actions are:

- **Continue Choosing** returns to the gallery with the draft intact.
- **Save & Home** saves the choice and returns directly to Home.

Tap elsewhere in full-screen preview to hide or show these controls, so every
part of Home can be inspected. Back returns to the chooser. No radio tuning or
volume controls are active during preview.

The chooser also has **Save & Home** and **Cancel**. Cancel discards every
unsaved preview change. Save failures retain the draft and show an inline error.

Themes contain colors, text size and layout. The S-meter is an independent
setting: changing it never creates or modifies a theme, and changing themes
keeps the chosen meter. **LED Bar**, under **LED / Slider**, is the original
meter. Other filters are All, Analog and Magic Eye. Meter thumbnails retain
callsign credits. There is no additional enlarged meter outside the Home preview.

Customize provides name, sidebar side, corners, text size, units and colors.
Changes render in the real Home preview, including a left sidebar and the
space tall meters take from Bandpass. Editing a built-in's appearance creates
an automatically named copy; saved themes update in place. Make a Copy is
explicit, and deletion requires confirmation. Built-ins are protected.

The renderer temporarily uses the candidate for each Home frame, then restores
the active runtime theme before processing user input. Preview never writes
preferences, starts another receiver connection or changes the radio. A GPU
copy supplies the miniature and full-screen views; the Home UI is not rebuilt
from mock controls or screenshot text. Waterfall history keeps its original
pixels so Cancel can restore their active-theme rendering without clearing it.
