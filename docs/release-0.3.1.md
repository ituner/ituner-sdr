# iTuner SDR 0.3.1

This update synchronizes the deployed CM5 application with GitHub main.

- ADS-B coverage accumulates new positions in RAM instead of repeatedly
  reprojecting the complete archive. Late packets, rolling windows, aircraft
  indexes and immutable native/web snapshots remain consistent.
- Retained ADS-B data shares a 250 MiB budget. Old rotated logs and cached
  aircraft details are reclaimed before oldest positions. SQLite compaction
  reclaims storage, and a durable cutoff prevents log replay resurrecting
  removed history. This cap takes priority over seven-day retention.
- The native 3D dome holds its detailed frame during reception updates. Picking,
  ground geometry and localized reception pulses stay paired with that frame.
- Long Scan gains the deployed 64× history zoom, panning, overview navigation,
  selectable trace details, offline station/country search, short reconnect
  continuity guards and waterfall response metrics.
- The HOME footer shows total system RAM headroom, sampled every two seconds.

Existing receiver settings, recorded history and display/touch/audio hardware
profiles are preserved. Five-minute ADS-B saves remain in effect. See
[coverage and storage](adsb-reception-coverage.md) and [Long Scan](long-scan.md).

Validation: 1,160 UI tests passed on CM5; 224 core tests passed with four
platform/dependency skips; all 14 web test files passed. Release files are
verified by SHA-256 against the deployed CM5 payload.
