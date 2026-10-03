# board_v1 changelog — unified receiver browser and interface pass

This document records every change made on `board_v1` for the unified receiver
browser and the accompanying CM5 interface cleanups. It complements
[the receiver audit](board-v1-review.md), which states the product rules, and
[the source plan](superpowers/plans/2026-10-02-unified-receiver-browser-capabilities.md).

The work targets the 1280x800 CM5 panel (and the same logical resolution on the
macOS test host). KiwiSDR remains the default and most complete receiver type.

## 1. Unified receiver browser

- One protocol-neutral catalog replaces the separate list/map code paths.
  New module [`UI/receiver_catalog.py`](../UI/receiver_catalog.py) defines
  `ReceiverRecord` and a `ReceiverCapabilities` contract that is dependency-free,
  so the renderer, the health worker, and future tools share one description of
  a receiver. `SOURCE_FILTERS` fixes the browser order
  `kiwi`, `openwebrx`, `local`, `fmdx`, `all`.
- A record keeps its **transport** (`protocol`) separate from its **browser
  segment** (`source_group`). A LAN Kiwi is `protocol="kiwi"` but appears under
  `LOCAL` and never enters the USB local-device worker.
- [`UI/receiver_sources.json`](../UI/receiver_sources.json) seeds static
  endpoints (for example `openwebrx:oh6ah`, `local:kiwisdr`) so known receivers
  exist before any network probe.
- A single source-segment header (`KIWI`, `OPENWEBRX`, `LOCAL`, `FM-DX`, `ALL`)
  spans the top of the 1024 px content canvas. `receiver_source_segments()` and
  `picker_source_segment_at()` own the layout and tap resolution.
- The list and map views read the same filtered collection, so the source
  filter, query, sort, favorites toggle, and selected receiver survive a view
  switch. Opening Receivers selects `KIWI`; the `ALL` view always sorts Kiwi,
  OpenWebRX, Local, then FM-DX.
- Capability checks: controls stay visible across receiver types. A fixed or
  unsupported control renders disabled and explains itself when pressed, so no
  input is silently ignored. Waterfall captions distinguish an RF waterfall from
  FM-DX's derived audio spectrum.
- `OpenWebRxSession.negotiated_capabilities()` reports the active server's
  profile; local receivers expose only hardware-implemented controls.
- An empty source shows the shared `NO RECEIVERS IN THIS SOURCE` text instead of
  a blank list.

## 2. Globe (was “MAP”) and right-rail controls

- The browser's map view is renamed **GLOBE** everywhere (`receiver_map_*`
  helpers, labels, and the header).
- All Globe commands live in the right rail, never floating over the map canvas:
  `LIST`, `VIEW`, zoom, and `BACK` reuse the standard square launcher tile
  (`lcd_nav_box`) or the shared bottom Back target (`lcd_drawer_back_box`).
- The colour legend chips moved **off the map overlay and into the right rail**.
  `receiver_map_legend_boxes()` now stacks chips vertically
  (`RECEIVER_MAP_LEGEND_RAIL_TOP=88`, `RECEIVER_MAP_LEGEND_RAIL_H=46`,
  `RECEIVER_MAP_LEGEND_GAP=8`) between the rail edges, and the legend is drawn
  with the `RECEIVERS / GLOBE` header. Tapping a chip toggles that source
  group's dots (Kiwi, OpenWebRX, Local, FM-DX) in the globe and on the hover
  surface — session-only.
- The zoom controls now carry **only the `+` and `−` glyphs**; the `ZOOM +` /
  `ZOOM −` captions were removed (`draw_globe_zoom_tile`).

## 3. FM-DX shared-tuner safety

- FM-DX servers are shared: a frequency change retunes the station for every
  listener. iTuner therefore listens read-only by default.
- [`UI/fmdx.py`](../UI/fmdx.py) adds `FmdxControlPolicy` with the states
  `READ_ONLY` and `SHARED_ACKNOWLEDGED`. No tune command is sent on connect, and
  none is sent while read-only.
- The FM-DX drawer shows the shared-tuner explanation and a single
  `ENABLE SHARED CONTROL` action. Shared frequency control requires an explicit
  acknowledgement for the active server, held **only in memory for the session**;
  leaving the server or restarting the app always returns to read-only, and the
  acknowledgement is never persisted. Band scan is omitted entirely while
  read-only, and the tuning step is hidden.

## 4. Local receiver reachability

- The built-in LAN Kiwi (`LOCAL_KIWI_SERVER`) is hidden until it is confirmed
  reachable. `filtered_stations(..., station_health=None)` drops the unconfirmed
  built-in LAN station when a health map is supplied, so `LOCAL` never offers a
  receiver that will not answer.
- `local_kiwi_is_reachable(server, station_health, now)` gates the built-in
  entry; every main-loop `filtered_stations` call site passes `station_health`.
- [`UI/kiwi_station_health.py`](../UI/kiwi_station_health.py) adds
  `probe_station_list(...)`, `local_station_rows(...)`, and
  `LOCAL_PROBE_INTERVAL_SECONDS=300.0`. `main()` re-probes the LAN Kiwi about
  every five minutes.
- The receiver browser only returns to the main screen after a real receiver
  change: re-selecting the already-live endpoint (or switching source while a
  pick is still settling) keeps the browser open, so the `LOCAL` tab no longer
  dismisses itself under the operator. The picker block claims its gestures
  before the Home/waterfall branches, and the wake-on-touch path is exempted
  while the picker is open.

## 5. Home and control cleanups

- **Square UP/DOWN tiles.** The frequency drawer's up/down controls are equal
  squares (113x113 at y=184–297), matching the other launcher tiles.
- **Unified big-frequency style.** A single `draw_big_frequency` helper with
  `BIG_FREQUENCY_SIZE=58` and the VFO neon colour drives the top strip, the
  compact rail, the FREQUENCY drawer, and the font-review preview, so the large
  frequency reads the same everywhere.
- **Hidden font setting.** The FREQUENCY drawer no longer exposes a font control
  (no `font` box, no `action == "font"`).
- **FM-DX disclaimer.** Choosing the `FM-DX` source segment opens a modal
  (`FM-DX SHARED SERVERS`) explaining the shared tuner; `OK` dismisses it.
- **Empty right-rail tap is inert.** The mode grid is shorter than the tappable
  annunciator block. A tap on the empty space beneath it no longer opens the
  MODES drawer: the `radio_toggle` handler now hit-tests `lcd_home_mode_boxes()`
  before engaging a mode or toggling `radio_setup_open`.

## 6. Files

| File | Change |
| --- | --- |
| [`UI/receiver_catalog.py`](../UI/receiver_catalog.py) | New: protocol-neutral records and capability contract |
| [`UI/receiver_sources.json`](../UI/receiver_sources.json) | New: static seed receivers |
| [`UI/test_receiver_catalog.py`](../UI/test_receiver_catalog.py) | New: catalog/capability tests |
| [`UI/kiwi_gl_display.py`](../UI/kiwi_gl_display.py) | Browser, Globe rail, legend, zoom, Home fixes |
| [`UI/kiwi_station_health.py`](../UI/kiwi_station_health.py) | Reachability probing, local station rows |
| [`UI/fmdx.py`](../UI/fmdx.py) | `FmdxControlPolicy` shared-tuner safety |
| [`UI/openwebrx_client.py`](../UI/openwebrx_client.py) | `negotiated_capabilities()` |
| [`UI/test_board_v1.py`](../UI/test_board_v1.py) | Layout/receiver regression coverage |
| [`UI/test_ui_navigation.py`](../UI/test_ui_navigation.py) | Drawer, big-frequency, disclaimer tests |
| [`UI/test_fmdx.py`](../UI/test_fmdx.py), [`UI/test_fmdx_ui.py`](../UI/test_fmdx_ui.py) | FM-DX policy and UI tests |
| [`README.md`](../README.md) | Receivers section |
| [`docs/board-v1-review.md`](board-v1-review.md) | Receiver-browser rules and status |

## 7. Verification

- UI suite: 144 tests pass
  (`cd UI && ./.venv/bin/python -m unittest discover -s . -p 'test_*.py'`).
- Installer suite: 13 tests pass
  (`./UI/.venv/bin/python -m unittest discover -s tests`).
- `python -m py_compile` is clean and `git diff --check` reports no whitespace
  errors.
- Live OpenGL frames on the 1280x800 logical resolution confirm: an empty rail
  tap does not open MODES; the rail legend chips render and toggle their source
  group; and the zoom buttons draw the `+` / `−` glyph only.
- Physical touch behaviour on the CM5 panel still requires a device trial.
