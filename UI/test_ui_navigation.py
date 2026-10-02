import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiwi_gl_display as ui  # noqa: E402


class MenuIconTests(unittest.TestCase):
    def test_required_runtime_icons_exist_in_both_asset_roots(self):
        required = {
            "apps.png",
            "audio-muted.png",
            "audio.png",
            "digi.png",
            "display.png",
            "dual.png",
            "frequency-chevron.png",
            "home.png",
            "info.png",
            "receivers.png",
            "rf.png",
            "settings.png",
            "stats.png",
        }
        repository = Path(__file__).resolve().parents[1]
        roots = (
            repository / "UI/assets/menu-icons",
            repository / "assets/menu-icons",
        )
        for root in roots:
            self.assertEqual(
                required - {path.name for path in root.glob("*.png")},
                set(),
            )
            for name in required:
                with Image.open(root / name) as image:
                    self.assertEqual(image.size, (64, 64))
                    self.assertIsNotNone(image.convert("RGBA").getchannel("A").getbbox())

    def test_audio_icon_tracks_existing_muted_state(self):
        self.assertEqual(ui.menu_icon_filename("audio", muted=False), "audio.png")
        self.assertEqual(ui.menu_icon_filename("audio", muted=True), "audio-muted.png")
        self.assertEqual(ui.menu_icon_filename("tests", muted=True), "apps.png")
        self.assertEqual(ui.menu_icon_filename("dual"), "dual.png")

    def test_dual_icon_has_requested_wide_low_profile(self):
        icon = Path(__file__).resolve().parent / "assets/menu-icons/dual.png"
        with Image.open(icon).convert("RGBA") as image:
            x0, y0, x1, y1 = image.getchannel("A").getbbox()
        self.assertGreater(x1 - x0, y1 - y0)
        self.assertLessEqual(y1 - y0, 42)


class DrawerGeometryTests(unittest.TestCase):
    def test_home_destinations_are_preserved_with_updated_mode_label(self):
        kinds = [kind for kind, _label in ui.MENU_ITEMS]
        self.assertEqual(
            kinds,
            ["local_rx", "rx", "audio", "digital", "dual", "settings"],
        )
        self.assertEqual(dict(ui.MENU_ITEMS)["digital"], "MODES")

    def test_settings_uses_info_and_has_no_duplicate_kiwi_route(self):
        labels = dict(ui.SETTINGS_MENU_ITEMS)
        self.assertEqual(labels["tests"], "APPS")
        self.assertEqual(labels["system"], "INFO")
        self.assertEqual(labels["settings_back"], "BACK")
        self.assertNotIn("kiwi", labels)
        self.assertEqual(ui.menu_icon_filename("system"), "info.png")

    def test_drawers_share_one_back_target(self):
        expected = ui.lcd_drawer_back_box()
        self.assertEqual(ui.lcd_radio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_display_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_audio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_filter_drawer_boxes()["close"], expected)
        self.assertEqual(ui.receiver_home_drawer_boxes()["close"], expected)
        self.assertEqual(ui.fan_curve_drawer_boxes()["close"], expected)
        self.assertEqual(ui.compact_font_review_boxes()["exit"], expected)

    def test_font_review_owns_the_full_rail_without_covering_back(self):
        boxes = ui.compact_font_review_boxes()
        self.assertEqual(
            boxes["panel"],
            (ui.LCD_NAV_X0, 0, ui.LOGICAL_W, ui.LOGICAL_H),
        )
        back = boxes["exit"]
        for name in ("previous", "next", "like", "delete", "use"):
            control = boxes[name]
            self.assertLessEqual(control[3], back[1])

    def test_settings_back_tile_uses_shared_back_target(self):
        last = len(ui.SETTINGS_MENU_ITEMS) - 1
        self.assertEqual(
            ui.lcd_nav_box(last, len(ui.SETTINGS_MENU_ITEMS), True),
            ui.lcd_drawer_back_box(),
        )

    def test_modes_drawer_contains_families_wspr_and_back_without_overlap(self):
        ui.LCD_RADIO_DRAWER_PROGRESS = 1.0
        mode_boxes = [box for _family, _modes, box in ui.radio_mode_layout()]
        step_boxes = [box for _step, box in ui.radio_step_options("kiwi")]
        wspr_box = ui.radio_wspr_box()
        back_box = ui.lcd_radio_drawer_close_box()
        overlaps = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
        for box in (*mode_boxes, *step_boxes):
            self.assertFalse(overlaps(box, wspr_box))
        self.assertFalse(overlaps(wspr_box, back_box))
        x = (wspr_box[0] + wspr_box[2]) / 2
        y = (wspr_box[1] + wspr_box[3]) / 2
        self.assertEqual(ui.radio_option_at(x, y), ("workspace", "wspr"))

    def test_stats_close_target_is_inside_graph_header(self):
        graph = (120, 90, 900, 420)
        close = ui.cpu_utilization_graph_close_box(graph)
        self.assertGreaterEqual(close[0], graph[0])
        self.assertGreaterEqual(close[1], graph[1])
        self.assertLessEqual(close[2], graph[2])
        self.assertLess(close[3], graph[1] + 44)

    def test_frequency_drawer_controls_are_bounded_and_disjoint(self):
        boxes = ui.frequency_drawer_boxes()
        panel = boxes["panel"]
        controls = [boxes[name] for name in ("readout", "down", "up", "manual", "step", "font", "close")]
        overlaps = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
        for box in controls:
            self.assertGreaterEqual(box[0], panel[0])
            self.assertGreaterEqual(box[1], panel[1])
            self.assertLessEqual(box[2], panel[2])
            self.assertLessEqual(box[3], panel[3])
        for index, box in enumerate(controls):
            for other in controls[index + 1:]:
                self.assertFalse(overlaps(box, other))
        for name in ("down", "up", "manual", "step", "font", "close"):
            box = boxes[name]
            self.assertEqual(ui.frequency_drawer_action_at((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), name)

    def test_frequency_step_uses_hz_increment_and_receiver_bounds(self):
        self.assertEqual(ui.frequency_step_target(7075.0, 1, 100, 0, 30000), 7075.1)
        self.assertEqual(ui.frequency_step_target(10.0, -1, 100_000, 0, 108000), 0.0)
        self.assertEqual(ui.frequency_step_target(7075.05, 1, 100, 0, 30000), 7075.1)
        self.assertEqual(ui.frequency_step_target(7075.05, -1, 100, 0, 30000), 7075.0)
        self.assertEqual(ui.configured_tune_step_hz("kiwi", 500, 100_000), 500)
        self.assertEqual(ui.configured_tune_step_hz("fmdx", 500, 50_000), 50_000)
        self.assertEqual(ui.format_frequency_digits(7075.794), "007.075.794")
        self.assertEqual(ui.format_tune_step(100_000), "100 kHz")

    def test_entire_compact_frequency_area_opens_tuning_target(self):
        compact = ui.compact_frequency_touch_box()
        measured = (compact[0] + 40, compact[1] + 10, compact[2] - 40, compact[3] - 10)
        self.assertTrue(ui.is_frequency_readout_touch(compact[0] + 2, compact[1] + 2, measured, compact=True))
        self.assertFalse(ui.is_frequency_readout_touch(compact[0] + 2, compact[1] + 2, measured, compact=False))

    def test_sidebar_headers_use_one_centered_compact_style(self):
        with mock.patch.object(ui, "draw_logical_rect"), mock.patch.object(ui, "draw_logical_line"), mock.patch.object(ui, "draw_text") as draw_text:
            ui.draw_sidebar_header(object(), "SETTINGS")
        args = draw_text.call_args.args
        self.assertEqual(args[1], (ui.LCD_NAV_X0 + ui.LOGICAL_W) / 2)
        self.assertEqual(args[5], 15)
        self.assertTrue(args[6])
        self.assertEqual(args[8], "cm")


class ParentNavigationTests(unittest.TestCase):
    def test_shared_destination_records_the_surface_that_opened_it(self):
        self.assertEqual(ui.navigation_parent(ui.MENU_ITEMS, "rx"), "home")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "display"), "settings")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "tests"), "settings")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "settings_back"), "home")

    def test_unknown_parent_falls_back_to_home(self):
        self.assertEqual(ui.navigation_back_surface("settings"), "settings")
        self.assertEqual(ui.navigation_back_surface("home"), "home")
        self.assertEqual(ui.navigation_back_surface("unexpected"), "home")

    def test_stats_keeps_settings_surface_when_launched_from_settings(self):
        self.assertTrue(ui.stats_keeps_settings_sidebar("settings"))
        self.assertFalse(ui.stats_keeps_settings_sidebar("home"))


class WorkspaceLayoutTests(unittest.TestCase):
    def test_settings_center_workspace_stays_outside_sidebar(self):
        x0, y0, x1, y1 = ui.settings_center_workspace_box()
        self.assertGreaterEqual(x0, 0)
        self.assertEqual(x1, ui.LCD_NAV_X0)
        self.assertGreater(y1, y0)
        self.assertLessEqual(y1, ui.LOGICAL_H)

    def test_constellation_layout_fits_current_display(self):
        layout = ui.constellation_layout()
        for box in layout.values():
            x0, y0, x1, y1 = box
            self.assertGreaterEqual(x0, 0)
            self.assertGreaterEqual(y0, 0)
            self.assertLessEqual(x1, ui.LOGICAL_W)
            self.assertLessEqual(y1, ui.LOGICAL_H)
            self.assertGreater(x1, x0)
            self.assertGreater(y1, y0)
        self.assertLessEqual(layout["map"][2], ui.LCD_NAV_X0)
        self.assertGreaterEqual(layout["sidebar"][0], ui.LCD_NAV_X0)


if __name__ == "__main__":
    unittest.main()
