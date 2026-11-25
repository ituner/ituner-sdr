# HOME Theme Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace the granular Theme screen with preset selection and Accent, Text size, Straight/Rounded, Color intensity, and Border intensity controls over real, full-size HOME.

**Architecture:** Retain the GPU HOME preview and the existing theme library. Store built-in customizations separately from immutable presets, keep legacy saved themes, and keep operational settings independent of choosing a preset. Spectrum and waterfall colors follow the chosen theme. Rendering and input share the same physical screen rectangles, including left-sidebar placement.

**Tech Stack:** Python, Pygame, OpenGL, unittest, existing semantic UI styles.

## Global Constraints

- Implement Theme first; pause for user testing before changing DISPLAY.
- HOME stays 1280 × 800; the inspector overlays the RF canvas without resizing it.
- Accent, text size, corners, color intensity, and border intensity are draft-only until Apply; Reset restores all five to the selected preset baseline; Cancel restores the entry setup.
- Preserve receiver state, sidebar side, units, meter, instrument placement, numerical contrast ranges, and raw signal history. Theme changes recolor spectrum and waterfall as explicitly requested in the follow-up.
- Use the existing 80–120% text bounds and 0/8 px corner choices.
- Keep saved themes and version-1 documents readable; no automatic custom-theme proliferation.
- Protected inspector controls remain readable and use shared button rendering.
- No receiver connections or preference writes during screenshots.

## Task 1: Session and persistence

Files: `UI/theme_editor.py`, `UI/theme_system.py`, `UI/test_theme_editor.py`, `UI/test_theme_save.py`.

Interfaces: `ThemeEditor.show()`, `select_theme(identifier)`, `reset_theme()`, `save()`, `back()`, `cancel()`, `tap(x,y)`, and `theme_screen_boxes(editor)`. `ThemeLibrary.customize_builtin(theme)` commits an override atomically. Existing `get`, `activate`, `set_smeter_style`, and saved-theme `upsert` remain supported.

- [x] Write and run behavioral tests before implementation: selecting Green enters full-screen editing without writes; Accent/text/corners change only the draft; Reset restores the selected built-in; Cancel restores entry; Apply survives restart; repeated saves retain one built-in override; save failure rolls back.
- [x] Implement the session and bounded accent mapping. Keep operational fields from the entry snapshot and retain per-preset drafts when returning to the chooser.
- [x] Implement optional `builtin_overrides` in the existing version-1 document, with rollback on save failure. Persist optional `waterfall_style` so interface preset IDs do not change the current signal mapping.
- [x] Run `UI/.venv/bin/python -m unittest discover -s UI -p 'test_theme_*.py'` and update obsolete granular-editor assertions to the approved workflow.

Example contract:

```python
editor.show()
editor.select_theme('green')
assert editor.fullscreen
editor.draft['radius'] = 8
editor.reset_theme()
assert editor.preview['radius'] == 0
assert editor.open  # Reset does not Apply.
```

## Task 2: Native rendering and event integration

Files: `UI/theme_screen_render.py`, `UI/kiwi_gl_display.py`, `UI/test_theme_editor.py`, `UI/test_smeter_styles.py`.

Consumes Task 1's draft and rectangles. Produces a full-screen live HOME layer, a four-preset chooser with legacy-theme pagination, and a hideable protected inspector with Accent/Text/Corners/Reset/Choose theme/Cancel/Apply.

- [x] Add tests for physical rectangles on both sidebar sides, non-overlap, minimum target heights, explicit Hide/Show, background-tap neutrality, and full-size preview drawing.
- [x] Draw HOME at `(0,0,1280,800)` in both chooser and customization; overlay controls using a protected neutral style.
- [x] Wire candidate rendering and waterfall-style signatures. Prevent Theme Apply from invoking meter-driven frequency relocation when the meter did not change.
- [x] Replace tests for the removed Theme meter gallery with tests of the existing independent Home meter picker.
- [x] Run Theme, meter, preview, navigation, and board-layout regression suites.

## Task 3: Verification and handoff

Files: `docs/themes.md`, this plan; screenshots outside the application checkout.

- [x] Update user documentation for preset tap → full-size HOME, corner choices, exact reset scope, legacy themes, and independent signal settings.
- [x] Render actual native screenshots, including rounded corners, reset, hidden inspector and left-side placement. Verify no receiver/persistence activity and inspect labels/overlap.
- [x] Run the full UI unittest discovery, record failures/skips honestly, and run `git diff --check`.
- [x] Obtain an independent final review of persistence rollback, preset immutability, input mapping, and signal-color preservation; fix material findings and rerun the relevant suites.
- [x] Leave local feature-branch changes reviewable for the user's Mac/CM5 testing; do not push or change DISPLAY in this stage.

## Execution notes

- Starting point: clean `5546c51`; local feature branch `work/theme-home-editor` in the user's existing checkout so their usual Mac launch command exercises the changes.
- Approval: the user approved the mockup flow and added Straight/Rounded before authorizing implementation.
- No shared implementation interfaces outside the three files above; existing ThemeLibrary callers remain compatible.

## Verification record

- Theme workflow: 14 tests passed, including observed failing tests before the new flow and the 120% passband spacing correction.
- Complete UI suite: 1,157 tests run; 1,154 passed; three existing FIS-B integration tests skipped because the optional engine is not installed. No Theme checks skipped.
- Native renderer: six isolated 1280 × 800 screens captured and visually checked, including rounded controls, reset, hidden inspector, left sidebar, and inverted appearance at 120% text. No receiver workers or preference writes in this rendering check.
- Independent review: no material correctness defects. Clarified the Choose theme/Cancel wording identified during review.
- Additional observed issue: PASSBAND caption overlapped its numeric value at 120%; a native-font regression test reproduced it, then passed after bounding the caption to its available space.
- Python compilation and git diff whitespace check passed.
- CM5 touch, hardware performance, and real receiver/audio validation remain user/device checks. DISPLAY restructuring is deliberately the next stage after this Theme screen is tested.
- Changes remain local and uncommitted on work/theme-home-editor; no push or deployment performed.

## Approved follow-up: pagination, intensity, and RF appearance

- User requires both Previous and Next visible, including disabled directions and single-page choosers. Disabled input is inert; pagination does not select a theme.
- User clarified COLOR INTENSITY means brighter/dimmer colors, not saturation; implement relative brightness 50–150%, default100%. BORDER INTENSITY controls outline visibility25–200%, default100%, with5% steps and sliders. Reset covers both.
- User explicitly reversed signal-color isolation: selected themes recolor spectrum and waterfall again. Keep numerical measurement data, contrast bounds, and history unchanged. Repair earlier interface-only builtin overrides at load without writing the preference file.
- Persist bounded optional parameters and a sanitized original base for existing named themes, preventing cumulative brightness on reopen.
- Preserve essential text and pressed-button contrast during dimming. Inspector controls use their protected palette and physical geometry.
- Regression tests cover paging boundaries, brightness/border independence, original reset, restart, legacy base persistence, inverted outlines, pointer-drag capture, NumPy/fallback RGB conversion, alpha, and waterfall cache invalidation.

### Follow-up verification

- Pagination regression failed with hidden buttons, then passed with fixed visible disabled controls.
- New intensity and plot-color tests failed before implementation; all76 Theme checks now pass, including scalar/NumPy waterfall RGB and alpha checks.
- Full UI suite after follow-up:1,168 run;1,165 passed; the same three optional FIS-B engine tests skipped. No Theme tests skipped.
- Native screenshots inspected for visible disabled pagination, restored Green and Inverted plot colors, brightness80%/border140%, corner changes and left-side placement.
- Independent delta review found no material defects; existing legacy restart and save-failure tests cover those behaviors separately.
- User's later request explicitly supersedes the initial signal-color preservation design; numerical signal values, receiver controls and contrast modes remain unchanged.

## Approved follow-up: floating customization panel

- User requires a taller panel with padding between description text and sections. Height changes398→494px; full-size HOME remains unchanged.
- User explicitly requests that the candidate theme apply to the popup's contents too, superseding the protected neutral inspector. Its palette, text scaling, border intensity and corner radius now follow the preview. Physical touch positions stay fixed.
- Background uses the selected theme's background at228/255 alpha, with a subtle shadow. The chooser remains a separate neutral selection surface.
- Regression tests reproduce the old cramped geometry and neutral styling, then verify the new theme-aware translucent panel and readable light-theme intensity values.

## Final approved behavior and delivery — 5 November 2026

- Later user instructions supersede intermediate defaults and neutral-panel notes above: both windows share a theme-aware floating style; border intensity defaults to25%; color intensity defaults to100%; Color contains the intensity and saturation sliders without step buttons.
- Color has side-by-side Accent/Text sections, smaller unlabeled black/white swatches, rainbow strips, clear selection feedback, and Save/Cancel back to Customize.
- Five font styles, dimmed related subtitle colors, passband accent wiring, and the Customize drag-crash correction are included.
- The exhaustive final change list is in `docs/theme-redesign-changelog.md`; outstanding screen wiring is recorded in `docs/theme-screen-audit-2026-11-05.md`.
- The user explicitly authorized committing this complete Theme change and pushing it to lucaiuli/main. Publish the Theme commit from refreshed public-fork/main, without unrelated local merge history.
- Final validation before delivery:1,196 UI tests run,1,193 passed,3 skipped for the optional FIS-B engine; native previews inspected and whitespace checks clean. No CM5 hardware validation is claimed.
