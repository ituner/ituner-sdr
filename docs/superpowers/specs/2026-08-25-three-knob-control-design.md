# Three-Knob Control Design

## Objective

Make the complete iTuner SDR interface operable through one large 600-click-per-revolution tuning encoder and two smaller rotary encoders, all with short-press and long-press switches. Preserve the existing 8-inch touchscreen as a fully active, simultaneous input method.

The finished system must support direct Raspberry Pi GPIO encoders, USB or Bluetooth HID knobs, and mixed configurations through one normalized input model.

## Success Criteria

- Every actionable UI control is reachable and operable with knobs only.
- The touchscreen retains all current behavior and remains usable when knobs are absent or faulty.
- Slow tuning moves exactly one current tuning step per logical click.
- Fast tuning accelerates without creating delayed receiver commands.
- Menu focus and value-edit state are always visible when knob input is active.
- GPIO-only, HID-only, and mixed-device installations use the same UI behavior.
- Missing, disconnected, or invalid knob hardware never prevents the radio UI from starting.
- Knob-to-visible-response latency is below 80 ms at the 95th percentile on the Raspberry Pi target.
- With acceleration disabled, one full diagnostic rotation of the large knob reports exactly 600 logical clicks.

## Chosen Architecture

Use a normalized knob-action router beside the existing touchscreen path. Do not emulate screen coordinates or synthetic touch gestures, and do not rewrite the complete touch interaction state machine.

The data flow is:

```text
GPIO encoders ----\
                   +-- hardware adapters -- normalized knob events -- context router -- UI commands
USB/HID knobs ----/                                                        |
Touchscreen ------------------- existing touch path -----------------------+
```

Hardware workers may decode and enqueue events, but all UI state mutation and command execution stays on the main Pygame thread.

## Components and Boundaries

### `UI/knob_input.py`

This module owns hardware-facing input only.

- Discover configured GPIO and Linux input devices.
- Decode GPIO quadrature transitions through edge-driven `libgpiod` events.
- Read USB and Bluetooth HID behavior from Linux input events.
- Support HID relative axes such as `REL_DIAL` and `REL_WHEEL`, key pairs, buttons, and configured vendor-specific event codes.
- Normalize rotation, press, release, and hold events.
- Apply device-specific direction inversion, transitions per logical click, debounce, and assignment to `TUNE`, `VIEW`, or `NAV`.
- Calculate rotation timing information without deciding UI acceleration behavior.
- Monitor disconnects and reconnect configured devices.
- Place immutable normalized events in a thread-safe queue.
- Never read or mutate radio or UI state.

The normalized event vocabulary is:

- `TURN`: knob identity, signed logical-click delta, timestamp, and source identity.
- `PRESS`: one debounced button-down event.
- `RELEASE`: one debounced button-up event when no hold was emitted.
- `HOLD`: one event after the configured threshold; release must not also produce a short press.
- `DEVICE_STATUS`: connected, disconnected, invalid, or recovered.

### `UI/knob_controller.py`

This module owns hardware-independent knob interaction state.

- Track the active screen context and focused control.
- Retain focus per screen where the control still exists.
- Own value-edit mode and the original value needed for cancellation.
- Own the VIEW knob's radio mode: `ZOOM` or `VOLUME`.
- Convert normalized input into semantic commands.
- Compute the large tuning knob's bounded acceleration multiplier.
- Reset acceleration on pauses, direction reversals, context changes, and direct touch takeover.
- Coalesce rotation occurring within one UI frame while preserving the exact signed net logical-click count.
- Expose focus and knob-mode state for rendering and tests.
- Never call hardware APIs or draw directly.

The semantic command vocabulary includes:

- `TUNE`, `CYCLE_TUNE_STEP`, and `OPEN_FREQUENCY_ENTRY`.
- `SET_ZOOM`, `SET_VOLUME`, `TOGGLE_MUTE`, and `TOGGLE_VIEW_MODE`.
- `FOCUS_NEXT`, `FOCUS_PREVIOUS`, `ACTIVATE`, `BACK`, and `HOME`.
- `BEGIN_EDIT`, `ADJUST_FINE`, `ADJUST_COARSE`, `COMMIT_EDIT`, and `CANCEL_EDIT`.
- `SCROLL`, `PAGE`, `MAP_PAN_X`, `MAP_PAN_Y`, `MAP_ZOOM`, and `SELECT_MAP_TARGET`.

### `UI/kiwi_gl_display.py`

The active OpenGL UI remains the owner of application state and rendering.

- Start and stop the knob input manager without making it a startup dependency.
- Publish a compact active-screen context to the controller.
- Consume queued knob events once per frame on the main thread.
- Execute semantic commands through explicit action functions.
- Reuse those action functions from touch handlers where doing so is a focused, behavior-preserving change.
- Publish focusable controls for the active screen in a deterministic order.
- Draw the focus indicator, edit indicator, VIEW mode, tuning step, and acceleration multiplier.
- Preserve the existing touch gesture path.

This work must not attempt a broad decomposition of `kiwi_gl_display.py`. Small action helpers are introduced only where knob and touch behavior genuinely share an operation.

### `config/ituner-knobs.json`

This file defines hardware mapping and interaction timing without embedding board pins or HID codes in UI code.

Each physical knob configuration contains:

- Logical role: `TUNE`, `VIEW`, or `NAV`.
- Source type: `gpio` or `evdev`.
- GPIO A, B, and push-button lines or a stable Linux input-device matcher.
- HID rotation and button event codes when applicable.
- Direction inversion.
- Raw quadrature transitions per logical click.
- Expected logical clicks per revolution.
- Rotation and button debounce durations.
- Long-press duration.

The large encoder's expected click count is `600`. Raw electrical transitions remain distinct from logical clicks so encoders reporting two or four edges per click do not multiply tuning.

Configuration validation rejects duplicate GPIO assignments, duplicate logical roles, incomplete encoders, unsupported event codes, non-positive click ratios, and ambiguous device matchers. The default installed configuration is disabled until hardware mapping is supplied.

## Physical Interaction Model

### Main Radio

#### Large TUNE knob

- Rotate slowly: tune one current radio step per logical click.
- Rotate quickly: apply bounded velocity acceleration that emulates a longer horizontal waterfall swipe.
- Reverse direction or pause: immediately reset acceleration to the precision tier.
- Short-press: cycle the current tuning step.
- Long-press: open direct frequency entry.

#### Small VIEW knob

- Rotate in `ZOOM` mode: adjust waterfall zoom.
- Rotate in `VOLUME` mode: adjust main audio volume.
- Short-press: switch between `ZOOM` and `VOLUME`.
- Long-press: open Home from the main radio and act as Back in nested contexts.

#### Small NAV knob

- Rotate: move focus through visible on-canvas controls and sidebar commands.
- Short-press: activate the focused control or enter edit mode.
- Long-press: open Home from the main radio and act as Back in nested contexts.

### Menus and Drawers

- NAV rotation moves focus through visible controls in reading order.
- NAV short-press activates discrete controls or enters edit mode for adjustable values.
- While editing, TUNE provides fine adjustment and VIEW provides coarse adjustment.
- NAV short-press commits the value and leaves edit mode.
- NAV long-press cancels editing, restores the captured original value, and stays on the current screen.
- A subsequent NAV long-press performs Back.
- When no value is being edited, TUNE retains receiver tuning and VIEW scrolls or pages where the screen contains off-screen content.

### Receiver Directory and Search

- NAV moves through GLOBE, SEARCH, SORT, route filters, receiver rows, and BACK.
- NAV press activates the selected command or connects the focused receiver.
- VIEW rotates by one page while the receiver list is focused.
- Search's on-screen keyboard is completely traversable with NAV.
- TUNE remains available when the directory is open and no editable field is active.

### Globe and Map Screens

- TUNE rotates the globe horizontally.
- VIEW rotates the vertical axis or adjusts zoom.
- VIEW short-press toggles its visible map mode between `PAN Y` and `ZOOM`.
- NAV traverses map commands and the ordered set of receiver candidates.
- NAV press activates a command or selects the focused receiver candidate.
- NAV long-press returns to the preceding receiver or test screen.

### Numeric Entry and On-Screen Keyboards

- NAV moves through keys and activates the focused key.
- VIEW moves by row or page when that reduces excessive rotation.
- TUNE adjusts the selected digit or numeric value where a direct numeric editing model exists.
- Long-press NAV cancels and returns without applying an invalid value.

### Freeform Touch Alternatives

Every freeform touch gesture receives a deterministic knob action:

- Horizontal waterfall swipe becomes accelerated TUNE rotation.
- Pinch zoom becomes VIEW rotation in `ZOOM` mode.
- Map drag becomes TUNE horizontal pan plus VIEW vertical pan.
- Slider drag becomes focused fine and coarse adjustment.
- Movable caption and monitoring overlays use ordered lane cycling instead of pixel dragging.

## Focus and Feedback

- The active knob focus uses a bright outline that remains legible over dark panels, the waterfall, and selected tiles.
- Edit mode uses a distinct accent and displays the value being adjusted.
- Focus appears on the first knob event and remains tied to the active screen.
- Focus never targets a hidden, disabled, or covered control.
- Screen transitions select the first useful control or restore the last still-valid focus for that screen.
- Touch immediately commits the currently displayed knob-edited value, leaves edit mode, uses the existing touch behavior, and temporarily hides the knob focus.
- The next knob event restores focus to the touched control when it can be identified; otherwise it uses that screen's default focus.
- Temporary overlays identify `TUNE STEP`, `ZOOM`, `VOLUME`, tuning acceleration, and map-axis mode.
- Temporary status warnings report missing or disconnected configured devices without blocking the UI.

## Tuning Acceleration and Command Delivery

Acceleration is computed from logical-click timing in `knob_controller.py`, not from raw GPIO edges.

- The precision tier always equals one current tuning step per logical click.
- Medium and fast tiers use configurable, bounded multipliers.
- Direction reversal resets to the precision tier before applying the reversing click.
- A pause longer than the configured acceleration window resets to the precision tier.
- Acceleration is disabled in diagnostic count mode and while adjusting ordinary menu values.
- Per-frame coalescing combines signed movement into one newest desired frequency.
- The existing radio state remains the source of truth, allowing Kiwi workers to consume the latest requested frequency without accumulating a playback queue.
- All resulting frequencies pass through the existing receiver-range clamp and step quantization.

## Touch Coexistence

The touchscreen is always enabled.

- Knob and touch paths may be used alternately without changing modes in configuration.
- Touch takes immediate ownership when a gesture starts.
- Touch commits the currently displayed knob-edited value before normal touch handling continues.
- Live values already committed through a knob remain committed.
- Knob activity during an active touch gesture is queued only until that gesture ends, then stale motion events are discarded and button events are processed in order.
- No synthetic touch events are generated for physical knobs.

## Hardware and Runtime Behavior

### GPIO

- Use the Raspberry Pi's `libgpiod` character-device interface.
- Decode quadrature with a valid Gray-code transition table.
- Use edge events rather than polling.
- Count and ignore impossible transitions.
- Keep rotation debounce and push-button debounce independent.

### USB and Bluetooth HID

- Match devices using stable configured identity fields instead of `/dev/input/eventN` numbering.
- Read Linux evdev events directly so relative dials, wheels, and key-emitting devices share one adapter.
- Reopen configured devices after disconnect and reconnect.
- Do not claim or exclusively grab a device unless configuration explicitly enables that behavior.

### Desktop Simulation

A development-only keyboard profile emits normalized knob events:

- TUNE left and right.
- VIEW left, right, press, and hold.
- NAV previous, next, press, and hold.

Simulation exercises the same controller and UI command path as physical hardware.

## Installation and Diagnostics

- Install the Raspberry Pi `libgpiod` Python binding and any required evdev dependency through the existing installer.
- Install a disabled example `ituner-knobs.json` without overwriting an existing operator configuration.
- Keep the service in the `input` supplementary group.
- Knob initialization failure must not make systemd restart the UI.
- Add a diagnostic command that lists matching hardware, validation errors, normalized live events, logical click totals, press duration, and disconnect/reconnect status.
- Diagnostic count mode disables acceleration and provides the 600-click full-rotation acceptance check.

## Error Handling

- Missing configuration means knob support is disabled and touch starts normally.
- Invalid configuration disables only the affected source and reports the exact validation error.
- A disconnected device retains its logical role for reconnection but produces no UI actions.
- A reconnect starts with cleared quadrature and press state so stale edges cannot create motion or a false press.
- Long-press emits exactly one `HOLD`; its release does not emit `RELEASE` as a short activation.
- Event-queue pressure coalesces rotations by knob and frame while preserving signed net clicks. Button and device-status events are never coalesced away.
- Tuning and adjustable values remain clamped to their existing legal ranges.

## Test Strategy

### Input Unit Tests

- Valid clockwise and counterclockwise GPIO Gray-code sequences.
- Impossible and bouncing transitions.
- Two-edge and four-edge encoders normalized to logical clicks.
- Exactly 600 logical clicks in diagnostic count mode.
- HID relative-axis and key-pair mappings.
- Direction inversion and mixed hardware sources.
- Press, release, debounce, hold, and hold-without-short-press behavior.
- Disconnect, reconnect, invalid configuration, and duplicate assignment handling.

### Controller Unit Tests

- Slow, medium, and fast tuning tiers.
- Immediate acceleration reset after reversal, pause, context change, or touch takeover.
- Per-frame coalescing with exact signed net movement.
- Focus order, disabled-control skipping, wrapping, restoration, and screen transitions.
- VIEW mode switching between Zoom and Volume.
- Begin, fine adjust, coarse adjust, commit, and cancel edit behavior.
- Back and Home behavior in every context.

### UI Integration Tests

Tests send normalized events rather than physical input.

- Traverse every registered control on every screen.
- Open and close Receivers, Search, Modes, Audio, Display, Filter, Settings, Tests, ASR, direct frequency entry, and both globe surfaces without touch.
- Select receiver rows and operate SORT and route filters.
- Operate all sliders with fine and coarse adjustment, including cancellation restore.
- Pan and zoom maps and select receiver candidates.
- Tune, zoom, change volume, mute, and cycle tuning steps from the main radio.
- Switch from knob to touch and back while preserving valid committed state.
- Verify no focus target is hidden, disabled, outside the active screen, or inaccessible.

### Physical Raspberry Pi Acceptance

Run on the target Raspberry Pi 5, 8-inch touchscreen, large 600-click encoder, and two small encoders:

- GPIO-only profile.
- HID-only profile.
- Mixed GPIO and HID profile.
- Cold boot with all devices, with one missing device, and with no knobs.
- Disconnect and reconnect each HID device while the UI remains active.
- Rotate the large knob slowly for exact step tuning and quickly for bounded acceleration.
- Perform a full 600-click diagnostic rotation with acceleration disabled.
- Traverse the complete UI using knobs only, then repeat representative actions with touch.
- Confirm knob-to-visible-response latency is below 80 ms at p95.
- Confirm rapid tuning leaves no delayed retune playback after rotation stops.

## Delivery Sequence

1. Normalized event types, configuration validation, desktop simulator, and diagnostics.
2. GPIO and HID adapters with unit tests and reconnect behavior.
3. Pure controller, acceleration, focus state, and command vocabulary.
4. Main radio tuning, Zoom/Volume, Home, focus rendering, and touch takeover.
5. Menus, drawers, receiver directory, keyboards, and adjustable values.
6. Waterfall, maps, globes, overlay lanes, and remaining spatial interactions.
7. Installer integration, automated full traversal, Pi latency measurement, and physical acceptance.

Each stage must leave the touchscreen path operational and must be independently testable before the next stage begins.

## Out of Scope

- Removing or disabling touchscreen interaction.
- Replacing the existing SDR state, Kiwi stream workers, or touch gesture system.
- A broad visual redesign unrelated to focus and knob feedback.
- Hard-coding one vendor's HID identifiers or one fixed GPIO pinout.
- Remote control over a network protocol.
