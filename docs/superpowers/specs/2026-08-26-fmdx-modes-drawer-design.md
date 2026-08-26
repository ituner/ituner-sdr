# FM-DX Modes Drawer Design

## Problem

The live FM-DX display correctly identifies its protocol-owned mode as
`FM-FMDX`, but the Modes drawer receives the remembered Kiwi demodulator
value. This makes AM appear selected even though FM-DX supplies already
demodulated programme audio and does not accept Kiwi mode changes.

## User Experience

When the active receiver is FM-DX, opening Modes keeps the existing drawer in
the same right-side position. The drawer shows one prominent, selected
`FM-FMDX` mode with a short explanation that demodulation is controlled by the
FM-DX server. Kiwi mode families such as AM, USB, LSB, CW, and IQ are not
shown. Tuning-step controls remain available because they still affect manual
frequency scrubbing.

The drawer retains its existing Back behavior. Switching back to a Kiwi
receiver restores the normal Kiwi mode-family controls and the remembered
Kiwi mode.

## Implementation Boundary

The render loop will pass the effective receiver mode, already derived through
`fmdx.receiver_mode`, into the Modes drawer. The drawer will select between two
presentations:

- `FM-FMDX`: one server-controlled mode card plus tuning-step controls.
- Kiwi mode: the existing mode-family and tuning-step controls unchanged.

Hit testing will use the same effective-mode distinction. In FM-DX mode, taps
over the area formerly occupied by Kiwi mode families are inert; Back and
tuning-step actions remain active. No FM-DX tap may mutate the remembered Kiwi
demodulator state.

## State and Data Flow

1. The active server and remembered Kiwi mode produce an effective mode.
2. Home and the Modes drawer receive the same effective mode.
3. The drawer renders the protocol-appropriate controls.
4. Input routing checks whether the effective mode is `FM-FMDX` before
   resolving a mode-family action.
5. A later Kiwi receiver selection exposes the unchanged remembered Kiwi mode.

## Error Handling

Unknown or missing receiver metadata continues through the existing Kiwi
fallback. Only a receiver positively identified as FM-DX receives the
server-controlled presentation.

## Verification

Regression tests will verify that:

- An FM-DX server resolves the drawer mode to `FM-FMDX` even when the remembered
  Kiwi mode is AM.
- FM-DX mode-family hit testing returns no action.
- Back and tuning-step actions remain available in the FM-DX drawer.
- Kiwi mode-family hit testing remains unchanged.
- The full UI suite and Python compilation pass.

