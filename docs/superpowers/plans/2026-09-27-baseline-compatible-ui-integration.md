# Baseline-Compatible UI Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved icon refresh, sidebar consistency, parent-aware navigation, and enlarged workspace presentation to PR #11 without replacing or regressing current upstream behavior.

**Architecture:** Treat commits `08588f7`, `a2f5c64`, and `c71268f` as visual references, not cherry-picks. Port assets and behavior into the current `UI/kiwi_gl_display.py` through small pure helpers shared by drawing and hit testing, then adapt individual screens while preserving all current receiver workers and destinations.

**Tech Stack:** Python 3.13 production baseline, Python 3.14 macOS test environment, pygame/OpenGL renderer, unittest, SVG source assets, 64×64 RGBA PNG runtime assets.

## Global Constraints

- Preserve current CM5 application-only installation, legacy installation, seeded display defaults, and 800×1280 logical geometry.
- Preserve KiwiSDR, OpenWebRX, local RTL-SDR, and FM-DX behavior.
- Preserve current Home destinations, including Local RX and Dual; presentation may change but destinations may not disappear.
- Do not replace `UI/kiwi_gl_display.py` with an earlier revision.
- Do not add knob controllers, knob inputs, focus overlays, or knob-specific routing.
- Do not add map/globe navigation mechanics or change existing map gestures and receiver-selection behavior.
- Static visual enlargement of the Constellation workspace is allowed.
- Drawing and hit testing must consume the same geometry helpers.
- Current upstream behavior wins when an older visual rule conflicts with the accepted baseline.
- Run UI tests with the disposable interpreter at `/private/tmp/ituner-ui-integration-venv/bin/python`; do not add a virtual environment to the repository.

---

### Task 1: Refresh and validate menu icon assets

**Files:**
- Modify: `UI/assets/menu-icons-svg/{audio,digi,display,home,receivers,rf,settings,stats}.svg`
- Create: `UI/assets/menu-icons-svg/apps.svg`
- Create: `UI/assets/menu-icons-svg/audio-muted.svg`
- Modify: `UI/assets/menu-icons/*.png`
- Modify: `assets/menu-icons/*.png`
- Create: `UI/test_ui_navigation.py`
- Modify: `UI/kiwi_gl_display.py:384-390`
- Modify: `UI/kiwi_gl_display.py:13269-13300`

**Interfaces:**
- Consumes: Existing `MENU_ICON_ASSET_DIR`, `MENU_ICON_FILENAMES`, and `menu_icon_texture(...)`.
- Produces: `menu_icon_filename(kind: str, muted: bool = False) -> str`, refreshed SVG sources, and synchronized 64×64 PNG assets in both runtime locations.

- [ ] **Step 1: Prepare the disposable Mac test environment**

```bash
python3 -m venv /private/tmp/ituner-ui-integration-venv
/private/tmp/ituner-ui-integration-venv/bin/pip install pygame pillow PyOpenGL numpy
/private/tmp/ituner-ui-integration-venv/bin/python -c 'import pygame, PIL, OpenGL, numpy'
```

Expected: imports succeed. This environment remains outside the repository.

- [ ] **Step 2: Write failing asset and selection tests**

Create `UI/test_ui_navigation.py`:

```python
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiwi_gl_display as ui  # noqa: E402


class MenuIconTests(unittest.TestCase):
    def test_required_runtime_icons_exist_in_both_asset_roots(self):
        required = {
            "apps.png", "audio-muted.png", "audio.png", "digi.png",
            "display.png", "home.png", "receivers.png", "rf.png",
            "settings.png", "stats.png",
        }
        repository = Path(__file__).resolve().parents[1]
        roots = (repository / "UI/assets/menu-icons", repository / "assets/menu-icons")
        for root in roots:
            self.assertEqual(required - {path.name for path in root.glob("*.png")}, set())
            for name in required:
                image = ui.pygame.image.load(str(root / name))
                self.assertEqual(image.get_size(), (64, 64))

    def test_audio_icon_tracks_existing_muted_state(self):
        self.assertEqual(ui.menu_icon_filename("audio", muted=False), "audio.png")
        self.assertEqual(ui.menu_icon_filename("audio", muted=True), "audio-muted.png")
        self.assertEqual(ui.menu_icon_filename("tests", muted=True), "apps.png")
```

- [ ] **Step 3: Run the focused test and verify it fails**

Run:

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest UI/test_ui_navigation.py
```

Expected: FAIL because `menu_icon_filename` and the new UI asset files do not exist.

- [ ] **Step 4: Restore the approved icon artwork from the reference commit**

Use commit `08588f7` as the source for the listed SVG and PNG paths. Restore only menu-icon files; do not restore `kiwi_gl_display.py`, README files, map imagery, or runtime configuration from that commit.

Ensure both runtime directories contain matching copies of:

```text
apps.png
audio-muted.png
audio.png
digi.png
display.png
home.png
receivers.png
rf.png
settings.png
stats.png
```

- [ ] **Step 5: Add a state-aware filename helper and use it during rendering**

Add near `MENU_ICON_FILENAMES`:

```python
MENU_ICON_FILENAMES = {
    "rx": "receivers.png",
    "digital": "digi.png",
    "wspr": "digi.png",
    "tests": "apps.png",
}


def menu_icon_filename(kind, muted=False):
    if kind == "audio" and muted:
        return "audio-muted.png"
    return MENU_ICON_FILENAMES.get(kind, f"{kind}.png")
```

Extend `menu_icon_texture` with `muted=False`, include muted state in its cache key, and call `menu_icon_filename(kind, muted)`. Pass `muted and kind == "audio"` from `draw_lcd_navigation`; keep non-audio callers unchanged.

- [ ] **Step 6: Run focused and FM-DX tests**

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest UI/test_ui_navigation.py UI/test_fmdx.py UI/test_fmdx_ui.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit the icon layer**

```bash
git add UI/assets/menu-icons-svg UI/assets/menu-icons assets/menu-icons UI/kiwi_gl_display.py UI/test_ui_navigation.py
git commit -m "feat: restore refreshed menu icon system"
```

---

### Task 2: Introduce shared drawer geometry and navigation labels

**Files:**
- Modify: `UI/kiwi_gl_display.py:1920-1930`
- Modify: `UI/kiwi_gl_display.py:2369-2378`
- Modify: `UI/kiwi_gl_display.py:7659-7675`
- Modify: `UI/kiwi_gl_display.py:7845-7850`
- Modify: `UI/kiwi_gl_display.py:9420-9425`
- Modify: `UI/kiwi_gl_display.py:13392-13398`
- Modify: `UI/kiwi_gl_display.py:13664-13685`
- Modify: `UI/kiwi_gl_display.py:13852-13890`
- Test: `UI/test_ui_navigation.py`

**Interfaces:**
- Consumes: `LCD_NAV_X0`, `LOGICAL_W`, `lcd_rail_bottom()`, existing panel-box helpers.
- Produces: `lcd_drawer_back_box() -> tuple[float, float, float, float]`, `draw_picker_two_line_button(...)`, and consistent labels without removing current destinations.

- [ ] **Step 1: Write failing geometry and label tests**

Add:

```python
class DrawerGeometryTests(unittest.TestCase):
    def test_home_destinations_are_preserved_with_updated_mode_label(self):
        kinds = [kind for kind, _label in ui.MENU_ITEMS]
        self.assertEqual(kinds, ["local_rx", "rx", "audio", "digital", "dual", "settings"])
        self.assertEqual(dict(ui.MENU_ITEMS)["digital"], "MODES")

    def test_settings_apps_and_back_labels_preserve_routes(self):
        labels = dict(ui.SETTINGS_MENU_ITEMS)
        self.assertEqual(labels["tests"], "APPS")
        self.assertEqual(labels["settings_back"], "BACK")

    def test_drawers_share_one_back_target(self):
        expected = ui.lcd_drawer_back_box()
        self.assertEqual(ui.lcd_radio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_display_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_audio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_filter_drawer_boxes()["close"], expected)

    def test_settings_back_tile_uses_shared_back_target(self):
        last = len(ui.SETTINGS_MENU_ITEMS) - 1
        self.assertEqual(ui.lcd_nav_box(last, len(ui.SETTINGS_MENU_ITEMS)), ui.lcd_drawer_back_box())
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest UI/test_ui_navigation.py
```

Expected: FAIL for old labels and non-shared drawer geometry.

- [ ] **Step 3: Add the shared Back geometry and adapt all current drawer helpers**

```python
def lcd_drawer_back_box():
    """One physical Back target shared by every right-sidebar route."""
    return (
        LCD_NAV_X0 + 10,
        lcd_rail_bottom() - 78,
        LOGICAL_W - 10,
        lcd_rail_bottom() - 10,
    )
```

Make radio, display, audio, filter, receiver-profile, and fan drawer close helpers return this box. Keep their current action names and closing behavior. Make the final Settings item use this box in `lcd_nav_box`.

- [ ] **Step 4: Update presentation labels without removing destinations**

Change only these labels:

```python
("digital", "MODES")
("tests", "APPS")
("settings_back", "BACK")
```

Change the non-FM-DX audio-drawer label from `FILTER` to `PASSBAND`. Keep `local_rx`, `dual`, `network`, `kiwi`, `stats`, and `system` routes present and behaviorally unchanged.

- [ ] **Step 5: Add a reusable two-line sidebar button**

```python
def draw_picker_two_line_button(text_cache, box, first_line, second_line, size=16, selected=False):
    x0, y0, x1, y1 = box
    draw_picker_button(text_cache, box, "", size, selected)
    center_x = (x0 + x1) / 2
    center_y = (y0 + y1) / 2
    line_offset = max(10, size * 0.65)
    draw_text(text_cache, center_x, center_y - line_offset, first_line,
              (238, 240, 242), size, True, False, "cm")
    draw_text(text_cache, center_x, center_y + line_offset, second_line,
              (238, 240, 242), size, True, False, "cm")
```

Use it for receiver Sort and map View controls. Do not change their hitboxes or actions.

- [ ] **Step 6: Run focused tests and compile**

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest UI/test_ui_navigation.py UI/test_fmdx_ui.py
/private/tmp/ituner-ui-integration-venv/bin/python -m py_compile UI/kiwi_gl_display.py
```

Expected: all tests and compilation pass.

- [ ] **Step 7: Commit shared geometry and labels**

```bash
git add UI/kiwi_gl_display.py UI/test_ui_navigation.py
git commit -m "feat: unify sidebar geometry and labels"
```

---

### Task 3: Add parent-aware Settings navigation

**Files:**
- Modify: `UI/kiwi_gl_display.py` navigation helpers near `lcd_nav_items`
- Modify: `UI/kiwi_gl_display.py` `main()` state initialization and `activate_navigation_item`
- Modify: `UI/kiwi_gl_display.py` leaf-screen Back handlers
- Test: `UI/test_ui_navigation.py`

**Interfaces:**
- Consumes: `MENU_ITEMS`, `SETTINGS_MENU_ITEMS`, existing leaf-screen boolean state.
- Produces: `navigation_parent(items, kind) -> str` and `navigation_back_surface(parent) -> str`; the event loop uses these helpers for parent restoration.

- [ ] **Step 1: Write failing parent-routing tests**

```python
class ParentNavigationTests(unittest.TestCase):
    def test_shared_destination_records_the_surface_that_opened_it(self):
        self.assertEqual(ui.navigation_parent(ui.MENU_ITEMS, "rx"), "home")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "display"), "settings")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "tests"), "settings")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "settings_back"), "home")

    def test_unknown_parent_falls_back_to_home(self):
        self.assertEqual(ui.navigation_back_surface("settings"), "settings")
        self.assertEqual(ui.navigation_back_surface("home"), "home")
        self.assertEqual(ui.navigation_back_surface("unexpected"), "home")
```

- [ ] **Step 2: Run and verify failure**

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest UI/test_ui_navigation.py
```

Expected: FAIL because routing helpers are not defined.

- [ ] **Step 3: Implement the pure parent helpers**

```python
def navigation_parent(items, kind):
    if items is SETTINGS_MENU_ITEMS and kind != "settings_back":
        return "settings"
    return "home"


def navigation_back_surface(parent):
    return "settings" if parent == "settings" else "home"
```

- [ ] **Step 4: Record parent state for shared leaf destinations**

In `main()`, initialize explicit parent variables to `"home"` for receiver picker, display drawer, receiver profile, fan controls, tests/apps, and CPU/statistics. When `activate_navigation_item` opens one of these destinations, set its parent using `navigation_parent(items, kind)`.

Do not rename or reroute current `network`, `kiwi`, `stats`, or `system` actions. Do not alter which worker is used by receiver selection.

- [ ] **Step 5: Restore the correct parent from each adapted Back handler**

For each shared leaf, use:

```python
return_surface = navigation_back_surface(leaf_parent)
settings_menu_open = return_surface == "settings"
```

Close the leaf exactly as before. Clear transient input state exactly as the current handler does. Invalid parent state returns Home.

- [ ] **Step 6: Run navigation and receiver regression tests**

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest UI/test_ui_navigation.py UI/test_fmdx.py UI/test_fmdx_ui.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit parent-aware routing**

```bash
git add UI/kiwi_gl_display.py UI/test_ui_navigation.py
git commit -m "feat: preserve parent-aware sidebar navigation"
```

---

### Task 4: Enlarge leaf workspaces and reorganize Constellation visuals

**Files:**
- Modify: `UI/kiwi_gl_display.py:9781-9825` (`draw_tests_panel`)
- Modify: `UI/kiwi_gl_display.py:12142-12350` (`draw_receiver_map` presentation only)
- Modify: `UI/kiwi_gl_display.py:12506-12640` (`draw_globe_panel` presentation only)
- Modify: `UI/kiwi_gl_display.py:14000-14060` (`draw_lcd_navigation`)
- Test: `UI/test_ui_navigation.py`

**Interfaces:**
- Consumes: shared Back geometry and current Constellation receiver data.
- Produces: `settings_center_workspace_box() -> tuple`, `constellation_layout() -> dict[str, tuple]`, and `draw_settings_leaf_sidebar(...)`; drawing functions use returned boxes without changing event mechanics.

- [ ] **Step 1: Write failing bounded-layout tests**

```python
class WorkspaceLayoutTests(unittest.TestCase):
    def test_settings_center_workspace_stays_outside_sidebar(self):
        x0, y0, x1, y1 = ui.settings_center_workspace_box()
        self.assertGreaterEqual(x0, 0)
        self.assertEqual(x1, ui.LCD_NAV_X0)
        self.assertGreater(y1, y0)
        self.assertLessEqual(y1, ui.LOGICAL_H)

    def test_constellation_layout_fits_current_display(self):
        layout = ui.constellation_layout()
        for box in layout.values():
            x0, y0, x1, y1 = box
            self.assertGreaterEqual(x0, 0)
            self.assertGreaterEqual(y0, 0)
            self.assertLessEqual(x1, ui.LOGICAL_W)
            self.assertLessEqual(y1, ui.LOGICAL_H)
            self.assertGreater(x1, x0)
            self.assertGreater(y1, y0)
        self.assertLessEqual(layout["map"][2], ui.LCD_NAV_X0)
        self.assertGreaterEqual(layout["sidebar"][0], ui.LCD_NAV_X0)
```

- [ ] **Step 2: Run and verify failure**

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest UI/test_ui_navigation.py
```

Expected: FAIL because layout helpers are not defined.

- [ ] **Step 3: Add bounded workspace helpers**

```python
def settings_center_workspace_box():
    return 0, 0, LCD_NAV_X0, LOGICAL_H


def constellation_layout():
    return {
        "map": (0, 0, LCD_NAV_X0, 545),
        "info": (0, 545, LCD_NAV_X0, 714),
        "status": (0, 714, LCD_NAV_X0, LOGICAL_H),
        "sidebar": (LCD_NAV_X0, 0, LOGICAL_W, LOGICAL_H),
    }
```

If current status-bar or orientation helpers require adjusted vertical boundaries, change only these values while retaining the asserted invariants.

- [ ] **Step 4: Add the Settings leaf sidebar renderer**

```python
def draw_settings_leaf_sidebar(text_cache, title, detail="CENTER WORKSPACE"):
    draw_logical_rect(LCD_NAV_X0, 0, LOGICAL_W, LOGICAL_H, (3, 7, 11, 255))
    draw_logical_line(LCD_NAV_X0, 0, LCD_NAV_X0, LOGICAL_H, (125, 147, 158, 118), 1)
    draw_lcd_drawer_heading(text_cache, LCD_NAV_X0 + 18, 62, title)
    draw_text(text_cache, LCD_NAV_X0 + 18, 96, detail,
              (139, 174, 183), 13, False, False, "lm", family="Liberation Sans")
    draw_radio_close_button(text_cache, lcd_drawer_back_box())
```

Use it only for Settings-opened leaf workspaces. Do not draw a modal veil over the active center workspace.

- [ ] **Step 5: Adapt Apps and Constellation presentation**

For Apps on the 800×1280 layout, use the right rail for category tiles and the shared Back control while keeping the center workspace unobscured.

For Constellation:

- Use `constellation_layout()` for map, information, status, and sidebar regions.
- Move headings, legend, hot-receiver information, and scouting status relative to those boxes.
- Keep existing receiver selection, drag, pinch, wheel, loading, scout, and listener logic unchanged.
- Keep existing map action hitboxes and event names unchanged.
- Use the shared Back control only for exit presentation and hit testing.

- [ ] **Step 6: Run UI suites and compile**

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest discover -s UI -p 'test_*.py'
/private/tmp/ituner-ui-integration-venv/bin/python -m py_compile UI/kiwi_gl_display.py UI/fmdx.py UI/kiwi_station_health.py
```

Expected: all tests pass and compilation exits zero.

- [ ] **Step 7: Commit workspace layout changes**

```bash
git add UI/kiwi_gl_display.py UI/test_ui_navigation.py
git commit -m "feat: enlarge baseline-compatible UI workspaces"
```

---

### Task 5: Complete compatibility verification and update PR documentation

**Files:**
- Modify: `README.md` only if operator-visible labels or desktop controls need correction.
- Modify: PR #11 description after local verification.

**Interfaces:**
- Consumes: completed Tasks 1–4.
- Produces: verified PR branch with a precise review summary and no deferred features.

- [ ] **Step 1: Run all automated tests with normal Mac Python**

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 /private/tmp/ituner-ui-integration-venv/bin/python -m unittest discover -s UI -p 'test_*.py'
/private/tmp/ituner-ui-integration-venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Expected: every discovered test passes with zero failures and errors.

- [ ] **Step 2: Run static verification**

```bash
/private/tmp/ituner-ui-integration-venv/bin/python -m py_compile UI/kiwi_gl_display.py UI/fmdx.py UI/kiwi_station_health.py UI/test_ui_navigation.py
bash -n scripts/install.sh scripts/install-dependencies.sh scripts/install-cm5-app-only.sh
git diff --check upstream/main...HEAD
```

Expected: every command exits zero.

- [ ] **Step 3: Audit final scope**

```bash
git diff --name-status upstream/main...HEAD
git diff --stat upstream/main...HEAD
git diff upstream/main...HEAD -- UI/kiwi_gl_display.py | rg 'knob_controller|knob_input|DesktopKnobAdapter|knob_overlay|knob_focus'
```

Expected: the final search returns no matches. Review every map-related hunk and confirm it changes presentation coordinates or shared Back rendering only—not gesture, selection, zoom, or receiver-worker behavior.

- [ ] **Step 4: Attempt a desktop OpenGL smoke test**

Run the existing desktop entry point with a short bounded session and current README arguments. Confirm the window initializes, renders Home, opens Settings and Apps, displays the receiver picker, and opens/closes Constellation. If the environment cannot provide a live receiver or display context, record the exact limitation and do not describe the smoke test as passed.

- [ ] **Step 5: Review upstream preservation**

```bash
git merge-base --is-ancestor upstream/main HEAD
git diff --diff-filter=D --name-only upstream/main...HEAD
git status --short --branch
```

Expected: upstream main is an ancestor, no upstream file is unintentionally deleted, and the worktree is clean.

- [ ] **Step 6: Update PR #11 description**

Add a separate section describing the refreshed icon system, consistent sidebar/Back behavior, parent-aware navigation, and enlarged workspace presentation. State that current receiver/runtime behavior is preserved and deferred controls are not included.

- [ ] **Step 7: Push and verify the public branch**

```bash
git push public-fork pr/fmdx-support-baseline
git rev-parse HEAD
git ls-remote --heads public-fork pr/fmdx-support-baseline
gh pr view 11 --repo ituner/ituner-sdr --json state,mergeable,mergeStateStatus,headRefOid,changedFiles,additions,deletions,url
```

Expected: local HEAD, public remote ref, and PR #11 head SHA match; the PR remains open and mergeable.
