"""Full-width Home keeps RF geometry and visible touch targets in agreement."""
import unittest
from unittest.mock import patch
import kiwi_gl_display as ui


class CollapsibleSidebarTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        self.addCleanup(ui.set_home_rail_hidden, False)
        self.addCleanup(ui.set_display_page, False)

    def test_collapse_expands_rf_without_reallocating_waterfall(self):
        texture_width = ui.WF_TEX_W
        self.assertEqual(ui.rf_canvas_width(), 1024)
        ui.set_home_rail_hidden(True)
        self.assertEqual(ui.rf_canvas_width(), 1280)
        self.assertEqual(ui.WF_TEX_W, texture_width)
        self.assertTrue(ui.is_waterfall_tune_touch(1150, 600))
        self.assertIsNone(ui.lcd_nav_item_at(1150, 600))
        self.assertFalse(ui.home_rail_controls_available(False, False, False))
        ui.set_home_rail_hidden(False)
        self.assertEqual(ui.rf_canvas_width(), 1024)
        self.assertFalse(ui.is_waterfall_tune_touch(1150, 600))

    def test_restore_tab_is_only_active_when_hidden_and_requires_same_target(self):
        self.assertFalse(ui.home_rail_restore_at(1260, 400))
        ui.set_home_rail_hidden(True)
        box = ui.home_rail_restore_box()
        self.assertEqual((box[1] + box[3]) / 2, ui.LOGICAL_H / 2)
        self.assertTrue(ui.home_rail_restore_at(1260, 400))
        self.assertTrue(ui.confirmed_box_tap(box, 1260, 400, 1260, 410))
        self.assertFalse(ui.confirmed_box_tap(box, 1200, 400, 1260, 410))
        self.assertFalse(ui.is_waterfall_tune_touch(1260, 400))
        with patch.object(ui, 'draw_styled_button_frame') as draw, patch.object(ui, 'draw_logical_line'):
            ui.draw_home_rail_restore_tab(None)
            self.assertEqual(draw.call_args.args[0], box)
            ui.set_home_rail_hidden(False)
            draw.reset_mock()
            ui.draw_home_rail_restore_tab(None)
            draw.assert_not_called()

    def test_collapse_tab_stays_outside_rail_and_points_toward_it(self):
        for side, expected_x, direction in (('right', 976, 1), ('left', 0, -1)):
            with patch.dict(ui.theme_system.runtime_theme, sidebar=side):
                ui.set_home_rail_hidden(False)
                box = ui.home_rail_collapse_box()
                self.assertEqual(box, (expected_x, 352, expected_x + 48, 448))
                self.assertLessEqual(box[2], ui.LCD_NAV_X0)
                with patch.object(ui, 'draw_home_rail_tab') as draw:
                    ui.draw_home_rail_collapse_tab(None)
                    ui.draw_home_rail_restore_tab(None)
                    draw.assert_called_once_with(box, direction)
                    ui.set_home_rail_hidden(True)
                    draw.reset_mock()
                    ui.draw_home_rail_collapse_tab(None)
                    ui.draw_home_rail_restore_tab(None)
                    draw.assert_called_once_with(ui.home_rail_restore_box(), -1)
                self.assertFalse(ui.confirmed_box_tap(box, box[0]-10, 400, box[0]+10, 400))
                self.assertTrue(ui.confirmed_box_tap(box, box[0]+10, 400, box[0]+11, 401))

    def test_centered_cluster_preserves_each_theme_meter_and_readout_selection(self):
        ui.set_home_rail_hidden(True)
        for style in ui.METER_STYLES:
            for side in ('left', 'right'):
                with patch.dict(ui.theme_system.runtime_theme, smeter_style=style, sidebar=side):
                    freq, meter = ui.collapsed_instrument_boxes()
                    self.assertEqual((freq[0] + meter[2]) / 2, 640)
                    self.assertEqual(meter[3] - meter[1], ui.METER_STYLES[style].height)
                    self.assertGreater(meter[0], freq[2])
                    self.assertFalse(ui.mirror_top_instruments())
                    for position in ('left', 'middle', 'right'):
                        self.assertEqual(ui.frequency_display_box(None, 7075, position=position), freq)
                        self.assertFalse(ui.is_home_mode_touch(1100, 250, position))
                    self.assertEqual(ui.theme_system.runtime_theme['smeter_style'], style)

    def test_advanced_hide_control_is_full_width_above_back(self):
        ui.set_display_page(True)
        box = ui.DISPLAY_HIDE_RAIL_BOX
        back = ui.lcd_drawer_back_box()
        self.assertEqual(box[::2], back[::2])
        self.assertEqual(box[3] + ui.LCD_NAV_GAP, back[1])
        self.assertEqual(ui.display_option_at((box[0]+box[2])/2, (box[1]+box[3])/2), ('hide_sidebar', None))
        ui.set_display_page(False)
        self.assertNotEqual(ui.display_option_at((box[0]+box[2])/2, (box[1]+box[3])/2), ('hide_sidebar', None))

    def test_hidden_navigation_does_not_paint_over_rf(self):
        ui.set_home_rail_hidden(True)
        with patch.object(ui, 'draw_logical_rect') as rect:
            ui.draw_lcd_navigation(None)
            rect.assert_not_called()
        self.assertEqual(ui.cpu_annunciator_touch_box()[2], 1280)


if __name__ == '__main__':
    unittest.main()
