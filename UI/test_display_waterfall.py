import unittest
from unittest.mock import patch

import kiwi_gl_display as ui


class DisplayWaterfallTests(unittest.TestCase):
    def state(self):
        return ui.SharedState('http://example.test:8073', 9740, 4, -95, 142, 245, 4, 'am', True)

    def test_auto_uses_current_window_and_resets_after_pan_and_zoom(self):
        state = self.state()
        weak = bytes([100]*900+[120]*100+[145]*24)
        strong = bytes([170]*900+[190]*100+[215]*24)
        first = state.waterfall_levels(weak)
        settled = state.waterfall_levels(strong)
        self.assertLess(first[0], settled[0])
        self.assertLess(settled[0], 165)
        state.set_view(freq_khz=9800, zoom=8)
        fresh = state.waterfall_levels(strong)
        self.assertEqual(fresh[0], 165)
        self.assertGreater(fresh[1], first[1])

    def test_manual_holds_visible_levels_and_auto_can_be_reenabled(self):
        state = self.state()
        observed = state.waterfall_levels(bytes([100]*900+[120]*100+[145]*24))
        state.select_waterfall_mode(False)
        self.assertFalse(state.waterfall_snapshot()[3])
        self.assertEqual(state.waterfall_snapshot()[:2], observed)
        self.assertEqual(state.waterfall_levels(bytes([200]*1024)), observed)
        state.select_waterfall_mode(True)
        self.assertTrue(state.waterfall_snapshot()[3])
        self.assertNotEqual(state.waterfall_levels(bytes([200]*1024)), observed)

    def test_local_zoom_ignores_strong_signals_outside_visible_window(self):
        state = self.state()
        samples = bytes([200]*300+[100]*424+[200]*300)
        state.set_view(zoom=8)
        wide = state.waterfall_levels(samples, 9740, 100)
        state.set_view(zoom=10)
        narrow = state.waterfall_levels(samples, 9740, 100)
        self.assertGreater(wide[1], 200)
        self.assertLess(narrow[1], 150)

    def test_palette_preserves_auto_or_manual_choice(self):
        state = self.state()
        for automatic in (True, False):
            state.select_waterfall_mode(automatic)
            for palette in ('classic', 'kiwi', 'gqrx'):
                ui.apply_waterfall_palette_preset(state, palette)
                self.assertEqual(state.waterfall_snapshot()[3], automatic)
                self.assertEqual(state.waterfall_snapshot()[4], palette)

    def test_first_upgrade_defaults_auto_and_explicit_manual_survives_restore(self):
        state = self.state()
        ui.restore_waterfall_preferences(state, {'auto': False, 'floor': 90, 'ceil': 150})
        self.assertTrue(state.waterfall_snapshot()[3])
        ui.restore_waterfall_preferences(state, {'contrast_mode': 'manual', 'floor': 90, 'ceil': 150})
        self.assertEqual(state.waterfall_snapshot()[:4], (90, 150, 4, False))
        ui.restore_waterfall_preferences(state, {'contrast_mode': 'auto', 'floor': 90, 'ceil': 150})
        self.assertTrue(state.waterfall_snapshot()[3])

    def test_cycles_preserve_listening_and_do_not_pause_or_clear_the_receiver(self):
        state=self.state();before=state.snapshot()
        for name in ('spectrum','waterfall'):
            if name=='spectrum':
                state.set_spectrum_enabled(False)
                enabled=state.spectrum_enabled_snapshot
                automatic=state.spectrum_auto_snapshot
            else:
                state.set_waterfall_enabled(False)
                enabled=state.waterfall_enabled_snapshot
                automatic=lambda:state.waterfall_snapshot()[3]
            for want_enabled,want_auto in ((True,False),(True,True),(False,True)):
                ui.cycle_display_control(state,name+'_cycle')
                self.assertEqual((enabled(),automatic()),(want_enabled,want_auto))
                self.assertFalse(state.stream_paused_snapshot())
                self.assertEqual(state.snapshot(),before)
        state.set_waterfall(speed=1)
        for wanted in (2,4,1):
            ui.cycle_display_control(state,'speed_cycle')
            self.assertEqual(state.waterfall_snapshot()[2],wanted)

    def test_floor_ceiling_fixed_tracks_keep_other_edge_unchanged(self):
        ui.configure_output(True);ui.configure_popup_layout();ui.set_display_page(False)
        state=self.state();state.set_waterfall(floor=80,ceil=190,auto=False)
        floor_box,ceil_box=ui.DISPLAY_FLOOR_MINUS_BOX,ui.DISPLAY_CEIL_MINUS_BOX
        x=floor_box[0]+10+(floor_box[2]-floor_box[0]-20)*.8
        state.set_waterfall(floor=ui.waterfall_floor_at_x(x,190),auto=False)
        self.assertEqual(state.waterfall_snapshot()[1],190)
        self.assertEqual(state.waterfall_snapshot()[0],160)
        self.assertEqual(ui.waterfall_floor_at_x(x,240),184)
        # The same pointer position maps to the same level until gap-clamped.
        x=ceil_box[0]+10+(ceil_box[2]-ceil_box[0]-20)*.8
        self.assertEqual(ui.waterfall_ceiling_at_x(x,80),ui.waterfall_ceiling_at_x(x,150))
        state.set_waterfall(ceil=ui.waterfall_ceiling_at_x(ceil_box[0],160),auto=False)
        self.assertEqual(state.waterfall_snapshot()[:2],(160,190))

    def test_auto_display_tracks_live_levels_and_manual_freezes_them(self):
        state=self.state()
        observed=state.waterfall_levels(bytes([100]*900+[120]*100+[145]*24))
        self.assertEqual(state.waterfall_display_levels(),observed)
        state.select_waterfall_mode(False)
        state.waterfall_levels(bytes([200]*1024))
        self.assertEqual(state.waterfall_display_levels(),observed)
        ui.restore_waterfall_preferences(state,{'enabled':False,'contrast_mode':'auto'})
        self.assertFalse(state.waterfall_enabled_snapshot())
        ui.reset_display_view(state)
        self.assertTrue(state.waterfall_enabled_snapshot())
        ui.configure_output(True);ui.set_display_page(False)
        self.assertTrue(ui.display_page_action('advanced'))
        self.assertTrue(ui.display_page_action('close'))
        self.assertFalse(ui.DISPLAY_ADVANCED_OPEN)

    def test_returning_to_auto_reseeds_from_next_row_instead_of_manual_or_old_estimate(self):
        state=self.state()
        weak=bytes([100]*900+[120]*100+[145]*24)
        strong=bytes([170]*900+[190]*100+[215]*24)
        state.waterfall_levels(weak)
        state.select_waterfall_mode(False)
        state.set_waterfall(floor=180,ceil=240,auto=False)
        # No intervening waterfall row: the old context can still say Auto.
        state.select_waterfall_mode(True)
        self.assertIsNone(state.wf_live_levels)
        self.assertIsNone(state.wf_level_context)
        expected=ui.AutoWaterfallLevels().levels_for(strong)
        self.assertEqual(state.waterfall_levels(strong),expected)
        self.assertNotEqual(expected,(180,240))

    def test_auto_level_instruments_are_dimmed_and_readonly_gesture_is_quiet(self):
        ui.configure_output(True);ui.configure_popup_layout();ui.set_display_page(False)
        with patch.object(ui,'draw_lcd_audio_tile'), patch.object(ui,'draw_styled_two_line_button'), \
             patch.object(ui,'draw_logical_rect'), patch.object(ui,'draw_radio_close_button'), \
             patch.object(ui,'draw_sidebar_header'), patch.object(ui,'draw_display_control'), \
             patch.object(ui,'draw_lcd_drawer_heading'), patch.object(ui,'draw_display_slider_section') as sliders:
            ui.draw_display_setup_panel(None,105,195,2,True,'kiwi',True,waterfall_auto=True)
        self.assertTrue(all(not c.args[-1] for c in sliders.call_args_list))
        self.assertEqual([c.args[-2] for c in sliders.call_args_list],['AUTO 105','AUTO 195'])
        self.assertIn('display_readonly',ui.TOOLBOX_CONTINUOUS_GESTURES)

    def test_spectrum_auto_is_independent_of_waterfall_manual(self):
        state = self.state()
        state.select_waterfall_mode(False)
        before = state.waterfall_snapshot()
        ui.toggle_display_spectrum_control(state, 'auto')
        self.assertEqual(state.waterfall_snapshot(), before)
        self.assertFalse(state.spectrum_auto_snapshot())


if __name__ == '__main__':
    unittest.main()
