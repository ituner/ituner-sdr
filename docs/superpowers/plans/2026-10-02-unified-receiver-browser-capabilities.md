# Unified Receiver Browser and Capability-Aware Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate map/directory paths with one receiver browser, prioritize KiwiSDR and OpenWebRX, and make every radio and waterfall control truthfully reflect the selected receiver's capabilities and control scope.

**Architecture:** Add a protocol-neutral receiver record and capability contract, then feed KiwiSDR, OpenWebRX, local SDR, and FM-DX sources into one catalog. The receiver workspace owns a `LIST | MAP` view selector plus a single-select source segment ordered `KIWI | OPENWEBRX | LOCAL | FM-DX | ALL`; opening the workspace defaults to `KIWI`. Home controls remain visually consistent across sources, but every action is checked against the active capability contract and explains fixed or unavailable behavior instead of silently ignoring the input.

**Tech Stack:** Python 3, Pygame/OpenGL, `unittest`, existing Kiwi/OpenWebRX/FM-DX transports, JSON configuration and caches.

## Global Constraints

- KiwiSDR is the default receiver filter and remains the primary, most complete experience.
- OpenWebRX is a production receiver type in the catalog, not a test-panel shortcut.
- The browser has one receiver catalog, one list renderer, one map renderer, and one shared selection path.
- Source segment order is `KIWI`, `OPENWEBRX`, `LOCAL`, `FM-DX`, `ALL`.
- `FAVORITES` remains a secondary toggle/search modifier so the five source segments stay readable on the 1280x800 display.
- FM-DX is read-only by default because its tuner frequency is shared by all users connected to that server.
- FM-DX must not send an initial tune command, expose band scan, or send a frequency command in read-only mode.
- Optional FM-DX shared control requires an explicit, session-only acknowledgement for the active server; it is never remembered.
- Controls stay visible across receiver types. Unsupported or fixed controls render disabled and explain why when pressed.
- Waterfall labels must distinguish an RF waterfall from FM-DX's derived audio spectrum.
- Existing remembered receiver data is migrated without losing the selected server or Kiwi mode.

---

## File Structure

- Create `UI/receiver_catalog.py`: protocol-neutral receiver records, capability contracts, source ordering, filtering, and legacy-row adapters.
- Create `UI/receiver_sources.json`: built-in OpenWebRX and local receiver metadata using the same catalog schema; seed it with the currently tested OpenWebRX endpoint.
- Create `UI/test_receiver_catalog.py`: unit coverage for normalization, filters, ordering, capability decisions, and legacy migration.
- Modify `UI/kiwi_gl_display.py`: unified receiver workspace, selection state, capability-aware controls, and transport handoff.
- Modify `UI/openwebrx_client.py`: expose negotiated OpenWebRX capabilities from the server configuration.
- Modify `UI/fmdx.py`: explicit read-only/shared-control behavior and no implicit tune command.
- Modify `UI/kiwi_station_health.py`: protocol-aware health records for the unified catalog.
- Modify `UI/test_board_v1.py`, `UI/test_ui_navigation.py`, `UI/test_fmdx_ui.py`, and `UI/test_fmdx_sidebar.py`: regression coverage for the new navigation and FM-DX safety boundary.
- Modify `docs/board-v1-review.md`: document the unified receiver experience and the shared FM-DX tuner limitation.

---

### Task 1: Introduce the receiver and capability contracts

**Files:**
- Create: `UI/receiver_catalog.py`
- Create: `UI/test_receiver_catalog.py`

**Interfaces:**
- Produces: `ReceiverRecord`, `ReceiverCapabilities`, `ControlDecision`, `normalize_receiver()`, `filter_receivers()`, `sort_receivers()`, and `legacy_station_row()`.
- Consumes: no UI state; this module stays dependency-free so health workers and renderers can share it.

- [ ] **Step 1: Write failing contract tests**

```python
class ReceiverCapabilityTests(unittest.TestCase):
    def test_source_order_prioritizes_kiwi_and_openwebrx(self):
        self.assertEqual(catalog.SOURCE_FILTERS, ("kiwi", "openwebrx", "local", "fmdx", "all"))

    def test_fixed_passband_returns_an_explanation(self):
        caps = catalog.ReceiverCapabilities.fixed_audio("fmdx", "FM-DX")
        decision = caps.decide("passband")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.message, "Fixed passband on this receiver")

    def test_fmdx_frequency_is_shared_and_read_only_by_default(self):
        record = catalog.normalize_receiver({
            "id": "fm:test", "protocol": "fmdx", "endpoint": "https://fm.test",
            "name": "FM test", "control_scope": "shared_server",
        })
        self.assertEqual(record.capabilities.decide("frequency").message,
                         "Shared tuner: changing frequency affects every listener")

    def test_filtering_all_keeps_priority_order(self):
        records = tuple(catalog.normalize_receiver(item) for item in (
            {"id": "f", "protocol": "fmdx", "endpoint": "https://fm"},
            {"id": "o", "protocol": "openwebrx", "endpoint": "owrxs://owrx"},
            {"id": "k", "protocol": "kiwi", "endpoint": "https://kiwi"},
        ))
        self.assertEqual([item.protocol for item in catalog.filter_receivers(records, "all")],
                         ["kiwi", "openwebrx", "fmdx"])
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `UI/.venv/bin/python -m unittest UI/test_receiver_catalog.py -v`

Expected: FAIL because `receiver_catalog` does not exist.

- [ ] **Step 3: Implement immutable records and decisions**

```python
SOURCE_FILTERS = ("kiwi", "openwebrx", "local", "fmdx", "all")
SOURCE_PRIORITY = {name: index for index, name in enumerate(SOURCE_FILTERS[:-1])}

@dataclass(frozen=True)
class ControlDecision:
    allowed: bool
    message: str = ""

@dataclass(frozen=True)
class ReceiverCapabilities:
    protocol: str
    label: str
    controls: frozenset[str]
    fixed_controls: Mapping[str, str]
    modes: tuple[str, ...]
    waterfall_kind: str
    control_scope: str

    def decide(self, control: str) -> ControlDecision:
        if control in self.controls:
            return ControlDecision(True)
        return ControlDecision(False, self.fixed_controls.get(control, f"{control.title()} is unavailable on this receiver"))

@dataclass(frozen=True)
class ReceiverRecord:
    id: str
    protocol: str
    source_group: str
    endpoint: str
    name: str
    location: str
    latitude: float | None
    longitude: float | None
    capabilities: ReceiverCapabilities
    listeners_used: int | None = None
    listeners_total: int | None = None
    favorite: bool = False
```

`protocol` selects the transport (`kiwi`, `openwebrx`, `fmdx`, or `local`), while
`source_group` selects the browser segment. A LAN Kiwi therefore uses
`protocol="kiwi"` and `source_group="local"`; it does not accidentally enter the
USB local-device worker.

Define concrete contracts:

- Kiwi: per-session frequency, mode, passband, RF waterfall pan/zoom, AGC, squelch, and volume.
- OpenWebRX: per-session frequency, negotiated modes, passband, profile-bounded RF waterfall, squelch, and volume.
- Local: local-device controls from the existing `ReceiverCapabilities` definitions.
- FM-DX: read-only shared-server frequency, fixed FM mode, fixed passband, derived audio spectrum, volume only.

- [ ] **Step 4: Add adapters without changing the live UI yet**

`legacy_station_row(record)` must preserve the existing tuple shape:

```python
return (
    record.name, record.location, record.endpoint,
    record.listeners_used, record.listeners_total,
    record.latitude, record.longitude, record.protocol,
)
```

This allows the catalog to land independently before the renderer stops consuming tuples.

- [ ] **Step 5: Run the catalog tests**

Run: `UI/.venv/bin/python -m unittest UI/test_receiver_catalog.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the contract**

```bash
git add UI/receiver_catalog.py UI/test_receiver_catalog.py
git commit -m "feat: define receiver capability contracts"
```

---

### Task 2: Build one catalog and promote OpenWebRX from test-only status

**Files:**
- Create: `UI/receiver_sources.json`
- Modify: `UI/receiver_catalog.py`
- Modify: `UI/kiwi_gl_display.py:3241-3369`
- Modify: `UI/kiwi_station_health.py`
- Test: `UI/test_receiver_catalog.py`

**Interfaces:**
- Consumes: `ReceiverRecord`, `normalize_receiver()`.
- Produces: `load_receiver_catalog() -> tuple[ReceiverRecord, ...]`, `records_from_kiwi_directory()`, `records_from_fmdx_directory()`, and `records_from_static_sources()`.

- [ ] **Step 1: Add failing merge and deduplication tests**

```python
def test_catalog_merges_all_sources_by_stable_id(self):
    merged = catalog.merge_catalogs(kiwi_rows, openwebrx_rows, local_rows, fmdx_rows)
    self.assertEqual({item.protocol for item in merged}, {"kiwi", "openwebrx", "local", "fmdx"})
    self.assertEqual(len({item.id for item in merged}), len(merged))

def test_openwebrx_endpoint_is_not_classified_as_kiwi(self):
    record = catalog.normalize_receiver({
        "id": "openwebrx:oh6ah", "protocol": "openwebrx",
        "endpoint": "owrxs://rx.oh6ah.fi/", "name": "OH6AH OpenWebRX",
    })
    self.assertEqual(record.protocol, "openwebrx")
```

- [ ] **Step 2: Add the static-source schema**

```json
{
  "version": 1,
  "receivers": [
    {
      "id": "openwebrx:oh6ah",
      "protocol": "openwebrx",
      "source_group": "openwebrx",
      "endpoint": "owrxs://rx.oh6ah.fi/",
      "name": "OH6AH OpenWebRX",
      "location": "Finland",
      "control_scope": "per_session"
    },
    {
      "id": "local:kiwisdr",
      "protocol": "kiwi",
      "source_group": "local",
      "endpoint": "http://kiwisdr.local:8073",
      "name": "Local KiwiSDR",
      "location": "Local network",
      "control_scope": "per_session"
    }
  ]
}
```

OpenWebRX catalog growth happens through this schema until a reviewed, stable external directory source is selected. Do not scrape or infer OpenWebRX from arbitrary Kiwi URLs.

- [ ] **Step 3: Merge all inputs into one catalog**

Replace the split `STATIONS`, `FMDX_RECEIVERS`, and globe-only merge path with one catalog load. Keep the existing cache files as input adapters during migration, then derive both list and map rows from the same `ReceiverRecord` collection.

- [ ] **Step 4: Make health checks protocol-aware**

Return the same health shape for each record:

```python
{
    "receiver_id": record.id,
    "protocol": record.protocol,
    "audio": True | False | None,
    "waterfall": True | False | None,
    "checked": unix_time,
}
```

Do not pretend the FM-DX audio-derived spectrum is a remote waterfall endpoint; describe it as `waterfall_kind="audio_spectrum"` in capabilities.

- [ ] **Step 5: Verify catalog and legacy regression tests**

Run: `UI/.venv/bin/python -m unittest UI/test_receiver_catalog.py UI/test_fmdx.py UI/test_fmdx_ui.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the unified data source**

```bash
git add UI/receiver_sources.json UI/receiver_catalog.py UI/kiwi_gl_display.py UI/kiwi_station_health.py UI/test_receiver_catalog.py
git commit -m "feat: unify receiver catalog sources"
```

---

### Task 3: Replace separate map and directory navigation with one receiver workspace

**Files:**
- Modify: `UI/kiwi_gl_display.py:1900-1950,12166-12886,14526-15310,20836-23370`
- Modify: `UI/test_ui_navigation.py`
- Modify: `UI/test_board_v1.py`

**Interfaces:**
- Consumes: unified `ReceiverRecord` catalog and `filter_receivers()`.
- Produces: `ReceiverBrowserState(view, source, query, sort, favorites_only)`, `receiver_browser_action_at()`, and one `connect_to_receiver(record)` path.

- [ ] **Step 1: Write failing state and geometry tests**

```python
def test_receiver_browser_defaults_to_kiwi_list(self):
    state = ui.ReceiverBrowserState()
    self.assertEqual((state.view, state.source), ("list", "kiwi"))

def test_source_segments_are_single_select_and_in_priority_order(self):
    segments = ui.receiver_source_segments()
    self.assertEqual([source for source, _box in segments],
                     ["kiwi", "openwebrx", "local", "fmdx", "all"])
    self.assertTrue(all(not ui.boxes_overlap(a, b)
                        for index, (_name, a) in enumerate(segments)
                        for _other, b in segments[index + 1:]))

def test_list_and_map_use_the_same_filtered_records(self):
    state = ui.ReceiverBrowserState(source="openwebrx")
    self.assertEqual(ui.browser_records(records, state, "list"),
                     ui.browser_records(records, state, "map"))
```

- [ ] **Step 2: Add a two-level segmented header**

At the top of the 1024 px content canvas render:

```text
RECEIVERS                 [ LIST | MAP ]
[ KIWI | OPENWEBRX | LOCAL | FM-DX | ALL ]
```

Keep Search, Sort, Favorites, and Back in the right rail. Remove the `GLOBE` launcher and the separate `RADIOGARDEN_LIST_BOX` navigation path.

- [ ] **Step 3: Use one browser state for both views**

Switching `LIST | MAP` preserves source filter, query, sort, favorites, and selected receiver. Switching a source segment resets only list scroll and map hover, not the selected live receiver.

- [ ] **Step 4: Replace duplicated selection handlers**

Both a list row and a map marker call:

```python
def connect_to_receiver(record: ReceiverRecord):
    state.set_server(record.endpoint, receiver_type=record.protocol)
    write_remembered_view(save_current_frequency=True, force=True)
    clear_receiver_visual_buffers()
```

The handler then applies the record's capability-derived initial mode, tuning bounds, and waterfall description.

- [ ] **Step 5: Make priority visible without hiding alternatives**

- Opening Receivers always selects `KIWI`.
- `ALL` sorts Kiwi first, OpenWebRX second, Local third, FM-DX last.
- FM-DX rows carry `SHARED TUNER` instead of a generic route badge.
- OpenWebRX rows carry `OPENWEBRX` and the negotiated profile span when known.

- [ ] **Step 6: Run navigation tests**

Run: `UI/.venv/bin/python -m unittest UI/test_ui_navigation.py UI/test_board_v1.py -v`

Expected: PASS with no overlapping segments or split map/list state.

- [ ] **Step 7: Commit the workspace**

```bash
git add UI/kiwi_gl_display.py UI/test_ui_navigation.py UI/test_board_v1.py
git commit -m "feat: unify receiver list and map navigation"
```

---

### Task 4: Route all controls through capability decisions

**Files:**
- Modify: `UI/kiwi_gl_display.py:7600-8040,12887-14580,26179-26430`
- Modify: `UI/openwebrx_client.py`
- Modify: `UI/test_receiver_catalog.py`
- Modify: `UI/test_ui_navigation.py`

**Interfaces:**
- Consumes: `ReceiverCapabilities.decide(control)` and active `ReceiverRecord`.
- Produces: `apply_receiver_control(control, value) -> ControlDecision`, `draw_control_notice()`, and `OpenWebRxSession.negotiated_capabilities()`.

- [ ] **Step 1: Write failing control-policy tests**

```python
def test_unsupported_control_does_not_mutate_state(self):
    before = state.radio_snapshot()
    decision = ui.apply_receiver_control(state, fmdx_record, "passband", (-2400, 2400))
    self.assertFalse(decision.allowed)
    self.assertEqual(state.radio_snapshot(), before)

def test_openwebrx_profile_bounds_frequency(self):
    caps = session.negotiated_capabilities()
    self.assertEqual(caps.frequency_ranges_khz, ((source_low, source_high),))
    self.assertIn("passband", caps.controls)
```

- [ ] **Step 2: Define the consistent visible controls**

Always render Frequency, Mode, Passband, and Waterfall rows. Render their current values plus one of:

- enabled: ordinary control appearance;
- fixed: dimmed value and `FIXED` badge;
- unsupported: dimmed value and `NOT AVAILABLE` badge;
- shared: amber `SHARED` badge.

- [ ] **Step 3: Explain rejected actions**

Tapping or turning a fixed/unsupported control opens a short notice for 2.5 seconds:

```text
PASSBAND
Fixed passband on this receiver.
```

Required messages:

- FM-DX passband: `Fixed passband on this receiver`.
- FM-DX mode: `FM mode is controlled by the shared receiver`.
- FM-DX waterfall pan/zoom: `Audio spectrum is fixed to 20 kHz`.
- Local unsupported mode: `<MODE> is not implemented by <DEVICE>`.
- OpenWebRX outside profile: `This OpenWebRX profile covers <LOW>–<HIGH> kHz`.

- [ ] **Step 4: Negotiate OpenWebRX capabilities**

`OpenWebRxSession.negotiated_capabilities()` derives the profile frequency range from `center_freq` and `samp_rate`, maps server-supported modes when advertised, and falls back to the modes already implemented in `DEFAULT_FILTERS`. Passband stays per-session; waterfall pan is bounded to the active profile.

- [ ] **Step 5: Label waterfall provenance**

Use one of these exact captions in the waterfall status area:

- `KIWI RF WATERFALL`
- `OPENWEBRX RF WATERFALL · PROFILE <SPAN> kHz`
- `LOCAL RF WATERFALL · <DEVICE>`
- `FM-DX AUDIO SPECTRUM · FIXED 20 kHz`

- [ ] **Step 6: Run capability and UI tests**

Run: `UI/.venv/bin/python -m unittest UI/test_receiver_catalog.py UI/test_ui_navigation.py UI/test_fmdx_ui.py -v`

Expected: PASS and no unsupported action mutates radio state.

- [ ] **Step 7: Commit capability-aware controls**

```bash
git add UI/receiver_catalog.py UI/kiwi_gl_display.py UI/openwebrx_client.py UI/test_receiver_catalog.py UI/test_ui_navigation.py UI/test_fmdx_ui.py
git commit -m "feat: make receiver controls capability aware"
```

---

### Task 5: Make FM-DX safe and explicitly secondary

**Files:**
- Modify: `UI/fmdx.py:716-717`
- Modify: `UI/kiwi_gl_display.py:7800-8040,19446-19605`
- Modify: `UI/test_fmdx.py`
- Modify: `UI/test_fmdx_ui.py`
- Modify: `UI/test_fmdx_sidebar.py`
- Modify: `UI/test_board_v1.py`

**Interfaces:**
- Consumes: FM-DX capability contract with `control_scope="shared_server"`.
- Produces: `FmdxControlPolicy.READ_ONLY`, `FmdxControlPolicy.SHARED_ACKNOWLEDGED`, and `request_fmdx_shared_control()`.

- [ ] **Step 1: Write failing safety tests**

```python
def test_fmdx_connect_does_not_send_a_tune_command(self):
    session = start_fmdx_session(policy="read_only")
    self.assertNotIn("T101700", session.control.sent_text)

def test_fmdx_scan_is_absent_in_read_only_mode(self):
    actions = [action for action, _box in ui.fmdx_control_layout(stations, False, shared_control=False)]
    self.assertNotIn("scan_start", actions)

def test_shared_acknowledgement_is_server_scoped_and_not_persisted(self):
    policy.acknowledge("https://fm-a.test")
    self.assertTrue(policy.can_tune("https://fm-a.test"))
    self.assertFalse(policy.can_tune("https://fm-b.test"))
    self.assertEqual(policy.serialize(), {})
```

- [ ] **Step 2: Remove implicit retuning**

In `fmdx_audio_session()`, do not call `control.send_text(fmdx.tune_command(freq_khz))` on connect in read-only mode. Take the server's current frequency from its status messages and update the displayed frequency without incrementing a user tune generation.

- [ ] **Step 3: Remove scan and tuning controls from the default FM-DX drawer**

Replace preset/scan controls with:

```text
FM-DX · SHARED TUNER
Listening at 101.7 MHz
Frequency changes affect every connected listener.
[ ENABLE SHARED CONTROL ]
```

Do not allow waterfall drag, frequency entry, tuning step, preset next/previous, or band scan while read-only.

- [ ] **Step 4: Add a session-only shared-control confirmation**

First activation presents:

```text
CONTROL SHARED FM-DX TUNER?
Changing frequency changes the station for everyone connected to this server.
[ CANCEL ]  [ ENABLE FOR THIS SESSION ]
```

Acknowledgement is held only in memory for the current server generation. Leaving the server or restarting the app returns to read-only.

- [ ] **Step 5: Keep scanning out of the normal product flow**

Even after shared control is enabled, expose direct tuning and server presets only. Remove band scan from the production drawer because it repeatedly retunes the shared receiver. Retain scan helpers only if a separate diagnostic/developer surface still needs them.

- [ ] **Step 6: Run all FM-DX safety tests**

Run: `UI/.venv/bin/python -m unittest UI/test_fmdx.py UI/test_fmdx_ui.py UI/test_fmdx_sidebar.py UI/test_board_v1.py -v`

Expected: PASS; no test observes an FM-DX tune command before acknowledgement.

- [ ] **Step 7: Commit the safety boundary**

```bash
git add UI/fmdx.py UI/kiwi_gl_display.py UI/test_fmdx.py UI/test_fmdx_ui.py UI/test_fmdx_sidebar.py UI/test_board_v1.py
git commit -m "fix: make shared FM-DX tuning opt in"
```

---

### Task 6: Migrate persistence and remove obsolete split-browser state

**Files:**
- Modify: `UI/kiwi_gl_display.py:4164-4230,20836-21340`
- Modify: `UI/test_receiver_catalog.py`
- Modify: `UI/test_ui_navigation.py`

**Interfaces:**
- Consumes: existing remembered server, receiver type, frequency, zoom, and mode.
- Produces: remembered `receiver_id`, browser source selection, and backward-compatible load.

- [ ] **Step 1: Add migration tests**

```python
def test_old_remembered_fmdx_view_loads_as_read_only(self):
    loaded = catalog.migrate_remembered_view({
        "server": "https://fm.test", "receiver_type": "fmdx", "frequency_khz": 101700,
    })
    self.assertEqual(loaded["receiver_id"], "fmdx:https://fm.test")
    self.assertEqual(loaded["shared_control"], False)

def test_old_kiwi_view_preserves_mode_and_frequency(self):
    loaded = catalog.migrate_remembered_view(old_kiwi_payload)
    self.assertEqual((loaded["mode"], loaded["frequency_khz"]), ("LSB", 7075.0))
```

- [ ] **Step 2: Persist stable receiver identity**

Save `receiver_id` and `protocol` alongside the endpoint. Never save FM-DX shared-control acknowledgement. Keep loading legacy `receiver_type` and tuple-based favorites for one migration cycle.

- [ ] **Step 3: Delete obsolete UI state**

Remove `picker_map_open`, separate globe/list exit flows, route boxes named `DIRECT` and `PROXY`, and the fixed OpenWebRX test restore state after their replacements pass tests. Keep constellation/scout functionality separate from receiver browsing because it is a Kiwi-only operating workspace, not a second receiver map.

- [ ] **Step 4: Run migration and navigation tests**

Run: `UI/.venv/bin/python -m unittest UI/test_receiver_catalog.py UI/test_ui_navigation.py UI/test_board_v1.py -v`

Expected: PASS.

- [ ] **Step 5: Commit cleanup**

```bash
git add UI/receiver_catalog.py UI/kiwi_gl_display.py UI/test_receiver_catalog.py UI/test_ui_navigation.py
git commit -m "refactor: remove split receiver browser state"
```

---

### Task 7: Validate the complete receiver experience and document limits

**Files:**
- Modify: `docs/board-v1-review.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: completed receiver browser and capability behavior.
- Produces: operator-facing behavior description and validation evidence.

- [ ] **Step 1: Run the complete Python suite**

Run: `UI/.venv/bin/python -m unittest discover -s UI -p 'test_*.py' -v`

Expected: all UI tests PASS.

Run: `python3 -m unittest discover -s tests -v`

Expected: all installer/hardware tests PASS.

- [ ] **Step 2: Run static validation**

Run: `UI/.venv/bin/python -m py_compile UI/receiver_catalog.py UI/openwebrx_client.py UI/fmdx.py UI/kiwi_station_health.py UI/kiwi_gl_display.py`

Run: `git diff --check`

Expected: both commands exit 0.

- [ ] **Step 3: Perform the 1280x800 interaction review**

Verify on the CM5 layout:

- Receivers opens on `KIWI` and `LIST`.
- Each source segment is readable and has one selected state.
- `LIST | MAP` preserves the active filter and selection.
- Kiwi remains first in `ALL`; OpenWebRX appears before Local and FM-DX.
- List and map select the same record through the same connection path.
- Fixed controls remain visible and explain themselves when touched.
- OpenWebRX cannot tune outside its active profile.
- FM-DX connects without changing the server frequency.
- FM-DX has no scan action and cannot tune before explicit shared-control acknowledgement.
- Leaving FM-DX revokes shared control.

- [ ] **Step 4: Update documentation**

Document these exact product rules:

```text
KiwiSDR is the default and most complete receiver type. OpenWebRX uses the
same browser and adapts controls to the active server profile. Local receivers
show only controls implemented by the connected hardware. FM-DX servers use a
shared tuner: iTuner listens without retuning by default, and any shared
frequency control requires an explicit acknowledgement for that session.
```

- [ ] **Step 5: Commit validation and documentation**

```bash
git add README.md docs/board-v1-review.md
git commit -m "docs: explain receiver capabilities and shared tuning"
```

---

## Acceptance Criteria

- There is one Receivers entry point and one shared receiver collection.
- The same filtered records drive both list and map views.
- `KIWI` is selected when the receiver browser opens.
- OpenWebRX is available through the receiver catalog and no longer depends on the Tests panel.
- Source priority is Kiwi, OpenWebRX, Local, FM-DX, then the combined All view.
- Mode, passband, frequency, and waterfall controls always reflect actual receiver behavior.
- Rejected control changes show a clear reason and leave state unchanged.
- FM-DX never changes a shared server frequency without explicit session-only acknowledgement.
- FM-DX band scan is absent from the production interface.
- Existing Kiwi workflows, saved mode, health indicators, and constellation behavior remain functional.
