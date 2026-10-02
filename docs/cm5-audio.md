# CM5 carrier audio: tested ES8316 / TPA3113 profile

This optional profile reproduces the custom CM5 carrier's working audio setup.
It does not apply to the original LCD machine's USB audio hardware. It installs
no display/touch driver and changes no orientation or touch mapping.

## Installation

On the custom carrier, with an already working display:

```sh
git pull --ff-only origin main
sudo bash scripts/install.sh --cm5-existing-display --cm5-audio
sudo reboot
```

The explicit `--cm5-audio` flag selects this hardware. Subsequent application
installs retain an already enabled profile. A normal `--cm5-existing-display`
install on a machine without the profile continues to preserve its audio setup.

If the updated application and working `CM5ES8316` sound card are already
installed, update just the audio software, without changing boot files:

```sh
sudo bash scripts/install-cm5-audio.sh --software-only
```

The full audio installer retains an available ES8316 kernel driver. If missing,
it builds the bundled upstream source against the **running kernel's matching
headers**. Header installation failure stops before boot changes. It installs
the audio overlay and makes GPIO13 an output LOW at boot. Reboot is required
when adding hardware support. It never installs the ST7701/JD9365 or touch
drivers, and does not upgrade the kernel. An externally built codec module is
kernel-specific: rerun the audio installer after changing kernels if the new
kernel lacks ES8316 support; this is not a DKMS installation.

## What changed

* The main UI now has an opt-in ES8316 adapter, replacing the separate test copy.
  The volume slider controls codec DAC attenuation: 50% amplitude is about
  -6 dB, 75% about -2.5 dB, and 100% is 0 dB. Analog headphone/mixer gains stay
  at the tested 0 dB values; unwanted analog input mixing is disabled.
* `cm5_speaker` converts incoming PCM (normally Kiwi's 12 kHz mono) to the
  verified **48 kHz, stereo, S16_LE** codec format. Explicit
  `rate_converter "samplerate_best"` and the `libasound2-plugins` dependency
  replace the original linear converter that produced metallic-sounding audio.
* Class-D GPIO13 is HIGH only while playback is ready, volume is nonzero,
  the SDR is unmuted, and headphones are absent. Stop and missing-codec paths
  leave it LOW. The DAC continues playing when headphones mute the speaker.
* `cm5-headphone-monitor.service` reads the codec's volatile register 0x4f
  through regmap/debugfs every 100 ms, with three-sample debounce. On this
  tested board bit2 is **1 inserted**, **0 removed** (0x26 / 0x22 observed).
  It changes no codec registers. The app alone controls GPIO13; stale (>2 s)
  or unknown jack state inhibits the speaker, preserving headphone playback.
* Detection and audio controls start with the service and persist across boots.
  The installer selects ALSA while retaining receiver, volume, mute, display,
  and other saved preferences. PipeWire remains an optional experimental UI
  backend; the CM5 Class-D profile is validated with ALSA selected.

The monitor requires root-readable `/sys/kernel/debug/regmap/1-0010/registers`.
If that interface is unavailable, inspect the monitor journal rather than
bypassing the headphone interlock. This is a carrier-specific software bridge,
not a standard ALSA jack event or a generic headset detector.

The previous desktop WirePlumber format rule was an exploratory playback aid;
it is not needed or installed by this direct-ALSA profile. Temporary tones,
third-party speech/music recordings, raw mixer dumps and listening experiments
are not dependencies and are not bundled.

## Hardware prerequisites and remaining board improvements

The tested r2 carrier required I2S data-line rework so CM5 playback DOUT reaches
ES8316 SDIN (and ES8316 SDOUT reaches CM5 capture DIN). Its U20 regulator input
was also on an isolated `3.3V` net instead of powered `3V3`. The verified repair
connected powered **R60 left pad to C75 left pad**, yielding about 3.3 V at C75
and 1.85 V at C74. **C74 is the 1.8 V output, not a 3.3 V connection point.**
Pad directions refer to the tested r2 top-view board; verify net identities on
another revision. Supply/wiring faults cannot be repaired by this installer.

CN6's insertion switch is wired through R64 to ES8316 GPIO1 and MCP23008 GP2.
The expander did not distinguish plugged/unplugged reliably; the codec did.
R60=R61=100 kΩ nominally yields only 1.65 V in the HIGH state. The current
codec-based workaround passed listening tests, but does not establish logic
margin across all boards/temperatures. For the next revision, use R60=10 kΩ
with R61=100 kΩ (nominal HIGH about 3.0 V), validating both attached inputs.
No resistor modification is performed or assumed by the software.

Moving the codec close to the amplifier and improving analog return routing
remain PCB improvements. Software does not fix the long analog route's hum.

## Check and undo

```sh
systemctl status cm5-headphone-monitor.service ituner-sdr.service
cat /run/cm5-headphone/state.json
pinctrl get 13
aplay -l
journalctl -u cm5-headphone-monitor.service -u ituner-sdr.service -n 60
```

Plugging headphones in should make GPIO13 LOW; unplugging should restore HIGH
only if the SDR is playing, unmuted and above zero volume. The sound-card number
may change, so configuration uses `CM5ES8316` by name. Preserve
`samplerate_best` for the accepted sound quality; changing to `linear`
intentionally restores the poorer comparison converter.

```sh
sudo bash scripts/disable-cm5-audio.sh
```

This stops the app, disables the profile/monitor and leaves Class-D off. The
audio overlay remains installed. Configure another audio output before
restarting the app. Each installation saves previous drop-ins, preferences and
(for hardware installs) audio overlay/boot configuration under
`/var/lib/ituner-sdr/cm5-audio-backup-*`. Old experimental CM5 drop-ins are moved
there so they cannot keep launching the separate test application.

## Validation

On the working CM5, direct reference speech/music and the improved SDR
conversion were accepted by listening; reverting to linear brought back the
metallic sound. Headphone detection changed 0x26 -> 0x22 on unplug, GPIO13
switched LOW -> HIGH, and the user confirmed speaker playback resumed.
Automated tests cover DAC scaling, speaker interlocks, absent codec, stale
detection and preservation of display settings when adding the audio boot lines.
The packaged software-only installer was then run on the working CM5: the main
UI replaced the separate test launcher, both services stayed active, hardware
playback remained S16_LE/stereo/48 kHz, libsamplerate was loaded, and the boot
configuration's SHA-256 remained unchanged. All 13 repository tests passed on
the target's Python 3.13. A completely blank OS installation was not rerun for
this change.
These are functional checks, not amplifier power, THD, or RF emissions measurements.
