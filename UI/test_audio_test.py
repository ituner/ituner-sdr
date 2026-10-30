"""Signal calibration and exclusive-output cleanup, without emitting sound."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from audio_test import RATE, SineTest, AudioTestWorkspace, sine_pcm


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.external_audio = False
        self.external_audio_generation = 0
        self.external_audio_sink_released = False
        self.mute = False
        self.release = True

    def audio_controls_snapshot(self):
        return {'mute': self.mute}, 0

    def external_audio_sink_released_snapshot(self):
        return self.release


class AudioTestTests(unittest.TestCase):
    def test_tone_frequency_amplitude_stereo_and_fades(self):
        pcm = np.frombuffer(sine_pcm(1000, -6, 0, RATE, RATE), '<i2').reshape(-1, 2)
        np.testing.assert_array_equal(pcm[:, 0], pcm[:, 1])
        self.assertEqual(pcm[0, 0], 0)
        self.assertEqual(pcm[-1, 0], 0)
        steady = pcm[2400:45600, 0].astype(float)
        rms = np.sqrt(np.mean(steady ** 2))
        self.assertAlmostEqual(rms / 32767, 10 ** (-6/20) / np.sqrt(2), places=4)
        spectrum = np.abs(np.fft.rfft(steady))
        self.assertAlmostEqual(np.argmax(spectrum) * RATE / len(steady), 1000)
        full = np.frombuffer(sine_pcm(1000, 0, 2400, 4800, RATE), '<i2')
        self.assertLessEqual(np.max(full), 32767)
        self.assertGreaterEqual(np.min(full), -32767)

    def make_test(self):
        self.state = State()
        self.player = Mock()
        self.player.poll.return_value = None
        self.ui = Mock()
        self.ui.BufferedAudioPlayer.return_value = self.player
        self.args = SimpleNamespace(audio=True, audio_rate=12000, output_volume=.75)
        return SineTest(self.ui, self.args, self.state)

    def test_stop_releases_output_without_changing_volume_or_radio_pause(self):
        test = self.make_test()
        test.start(1000, -30, 5)
        deadline = time.monotonic() + 1
        while not self.player.submit.called and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(self.player.submit.called)
        test.stop()
        test.thread.join(1)
        self.assertFalse(test.snapshot()['running'])
        self.assertFalse(self.state.external_audio)
        self.ui.stop_audio_player.assert_called_once_with(self.player)
        playback_args, channels = self.ui.BufferedAudioPlayer.call_args.args
        self.assertEqual(channels, 2)
        self.assertEqual(playback_args.audio_rate, 48000)
        self.assertIsNone(playback_args.output_volume)
        self.assertEqual(self.args.audio_rate, 12000)
        self.assertEqual(self.args.output_volume, .75)

    def test_output_failure_restores_radio(self):
        test = self.make_test()
        self.player.poll.return_value = 1
        test.start(1000, -30, 5)
        test.thread.join(1)
        self.assertFalse(self.state.external_audio)
        self.assertIn('Could not open', test.snapshot()['status'])
        self.ui.stop_audio_player.assert_called_once()

    def test_mute_or_other_tool_prevents_start(self):
        test = self.make_test()
        self.state.mute = True
        with self.assertRaisesRegex(ValueError, 'Unmute'):
            test.start(1000, -30, 5)
        self.state.mute = False
        self.state.external_audio = True
        with self.assertRaisesRegex(ValueError, 'Another tool'):
            test.start(1000, -30, 5)
        self.ui.BufferedAudioPlayer.assert_not_called()

    def test_cancel_while_waiting_never_opens_device(self):
        test = self.make_test()
        self.state.release = False
        test.start(1000, -30, 5)
        test.stop()
        test.thread.join(1)
        self.ui.BufferedAudioPlayer.assert_not_called()
        self.assertFalse(self.state.external_audio)

    def test_new_owner_is_not_released_by_old_test(self):
        test = self.make_test()
        self.state.release = False
        test.start(1000, -30, 5)
        with self.state.lock:
            self.state.external_audio_generation += 1
        test.stop()
        test.thread.join(1)
        self.assertTrue(self.state.external_audio)

    def test_timed_completion(self):
        test = self.make_test()
        with patch('audio_test.DURATIONS', (.04,)):
            test.start(1000, -30, .04)
        test.thread.join(1)
        self.assertFalse(test.snapshot()['running'])
        self.assertIn('Finished', test.snapshot()['status'])
        self.assertFalse(self.state.external_audio)

    def test_back_stops_and_level_controls_disabled_during_playback(self):
        test = self.make_test()
        ui = self.ui
        ui.contains = lambda box, x, y: box[0] <= x <= box[2] and box[1] <= y <= box[3]
        workspace = AudioTestWorkspace(ui, self.args, self.state)
        workspace.open = True
        workspace.actions = [((0, 0, 20, 20), ('back', None))]
        workspace.tap(10, 10)
        self.assertFalse(workspace.open)
        self.assertTrue(workspace.test.stop_event.is_set())


if __name__ == '__main__':
    unittest.main()
