import unittest
from unittest.mock import patch

import kiwi_gl_display as ui


class AudioPageTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.set_audio_page(False)
        self.addCleanup(ui.set_audio_page, False)
        self.state = ui.SharedState('http://kiwi.test', 7075, 8, -95, 142, 245, 3, 'am', True)

    def test_advanced_and_back_leave_audio_settings_and_frequency_unchanged(self):
        self.state.set_audio_controls(voice_clean_level=.74, tone_profile=2, squelch_level=12)
        audio = self.state.audio_controls_snapshot()
        frequency = self.state.snapshot()
        self.assertTrue(ui.audio_page_action('advanced'))
        self.assertTrue(ui.AUDIO_ADVANCED_OPEN)
        self.assertTrue(ui.audio_page_action('close'))
        self.assertFalse(ui.AUDIO_ADVANCED_OPEN)
        self.assertFalse(ui.audio_page_action('close'))
        self.assertEqual(self.state.audio_controls_snapshot(), audio)
        self.assertEqual(self.state.snapshot(), frequency)

    def test_header_is_quiet_and_slider_gaps_are_not_other_buttons(self):
        self.assertEqual(ui.AUDIO_HEADER_H, 32)
        self.assertIsNone(ui.audio_option_at(ui.LCD_NAV_X0 + 128, 17))
        self.assertIn('audio_header', ui.TOOLBOX_CONTINUOUS_GESTURES)
        sliders = (ui.AUDIO_VOLUME_BOX, ui.AUDIO_SQUELCH_BOX,
                   ui.AUDIO_DENOISE_BOX, ui.AUDIO_VOICE_CLEAN_BOX, ui.AUDIO_PASSBAND_BOX)
        for a, b in zip(sliders, sliders[1:]):
            self.assertGreaterEqual(b[1] - a[3], 16)
            self.assertIsNone(ui.audio_option_at(a[0] + 20, (a[3]+b[1])/2))

    def test_combined_volume_reserves_speaker_taps_and_slider_range(self):
        mute = ui.volume_mute_box(ui.AUDIO_VOLUME_BOX)
        track = ui.volume_track_box(ui.AUDIO_VOLUME_BOX)
        self.assertEqual(ui.audio_option_at((mute[0]+mute[2])/2, (mute[1]+mute[3])/2), 'mute')
        self.assertIsNone(ui.audio_option_at(track[0], (track[1]+track[3])/2))
        self.assertEqual(ui.audio_volume_at_x(track[0]), 0)
        self.assertEqual(ui.audio_volume_at_x(track[2]), 1)
        self.assertLess(ui.AUDIO_MUTE_BOX[0], 0)
        self.assertLess(ui.AUDIO_BLANKER_BOX[0], 0)
        ui.set_audio_page(True)
        self.assertGreater(ui.AUDIO_BLANKER_BOX[0], 0)

    def test_passband_slider_changes_width_without_tuning_or_moving_center(self):
        self.state.set_filter(-1500, 3500)
        frequency = self.state.snapshot()[1]
        x0, _, x1, _ = ui.AUDIO_PASSBAND_BOX
        for fraction in (0, .2, .5, .75, 1):
            ui.apply_audio_slider(self.state, 'audio_passband', x0 + (x1-x0)*fraction)
            _, low, high, _ = self.state.radio_snapshot()
            self.assertAlmostEqual((low + high)/2, 1000, delta=25)
            self.assertAlmostEqual(high-low, ui.filter_width_from_slider_fraction(fraction), delta=100)
            self.assertEqual(self.state.snapshot()[1], frequency)
        self.assertIn('audio_passband', ui.VALUE_SLIDER_GESTURES)
        self.assertIn('audio_passband', ui.TOOLBOX_CONTINUOUS_GESTURES)

    def test_main_and_advanced_render_only_their_own_controls(self):
        controls, _ = self.state.audio_controls_snapshot()
        for advanced in (False, True):
            ui.set_audio_page(advanced)
            with patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
                 patch.object(ui, 'draw_text'), patch.object(ui, 'draw_section_divider'), \
                 patch.object(ui, 'draw_radio_close_button'), \
                 patch.object(ui, 'draw_lcd_home_volume_slider') as volume, \
                 patch.object(ui, 'draw_lcd_home_bandwidth') as passband, \
                 patch.object(ui, 'draw_lcd_audio_slider_tile') as sliders, \
                 patch.object(ui, 'draw_lcd_audio_tile') as tiles, \
                 patch.object(ui, 'draw_styled_text_button') as buttons:
                ui.draw_lcd_audio_drawer(object(), .5, controls, -400, 400, True, 'am', 'alsa')
            if advanced:
                self.assertFalse(sliders.called)
                self.assertFalse(volume.called)
                self.assertFalse(passband.called)
                self.assertEqual({c.args[2] for c in tiles.call_args_list},
                                 {'NOTCH', 'DE-EMPH', 'HF ENH', 'BLANKER', 'PASSBAND', 'OUTPUT', 'RESET'})
            else:
                self.assertEqual({c.args[2] for c in sliders.call_args_list},
                                 {'DENOISE', 'VOICE (RNNOISE)', 'SQUELCH', 'WIDTH'})
                self.assertTrue(all(c.kwargs['roomy'] for c in sliders.call_args_list))
                self.assertEqual(volume.call_args.kwargs['box'], ui.AUDIO_VOLUME_BOX)
                self.assertEqual(passband.call_args.kwargs['box'], ui.AUDIO_PASSBAND_GRAPH_BOX)
                self.assertEqual([c.args[2] for c in tiles.call_args_list], ['AGC', 'TONE'])
                self.assertEqual([c.args[2] for c in buttons.call_args_list], ['ADVANCED'])


if __name__ == '__main__':
    unittest.main()
