import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiwi_gl_display as ui


class ModeAnnunciatorNavigationTests(unittest.TestCase):
    def test_every_visible_mode_cell_resolves_to_its_mode(self):
        cells = tuple(ui.lcd_mode_annunciator_cells())
        self.assertEqual(
            tuple(mode for mode, _box in cells),
            ui.DESKTOP_1280_MODE_ANNUNCIATORS,
        )
        for mode, (x0, y0, x1, y1) in cells:
            self.assertEqual(
                ui.lcd_mode_annunciator_at((x0 + x1) / 2, (y0 + y1) / 2),
                mode,
            )

    def test_non_mode_parts_of_annunciator_do_not_claim_a_mode(self):
        x0, y0, x1, _y1 = ui.LCD_ANNUNCIATOR_BOX
        self.assertIsNone(ui.lcd_mode_annunciator_at((x0 + x1) / 2, y0 + 30))
        self.assertIsNone(ui.lcd_mode_annunciator_at((x0 + x1) / 2, y0 + 95))
        self.assertIsNone(ui.lcd_mode_annunciator_at(x0 - 1, y0 + 150))


class RightSidebarNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ui.configure_popup_layout()

    def test_all_lcd_drawers_share_one_bottom_right_back_box(self):
        expected = ui.lcd_drawer_back_box()
        self.assertEqual(ui.lcd_radio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_display_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_audio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_filter_drawer_boxes()["close"], expected)
        self.assertEqual(ui.receiver_home_drawer_boxes()["close"], expected)
        self.assertEqual(ui.fan_curve_drawer_boxes()["close"], expected)

    def test_settings_back_uses_shared_bottom_right_box(self):
        items = ui.lcd_nav_items(True)
        back_index = next(index for index, item in enumerate(items) if item[0] == "settings_back")
        self.assertEqual(items[back_index][1], "BACK")
        self.assertEqual(ui.lcd_nav_box(back_index, len(items)), ui.lcd_drawer_back_box())

    def test_remaining_menu_routes_use_the_right_sidebar(self):
        self.assertEqual(ui.PICKER_EXIT_BOX, ui.lcd_drawer_back_box())
        self.assertEqual(ui.RADIOGARDEN_EXIT_BOX, ui.lcd_drawer_back_box())
        self.assertEqual(ui.TEST_PANEL_BOX[0], ui.LCD_NAV_X0)
        self.assertEqual(ui.ASR_PANEL_BOX[0], ui.LCD_NAV_X0)
        self.assertEqual(ui.ASR_PANEL_BOX[2], ui.LOGICAL_W)


if __name__ == "__main__":
    unittest.main()
