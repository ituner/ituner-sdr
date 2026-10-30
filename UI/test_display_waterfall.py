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

    def test_mode_controls_fit_existing_rail_without_covering_other_controls(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        for automatic, box in ui.DISPLAY_WATERFALL_MODE_BOXES:
            self.assertGreaterEqual(box[1], ui.DISPLAY_LAYOUT_BOXES[0][1][3]+8)
            self.assertLessEqual(box[3], ui.DISPLAY_RESET_BOX[1]-8)
            self.assertGreaterEqual(box[3]-box[1], 56)
            self.assertEqual(ui.display_option_at((box[0]+box[2])/2, (box[1]+box[3])/2),
                             ('waterfall_mode', automatic))

    def test_spectrum_auto_is_independent_of_waterfall_manual(self):
        state = self.state()
        state.select_waterfall_mode(False)
        before = state.waterfall_snapshot()
        ui.toggle_display_spectrum_control(state, 'auto')
        self.assertEqual(state.waterfall_snapshot(), before)
        self.assertFalse(state.spectrum_auto_snapshot())


if __name__ == '__main__':
    unittest.main()
