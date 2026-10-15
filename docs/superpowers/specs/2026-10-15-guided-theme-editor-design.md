# Guided Theme Editor

## Purpose

The current Theme Editor fills the 1280 × 800 screen with a simulated Preview, five top tabs, three scene tabs, a family chooser, color-part pages, and a 16-swatch grid. The theme draft already applies to the running app, but the user cannot see the real app while the editor covers it. Replace the editor's navigation and simulated Preview with one category at a time and an explicit way to view the running app. Preserve the Theme Library, saved-theme format, built-in themes, and live application of draft changes.

## Entry and navigation

The Theme Library continues to let the user apply a card, customize a built-in theme as a new saved theme, edit a saved theme, delete a saved theme, or start a new theme. Opening the editor begins an unsaved draft. The full-screen editor has one header showing the theme name and `CATEGORY N / 6`, one category body, and a bottom navigation row. It has no Preview area, scene tabs, permanent category tabs, or always-visible Advanced tab.

The bottom row contains `PREV`, `NEXT`, and `VIEW APP` on the left, and the existing 236 × 64 px `BACK` at the bottom right. `PREV` is disabled on category 1 and `NEXT` on category 6. Category changes do not save the draft. The theme name is text in the header; tapping it opens the existing naming keypad. A new theme starts as a copy of the active theme.

`VIEW APP` hides the editor and shows the real running app with the unsaved draft already applied. A single 236 × 64 px `RETURN TO EDITOR` control stays at the bottom center and is the only editor control visible there. Outside that control, ordinary app navigation and interaction work, so the user can inspect HOME and other screens. Returning restores the same category and selected color family. Viewing never saves. The receiver, waterfall, audio, and decoder processes continue normally; theme changes do not restart or clear the waterfall.

## Six guided categories

Each category shows at most three family rows at once. A row is a labeled touch target with its current color sample, not a grid of action buttons. If a category has more than three families, the body scrolls. Selecting a row exposes one shared color editor in the remaining space. The existing palette keys remain grouped as follows, with every key in exactly one family:

| Page | User-facing category | Existing color families and other controls |
| --- | --- | --- |
| 1 | Surfaces | `SURFACES`, `FOOTER` |
| 2 | Text | `TEXT` |
| 3 | Buttons & states | `BUTTONS`, `STATES` |
| 4 | S-meter & passband | `S-METER`, `PASSBAND`, `SLIDERS`; S-meter face chooser |
| 5 | Spectrum & waterfall | `SPECTRUM`, `WATERFALL` |
| 6 | Layout & sizing | Straight/rounded corners, left/right sidebar, original/imperial/metric units, 80–120% text size |

The S-meter face chooser shows the selected face at usable size and opens a dedicated, swipeable face gallery when tapped. It does not put every face card on the category page. The four current built-in themes, including Black & White, remain unchanged.

## Color interaction

Selecting a color family displays a continuous rainbow hue strip and a two-dimensional field for lightness and color strength, including neutral gray. Dragging or tapping either control applies the result to the draft immediately. There is no `APPLY` button and no 16-swatch grid. A category's related colors receive coordinated shades automatically while preserving their relative light/dark order and each color's existing transparency. The selected row shows the resulting representative color and a short description of affected app elements.

One contextual `FINE TUNE` action opens the individual existing palette keys for the selected family. This is the only route to per-key hue/shade editing or optional exact hex entry; it is not part of the ordinary category sequence. If a selected key has an alpha channel, its detail view includes a 0–100% transparency value, edited with the existing numeric keypad and applied live. Keys without alpha do not show that control. An inline `RESET CATEGORY` action restores only that category from the draft's starting state, allowing recovery without discarding the whole theme. Live recoloring and fine tuning must preserve readable contrast across dark, inverted, monochrome, green, and custom themes.

## Save, discard, and errors

`BACK` returns immediately if the draft is unchanged. Otherwise it opens the existing three-choice confirmation: `SAVE & LEAVE`, `DISCARD & LEAVE`, and `KEEP EDITING`. Saving validates the name and writes the same theme schema used today. A built-in theme is never overwritten; customization creates a saved copy. Discarding restores the theme that was active when editing began, including after a `VIEW APP` visit. If a save fails, the draft stays open and the error uses the app's established Zoom-style notice. Deleting a saved theme remains a Theme Library action with its current confirmation.

## Implementation boundaries

Keep theme persistence and `apply_theme` in `UI/theme_system.py`. `UI/theme_editor.py` owns category, selected family, fine-tune, view-app, draft, and confirmation state. `UI/theme_screen_render.py` renders only the active category or overlay; `UI/kiwi_gl_display.py` routes input and suppresses editor drawing in View App mode. Shared geometry for hit testing and drawing remains centralized. Remove the obsolete simulated-preview geometry/rendering after equivalent live-view behavior is working.

## Acceptance checks

- A new user can change a family color, inspect it in the real app, return, and save without using Preview, hex entry, or an Apply button.
- The editor exposes no more than the active category and three family rows at once; bottom navigation remains stable across categories.
- Every existing palette key remains editable through its family; existing saved themes load without migration or visual change.
- A family recolor retains each member's alpha and relative light/dark order; per-key transparency is available only where the stored color supports it.
- `VIEW APP` retains the unsaved draft and category selection; normal app screens remain usable and `RETURN TO EDITOR` is always reachable.
- Save, discard, failed save, and built-in-theme customization have the behaviors described above.
- Applying or dragging theme colors does not reset live waterfall, spectrum, receiver, audio, or decoder state.
- The 1280 × 800 touch targets, disabled navigation states, sidebar-left layout, and four built-in themes are covered by focused tests and a visual check on the Mac app before CM5 validation.
