# FM-DX Modes Drawer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Modes drawer show the protocol-owned `FM-FMDX` mode on FM-DX receivers without exposing or mutating Kiwi demodulator choices.

**Architecture:** Use `SharedState.receiver_type_snapshot()` as the authoritative protocol boundary and derive one effective presentation mode for Home and the Modes drawer. Extend the drawer and its hit testing with an FM-DX branch that renders one server-controlled mode card, keeps Back and tuning-step controls active, and makes the hidden Kiwi family area inert.

**Tech Stack:** Python 3, pygame/OpenGL immediate-mode UI, `unittest`

## Global Constraints

- The drawer remains fixed in the existing right-side position.
- FM-DX shows one selected `FM-FMDX` mode and no Kiwi mode families.
- The drawer explains that demodulation is controlled by the FM-DX server.
- Back and tuning-step controls remain available.
- FM-DX interactions must not mutate the remembered Kiwi demodulator mode.
- Selecting a Kiwi receiver restores the existing Kiwi mode drawer unchanged.

---

### Task 1: Protocol-aware Modes input

**Files:**
- Modify: `UI/kiwi_gl_display.py:4887-4900`
- Test: `UI/test_ui_navigation.py`

**Interfaces:**
- Consumes: `fmdx.MODE_LABEL`, `radio_mode_layout()`, `radio_step_options()`
- Produces: `radio_option_at(x, y, family_open=None, effective_mode=None) -> tuple[str, object] | None`

- [ ] **Step 1: Write failing tests for FM-DX-safe mode hit testing**

Add tests that use the centers of real layout boxes:

```python
def test_fmdx_modes_drawer_blocks_kiwi_mode_family_actions(self):
    ui.configure_output(True)
    ui.configure_popup_layout()
    _family, modes, box = next(iter(ui.radio_mode_layout()))
    x = (box[0] + box[2]) / 2
    y = (box[1] + box[3]) / 2
    self.assertIsNone(
        ui.radio_option_at(x, y, effective_mode=ui.fmdx.MODE_LABEL)
    )
    self.assertEqual(
        ui.radio_option_at(x, y, effective_mode="AM"),
        ("mode_cycle", modes),
    )

def test_fmdx_modes_drawer_keeps_tuning_step_actions(self):
    option, box = next(iter(ui.radio_step_options()))
    x = (box[0] + box[2]) / 2
    y = (box[1] + box[3]) / 2
    self.assertEqual(
        ui.radio_option_at(x, y, effective_mode=ui.fmdx.MODE_LABEL),
        ("step", option),
    )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 UI/.venv/bin/python -m unittest \
  UI.test_ui_navigation.ModeAnnunciatorNavigationTests.test_fmdx_modes_drawer_blocks_kiwi_mode_family_actions \
  UI.test_ui_navigation.ModeAnnunciatorNavigationTests.test_fmdx_modes_drawer_keeps_tuning_step_actions
```

Expected: FAIL because `radio_option_at` does not accept `effective_mode` and currently resolves Kiwi family actions for every receiver.

- [ ] **Step 3: Add the minimal protocol-aware hit-test branch**

Update `radio_option_at` so Back is checked first, Kiwi family boxes are checked only when the effective mode is not `FM-FMDX`, and tuning-step boxes remain common:

```python
def radio_option_at(x, y, family_open=None, effective_mode=None):
    if LCD_800_MODE and y > lcd_radio_drawer_reveal_y():
        return None
    if LCD_800_MODE and contains(lcd_radio_drawer_close_box(), x, y):
        return "close", None
    if str(effective_mode or "").upper() != fmdx.MODE_LABEL:
        for _family, modes, box in radio_mode_layout():
            if contains(box, x, y):
                return "mode_cycle", modes
    for step_hz, box in radio_step_options():
        if contains(box, x, y):
            return "step", step_hz
    return None
```

At both gesture-start and gesture-release call sites, derive the current value
with `effective_radio_mode(state, radio_mode)` and pass it as `effective_mode`.
This keeps explicit row protocol metadata authoritative even if the same URL
was previously registered under another protocol. Keep the existing
`mode_cycle`, `step`, and `close` handlers unchanged.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command again. Expected: both tests PASS.

---

### Task 2: Dedicated FM-DX Modes presentation

**Files:**
- Modify: `UI/kiwi_gl_display.py:5014-5060`
- Modify: `UI/kiwi_gl_display.py:16427`
- Test: `UI/test_ui_navigation.py`

**Interfaces:**
- Consumes: effective mode string derived from `SharedState.receiver_type_snapshot()`
- Produces: `radio_setup_is_server_controlled(mode) -> bool`; FM-DX and Kiwi render branches in `draw_radio_setup_panel`

- [ ] **Step 1: Write the failing presentation-state test**

```python
def test_fmdx_effective_mode_selects_server_controlled_drawer(self):
    self.assertTrue(ui.radio_setup_is_server_controlled("FM-FMDX"))
    self.assertFalse(ui.radio_setup_is_server_controlled("AM"))
```

This catches an accidental return to the stale Kiwi `radio_mode` branch.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 UI/.venv/bin/python -m unittest \
  UI.test_ui_navigation.ModeAnnunciatorNavigationTests.test_fmdx_effective_mode_selects_server_controlled_drawer
```

Expected: FAIL with `AttributeError` because `radio_setup_is_server_controlled` does not exist.

- [ ] **Step 3: Implement the dedicated render branch**

Add:

```python
def radio_setup_is_server_controlled(mode):
    return str(mode).upper() == fmdx.MODE_LABEL
```

Pass `display_radio_mode`, not `radio_mode`, into `draw_radio_setup_panel`.

Inside `draw_radio_setup_panel`, when `radio_setup_is_server_controlled(mode)` is true:

- Render the existing drawer background and Back control.
- Render one full-width selected card labelled `FM-FMDX` in the mode-family area.
- Render two compact explanatory lines: `SERVER-DEMODULATED FM AUDIO` and `MODE CONTROLLED BY FM-DX SERVER`.
- Skip `radio_mode_layout()` family rendering.
- Render the existing `TUNING STEP` label and `radio_step_options()` buttons unchanged.
- Apply the same content in the desktop modal using its existing coordinates and styling primitives.

Do not change `state.radio_mode`, `manual_radio_mode`, or Kiwi filter bounds.

- [ ] **Step 4: Run focused tests and the complete suite**

Run:

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 UI/.venv/bin/python -m unittest \
  UI.test_ui_navigation.ModeAnnunciatorNavigationTests.test_fmdx_effective_mode_selects_server_controlled_drawer \
  UI.test_ui_navigation.ModeAnnunciatorNavigationTests.test_fmdx_modes_drawer_blocks_kiwi_mode_family_actions \
  UI.test_ui_navigation.ModeAnnunciatorNavigationTests.test_fmdx_modes_drawer_keeps_tuning_step_actions
PYGAME_HIDE_SUPPORT_PROMPT=1 UI/.venv/bin/python -m unittest discover -s UI -p 'test_*.py'
```

Expected: focused tests PASS and the complete UI suite reports zero failures.

- [ ] **Step 5: Verify the desktop UI visually**

Run:

```bash
UI/.venv/bin/python UI/kiwi_gl_display.py --desktop \
  --no-audio --no-remember-receiver \
  --server https://bucnorth.fmtuner.org --freq-khz 106700
```

Open Modes and verify:

- `FM-FMDX` is the only selected mode.
- AM and other Kiwi families are absent.
- The server-controlled explanation is readable.
- Tuning-step buttons and Back respond.
- Returning to a Kiwi receiver restores the regular Kiwi families.

- [ ] **Step 6: Final static verification**

Run:

```bash
PYGAME_HIDE_SUPPORT_PROMPT=1 UI/.venv/bin/python -m py_compile \
  UI/fmdx.py UI/kiwi_gl_display.py UI/test_fmdx.py UI/test_ui_navigation.py
git diff --check
```

Expected: both commands exit 0 with no errors.
