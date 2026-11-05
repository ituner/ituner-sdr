# Themes and S-meters

Open **Display → Themes**. The chooser sits over the complete, full-size live
HOME screen. Tap **Default**, **Default Inverted**, **Green**, or **Black & White**
to open that preset's customization immediately. Existing saved themes remain
available on additional chooser pages; paging does not select or apply a theme.
**Previous** and **Next** stay in fixed positions on every page, including a
single-page chooser. Unavailable directions are dimmed and do nothing when tapped.

The customization panel overlays the waterfall without shrinking HOME. It has
four sections:

- **Colors:** tap **Accent** or **Text** to open the color editor. It has
  side-by-side Accent and Text sections, each with separate unlabeled square
  black and white swatches and a thin rainbow slider with
  a taller touch area. Accent changes
  interface highlights; Text changes regular interface labels. Warning colors
  are retained. **Save** returns to Customize with those colors in the draft;
  **Cancel** restores the colors from before opening the editor. Apply in
  Customize saves the theme. Intensity and saturation controls live in this Color window;
  Save and Cancel include their changes too.
  Swatches and rainbow strips are 20% thinner than the previous color strips,
  while retaining 44-pixel touch targets.
  Selected black/white swatches show contrasting checkmarks and outer markers.
  Each row also names its selection beside the original color code, independently
  of brightness/saturation. Accent controls both the HOME passband indicator and
  the spectrum/waterfall passband overlay, retaining their alpha and RF geometry.
- **Text size:** minus/plus changes the size in 5% steps, within the existing
  80–120% range. Tap the percentage to return to 100%.
- **Corners:** **Straight** or **Rounded** (0 or 8 pixels), previewed on HOME's
  interface controls.
- **Font style:** **Current** preserves the original typography; **Clean** uses
  bundled Liberation Sans labels; **Instrument** uses bundled Liberation Mono
  labels; **Classic** uses Liberation Serif; **Readable** uses DejaVu Sans.
  Each equal-width button shows its own font, with a live sample below.
  Tapping changes the HOME labels and Customize immediately. Dedicated frequency
  and fixed-width numeric readouts keep their existing faces and alignment.
Within **Color**:

- **Color intensity:** brighter/dimmer theme colors, from 50% to 150%, with
  100% restoring the preset's original brightness. This is brightness, not
  saturation. Preset text and custom text colors follow this intensity directly.
  Spectrum colors and waterfall pixels follow the theme as well.
- **Border color intensity:** interface border visibility from 25% to 200%. Higher
  values strengthen borders on both dark and light themes. The default is
  **25%**; **100%** gives the full preset border color. Color intensity defaults
  to **100%**. Intensity controls use sliders without minus/plus buttons.
- **Saturation:** global colorfulness from **0%** (grayscale) to **200%**,
  defaulting to **100%**. It affects theme text, accents, borders, status colors,
  spectrum and waterfall while preserving alpha and original signal history.
  Received imagery and data-category legends retain their actual colors.

Minus and plus symbols on shared buttons such as Text Size are 50% larger than
regular button labels. Reset Theme, Choose Theme, Cancel, and Apply use equal-width buttons.

Subtitles and muted labels blend 65% of the chosen main text color with 35%
of the background. This applies after brightness and
saturation, including existing saved themes. Black text on a light surface
therefore gets gray secondary text; colored text keeps a related dimmed shade.
Pressed and disabled button subtitles also remain distinct from their titles.

**Hide controls** reveals the complete HOME screen. **Show theme controls**
reopens the panel with the same draft. The panel follows the available RF
canvas on either sidebar side; HOME's layout and the panel's touch targets do
not move when text size or corners change. The taller panel has extra space between descriptions and sections. Its text,
colors, border intensity, and corners follow the candidate along with HOME.
A roughly 90%-opaque theme-colored background and a subtle shadow give it a
floating appearance while keeping the controls readable.

The actions have separate scopes:

- **Reset theme** restores the selected built-in's original accent, text size,
  font style, corners, color intensity, border intensity, and saturation in the preview. Previously saved
  customizations of that built-in
  are also reset to its factory appearance. Reset does not save anything.
  For an existing named theme, Reset restores the original appearance retained
  when that theme was first opened in this editor.
- **Choose theme** returns to the chooser. Each
  candidate's unsaved changes remain available during that session.
- **Cancel** discards the whole session and returns to the setup active when
  Themes was opened.
- **Apply** saves the selected candidate and returns to HOME. If saving fails,
  the panel shows the error, retains the draft, and leaves the active setup intact.

Built-in customizations are stored separately from the immutable presets.
Repeated Apply does not create extra named copies. Existing version-1 theme
files and named themes remain readable; no theme is deleted by the new editor.

Theme selection preserves the sidebar side, distance/temperature conventions,
frequency placement, and S-meter selection. Spectrum and waterfall colors follow
the selected theme again, including Default Inverted, Green, and Black & White.
The current waterfall history is recolored without clearing its signal patterns;
color intensity changes its brightness without modifying the numerical contrast
range, tuning, or audio. Interface-only built-in overrides from the first HOME
editor are read with the preset's spectrum/waterfall colors restored. Live
receiver operation continues, but
radio tuning and volume touches are blocked while the Theme editor is open.
Previewing, resetting, choosing, dragging intensity sliders, and cancelling do
not write preferences or
start a second receiver connection.

S-meter selection is independent. Tap the meter on HOME to open its existing
visual picker. Choosing a theme keeps that meter; changing the meter does not
create or modify a theme. The original meter remains **LED Bar**. Meter artwork
and callsign credits are retained.

The preview uses the actual live HOME framebuffer, including the receiver's
real spectrum, waterfall, meter, and footer. The UI does not substitute an
approximate screenshot or synthetic RF scene during normal operation.

The editor derives brightness and border changes from an unchanged base each
time, avoiding accumulated rounding. Existing named themes retain their base
appearance with their saved customization parameters, so reopening and editing
them does not multiply the effect again. Essential label and pressed-button
contrast is protected for radio readouts while dimming. Regular text follows
Color Intensity directly; the Color window uses contrasting labels and readouts
so it stays usable while previewing dark text.

Inactive and disabled buttons use the same preset border color and intensity
as other controls. Border Intensity adjusts these outlines too; disabled labels stay
dimmed and the controls remain unavailable. Older built-in customizations adopt
the full-color factory border base while preserving their saved intensity choice.
The Theme list and Customize share the same position, theme colors, corner
style, translucent background, and shadow over HOME.
