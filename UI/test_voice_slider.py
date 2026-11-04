import json
import struct
import unittest
from unittest.mock import patch

import kiwi_gl_display as ui


class VoiceSliderTests(unittest.TestCase):
    def state(self):
        return ui.SharedState('http://kiwi.test', 7075, 8, -95, 142, 245, 3, 'am', True)

    def test_fractional_strength_survives_saved_preferences_and_excludes_hf(self):
        state = self.state()
        state.set_audio_controls(hf_enhance_level=1)
        state.set_audio_controls(voice_clean_level=0.37)
        controls, _ = state.audio_controls_snapshot()
        self.assertEqual(controls['voice_clean_level'], 0.37)
        self.assertTrue(controls['voice_clean'])
        self.assertEqual(controls['hf_enhance_level'], 0)
        saved = json.loads(json.dumps({'voice_clean_level': 0.37}))
        restored = self.state()
        restored.set_audio_controls(**ui.restore_voice_clean_profile(saved, 4))
        self.assertEqual(restored.audio_controls_snapshot()[0]['voice_clean_level'], 0.37)
        restored.set_audio_controls(voice_clean_level=0)
        self.assertFalse(restored.audio_controls_snapshot()[0]['voice_clean'])

    def test_legacy_strengths_and_hf_choice_keep_their_meaning(self):
        for profile in (2, 3, 4):
            for level, mix in ((0, 0), (1, 0.75), (2, 1)):
                restored = ui.restore_voice_clean_profile({'voice_clean_level': level}, profile)
                self.assertEqual(ui.voice_clean_mix(restored['voice_clean_level']), mix)
        self.assertEqual(ui.restore_voice_clean_profile({'voice_clean_level': 3}, 2),
                         {'voice_clean_level': 0, 'hf_enhance_level': 1})

    def test_tap_drag_coordinates_match_track_in_both_layouts(self):
        for desktop in (False, True):
            ui.configure_output(desktop)
            x0, _, x1, _ = ui.AUDIO_VOICE_CLEAN_BOX
            levels = [ui.audio_voice_level_at_x(x0 + (x1 - x0) * i / 100)
                      for i in range(101)]
            self.assertEqual((levels[0], levels[-1]), (0, 2))
            self.assertEqual(len(set(levels)), 101)
            mixes = list(map(ui.voice_clean_mix, levels))
            self.assertTrue(all(a < b for a, b in zip(mixes, mixes[1:])))
            self.assertEqual(ui.audio_voice_level_at_x(x0 - 30), 0)
            self.assertEqual(ui.audio_voice_level_at_x(x1 + 30), 2)
        self.assertIn('audio_voice_level', ui.TOOLBOX_CONTINUOUS_GESTURES)

    def test_local_strength_does_not_trigger_receiver_setup_but_toggle_does(self):
        state = self.state()
        state.set_audio_controls(voice_clean_level=0.01)
        first = ui.remote_audio_controls_key(state.audio_controls_snapshot()[0])
        for level in (0.2, 0.37, 1, 1.83, 2):
            state.set_audio_controls(voice_clean_level=level)
            self.assertEqual(ui.remote_audio_controls_key(state.audio_controls_snapshot()[0]), first)
        state.set_audio_controls(voice_clean_level=0)
        self.assertNotEqual(ui.remote_audio_controls_key(state.audio_controls_snapshot()[0]), first)

    def test_pcm_blend_uses_intermediate_amounts_without_recreating_processor(self):
        cleaner = ui.RNNoiseVoiceCleaner.__new__(ui.RNNoiseVoiceCleaner)
        cleaner.pending = bytearray()
        cleaner._apply_voice_tone = lambda samples: samples
        for level in (0.2, 0.6, 1, 1.5, 2):
            cleaner.wet_12k = [1000, -1000]
            cleaner.dry_12k = [5000, -5000]
            mix = ui.voice_clean_mix(level)
            output = cleaner.process_pcm(b'\0\0', mix=mix)
            expected = round(1000 * mix + 5000 * (1 - mix))
            self.assertEqual(struct.unpack('<2h', output), (expected, -expected))

    def test_voice_uses_shared_slider_with_requested_label_and_endpoint_names(self):
        controls = self.state().audio_controls_snapshot()[0]
        controls['voice_clean_level'] = 0.74
        ui.configure_output(True)
        with patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_text'), patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'draw_lcd_audio_tile'), patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'draw_styled_text_button'), \
             patch.object(ui, 'draw_lcd_audio_slider_tile') as sliders:
            ui.draw_lcd_audio_drawer(object(), 0.5, controls, -400, 400, True, 'am', 'pipewire')
        voice = next(call for call in sliders.call_args_list if call.args[1] == ui.AUDIO_VOICE_CLEAN_BOX)
        self.assertEqual(voice.args[2:7], ('VOICE (RNNOISE)', 0.74, 2.0, '37%', True))
        self.assertTrue(voice.kwargs['full_width'])
        self.assertEqual(ui.voice_clean_label(0), 'OFF')
        self.assertEqual(ui.voice_clean_label(2), 'STR')
        for invalid in (None, 'bad', float('nan'), float('inf')):
            self.assertEqual(ui.normalize_voice_clean_level(invalid), 0)


if __name__ == '__main__':
    unittest.main()
