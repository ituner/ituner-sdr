# Theme Screen Rebuild Design

Date: 2026-10-14
Status: Approved design direction

## Purpose and scope

Replace the current Theme Library and Theme editor interface with a touch-first flow that lets someone see a component, choose its color visually, and immediately see the result throughout the running app. This is a full rebuild of the Theme screens, not a change to the receiver, waterfall controls, or the saved theme file format. The existing three built-in themes remain **Default**, **Default Inverted**, and **Green**. Existing custom themes remain loadable and editable.

The display is 1280 × 800 logical pixels. New Theme and Edit Theme use the full canvas, including the area previously reserved for the 256 px sidebar. Only the **Back** control keeps its existing bottom-right rectangle, `(1034, 728, 1270, 792)`. Other controls are laid out for the full screen. The Theme Library uses the same full-canvas visual language.

## Theme Library

The Library opens from **Display → Theme**. Theme is removed from the Settings menu and appears as a 236 × 64 px button in the Display rail, above **Reset Display**, which remains the final action before Back. Its first row presents the three built-in themes as large preview cards. Saved custom themes follow in a scrollable/pageable card grid. Each card shows the theme name, button corner shape, representative colors, and active state. Touching the body of a card applies it immediately and persists the active choice. Each custom card has separate **Edit** and **Delete** actions. Built-in cards have **Customize**, which starts a new custom copy; they cannot be overwritten or deleted. **New Theme** creates a draft based on the currently active theme. Back from the Library returns to Display.

Delete requires an explicit, persistent confirmation tied to the selected custom theme. Theme-applied, saved, deleted, and error notices use the existing green analog-TV/Zoom notification style in its usual position. A failed save or delete leaves the current screen and draft intact and shows the error.

## Full-screen editor

New Theme and Edit Theme share one editor. A compact top bar contains the editable theme name, an **Unsaved** indicator when the draft differs from the saved starting point, **Save Theme**, scene selectors, and an **Advanced** entry. The Back button remains at `(1034, 728, 1270, 792)`; its area is reserved so no editor content or modal action sits beneath it.

The main canvas gives most of the width to a large preview and the rest to a contextual inspector. Preview scenes are **Home**, **Browse**, and **Popups**. Home includes frequency, S-meter, buttons in normal/active/selected/pressed states, passband, spectrum/waterfall sample, and footer. Browse includes receiver-list rows and selected states. Popups include the analog-TV notice and VOSC-style popup. The sample preview has a visible sidebar boundary and reflects left/right sidebar position, corner radius, units, and text scale. Preview samples are inert examples: clicking a preview component selects a color family, rather than tuning a receiver or opening a real receiver list.

The inspector opens for the selected semantic family, such as **Buttons**, **Text**, **Sidebar & Sections**, **Passband**, **S-meter**, **Spectrum**, **Waterfall**, **Notices & States**, **Sliders**, and **Footer**. It shows the family's component parts and current swatches, with a clear selected part. A part maps to one or more of the existing 69 palette keys; the mapping is explicit and visible in Advanced. Selecting a part never silently recolors unrelated parts.

Other editor controls remain easy to find: **Button Corners** chooses straight or rounded; **Sidebar Position** chooses left or right; **Units** chooses Imperial or Metric; **Text Size** adjusts the app-wide percentage from 80% to 120%, includes a 100% reset, and shows the result in the preview. The original built-in theme retains its historic `original` unit behavior until a custom copy chooses Imperial or Metric.

## Visual color control

The default picker contains a rainbow hue strip and a grid of related shades. The shade grid varies brightness and saturation within the chosen hue. Touching a hue previews a base color for the selected part; touching a shade chooses the exact color. The current and proposed swatches remain visible side by side, with a checkerboard behind any translucent swatch. **Apply Matching Shades** remaps the selected **family only** to the chosen hue while preserving each member's relative light/dark and muted/vivid character. It does not recolor the whole theme or other families. The family name and affected parts are shown before that action.

Where a palette color has an alpha channel, the picker also shows **Transparency**, an on-screen numeric input from 0 to 100. `0%` means fully opaque; `100%` means invisible. A hue or shade change preserves that color's existing alpha until Transparency is changed explicitly. The entered percentage maps to the existing 0–255 alpha channel, with rounding, and editing it updates the live preview. Colors stored as RGB only do not display a transparency field. An optional Advanced control exposes exact hex/RGBA values and all original palette keys for precise editing; hex entry is never the default path.

## Live application behavior and save flow

Entering the editor captures the previously active, persisted theme and starts a separate draft. Every committed picker, layout, unit, or text-size change applies the draft to the running app immediately without writing the theme file. Applying a hue during a drag can be coalesced to once per rendered frame on the CM5. Changing theme colors does not clear the waterfall history, reconnect audio, or alter receiver state. The library's saved active ID does not change until Save Theme succeeds.

**Save Theme** validates a nonempty, unique name of at most 32 characters and atomically saves/activates the draft using the existing version-1 theme library. Saving a built-in customization writes a new custom ID; editing an existing custom theme keeps its ID. After a successful save, the editor returns to the Library with the saved card active. An error retains the draft and the editor.

Back from an unchanged editor returns to the Library immediately. Back with unsaved changes opens a persistent modal with **Save & Leave**, **Discard & Leave**, and **Keep Editing**. Save & Leave follows the same validation and persistence path as Save Theme, then returns to the Library. Discard & Leave restores the theme that was active on entry and returns to the Library; it does not modify the theme file. Keep Editing closes only the modal. The modal blocks underlying controls, has touch-sized buttons, and cannot expire like a transient notice. A name change, color change, layout choice, units choice, or text-size choice marks the draft dirty; returning each value to its starting value clears the indicator. Back from the Library returns to Display without this modal.

## Architecture and data contracts

`UI/theme_system.py` remains the authority for the three built-ins, version-1 JSON normalization, persistence, and runtime palette application. Saved theme fields and palette keys stay compatible. A focused color-picker module should own hue/shade conversion and RGB/RGBA/percentage math without drawing dependencies. `UI/theme_editor.py` should own draft state, dirty comparison, semantic-family selection, Back/save/delete transitions, and shared hit targets. Rendering and input dispatch in `UI/kiwi_gl_display.py` should consume that state and the same geometry, so visible controls and touch targets cannot diverge. The UI must use existing theme-aware drawing helpers and text-only buttons.

The semantic family map is a view over existing palette keys, not a second persistent color model. Advanced exposes every original key, including colors not visible in the three preview scenes. Alpha-bearing tokens preserve their alpha unless explicitly edited. Applying the live draft should update existing theme-aware UI, including the spectrum/waterfall, footer, modal text, S-meter, and receiver rows; previously unthemed surfaces are outside this rebuild unless they prevent an accurate preview or live result.

## Verification and acceptance

- All three built-in cards appear; a card applies and survives restart; Customize creates a custom copy. Existing version-1 custom themes still load.
- Theme appears under Display, not Settings. Reset Display remains the last Display action before Back. Leaving the Theme Library returns to Display.
- New and Edit use the full 1280 × 800 canvas; Back remains at `(1034, 728, 1270, 792)`; preview, picker, and confirmation touch areas have no overlap.
- Hue/shade selection changes the selected part live. Apply Matching Shades changes only the selected family and preserves its member colors' relative contrast. Hue/shade selection preserves alpha. Transparency accepts 0–100 only and round-trips through save/reload within one percentage point.
- The three preview scenes show the expected component states. A preview tap selects a family without controlling the real receiver. Straight corners, sidebar position, units, and 80–120% text scaling preview and apply live.
- Back on a dirty draft offers all three choices. Discard restores the entry theme in the running app; Keep Editing leaves the draft untouched; Save & Leave persists it. Back on a clean draft leaves directly. Save errors keep the draft.
- Theme editing does not reset waterfall content or receiver/audio state. CM5 touch response and picker drag remain usable; verify on device after host tests.
- Focused state/color tests, UI geometry/draw tests, the existing Theme tests, and `git diff --check` pass. Host tests are not represented as CM5 hardware proof.
