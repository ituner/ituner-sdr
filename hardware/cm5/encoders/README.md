# CM5 three-knob input, r2 custom main board

This is an **opt-in input test**, separate from the working display and audio
setup. It describes the encoder board dated 2026-08-28 and CM5 main board dated
2026-08-26; confirm the installed PCBs have those revisions before use.

The encoder board's 20-pin FPC connects to `FPC3` on the main board. These are
**FPC contact numbers**, not CM5 module pin numbers or a 40-pin header pinout.

| Role | Encoder-board FPC | Main-board net | CM5 GPIO |
| --- | ---: | --- | ---: |
| TUNE phase A | 8 | `PHASE_A` (5 V to 3.3 V translator output) | 22 |
| TUNE phase B | 9 | `PHASE_B` (5 V to 3.3 V translator output) | 27 |
| VIEW phase A | 13 | `ENC1_A` | 17 |
| VIEW phase B | 14 | `ENC1_B` | 24 |
| VIEW press | 15 | `ENC1_D` | 23 |
| NAV phase A | 2 | `ENC2_A` | 6 |
| NAV phase B | 3 | `ENC2_B` | 5 |
| NAV press | 4 | `ENC2_D` | 11 |
| Unused second ENC2 shaft | 5, 6 | `ENC2_A1`, `ENC2_B1` | 9, 10 |

FPC3 pin 10 supplies 5 V, pin 17 supplies 3.3 V, and pins 1, 7, 11, 19,
and 20 are ground. The main-board schematic connects CM5 `GPIO_VREF` to 3.3 V.
The large TUNE encoder has **no push switch** in either schematic. Tuning-step
cycling and direct frequency entry therefore remain touchscreen actions.

The overlay creates three Linux rotary input devices and a separate two-button
input device. TUNE emits `REL_DIAL`, VIEW `REL_WHEEL`, NAV `REL_HWHEEL`;
VIEW press emits `BTN_0`, NAV press `BTN_1`. It leaves the dual-shaft ENC2's
second A/B pair idle. The 15-pulse/30-detent Alps mechanical encoders use two
stable steps per electrical period; the large encoder starts at one. Verify
actual click counts before making the app consume them. Turning direction may
need phase order swapped after physical testing.

## Build and inspect on the CM5

Keep the existing touchscreen working. Before enabling the overlay, check
whether another driver has claimed any input pin:

```bash
for pin in 5 6 11 17 22 23 24 27; do pinctrl get "$pin"; done
if command -v gpioinfo >/dev/null; then
    gpioinfo | grep -E 'line +([56]|11|17|22|23|24|27):'
fi
modinfo rotary_encoder
modinfo gpio_keys
```

If a driver is built into the kernel, `modinfo` may not list it; inspect
`/boot/config-$(uname -r)` for `CONFIG_INPUT_GPIO_ROTARY_ENCODER` and
`CONFIG_KEYBOARD_GPIO`. Compile the overlay only after those checks:

```bash
sudo apt-get install -y device-tree-compiler evtest
cd hardware/cm5/encoders
make
```

To enable it for the next boot, back up the boot configuration and any
same-named overlay first. Append `dtoverlay=cm5-main-three-knobs-overlay`
under `[all]` in `/boot/firmware/config.txt`, then reboot. Do not overwrite
the existing LCD, touch, or audio overlay settings.

```bash
sudo cp -a /boot/firmware/config.txt /boot/firmware/config.txt.before-three-knobs
sudo install -m 0644 cm5-main-three-knobs-overlay.dtbo /boot/firmware/overlays/
sudoedit /boot/firmware/config.txt
sudo reboot
```

After reboot, list and test the new input devices. Each rotation should emit
one signed relative event per logical click; each available push switch should
emit a press and release. The main TUNE shaft should report approximately 600
logical clicks per complete revolution if the fitted encoder matches the
original control design.

```bash
grep -A6 -B2 -E 'ituner-.*-encoder|iTuner encoder buttons' /proc/bus/input/devices
sudo evtest
```

`evtest` asks which `/dev/input/eventN` to inspect. Select each new rotary
device and the encoder-buttons device in turn; event numbers are assigned at
boot and must not be saved as configuration. Record the count and direction
of one full turn for each shaft before connecting these events to the app.
If input fails, remove the new `dtoverlay` line, restore the backed-up boot
configuration if needed, and reboot. This overlay does not replace or modify
the existing LCD, touch, or audio overlays.

## Non-invasive event check

After enabling the overlay, run from the repository root:

```bash
python3 scripts/check-cm5-knobs.py --duration 120
```

The reader discovers only the three named encoder devices and the named button
bank. It never saves event numbers or grabs the devices, and it does not open
the touchscreen or unrelated mouse wheels. Run as the application user so a
missing input-group permission is visible. It reconnects after device removal,
uses monotonic kernel timestamps for holds, and cancels pending presses after
lost synchronization or disconnect. This check makes no tuning changes.

Turn TUNE once clockwise, then VIEW and NAV five detents clockwise each.
Record net counts and direction, then test a short press and a hold on both
small knobs. TUNE has no press action. A hold is emitted once and does not
also activate a short click on release. Do not apply another quadrature divisor
in userspace: the kernel already emits logical clicks.

The application currently does not consume these new events. Its three-knob
controller and desktop simulation were developed in the separate, unmerged
`pr/knob-ui` branch. After hardware event validation, the input reader and
current UI integration must be ported and tested on this branch.
