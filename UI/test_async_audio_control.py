import threading
import time
import unittest
from async_audio_control import AsyncAudioControl


class Backend:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.volume = .2

    def get_volume(self):
        return self.volume

    def prepare(self):
        self.entered.set()
        if not self.release.wait(2):
            raise RuntimeError('Test failed to release simulated codec')
        self.calls.append(('prepare',))
        return True

    def ready(self, value=True):
        self.calls.append(('ready', value))

    def set_volume(self, value):
        self.calls.append(('volume', value))
        self.volume = value

    def set_mute(self, value):
        self.calls.append(('mute', value))


class AsyncControlTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.control = AsyncAudioControl(self.backend)

    def tearDown(self):
        self.backend.release.set()
        self.control.close()

    def stall_reconnect(self):
        thread = threading.Thread(target=self.control.prepare)
        thread.start()
        self.assertTrue(self.backend.entered.wait(1))
        return thread

    def test_ui_requests_do_not_wait_on_stalled_reconnect_and_coalesce(self):
        thread = self.stall_reconnect()
        started = time.monotonic()
        for i in range(101):
            self.control.set_volume(i / 100)
            self.control.set_mute(i == 0)
        self.assertLess(time.monotonic() - started, .1)
        self.assertEqual(self.control.get_volume(), 1)
        self.assertEqual(len(self.control._commands), 1)
        self.backend.release.set()
        thread.join(1)
        self.control.ready()
        self.assertEqual(self.backend.calls, [('prepare',), ('volume', 1), ('mute', False), ('ready', True)])

    def test_mute_precedes_volume_and_prepare_is_ordering_barrier(self):
        thread = self.stall_reconnect()
        self.control.set_volume(.4)
        self.control.set_mute(True)
        self.backend.release.set()
        thread.join(1)
        self.control.ready()
        self.assertEqual(self.backend.calls[1:3], [('mute', True), ('volume', .4)])

    def test_close_discards_unapplied_volume_and_disables_amp(self):
        thread = self.stall_reconnect()
        self.control.set_volume(1)
        closing = threading.Thread(target=self.control.close)
        closing.start()
        deadline = time.monotonic() + 1
        while not self.control._closed and time.monotonic() < deadline:
            time.sleep(.001)
        self.backend.release.set()
        closing.join(1)
        thread.join(1)
        self.assertFalse(closing.is_alive())
        self.assertEqual(self.backend.calls, [('prepare',), ('ready', False)])
        self.assertIsNone(self.control.set_volume(.8))

    def test_failed_hardware_request_does_not_kill_worker(self):
        def fail(value):
            raise OSError('simulated codec timeout')
        self.backend.set_volume = fail
        with self.assertLogs(level='ERROR'):
            self.control.set_volume(.4)
            self.control.ready()
        self.backend.set_volume = lambda value: self.backend.calls.append(('volume', value))
        self.control.set_volume(.3)
        self.control.ready()
        self.assertIn(('volume', .3), self.backend.calls)

    def test_nonfinite_volume_is_rejected(self):
        with self.assertRaises(ValueError):
            self.control.set_volume(float('nan'))


if __name__ == '__main__':
    unittest.main()
