# Guided Theme Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the simulated Theme Editor Preview with six simple category pages and a live VIEW APP mode while preserving saved themes and every palette key.

**Architecture:** Build the guided editor alongside the current editor, then switch the running app to it and remove the obsolete interface after its tests pass. `UI/theme_editor.py` owns draft/navigation state and touch geometry, `UI/theme_screen_render.py` paints those states, `UI/theme_colors.py` performs pure color transforms, and `UI/kiwi_gl_display.py` routes real app input during VIEW APP. Keep `UI/theme_system.py` persistence and schema unchanged.

**Tech Stack:** Python 3.12, Pygame/OpenGL, `unittest`; run tests with `UI/.venv/bin/python` from the `UI/` directory.

## Global Constraints

- Design source: `docs/superpowers/specs/2026-10-15-guided-theme-editor-design.md`.
- Canvas is 1280 × 800; BACK remains `(1034, 728, 1270, 792)`, a 236 × 64 px control. PREV, NEXT, and VIEW APP share its bottom row on the left.
- Exactly six category pages: Surfaces; Text; Buttons & states; S-meter & passband; Spectrum & waterfall; Layout & sizing. Show at most three family rows at once.
- Color changes apply to the running draft immediately. Family recoloring retains relative shade order and each key's alpha; a 0–100% transparency input appears only for RGBA keys.
- VIEW APP shows the real running app, keeps normal app navigation and interaction, and has a bottom-center 236 × 64 px RETURN TO EDITOR control. It neither saves nor restarts the receiver, waterfall, spectrum, audio, or decoders.
- Built-in themes and the version-1 saved-theme JSON schema remain unchanged. BACK uses Save & Leave, Discard & Leave, or Keep Editing for a dirty draft.
- Preserve existing local changes in `UI/kiwi_gl_display.py`, `UI/test_smeter_styles.py`, and untracked docs; do not reset or stage them outside the exact files of a task.

## File Map

- Modify `UI/theme_colors.py`: pure hue/lightness/strength family transform, preserving alpha.
- Modify `UI/theme_editor.py`: guided category model, color/fine-tune/meter/layout actions, view-app state, and the single source of touch geometry. Keep the old editor path intact until Task 6.
- Modify `UI/theme_screen_render.py`: guided category renderer and overlays. Keep Theme Library drawing unchanged.
- Modify `UI/kiwi_gl_display.py`: instantiate the guided editor, route VIEW APP touches to the app, draw RETURN TO EDITOR, and retain sidebar-left coordinate mapping.
- Modify `UI/test_theme_system.py`, `UI/test_smeter_styles.py`: focused state, drawing, persistence, and regression tests; remove only tests for the obsolete Preview interface in Task 7.

---

### Task 1: Pure family color transform

**Files:** Modify `UI/theme_colors.py`; test in `UI/test_theme_system.py`.

**Interfaces:** Produce `recolor_family_shades(colors: dict, keys: tuple[str, ...], hue: float, lightness: float, strength: float) -> dict`. Inputs are normalized to `0..1`; output is a new palette dict. Keep existing `recolor_family` for the old editor until Task 7.

- [ ] **Step 1: Write a failing test** using two differently lit RGBA surfaces plus one unrelated RGB text key. Assert `strength=0` yields gray RGB, `strength=1` yields colored RGB, the darker source stays darker, every alpha is unchanged, and the input dict is unchanged:

```python
base = {"dark": [25, 25, 25, 80], "light": [175, 175, 175, 220], "text": [240, 240, 240]}
result = recolor_family_shades(base, ("dark", "light"), 0.32, 0.50, 0.0)
self.assertEqual(result["dark"][0], result["dark"][1])
self.assertLess(sum(result["dark"][:3]), sum(result["light"][:3]))
self.assertEqual([result["dark"][3], result["light"][3]], [80, 220])
self.assertEqual(result["text"], base["text"])
self.assertEqual(base["dark"], [25, 25, 25, 80])
```

- [ ] **Step 2: Run the new test** from `UI/`: `.venv/bin/python -m unittest test_theme_system.ThemeSystemTests.test_guided_family_shades_preserve_alpha_and_order -v`. Expect import failure because the function does not exist.
- [ ] **Step 3: Implement** the pure transform with `colorsys.rgb_to_hls` / `colorsys.hls_to_rgb`; shift each source lightness toward the requested lightness by the same bounded offset, use requested strength as saturation, and copy untouched keys and alpha. Clamp RGB to integer `0..255` without changing the source dict:

```python
def recolor_family_shades(colors, keys, hue, lightness, strength):
    result = {key: list(value) for key, value in colors.items()}
    samples = [colorsys.rgb_to_hls(*(v / 255 for v in colors[key][:3]))[1] for key in keys]
    offset = max(0.0, min(1.0, lightness)) - sum(samples) / len(samples)
    for key, old in ((key, colors[key]) for key in keys):
        old_light = colorsys.rgb_to_hls(*(v / 255 for v in old[:3]))[1]
        new_light = max(0.02, min(0.98, old_light + offset))
        rgb = colorsys.hls_to_rgb(hue % 1.0, new_light, max(0.0, min(1.0, strength)))
        result[key] = [*(round(255 * value) for value in rgb), *old[3:]]
    return result
```

- [ ] **Step 4: Run** the focused test and `test_theme_system.ThemeSystemTests.test_visual_color_math_preserves_family_boundary_and_alpha`; both pass. Run `git diff --check`.
- [ ] **Step 5: Commit only** `UI/theme_colors.py` and the relevant test edits with `feat(ui): add guided theme color transform`.

### Task 2: Six-category state and touch geometry, in parallel with the old editor

**Files:** Modify `UI/theme_editor.py`; test in `UI/test_theme_system.py`.

**Interfaces:** Produce `GUIDED_CATEGORIES`, `GuidedThemeEditor(ThemeEditor)`, and `guided_theme_screen_boxes(editor, *, ignore_overlay=False) -> dict[str, tuple[int, int, int, int]]`. Keep `ThemeEditor` and `theme_screen_boxes` working for the old tests while building the replacement.

- [ ] **Step 1: Write failing tests** for the six category names and family mapping; opening a new draft starts at category 0; NEXT/PREV clamp to `0..5`; navigation leaves the draft unsaved; row boxes and navigation never overlap BACK; and VIEW APP exposes only RETURN TO EDITOR:

```python
editor = GuidedThemeEditor(self.library)
editor.begin()
self.assertEqual(editor.category_index, 0)
self.assertEqual(editor.category_families, ("SURFACES", "FOOTER"))
editor.tap(*center(guided_theme_screen_boxes(editor)["next"]))
self.assertEqual(editor.category_index, 1)
self.assertFalse(editor.dirty)
editor.tap(*center(guided_theme_screen_boxes(editor)["view_app"]))
self.assertEqual(guided_theme_screen_boxes(editor), {"return_to_editor": (522, 728, 758, 792)})
```

Define `center(box)` in the test as `((box[0]+box[2])/2, (box[1]+box[3])/2)`. Test all six categories and `len(visible_family_rows) <= 3`, not only the first two.

- [ ] **Step 2: Run** `test_theme_system.ThemeSystemTests.test_guided_category_navigation_and_geometry` from `UI/`; expect import failure for `GuidedThemeEditor`.
- [ ] **Step 3: Add** category tuples that cover all `COLOR_GROUPS` exactly once; add `category_index`, `selected_family`, `view_app`, `fine_tune`, and `meter_gallery_open` to the guided subclass. Its `begin()` calls `super().begin()` and resets guided state. Guided browse delegates to the existing library behavior; guided edit uses the new boxes. A category change selects its first family and never mutates the draft. Use these navigation branches:

```python
if action == "previous":
    self.category_index = max(0, self.category_index - 1)
elif action == "next":
    self.category_index = min(len(GUIDED_CATEGORIES) - 1, self.category_index + 1)
elif action == "view_app":
    self.view_app = True
elif action == "return_to_editor":
    self.view_app = False
```

`guided_theme_screen_boxes` keeps BACK fixed; place PREV `(24,728,260,792)`, NEXT `(268,728,504,792)`, VIEW APP `(512,728,748,792)`, and RETURN TO EDITOR `(522,728,758,792)`. Put no more than three family rows between y=120 and y=328; preserve overlay/keypad hit priority.

- [ ] **Step 4: Run** the new geometry tests plus the existing Theme Library paging tests; run `git diff --check`.
- [ ] **Step 5: Commit only** `UI/theme_editor.py` and the focused test edits with `feat(ui): add guided theme category state`.

### Task 3: Family color controls, fine tuning, and reset

**Files:** Modify `UI/theme_editor.py`, `UI/theme_screen_render.py`; test in `UI/test_theme_system.py`.

**Interfaces:** Guided actions are `family:<name>`, `hue`, `tone`, `fine_tune`, `key:<palette_key>`, `alpha_open`, `hex_open`, and `reset_category`. `GuidedThemeEditor.drag(control, x, y)` accepts `control` equal to `"hue"` or `"tone"` only when no overlay is open. Renderer uses `draw_guided_theme_editor(cache, editor, ui)` and the same `guided_theme_screen_boxes` as touch handling.

- [ ] **Step 1: Write failing tests** that select `BUTTONS`, drag the rainbow and tone field, assert the running `APP_UI_STYLE.palette` updates, alpha and unrelated family keys remain identical, neutral gray is reachable, and RESET CATEGORY restores only current category keys. Enter FINE TUNE, select `passband_fill`, change transparency to 40%, cancel a later transparency edit, and assert the earlier value remains. Assert hex is absent from the ordinary page and available only in FINE TUNE.

```python
editor = GuidedThemeEditor(self.library)
editor.begin()
editor.category_index = 2
editor.tap(*center(guided_theme_screen_boxes(editor)["family:BUTTONS"]))
old_text = list(editor.draft["colors"]["text"])
tone = guided_theme_screen_boxes(editor)["tone"]
editor.drag("tone", tone[0], (tone[1] + tone[3]) / 2)
self.assertEqual(editor.draft["colors"]["text"], old_text)
self.assertEqual(editor.draft["colors"]["surface"][3], editor.baseline["colors"]["surface"][3])
```

- [ ] **Step 2: Run** `test_theme_system.ThemeSystemTests.test_guided_color_controls_and_fine_tune -v`; expect missing guided color boxes/actions.
- [ ] **Step 3: Implement** hue strip + two-dimensional tone field (`x` = color strength, `y` = lightness), live family update through `recolor_family_shades`, and `RESET CATEGORY` from `baseline` only for family names in the current category. Snapshot the family source when its row is selected so repeated drag samples do not cumulatively alter lightness. Show a single current-color sample and optional FINE TUNE; the fine-tune list pages individual keys three at a time. Reuse `_alpha_key`, `_hex_key`, `_name_key`, and existing overlays, but expose alpha only for four-channel keys. Call `_apply_draft()` only when normalized RGB/alpha actually changes.

```python
keys = dict(COLOR_GROUPS)[self.selected_family]
updated = recolor_family_shades(self.family_source, keys,
                               self.hue, self.lightness, self.strength)
if updated != self.draft["colors"]:
    self.draft["colors"] = updated
    self._apply_draft()
```

The guided renderer draws no simulated HOME/RECEIVERS/POPUPS preview, no scene tabs, no 16-swatch grid, and no normal-path Apply button. Its color area labels the chosen family and draws the hue/tone controls using geometry from `guided_theme_screen_boxes`. RESET CATEGORY also refreshes the selected family's source snapshot and picker position so the next drag starts from the restored colors. Keep editor navigation and picker labels on a legible fixed chrome palette even when the draft has low-contrast colors, so the user can recover or discard it.

- [ ] **Step 4: Run** focused guided color/overlay tests, legacy `test_transparency_percent_input_maps_to_alpha`, and `test_named_theme_survives_restart_and_updates_shared_style`; run `git diff --check`.
- [ ] **Step 5: Commit only** the editor, renderer, and focused tests with `feat(ui): edit theme color families live`.

### Task 4: Layout controls and S-meter face gallery

**Files:** Modify `UI/theme_editor.py`, `UI/theme_screen_render.py`; test in `UI/test_theme_system.py` and `UI/test_smeter_styles.py`.

**Interfaces:** Guided actions `option:straight|rounded|left|right|original|imperial|metric`, `text:smaller|larger|reset`, `meter_gallery`, `meter:<id>`, `meter_previous`, `meter_next`, and `meter_close` all call `_apply_draft()` on a changed value.

- [ ] **Step 1: Write failing tests** for straight/rounded corners, left/right sidebar, all three units, 80–120% text-size bounds in 5% increments, and meter choice immediately appearing in `theme_system.runtime_theme`. Confirm gallery pages contain at most six face cards and any meter can be reached; category 4 itself shows only one selected-face control rather than all cards.

```python
editor = GuidedThemeEditor(self.library)
editor.begin()
editor.category_index = 3
editor.tap(*center(guided_theme_screen_boxes(editor)["meter_gallery"]))
editor.tap(*center(guided_theme_screen_boxes(editor)["meter:aviation"]))
self.assertEqual(theme_system.runtime_theme["smeter_style"], "aviation")
```

- [ ] **Step 2: Run** `test_smeter_styles.MeterTests.test_guided_gallery_applies_face_live -v`; expect a missing gallery action.
- [ ] **Step 3: Add** category-6 controls with active styles and only valid values; meter-gallery overlay uses the existing `METER_STYLES` and existing face drawing helper. Ensure its hit boxes match the rendered cards; selection closes the gallery and applies the draft. Disable previous/next on gallery boundaries. Preserve current `units="original"` on the Default built-in until a user chooses a new unit.

```python
if action.startswith("meter:"):
    choice = action.split(":", 1)[1]
    if choice in METER_STYLES and self.draft["smeter_style"] != choice:
        self.draft["smeter_style"] = choice
        self._apply_draft()
    self.meter_gallery_open = False
```

- [ ] **Step 4: Run** focused gallery/layout tests and the existing meter calibration and built-in-theme tests; run `git diff --check`.
- [ ] **Step 5: Commit only** the editor, renderer, and focused tests with `feat(ui): guide meter and layout choices`.

### Task 5: Make VIEW APP display and control the real running app

**Files:** Modify `UI/kiwi_gl_display.py`, `UI/theme_editor.py`; test in `UI/test_theme_system.py`.

**Interfaces:** Add pure `theme_editor_captures_touch(editor, x, y) -> bool` in `UI/kiwi_gl_display.py`. It returns true for every touch in edit mode except while `view_app` is true, when only RETURN TO EDITOR is captured. `GuidedThemeEditor.tap()` handles that return action.

- [ ] **Step 1: Write failing tests** for touch ownership inside/outside `(522,728,758,792)`, draft/category survival across VIEW APP, and sidebar-left coordinate mapping. Patch `draw_theme_panel` and `draw_styled_text_button` to assert VIEW APP draws the app plus only RETURN TO EDITOR, not the full-screen editor. Verify a theme edit does not call `state.set_waterfall` or clear a waterfall buffer.

```python
editor = GuidedThemeEditor(self.library)
editor.begin()
editor.view_app = True
self.assertFalse(ui.theme_editor_captures_touch(editor, 100, 300))
self.assertTrue(ui.theme_editor_captures_touch(editor, 640, 760))
```

- [ ] **Step 2: Run** `test_theme_system.ThemeSystemTests.test_view_app_keeps_live_controls_and_return_target -v`; expect the helper to be missing.
- [ ] **Step 3: In the main loop**, choose `gesture="theme"` only when `theme_editor_captures_touch` is true. During VIEW APP draw the real app and RETURN TO EDITOR instead of `draw_theme_panel`; when the return box is pressed, restore guided editing without re-running `begin()`. For a theme drag, identify whether its starting point is in the `hue` or `tone` box, then call `theme_editor.drag(control, x, y)` on motion and release. Audit every `theme_editor.open` gate in `UI/kiwi_gl_display.py`: the gesture priority, scope drag eligibility, `activate_navigation_item`, `rail_relocation_active`/`desktop_logical_point`, drawer idle behavior, and render overlay. Navigation in VIEW APP must not clear `editor.open` or its draft. Use the same geometry for the return drawing and hit test:

```python
def theme_editor_captures_touch(editor, x, y):
    return editor.open and (not editor.view_app or contains(
        guided_theme_screen_boxes(editor)["return_to_editor"], x, y
    ))
```

Retain the current change-of-sidebar handling so instrument position and touch mapping agree while a draft places the rail on the left. No receiver/audio/waterfall reset is part of this route.

- [ ] **Step 4: Run** the focused view tests, `test_theme_system`, and the full `unittest discover` suite from `UI/`. Check `git diff --check`.
- [ ] **Step 5: Commit only** main-loop, editor, and focused tests with `feat(ui): inspect draft themes on the live app`.

### Task 6: Switch the app to the guided editor and verify save/discard

**Files:** Modify `UI/kiwi_gl_display.py`, `UI/theme_editor.py`, `UI/theme_screen_render.py`; test in `UI/test_theme_system.py`.

**Interfaces:** The runtime constructs `GuidedThemeEditor(ThemeLibrary(...))`. Theme Library behavior remains on its existing path. Guided BACK/save/discard delegates to the same `ThemeLibrary.upsert` and `_leave_edit` semantics; failed save retains the draft and emits the existing Zoom-style error notice.

- [ ] **Step 1: Write failing end-to-end state tests**: Library NEW → category edit → VIEW APP → RETURN → BACK → SAVE creates one custom theme; DISCARD restores the entry theme; KEEP EDITING retains the category; a failed save leaves draft and app appearance intact; customizing a built-in creates a new ID. Assert `runtime_theme` updates on selection of meter face, side, color, and text scale without requiring a Save button.

```python
editor = GuidedThemeEditor(self.library)
editor.open = True
editor.tap(*center(theme_screen_boxes(editor)["new"]))
editor.set_color((25, 95, 72))
editor.back()
editor.tap(*center(guided_theme_screen_boxes(editor)["leave_save"]))
self.assertEqual(self.library.active_id, editor.selected_id)
```

- [ ] **Step 2: Run** `test_theme_system.ThemeSystemTests.test_guided_save_discard_and_failure -v`; expect missing guided confirmation geometry or runtime instantiation.
- [ ] **Step 3: Switch** the application construction to `GuidedThemeEditor`; direct `draw_theme_screen` to the guided renderer only in guided edit mode and keep the existing Library renderer. Route the old alpha/hex/name keypads and three-choice BACK overlay from guided geometry. When `save()` or discard leaves edit mode, clear `view_app`, fine-tune, and meter-gallery state. Restore the Display navigation parent only after the Theme Library actually closes, not when VIEW APP temporarily hides the editor.

```python
theme_editor = GuidedThemeEditor(
    theme_system.ThemeLibrary(args.theme_file),
    notice_duration=args.zoom_osd_seconds,
)
```

- [ ] **Step 4: Run** new guided flow tests and full UI `unittest discover`; manually walk the Library → edit → View App → return → save and discard paths on the Mac app. Run `git diff --check`.
- [ ] **Step 5: Commit only** the runtime switch, editor/renderer integration, and tests with `feat(ui): use guided theme editor`.

### Task 7: Remove old Preview and migrate obsolete tests

**Files:** Modify `UI/theme_editor.py`, `UI/theme_screen_render.py`, `UI/kiwi_gl_display.py`, `UI/test_theme_system.py`, `UI/test_smeter_styles.py`.

**Interfaces:** Export the guided implementation as the public `ThemeEditor` and `theme_screen_boxes` used by the rest of the app; retain `COLOR_GROUPS`, `ThemeLibrary`, and palette keys. Remove `GuidedThemeEditor` transitional name, old scene/panel/preview state, `EDITOR_PREVIEW_BOX`, `EDITOR_INSPECTOR_BOX`, preview hit boxes, old `_draw_preview_*` functions, and old 16-swatch editor UI. Keep exact hex and per-key alpha only behind FINE TUNE.

- [ ] **Step 1: Replace obsolete tests** `test_preview_scene_and_color_family_taps_do_not_change_receiver`, `test_full_canvas_editor_and_saved_text_scale`, `test_theme_preview_uses_full_canvas_and_scene_controls`, old `panel:*`/`family_open`/`shade:*` routes, and old meter chooser tests with guided category and live-view assertions. Update the S-meter persistence test to enter the gallery through category 4. Keep Library, persistence, color-token, receiver, and signal tests unchanged.
- [ ] **Step 2: Run** full UI `unittest discover -p 'test_*.py' -q` from `UI/`; fail if any test still refers to a removed Preview/scene/panel action.
- [ ] **Step 3: Remove** transitional legacy code and rename guided exports. Ensure `rg -n 'preview:|scene:|panel:advanced|EDITOR_PREVIEW_BOX|_draw_preview_' UI/theme_editor.py UI/theme_screen_render.py UI/test_theme_system.py` has no matches. Confirm `COLOR_GROUPS` still covers `set(COLOR_NAMES)` exactly.

```python
assert set(COLOR_NAMES) == {
    key for _family, keys in COLOR_GROUPS for key in keys
}
```

- [ ] **Step 4: Run** full UI suite, `git diff --check`, and a visual Mac check at 1280 × 800 for both sidebar positions, all six categories, meter gallery, View App, BACK choices, and the four built-in themes. Record any CM5-only touch/performance findings separately; Mac tests do not establish CM5 results.
- [ ] **Step 5: Commit only** obsolete-code removal and migrated tests with `refactor(ui): remove simulated theme preview`.

## Final verification

From `UI/`, run `.venv/bin/python -m unittest discover -p 'test_*.py' -q`; from the repository root, run `git diff --check` and inspect `git status --short` so pre-existing changes remain visible. Check a connected receiver for continued audio/waterfall motion while VIEW APP is open and while colors are dragged. The app's Mac visual check is required before asking the user to test; CM5 touch and frame-time validation remains a separate device check.
