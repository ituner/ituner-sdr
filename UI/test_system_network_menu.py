import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiwi_gl_display as ui


class SystemNetworkMenuTests(unittest.TestCase):
    def test_network_is_first_full_width_with_matching_touch_target(self):
        items = ui.SETTINGS_MENU_ITEMS
        self.assertEqual(items[0], ("network", "Wi-Fi / ETHERNET"))
        boxes = [ui.lcd_nav_box(i, len(items), True) for i in range(len(items))]
        network = boxes[0]
        self.assertEqual(network, (ui.LCD_NAV_X0 + 10, ui.lcd_drawer_back_box()[1] - 4 * (ui.LCD_NAV_TILE_H + ui.LCD_NAV_GAP),
                                   ui.LOGICAL_W - 10, ui.lcd_drawer_back_box()[1] - 4 * (ui.LCD_NAV_TILE_H + ui.LCD_NAV_GAP) + ui.LCD_NAV_TILE_H))
        self.assertEqual(network[2] - network[0], 236)
        self.assertEqual(boxes[-1], ui.lcd_drawer_back_box())
        self.assertEqual(boxes[-1][1] - boxes[-2][3], ui.LCD_NAV_GAP)
        self.assertEqual(boxes[1][1] - network[3], 8)
        with patch.object(ui, "LCD_800_MODE", True):
            for index, box in enumerate(boxes):
                x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                self.assertEqual(ui.lcd_nav_item_at(x, y, items), index)
                for other in boxes[index + 1:]:
                    self.assertFalse(box[0] < other[2] and other[0] < box[2]
                                     and box[1] < other[3] and other[1] < box[3])

    def test_left_rail_keeps_entire_network_button_tappable(self):
        items = ui.SETTINGS_MENU_ITEMS
        box = ui.lcd_nav_box(0, len(items), True)
        with patch.object(ui, "LCD_800_MODE", True), \
                patch.dict(ui.theme_system.runtime_theme, sidebar="left"):
            for physical_x in (11, 128, 245):
                logical_x = ui.theme_system.display_to_logical_x(physical_x)
                self.assertEqual(ui.lcd_nav_item_at(logical_x, (box[1] + box[3]) / 2, items), 0)

    def test_render_uses_same_first_full_width_box_as_touch(self):
        with patch.object(ui, "LCD_800_MODE", True), \
                patch.object(ui, "draw_logical_rect"), \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_sidebar_header"), \
                patch.object(ui, "draw_radio_close_button"), \
                patch.object(ui, "draw_navigation_button") as button:
            ui.draw_lcd_navigation(None, settings_open=True)
        first = button.call_args_list[0].args
        self.assertEqual(first[1], ui.lcd_nav_box(0, len(ui.SETTINGS_MENU_ITEMS), True))
        self.assertEqual(first[2], "Wi-Fi / ETHERNET")


if __name__ == "__main__":
    unittest.main()
