import unittest
from unittest.mock import patch

import kiwi_gl_display as ui
import kiwi_live_display_fb as kiwi
from test_waterfall_protocol import Transport


class AudioSliderTests(unittest.TestCase):
    def test_denoise_preserves_old_anchors_but_has_intermediate_coefficients(self):
        for level in range(1, 6):
            self.assertEqual(kiwi.denoise_wdsp_params(level),
                             kiwi.wdsp_noise_params(*kiwi.DENOISE_PRESETS[level][1]))
        gains = [kiwi.denoise_wdsp_params(i / 100)[2] for i in range(501)]
        self.assertEqual(len(set(gains)), 501)
        self.assertTrue(all(a < b for a, b in zip(gains, gains[1:])))
        for invalid in (None, 'bad', float('nan'), float('inf')):
            self.assertEqual(kiwi.denoise_level(invalid), 0)

    def test_denoise_fractional_state_and_smooth_makeup_gain(self):
        state = ui.SharedState('http://kiwi.test', 7075, 8, -95, 142, 245, 3, 'am', True)
        state.set_audio_controls(voice_clean_level=1.2)
        ui.configure_output(True)
        a,b=ui.slider_track_bounds(ui.AUDIO_DENOISE_BOX)
        ui.apply_audio_slider(state, 'audio_denoise_level', a + (b - a) * .37)
        controls, _ = state.audio_controls_snapshot()
        self.assertAlmostEqual(controls['denoise_level'], 1.85)
        self.assertFalse(controls['voice_clean'])
        self.assertEqual(controls['hf_enhance_level'], 0)
        self.assertAlmostEqual(ui.denoise_makeup_gain_db(1.85), 3.7)
        self.assertEqual(ui.denoise_label(1.85), '37%')
        for level, gain in enumerate(ui.DENOISE_MAKEUP_GAIN_DB):
            self.assertEqual(ui.denoise_makeup_gain_db(level), gain)
        ui.apply_audio_slider(state, 'audio_voice_level', ui.AUDIO_VOICE_CLEAN_BOX[2])
        self.assertTrue(state.audio_controls_snapshot()[0]['voice_clean'])

    def test_denoise_only_sends_changed_filter_params_without_retuning(self):
        ws = Transport()
        kiwi.send_snd_setup(ws, 7075, 'am', -4000, 4000, {'denoise_level': 2.1})
        first = len(ws.commands)
        kiwi.send_snd_setup(ws, 7075, 'am', -4000, 4000, {'denoise_level': 2.1})
        self.assertEqual(len(ws.commands), first)
        kiwi.send_snd_setup(ws, 7075, 'am', -4000, 4000, {'denoise_level': 2.13})
        changed = ws.commands[first:]
        self.assertTrue(changed)
        self.assertTrue(all(c.startswith('SET nr type=0 param=') for c in changed), changed)
        self.assertLessEqual(len(changed), 4)
        kiwi.send_snd_setup(ws, 7075, 'am', -4000, 4000, {'denoise_level': 0})
        self.assertEqual(ws.commands[-1], 'SET nr type=0 en=0')

    def test_reauthentication_resends_audio_settings_and_failed_writes_retry(self):
        ws = Transport()
        kiwi.send_snd_setup(ws, 7075, 'am', -4000, 4000)
        count = len(ws.commands)
        kiwi.send_kiwi_setup(ws, 'kiwi', 'test')
        ws.commands.clear()
        kiwi.send_snd_setup(ws, 7075, 'am', -4000, 4000)
        self.assertEqual(len(ws.commands), count)
        ws.fail = 'SET nr type=0 en=1'
        with self.assertRaises(OSError):
            kiwi.send_snd_setup(ws, 7075, 'am', -4000, 4000, {'denoise_level': .45})
        ws.fail = None
        before = len(ws.commands)
        kiwi.send_snd_setup(ws, 7075, 'am', -4000, 4000, {'denoise_level': .45})
        self.assertEqual(ws.commands[before:], ['SET nr type=0 en=1'])

    def test_neural_voice_and_hf_processing_bypass_receiver_denoise_in_voice_modes(self):
        for mode in kiwi.VOICE_AUDIO_MODES:
            for processor in ({'voice_clean': True}, {'hf_enhance_level': 1}):
                ws = Transport()
                kiwi.send_snd_setup(ws, 7075, mode, -4000, 4000,
                                    {'denoise_level': 2.5, **processor})
                self.assertIn('SET nr type=0 en=0', ws.commands)


if __name__ == '__main__':
    unittest.main()
