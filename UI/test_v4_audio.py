import atexit
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, (ROOT.parent / 'scripts' / filename if filename == 'cm5_v4_gpio.py' else ROOT / filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V4Audio(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.gpiod = types.ModuleType('gpiod')
        self.gpiod.LineSettings = lambda **kwargs: kwargs
        self.gpiod.request_lines = self.request
        self.line = types.ModuleType('gpiod.line')
        self.line.Direction = types.SimpleNamespace(INPUT='in', OUTPUT='out')
        self.line.Value = types.SimpleNamespace(ACTIVE=1, INACTIVE=0)
        self.modules = patch.dict(sys.modules, {'gpiod': self.gpiod, 'gpiod.line': self.line})
        self.modules.start()
        self.gpio = load('cm5_v4_gpio', 'cm5_v4_gpio.py')
        atexit.unregister(self.gpio.close)
        self.gpio._chip_path = lambda: '/dev/gpiochip14'

    def request(self, path, **kwargs):
        req = Mock()
        req.get_value.return_value = 1
        self.requests.append((path, kwargs, req))
        return req

    def tearDown(self):
        self.gpio.close()
        self.modules.stop()

    def test_amp_uses_only_p17_and_closes_low(self):
        self.gpio.set_speaker(True)
        self.gpio.set_speaker(False)
        self.assertEqual(len(self.requests), 1)
        _, config, req = self.requests[0]
        self.assertEqual(config['config'], {15: {'direction': 'out', 'output_value': 0}})
        self.assertEqual(req.set_value.call_args_list[0].args, (15, 1))
        self.gpio.close()
        req.set_value.assert_called_with(15, 0)
        req.release.assert_called_once()

    def test_jack_reads_only_p15_active_low(self):
        self.assertFalse(self.gpio.read_inserted())
        _, config, req = self.requests[0]
        self.assertEqual(config['config'], {13: {'direction': 'in'}})
        req.get_value.return_value = 0
        self.assertTrue(self.gpio.read_inserted())

    def test_app_interlocks_route_to_expander(self):
        with patch.dict(sys.modules, {'cm5_v4_gpio': self.gpio}), patch.dict(os.environ, {
            'ITUNER_CM5_BOARD': 'v4', 'ITUNER_CM5_JACK_STATE': '',
        }):
            app = load('audio_v4_test', 'cm5_audio_control.py')
        atexit.unregister(app._shutdown)
        app.run = Mock(side_effect=AssertionError('Unexpected direct GPIO/mixer command'))
        app.set_speaker = Mock()
        for ready, muted, volume, blocked, expected in [
            (True, False, .5, False, True),
            (True, False, .5, True, False),
            (True, True, .5, False, False),
            (True, False, 0, False, False),
            (False, False, .5, False, False),
        ]:
            app._ready, app._muted, app._volume, app._headphone_blocked = ready, muted, volume, blocked
            app._gate = None
            app.gate()
            app.set_speaker.assert_called_with(expected)
        app.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
