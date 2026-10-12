"""Exercise the actual subprocess boundary without a receiver or OpenGL window."""
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'UI'))
import kiwi_gl_display as ui


class WSPRRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.wav = Path(self.temp.name) / '261008_1800.wav'
        self.wav.write_bytes(b'fixture')
        self.session = SimpleNamespace(stop_event=threading.Event(),
            decode_scheduler=SimpleNamespace(wait_until_idle=lambda *args: True),
            decoder_settings=SimpleNamespace(snapshot=lambda: ('normal', 0)),
            _set_decode_state=Mock())
        self.worker = ui.WSPRDecodeWorker(self.session)

    def tearDown(self):
        self.temp.cleanup()

    def run_child(self, code, timeout=5):
        with patch.object(ui, 'wsprd_background_command', lambda command: [sys.executable, '-c', code]), \
             patch.object(ui, 'WSPR_DECODE_TIMEOUT_SECONDS', timeout):
            return self.worker._run_wsprd(self.wav, 7038.6)

    def test_decoder_writes_in_capture_directory_and_drains_large_output(self):
        result = self.run_child("from pathlib import Path; Path('ALL_WSPR.TXT').write_text('ok'); print(' ' * 200000); print('<DecodeFinished>')")
        self.assertEqual(result, [])
        self.assertEqual((self.wav.parent / 'ALL_WSPR.TXT').read_text(), 'ok')

    def test_failure_keeps_decoder_diagnostic(self):
        with self.assertRaisesRegex(RuntimeError, 'wsprd exited 1: Error: inaccessible data directory'):
            self.run_child("import sys; print('Error: inaccessible data directory', file=sys.stderr); sys.exit(1)")

    def test_timeout_reaps_child_and_releases_slot(self):
        with self.assertRaisesRegex(RuntimeError, 'decode timeout'):
            self.run_child('import time; time.sleep(30)', timeout=.15)
        self.assertEqual(self.run_child("print('<DecodeFinished>')"), [])

    def test_stop_reaps_child(self):
        self.worker.stop_event.set()
        self.assertIsNone(self.run_child('import time; time.sleep(30)'))

    def test_retry_and_next_cycle_clear_stale_progress(self):
        state = SimpleNamespace(lock=threading.Lock(), decode_audio_seconds=120., decode_cycle_start=123.)
        ui.WSPRMonitorSession._set_decode_state(state, 'RETRY', detail='connection timed out')
        self.assertEqual((state.decode_audio_seconds, state.decode_cycle_start), (0., 0.))
        ui.WSPRMonitorSession._set_decode_state(state, 'ARMED', cycle_start=240.)
        self.assertEqual((state.decode_audio_seconds, state.decode_cycle_start), (0., 240.))


if __name__ == '__main__':
    unittest.main()
