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
emit a press and release. The fitted main TUNE encoder is an LPD3806-360BM-G5-24C optical encoder,
rated at 360 pulses per revolution. With the current one-step-per-period
setting, expect approximately 360 signed logical counts per complete turn
(not 600). Four-edge decoding would instead give 1440 counts per turn.

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

## Debounce and the TXS0102 translator

The main TUNE A/B signals pass through a Texas Instruments TXS0102DCUR.
This is an automatic bidirectional level translator, not an encoder controller
or a debounce filter. The LPD3806 has NPN open-collector A/B outputs. Verify
the actual board pull-ups, OE, supply rails and wiring against the schematic;
the encoder's 5–24 V supply rating is not a permitted TXS0102 signal voltage.

Keep the two `gpio-keys` push switches at `debounce-interval = <25>` ms.
Rotation uses the Linux quadrature state machine. In Raspberry Pi's 6.12
`rotary_encoder.c`, there is no configurable timed debounce or glitch-filter
property; adding `debounce-interval` to the rotary nodes does nothing.
Do not claim that the rotary A/B GPIOs have timed debounce enabled.

TUNE is optical, so contact-bounce timing from a mechanical push switch is
inappropriate. At one revolution per second, its 360 periods are 2.78 ms
apart, with nominal quadrature transitions every 694 microseconds. At ten
revolutions per second these intervals become 278 and 69.4 microseconds.
A blanket millisecond lockout would lose legitimate movement. VIEW/NAV are
mechanical and need separate assessment from TUNE.

Before enabling radio actions, capture slow/fast rotation, reversals and an
idle period. Verify 360 TUNE counts per turn and the small-knob detent counts.
If spurious counts appear, inspect both A/B signals at the CM5 side of the
translator with a logic analyser or oscilloscope. Event-device logs report
already decoded counts and cannot establish raw glitch widths. Choose a
bounded GPIO-level filter only after measuring glitches and the fastest valid
pulses; preserve A/B phase order. Userspace throttling of decoded events is
not a substitute for GPIO debounce.

TI describes approximately 30 ns edge accelerators and warns that excessive
trace/connector capacitance and reflections can cause retriggering, contention
or oscillations. Do not add arbitrary debounce capacitors to the translator
outputs without checking those load limits.

References:
- [TI TXS0102 datasheet, sections 7.3.1–7.3.5](https://www.ti.com/lit/ds/symlink/txs0102.pdf)
- [LPD3806-360BM encoder datasheet](https://kitsandparts.com/tutorials/encoders/LPD3806-360BM-ETC.pdf)
- [Raspberry Pi 6.12 rotary encoder driver](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/input/misc/rotary_encoder.c)
