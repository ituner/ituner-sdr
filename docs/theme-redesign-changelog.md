# Theme redesign changes

- Replace the granular Theme screen with preset selection followed by customization over the complete, live HOME screen, so changes can be judged in context.
- Retain Default, Default Inverted, Green, Black & White, and existing saved themes; tapping a preset immediately opens its customization.
- Keep Previous and Next visible on every chooser page, including disabled directions; unavailable buttons remain inert.
- Place the Theme list and Customize in the same position beside either sidebar, using matching theme-aware colors, corners, translucent backgrounds and shadows.
- Make Customize taller and add spacing between section labels, descriptions and controls without shrinking HOME or moving touch targets when text changes.
- Keep edits in a preview draft: Apply saves and returns to HOME, Cancel restores the entry setup, and Reset Theme restores the selected preset's defaults without saving.
- Retain each preset's unsaved draft when Choose Theme returns to the list; Hide/Show Controls reveals HOME and restores the same customization session.
- Add Straight and Rounded corner choices for theme-aware controls.
- Keep Text Size adjustable from 80% to 120% in 5% steps, with a tap on the percentage restoring 100%; enlarge shared minus/plus glyphs by 50%.
- Use equal widths for Reset Theme, Choose Theme, Cancel and Apply instead of an unnecessarily wide reset action.
- Add Current, Clean, Instrument, Classic and Readable font styles, with buttons drawn in their own fonts and a live sample. Bundled label fonts keep Clean/Instrument/Classic/Readable consistent across systems; dedicated frequency and numeric instrument faces remain unchanged.
- Add a Color sub-editor with side-by-side Accent Color and Text Color sections; Save returns both choices to Customize, while Cancel restores the draft from before opening Color.
- Provide separate unlabeled black/white square swatches and rainbow hue strips; make their visible height 20% smaller while retaining larger touch targets.
- Show contrasting checkmarks and outer markers on selected black/white swatches, plus a named selection and original color code for each row, independent of intensity or saturation.
- Apply Accent to interface highlights, frequency accents, sliders, active controls and both the HOME and spectrum/waterfall passband indicators; retain passband transparency and actual RF geometry.
- Add Color Intensity from 50% to 150%, defaulting to 100%, to dim or brighten interface colors, preset/custom text, spectrum and waterfall.
- Add Border Color Intensity from 25% to 200%, defaulting to 25%, using full-color border bases consistently for inactive and disabled controls as well as active states.
- Keep the two intensity controls inside Color and use sliders without minus/plus step buttons.
- Add global Saturation from 0% to 200%, defaulting to 100%; adjust theme palette colors and spectrum/waterfall colorfulness while retaining alpha and original waterfall history.
- Derive subtitles and muted text from the chosen main text color after intensity/saturation. Dim the color toward the background and keep pressed/disabled button subtitles distinct from their titles.
- Restore theme-driven spectrum and waterfall recoloring, including already stored waterfall rows, and repair earlier interface-only built-in overrides when loading without writing preferences.
- Persist built-in customizations separately from immutable factory presets, retain version-1 and named-theme compatibility, and derive repeated edits from stable bases to prevent accumulated color changes. Roll back state when saving fails.
- Preserve tuning, audio, numerical signal ranges, raw history, sidebar placement, units, meter selection and instrument placement during appearance editing; keep S-meter selection in its independent HOME picker and avoid frequency relocation on unrelated Theme saves.
- Fix the crash caused by dragging in Customize after intensity controls moved to Color; drags only adjust controls present in the active window.
- Fit the PASSBAND caption beside its numeric value at enlarged text sizes to prevent overlap.
- Extend theme font routing to general Cantarell labels, ADS-B dashboard labels and VHF headings; connect INFO/Fan Curve descriptive text and shared rail dividers to theme palette roles.
- Add a two-agent screen audit documenting connected native screens and remaining Globe overlay, legacy-layout and browser-companion gaps; preserve received imagery and data-category legends as signal content.
- Expand regression coverage for draft/reset/cancel/apply behavior, save failures, pagination, both sidebar positions, fonts and caches, text shades, selection feedback, passband accents, drag safety, saturation, waterfall alpha and NumPy/scalar conversion parity.
- Update Theme user documentation, the implementation record and the screen audit with the final behavior and remaining verification limits.

Validation: native 1280 × 800 previews inspected; full UI suite has 1,196 tests,
with 1,193 passing and three optional FIS-B engine checks skipped. CM5 hardware
interaction and receiver/audio soak validation remain device checks.
