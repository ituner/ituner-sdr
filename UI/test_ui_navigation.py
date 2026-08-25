import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiwi_gl_display as ui


class ConstellationLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ui.configure_output(True)
        ui.configure_popup_layout()

    def test_constellation_uses_the_full_eight_inch_radio_canvas(self):
        map_x0, map_y0, map_x1, map_y1 = ui.GLOBE_MAP_BOX
        self.assertGreaterEqual(map_x1 - map_x0, 900)
        self.assertGreaterEqual(map_y1 - map_y0, 450)
        self.assertLessEqual(map_x1, ui.LCD_NAV_X0)

        info_x0, info_y0, info_x1, info_y1 = ui.GLOBE_INFO_BOX
        self.assertGreater(info_y0, map_y1)
        self.assertLessEqual(info_x1, ui.LCD_NAV_X0)
        self.assertLess(info_y1, ui.GLOBE_SCOUT_BAR_BOX[1])

    def test_constellation_warm_receivers_are_large_horizontal_touch_cards(self):
        previous_right = 0
        for box in ui.GLOBE_STATION_BOXES:
            x0, y0, x1, y1 = box
            self.assertGreaterEqual(x1 - x0, 280)
            self.assertGreaterEqual(y1 - y0, 72)
            self.assertGreaterEqual(x0, previous_right)
            self.assertGreater(y0, ui.GLOBE_MAP_BOX[3])
            self.assertLessEqual(x1, ui.LCD_NAV_X0)
            previous_right = x1

    def test_settings_keeps_the_live_radio_surface_undimmed(self):
        self.assertEqual(ui.settings_surface_overlay_alpha(True), 0)
        self.assertEqual(ui.settings_surface_overlay_alpha(False), 0)


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


class ReceiverPickerLandingTests(unittest.TestCase):
    def test_opening_receivers_centers_the_active_server(self):
        stations = [
            (f"Receiver {index:02d}", "Somewhere", f"server-{index}")
            for index in range(12)
        ]
        filtered, route, scroll = ui.receiver_picker_landing(
            stations, "name", "all", (), {}, "server-8", 1, 5,
        )
        self.assertEqual(route, "all")
        self.assertEqual(filtered[8][2], "server-8")
        self.assertEqual(scroll, 6)

    def test_route_falls_back_to_all_when_it_hides_the_active_server(self):
        stations = [
            (f"Receiver {index:02d}", "Somewhere", f"server-{index}")
            for index in range(12)
        ]
        _filtered, route, scroll = ui.receiver_picker_landing(
            stations, "name", "favorites", {"server-1"}, {}, "server-8", 1, 5,
        )
        self.assertEqual(route, "all")
        self.assertEqual(scroll, 6)


class MenuButtonContractTests(unittest.TestCase):
    def test_settings_labels_describe_their_actual_destinations(self):
        self.assertEqual(
            ui.SETTINGS_MENU_ITEMS,
            (
                ("display", "DISPLAY"),
                ("location", "LOCATION"),
                ("receivers", "RECEIVERS"),
                ("cpu", "CPU"),
                ("tests", "TESTS"),
                ("fan", "FAN"),
                ("settings_back", "BACK"),
            ),
        )

    def test_nested_drawer_back_returns_to_its_parent(self):
        for current, parent in (
            ("display", "settings"),
            ("location", "settings"),
            ("tests", "settings"),
            ("fan", "location"),
            ("filter", "audio"),
            ("dj_tune", "tests"),
            ("moon_languages", "asr"),
            ("deepgram", "asr"),
        ):
            with self.subTest(current=current):
                self.assertEqual(ui.navigation_back_target(current, parent), parent)

    def test_blank_drawer_space_is_not_a_close_action(self):
        for drawer in ("modes", "audio", "display", "tests", "passband"):
            with self.subTest(drawer=drawer):
                self.assertFalse(ui.drawer_blank_tap_closes(drawer))

    def test_settings_tiles_win_over_hidden_home_audio_controls(self):
        for kind in ("display", "location"):
            index = next(
                index for index, (candidate, _label) in enumerate(ui.SETTINGS_MENU_ITEMS)
                if candidate == kind
            )
            x0, y0, x1, y1 = ui.lcd_nav_box(index, len(ui.SETTINGS_MENU_ITEMS))
            self.assertEqual(
                ui.lcd_primary_action_at((x0 + x1) / 2, (y0 + y1) / 2, True),
                ("navigation", kind),
            )

    def test_settings_destinations_use_the_approved_panel_hierarchy(self):
        for kind in ("display", "location", "tests", "fan"):
            with self.subTest(kind=kind):
                self.assertEqual(ui.settings_destination_presentation(kind), "right")
        for kind in ("cpu", "receivers"):
            with self.subTest(kind=kind):
                self.assertEqual(ui.settings_destination_presentation(kind), "center")

    def test_settings_session_blocks_background_radio_input(self):
        self.assertFalse(ui.settings_background_input_enabled(True))
        self.assertTrue(ui.settings_background_input_enabled(False))

    def test_center_workspace_leaves_the_right_navigation_rail_visible(self):
        x0, y0, x1, y1 = ui.settings_center_workspace_box()
        self.assertGreater(x0, 0)
        self.assertGreater(y0, 0)
        self.assertLessEqual(x1, ui.LCD_NAV_X0)
        self.assertLess(y1, ui.LOGICAL_H)


class ReceiverButtonContractTests(unittest.TestCase):
    def test_picker_owns_input_before_every_hidden_background_control(self):
        self.assertFalse(ui.waterfall_overlay_controls_enabled(picker_open=True))
        self.assertTrue(ui.waterfall_overlay_controls_enabled(picker_open=False))

        source = Path(ui.__file__).read_text()
        for gesture in (
            "buffer_graph_move",
            "cpu_graph_move",
            "caption_translation_toggle",
            "callsign_caption",
            "caption_readonly",
            "frequency_entry_open",
            "cpu_utilization_graph",
            "audio_transport_graph",
            "radio_toggle",
        ):
            with self.subTest(gesture=gesture):
                assignment = f'gesture = "{gesture}"'
                assignment_at = source.index(assignment)
                condition_at = source.rfind("\n                            elif ", 0, assignment_at)
                condition_block = source[condition_at:assignment_at]
                self.assertIn(
                    "waterfall_overlay_controls_enabled(picker_open)",
                    condition_block,
                )

    def test_numeric_search_case_button_returns_to_letters(self):
        self.assertEqual(ui.next_search_case_mode("numeric"), "lower")
        self.assertEqual(ui.next_search_case_mode("lower"), "upper")
        self.assertEqual(ui.next_search_case_mode("upper"), "lower")

    def test_empty_receiver_result_uses_an_empty_range_label(self):
        self.assertEqual(ui.receiver_picker_range_label(0, 0), "0 / 0")
        self.assertEqual(ui.receiver_picker_range_label(12, 0), "1–5 / 12")

    def test_nearby_receiver_rows_are_individually_selectable(self):
        box = (0, 0, 1024, 800)
        rows = ui.map_nearby_receiver_boxes(box, 3)
        self.assertEqual(len(rows), 3)
        for index, (x0, y0, x1, y1) in enumerate(rows):
            self.assertEqual(
                ui.map_nearby_receiver_at((x0 + x1) / 2, (y0 + y1) / 2, box, 3),
                index,
            )

    def test_map_started_connection_does_not_close_an_explicit_list(self):
        self.assertFalse(ui.pending_connection_closes_picker("map", map_open=False))
        self.assertFalse(ui.pending_connection_closes_picker("map", map_open=True))
        self.assertTrue(ui.pending_connection_closes_picker("list", map_open=False))


if __name__ == "__main__":
    unittest.main()
