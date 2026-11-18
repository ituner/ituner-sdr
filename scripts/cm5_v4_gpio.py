"""V4 carrier audio GPIOs, using the kernel-owned TCA9555 driver."""
import atexit
from pathlib import Path
import sys

import gpiod
from gpiod.line import Direction, Value

AMP = 15  # P17, active-high TPA3113D2 SD input
JACK = 13  # P15 / CODEC_GPIO2 / JACK_SW; low with plug inserted
_amp = None
_jack = None


def _chip_path():
    for path in Path('/dev').glob('gpiochip*'):
        with gpiod.Chip(str(path)) as chip:
            info = chip.get_info()
            if info.label == '1-0020' and info.num_lines == 16:
                if chip.get_line_info(AMP).name != 'SPK_ON':
                    raise OSError('V4 amplifier line name does not match')
                if chip.get_line_info(JACK).name != 'CODEC_GPIO2':
                    raise OSError('V4 jack line name does not match')
                return str(path)
    raise OSError('V4 TCA9555 at I2C1 address 0x20 is unavailable')


def set_speaker(enabled):
    global _amp
    if _amp is None:
        _amp = gpiod.request_lines(
            _chip_path(), consumer='ituner-speaker',
            config={AMP: gpiod.LineSettings(
                direction=Direction.OUTPUT, output_value=Value.INACTIVE)},
        )
    _amp.set_value(AMP, Value.ACTIVE if enabled else Value.INACTIVE)


def read_inserted():
    global _jack
    if _jack is None:
        _jack = gpiod.request_lines(
            _chip_path(), consumer='ituner-headphone-detect',
            config={JACK: gpiod.LineSettings(direction=Direction.INPUT)},
        )
    return _jack.get_value(JACK) == Value.INACTIVE


def close():
    global _amp, _jack
    if _amp is not None:
        try:
            _amp.set_value(AMP, Value.INACTIVE)
        finally:
            _amp.release()
            _amp = None
    if _jack is not None:
        _jack.release()
        _jack = None


atexit.register(close)

if __name__ == '__main__':
    if sys.argv[1:] != ['--off']:
        raise SystemExit('Usage: cm5_v4_gpio.py --off')
    set_speaker(False)
    close()
