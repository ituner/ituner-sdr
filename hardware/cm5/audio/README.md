# CM5 ES8316 audio hardware support

See [installation and board prerequisites](../../../docs/cm5-audio.md).

`cm5-main-es8316-overlay.dts` is the working custom-carrier overlay:
I2C1 address 0x10, RP1 GPIO4 GPCLK0 at 12.288 MHz, I2S clock producer,
two 32-bit slots, card name `CM5-ES8316` (ALSA ID `CM5ES8316`).
The application's PCM uses 16-bit samples at 48 kHz despite 32-bit I2S slots.
Class-D enable is GPIO13, active HIGH. The headphone switch reaches codec
GPIO1, whose measured status is polled by the separate monitor.

`driver/es8316.c` and `driver/es8316.h` were retrieved from the working CM5
and verified byte-for-byte against Linux **v6.18**:

* https://github.com/torvalds/linux/blob/v6.18/sound/soc/codecs/es8316.c
* https://github.com/torvalds/linux/blob/v6.18/sound/soc/codecs/es8316.h

They are unmodified upstream files, with original copyright/SPDX notices and
GPL-2.0 license text retained in `driver/LICENSE`. The small Makefile builds
the codec separately when the OS does not provide the module. Compiled modules
are deliberately not committed; build against the target's own kernel headers.
