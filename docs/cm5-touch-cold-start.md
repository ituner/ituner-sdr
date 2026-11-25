# CM5 touchscreen cold-start investigation

## Failure captured

On 2026-11-02, the GT911 enumerated at 4.3 seconds and iTuner opened it at
17.8 seconds. Despite attempted taps, Linux recorded no input events and only
one touchscreen interrupt until approximately 157.7 seconds. The app continued
running; it did not restart when touch recovered.

A once-per-boot driver rebind was tested. Warm restart tests passed, but the
overnight test on 2026-11-03 disproved it as a reliable fix:

- Boot ID: `45b15592-b857-4df5-b13f-7f9d8a328fd2`.
- Automatic rebind completed at 11.41 seconds; app ready at 19.30 seconds.
- User taps produced no events. A second rebind at 80.76–82.19 seconds,
  followed by app restart, also failed to restore response.
- At 110.99 seconds, input events remained zero and IRQ count was 2.
- GPIO12 read low, GPIO16 high. Throttling flags were zero; temperature was
  35.6 C at 112.8 seconds. These readings do not rule out a panel power fault.
- First nonzero event sample was at 156.204 seconds, with last-event time
  152.592 seconds. No further driver reset or app restart occurred at recovery.

This establishes failure below the application input handling. It does not
prove whether the cause is controller scanning, electrical startup, or IRQ
signalling. The failed rebind hook has been removed from startup.

## Polling candidate and verification

The replacement setup is documented in
[the CM5 touch guide](../hardware/cm5/touch/README.md). It uses the native polling
support in the upstream Raspberry Pi Goodix driver, built for the installed
kernel, with a narrowly scoped overlay and a 10 ms input polling interval.

Controller configuration readback had a valid checksum and 800×1280 dimensions.
No controller configuration/firmware was written. The user verified normal
taps, releases and dragging at 17 ms, then requested faster response. The
interval was reduced to 10 ms and verified again after reboot.

Final warm reboot `d81e7da6-447d-426c-89a2-a7b60a53cb03`:

- Replacement module loaded automatically from the running kernel's `updates`.
- Native poll interval: 10 ms. Readiness check completed at 4.96 seconds.
- App ready at 16.88 seconds. User confirmed responsive, accurate touch.
- Recorder subsequently captured 883 events, 12 presses and 12 releases,
  with no dropped synchronization events.
- USB power service remained active; the ineffective reset service was inactive.

**An overnight cold-start test is still required.** The warm results establish
working polling and persistence, not resolution of the original long-off fault.
If the controller produces no coordinates during the failure, polling alone
cannot restore them.

## Evidence retained on the CM5

- Passive boot records: `/var/log/ituner-sdr/touch-boot/<boot-id>.jsonl`.
- Failed-boot kernel/startup logs:
  `/var/log/ituner-sdr/touch-investigation/2026-11-03-*.log`.
- Original panel configuration readback:
  `/var/log/ituner-sdr/touch-investigation/2026-11-03-config.hex`.
- Installation backup:
  `/var/backups/ituner-sdr/touch-polling-20261103T091211Z`.
