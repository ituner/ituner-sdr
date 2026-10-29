# iTuner SDR 0.2.0

This release synchronizes the application updates already running on the CM5
with the shared main branch.

- **Smart Seek:** survey the selected AM broadcast band while audio continues;
  screen candidates for persistent carriers and varying AM sidebands. Browse
  a stable station list with country flags, schedule matches, a Weak-to-Strong
  minimum-signal slider and a double-height listening row showing transmitter
  details. Tapping tunes without closing the list. Results are cached for five
  minutes per receiver and band. See [Smart Seek](smart-seek.md).
- **Prepared Auto Tune:** prepare and refine an AM carrier correction after
  tuning settles; apply it only when the operator selects the ready button.
  See [AM Auto Tune](am-auto-tune.md).
- **Audio test:** provide an explicit output-test workspace with controlled
  tone generation and cleanup that restores radio ownership. See
  [Audio test](audio-test.md).
- **USB receivers:** retain deliberate receiver assignment and queue handling,
  keep known devices quiet at startup, and request a receiver when a decoder
  or spectrum operation has no usable selection. See
  [Receiver registry](rtl-dongle-registry.md).
- **ADS-B:** synchronize coverage views, selection controls and the explicit
  dome reset independently of its time-window selector. See
  [Reception coverage](adsb-reception-coverage.md).

The version file and both boot-splash images identify this release. Display,
touch and audio hardware profiles are unchanged.

Validation: all 864 UI tests passed on the CM5, and all 62 JavaScript tests
passed locally. The CM5 runtime suite also completed successfully: 219 tests
with three optional tests skipped. The candidate application compiled on both
development and CM5 environments.
