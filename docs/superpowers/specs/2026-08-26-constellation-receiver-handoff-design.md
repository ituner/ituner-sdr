# Constellation Receiver Handoff and Receiver Filters

## Goal

Keep the receiver selected in Constellation active after Constellation closes, remove the post-Constellation lag and receiver changes, and make switching between KiwiSDR and FM-DX directories explicit on the 8-inch interface.

## Approved behavior

- Selecting a receiver in Constellation makes it the application’s active receiver.
- Leaving Constellation stops only its auxiliary warm-listener and scout work. It does not restore an earlier receiver or frequency.
- The normal receiver worker resumes ownership of audio and tuning for the selected receiver, allowing immediate waterfall scrubbing.
- Late events from a closed Constellation session are discarded. They cannot select a fallback, restart scouts, restart the mixer, or overwrite the remembered receiver.
- Opening Receivers lands on the active receiver’s protocol category and centers its selected row.
- The receiver rail contains `ALL`, `KIWI`, `FMDX`, `FAVORITES`, and `BACK`.
- `KIWI` contains both direct and proxied KiwiSDR endpoints. The separate `DIRECT` and `PROXY` buttons are removed.
- The selected receiver is written immediately to the existing receiver-state file and remains selected across navigation and application restart.

## Lifecycle design

Constellation has two kinds of state:

1. Persistent radio state: active server, receiver protocol, frequency, zoom, and radio controls.
2. Temporary Constellation state: three warm listener streams, scout probes, event queues, heat-map maintenance, and replacement scheduling.

Closing Constellation preserves the first group and terminates the second. The close transition marks the Constellation session inactive before stopping workers, clears queued session events, returns external-audio ownership to the normal receiver path, and prevents all Constellation event and maintenance branches from running while the screen is closed.

Worker events belong to the Constellation session that created them. A closed session’s ready, failed, scout, promotion, and rotation work is ignored even if a network call finishes after navigation has completed.

## Receiver-filter design

Receiver rows retain an explicit protocol value of `kiwi` or `fmdx`. Filtering uses that value rather than inferring protocol from button labels:

- `ALL`: every receiver.
- `KIWI`: direct and proxy KiwiSDR receivers.
- `FMDX`: FM-DX Webserver receivers.
- `FAVORITES`: saved favorites from either protocol.

When Receivers opens, its initial protocol filter follows the active receiver: `KIWI` for a KiwiSDR and `FMDX` for an FM-DX server. The active row is health-ordered, centered when possible, and visibly selected. The operator can always use `ALL` or the opposite protocol button to browse elsewhere.

## Performance constraints

- No Constellation mixer, scout, failover, promotion, or rotation may start while Constellation is closed.
- Closing Constellation must not wait for remote network timeouts.
- Stopping a session must be idempotent and safe when no worker is active.
- Receiver filtering remains an in-memory operation over the current directory and must not perform network access.

## Error handling

- If the selected receiver fails after Constellation closes, the normal receiver connection status reports the failure; Constellation must not silently choose another server.
- If a remembered receiver is absent from the current directory, the application retains the endpoint and exposes it through the existing remembered-receiver metadata path.
- An empty protocol category displays an empty result without changing the active receiver.

## Verification

Automated tests will cover:

- Closing Constellation preserves server, protocol, frequency, and zoom.
- Closing sets worker stop signals, clears external-audio ownership, and discards queued events.
- Closed Constellation sessions cannot run failover or periodic maintenance.
- `KIWI` includes direct and proxy KiwiSDR rows and excludes FM-DX rows.
- `FMDX` excludes KiwiSDR rows.
- Receiver opening chooses the active protocol filter and centers the active row.
- The selected receiver persists through a state-file round trip.
- Existing menu, receiver-picker, FM-DX, and Constellation tests remain green.

The final manual check follows this path: select a receiver in Constellation, exit, scrub the waterfall, open Receivers, confirm the same receiver is selected, switch to `FMDX`, switch back with `KIWI`, and verify the interface remains responsive throughout.
