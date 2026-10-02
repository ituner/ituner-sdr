import atexit
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AudioControls(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {'ITUNER_CM5_JACK_STATE': ''}):
            self.audio = load('cm5_audio_test', 'UI/cm5_audio_control.py')
        atexit.unregister(self.audio._shutdown)
        self.commands = []
        self.audio.run = lambda *args: self.commands.append(args)
        self.audio.card_available = lambda: True
        self.audio._ready = True
        self.audio._muted = False
        self.audio._volume = .75

    def test_volume_is_amplitude_not_linear_register_percentage(self):
        for volume, raw in [(1, 192), (.5, 180), (.75, 187), (0, 0)]:
            self.audio.set_volume(volume)
            self.assertIn(('amixer', '-q', '-c', 'CM5ES8316', 'sset', 'DAC', str(raw)), self.commands)
        self.assertEqual(self.commands[-1][-1], 'dl')

    def test_headphones_do_not_reenable_muted_or_stopped_speaker(self):
        for ready, muted, volume, inserted, enabled in [
            (True, False, .8, False, True),
            (True, False, .8, True, False),
            (True, True, .8, False, False),
            (False, False, .8, False, False),
            (True, False, 0, False, False),
        ]:
            with self.subTest(ready=ready, muted=muted, inserted=inserted):
                a = self.audio
                a._ready, a._muted, a._volume, a._headphone_blocked = ready, muted, volume, inserted
                a._gate = None
                a.gate()
                self.assertEqual(self.commands[-1], ('pinctrl', 'set', '13', 'op', 'dh' if enabled else 'dl'))

    def test_missing_codec_keeps_amp_off_without_mixer_access(self):
        self.audio.card_available = lambda: False
        self.audio.set_volume(.9)
        self.audio.prepare()
        self.audio.ready()
        self.assertFalse(self.audio._gate)
        self.assertTrue(all(command[0] == 'pinctrl' for command in self.commands))

    def test_initialization_closes_gate_before_mixer_changes(self):
        self.audio.prepare()
        self.assertEqual(self.commands[0], ('pinctrl', 'set', '13', 'op', 'dl'))
        self.assertIn(('amixer', '-q', '-c', 'CM5ES8316', 'sset', 'Left Headphone Mixer LLIN', 'off'), self.commands)
        self.assertFalse(self.audio._gate)

    def test_live_jack_watcher_and_stale_state(self):
        a = self.audio
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            a._jack_path = str(path)
            a._gate = None
            thread = threading.Thread(target=a._watch_headphones)
            thread.start()

            def check(inserted, enabled, age=0):
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'inserted': inserted, 'monotonic': time.monotonic() - age}))
                temporary.replace(path)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if a._gate is enabled:
                        return
                    time.sleep(.02)
                self.fail(f'Expected speaker {enabled}, got {a._gate}')

            try:
                check(False, True)
                check(True, False)
                check(False, True)
                check(False, False, age=5)
                check(False, True)
                check(None, False)
            finally:
                a._jack_stop.set()
                thread.join(3)
            # Jack changes must never mute or attenuate headphones.
            self.assertTrue(all(command[0] == 'pinctrl' for command in self.commands))


class HardwareConfiguration(unittest.TestCase):
    def test_audio_boot_changes_preserve_display_and_are_idempotent(self):
        config = load('audio_config', 'scripts/configure-cm5-audio.py')
        before = '[all]\ndtoverlay=verified-panel\ndtoverlay=verified-touch\n#dtoverlay=cm5-main-es8316\n'
        after = config.boot_config(before)
        self.assertTrue(after.startswith(before))
        self.assertIn('\ndtoverlay=cm5-main-es8316\n', after)
        self.assertIn('\ngpio=13=op,dl\n', after)
        self.assertEqual(config.boot_config(after), after)

    def test_disabled_section_is_not_active_audio(self):
        config = load('audio_config', 'scripts/configure-cm5-audio.py')
        after = config.boot_config('[none]\ndtoverlay=cm5-main-es8316\n')
        self.assertIn('[all]\n', after)
        self.assertEqual(after.count('dtoverlay=cm5-main-es8316'), 2)

    def test_codec_flag_uses_measured_board_polarity(self):
        monitor = load('jack_monitor', 'scripts/cm5-jack-monitor.py')
        with tempfile.TemporaryDirectory() as directory:
            monitor.REGISTERS = Path(directory) / 'registers'
            for value, inserted in [('22', False), ('26', True)]:
                monitor.REGISTERS.write_text('4e: 00\n4f: ' + value + '\n')
                self.assertIs(monitor.read_inserted(), inserted)
            monitor.REGISTERS.write_text('00: 00\n')
            with self.assertRaises(ValueError):
                monitor.read_inserted()


if __name__ == '__main__':
    unittest.main()
