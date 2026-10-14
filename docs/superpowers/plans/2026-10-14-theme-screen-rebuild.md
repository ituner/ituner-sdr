# Theme Screen Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Theme screens with a full-canvas, visual, live editor and move Theme from Settings to Display.

**Architecture:** Keep `ThemeLibrary` and the version-1 saved schema as the persistence boundary. Add a pure color-math module; rebuild `ThemeEditor` around draft state and shared hit geometry; draw the library, preview scenes, inspector, picker, and confirmation in the existing Pygame/OpenGL UI. Navigation enters and leaves the Theme Library through Display.

**Tech Stack:** Python 3.12, Pygame/OpenGL, `unittest`, existing `UI/.venv/bin/python`.

## Global Constraints

- Keep built-ins **Default**, **Default Inverted**, **Green**, and **Black & White**; built-ins cannot be overwritten or deleted.
- Preserve version-1 JSON theme fields and every existing palette key.
- New/Edit use all 1280 × 800 logical pixels. Back remains `(1034, 728, 1270, 792)`.
- Default picker is rainbow hue plus shades; hex is Advanced only.
- `Apply Matching Shades` affects only the selected semantic family and preserves alpha.
- Transparency is numeric 0–100, where 0 is opaque and 100 invisible.
- Changes apply live to the running app without saving until Save Theme succeeds.
- Dirty Back offers Save & Leave, Discard & Leave, Keep Editing.
- Theme is in Display, above Reset Display; Library Back returns to Display.
- Do not clear waterfall history or change receiver/audio state during editing.
- Preserve unrelated untracked files. Do not push without an explicit request.

---

### Task 1: Move Theme navigation to Display

**Files:** `UI/kiwi_gl_display.py`, `UI/test_ui_navigation.py`, `UI/test_board_v1.py`

**Interfaces:** `SETTINGS_MENU_ITEMS` omits `theme`; `DISPLAY_THEME_BOX` is the 236 × 64 touch target; `display_action_at(x, y)` returns `("theme", None)` for it.

- [ ] Add a failing navigation test that Theme is absent from Settings, Display Theme occupies the full 236 px rail width, and Reset Display remains below it.
- [ ] Run `UI/.venv/bin/python -m unittest UI.test_ui_navigation` from repository root and confirm the new assertion fails.
- [ ] Add Display geometry/drawing/hit dispatch and route Theme Library Back to Display. Keep desktop Display popup behavior consistent.
- [ ] Re-run the focused navigation tests and commit the navigation change.

### Task 2: Add pure visual color controls

**Files:** create `UI/theme_colors.py`; update `UI/test_theme_system.py`.

**Interfaces:** `shade_grid(hue: float) -> tuple[tuple[int,int,int], ...]`; `recolor_family(colors: dict, keys: tuple[str,...], hue: float) -> dict`; `transparency_percent(color: list[int]) -> int`; `with_transparency(color: list[int], percent: int) -> list[int]`.

- [ ] Write tests for hue/shade values, family-only changes, retained lightness ordering and alpha, and 0/100 transparency endpoints.
- [ ] Run the focused tests and confirm the new behavior fails.
- [ ] Implement the pure conversions with the standard-library `colorsys` module, clamp inputs, and preserve RGB-versus-RGBA length.
- [ ] Re-run focused tests and commit the color behavior.

### Task 3: Rebuild Theme editor state and touch geometry

**Files:** `UI/theme_editor.py`, `UI/test_theme_system.py`.

**Interfaces:** `ThemeEditor.begin(theme=None)`, `ThemeEditor.tap(x,y)`, `ThemeEditor.drag(x,y)`, `theme_screen_boxes(editor)`, `ThemeEditor.dirty`, `ThemeEditor.preview`. The editor owns modal state; the library owns only persistence.

- [ ] Replace obsolete two-column/keypad tests with tests for full-screen card actions, preview-scene selection, semantic part selection, hue/shade/transparency edits, dirty comparison, live runtime application, and all Back outcomes.
- [ ] Run the focused tests and confirm failures against the old editor.
- [ ] Implement reusable geometry, card paging, a semantic key map covering every palette key, draft snapshots, live application, keyboard/name and Advanced hex editing, save/rollback, and delete confirmation.
- [ ] Run `UI/.venv/bin/python -m unittest UI.test_theme_system`, fix failures, and commit the editor state.

### Task 4: Render the full-canvas Library and editor

**Files:** `UI/kiwi_gl_display.py`, `UI/test_theme_system.py`.

**Interfaces:** `draw_theme_panel(text_cache, editor)` consumes the state and boxes from Task 3; modal draws last and blocks all underlying hits.

- [ ] Write geometry/draw tests for the fixed Back target, 1280 px canvas, separate preview scenes, color inspector, transparency number input, card actions, and modal button visibility.
- [ ] Run focused tests and confirm the drawing expectations fail.
- [ ] Replace the old fixed left preview / center edit / right rail view with full-width library and editor rendering; use shared theme-aware text-only button helpers, checkerboard alpha samples, and the current Zoom-style notice function.
- [ ] Wire drag dispatch for the rainbow strip, keeping one color update per rendered frame where possible.
- [ ] Re-run focused tests and commit the presentation.

### Task 5: Integration and regression verification

**Files:** `UI/kiwi_gl_display.py`, `UI/test_theme_system.py`, `UI/test_ui_navigation.py`, `UI/test_board_v1.py`.

**Interfaces:** Theme entry/exit must use Display as its parent; left sidebar coordinates and the fixed Back target must still agree.

- [ ] Test apply/save/restart, built-in customization, discard restore, save failure, alpha persistence, left sidebar, and an unchanged waterfall generation/receiver snapshot during edits.
- [ ] Run `UI/.venv/bin/python -m unittest discover -s UI -p 'test_*.py'` and `git diff --check`; fix regressions related to this rebuild.
- [ ] Open the Python UI for a host smoke test and verify touch-size controls and scene layout at 1280 × 800. Record CM5 hardware verification as remaining if no device is available.
- [ ] Commit any integration fixes and report what was verified. Do not push until requested.
