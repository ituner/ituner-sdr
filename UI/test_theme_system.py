import json
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, call, patch

from theme_editor import ThemeEditor, theme_screen_boxes
from theme_system import (
    BUILTIN_THEME_IDS, DEFAULT_THEME, DEFAULT_THEME_ID, GREEN_THEME_ID,
    INSTRUMENT_THEME_ID, REMOVED_THEME_MIGRATIONS, STRAIGHT_INVERTED_THEME_ID,
    ThemeLibrary, apply_theme,
    display_distance, display_temperature, distance_axis_label,
    display_to_logical_x, new_theme, runtime_theme,
)
from ui_style import APP_UI_STYLE
import kiwi_gl_display as ui


class ThemeSystemTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "themes.json"
        self.library = ThemeLibrary(self.path)

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def test_named_theme_survives_restart_and_updates_shared_style(self):
        custom = new_theme("Amber")
        custom["colors"]["frequency"] = [255, 175, 60]
        custom["colors"]["pressed_surface"] = [51, 51, 51, 255]
        custom["shape"] = "square"  # Legacy theme setting must not resize buttons.
        custom["radius"] = 0
        custom["sidebar"] = "left"
        custom["units"] = "metric"
        self.library.upsert(custom)
        restarted = ThemeLibrary(self.path)
        self.assertEqual(restarted.active_id, custom["id"])
        self.assertEqual(tuple(APP_UI_STYLE.palette.frequency), (255, 175, 60))
        self.assertEqual(APP_UI_STYLE.button.height, 64)
        self.assertEqual(APP_UI_STYLE.button.radius, 0)
        self.assertNotIn("shape", restarted.get(custom["id"]))
        self.assertEqual(APP_UI_STYLE.button.resolve(pressed=True).fill, (51, 51, 51, 255))
        self.assertEqual(display_to_logical_x(100), 1124)
        self.assertEqual(display_to_logical_x(300), 44)
        self.assertEqual(display_distance(100), "100 km")
        self.assertEqual(display_temperature(40), "40°C")
        self.assertEqual(distance_axis_label(1000), "1k")

    def test_editor_columns_and_saved_text_scale(self):
        editor = ThemeEditor(self.library)
        editor.begin()
        boxes = theme_screen_boxes(editor)
        self.assertEqual(boxes["section:SIDEBAR"][1], 392)
        self.assertGreaterEqual(boxes["option:straight"][0], 536)
        editor.section = "UNITS"
        boxes = theme_screen_boxes(editor)
        self.assertLess(boxes["text:smaller"][2], boxes["text:larger"][0])
        editor.tap(650, 362)
        self.assertEqual(editor.draft["text_scale_percent"], 95)
        editor.tap(900, 362)
        self.assertEqual(editor.draft["text_scale_percent"], 100)
        editor.tap(900, 362)
        self.assertEqual(editor.draft["text_scale_percent"], 105)
        editor.tap(700, 440)
        self.assertEqual(editor.draft["text_scale_percent"], 100)
        editor.tap(900, 362)
        save = boxes["save"]
        editor.tap((save[0] + save[2]) / 2, (save[1] + save[3]) / 2)
        saved = ThemeLibrary(self.path).get(editor.selected_id)
        self.assertEqual(saved["text_scale_percent"], 105)
        self.assertEqual(ui.theme_system.scaled_text_size(20), 21)
        with patch.object(ui.pygame.font, "SysFont") as font_factory:
            cache = ui.TextCache()
            cache.font(20)
            self.assertEqual(font_factory.call_args.args[1], 21)

    def test_left_sidebar_frequency_positions_and_instrument_order(self):
        custom = new_theme("Left rail")
        custom["sidebar"] = "left"
        self.library.upsert(custom)
        ui.configure_output(True)
        cache = MagicMock()
        cache.font.return_value.size.return_value = (300, 58)
        self.assertEqual(ui.visible_frequency_position("right"), "left")
        self.assertEqual(ui.visible_frequency_position("left"), "right")
        self.assertEqual(ui.visible_frequency_position(
            ui.visible_frequency_position("right", "left"), "left"), "right")
        for position in ("left", "middle"):
            original = ui.frequency_display_box(cache, 7075, position=position, mirrored=False)
            self.assertEqual(ui.frequency_display_box(cache, 7075, position=position),
                             ui.mirror_rf_box(original))
        right_frequency = ui.frequency_display_box(cache, 7075, position="left")
        right_meter = ui.left_smeter_box(cache, 7075)
        right_band = ui.main_band_context_box(cache, 7075, position="left")
        self.assertLess(right_band[2], right_meter[0])
        self.assertLess(right_meter[2], right_frequency[0])
        middle_frequency = ui.frequency_display_box(cache, 7075, position="middle")
        middle_band = ui.main_band_context_box(cache, 7075, position="middle")
        middle_trace = ui.mirror_smeter_trace_x(675 + (50 if ui.DESKTOP_1280_MODE else 0), 6)
        self.assertLess(middle_trace + ui.SMETER_TRACE_WIDTH, middle_frequency[0])
        self.assertLess(middle_frequency[2], middle_band[0])
        with patch.object(ui, "draw_logical_rect"), \
                patch.object(ui, "draw_radio_close_button"), \
                patch.object(ui, "draw_lcd_audio_tile"), \
                patch.object(ui, "draw_lcd_drawer_heading"), \
                patch.object(ui, "draw_display_slider_section"), \
                patch.object(ui, "draw_sidebar_header"), \
                patch.object(ui, "draw_display_control") as control:
            ui.draw_display_setup_panel(None, 160, 220, 2, False, "classic", True,
                                        instrument_layout="right")
            active_positions = [item.args[2] for item in control.call_args_list
                                if item.args[2] in ("LEFT", "MIDDLE", "RIGHT")
                                and item.args[3]]
            self.assertEqual(active_positions, ["LEFT"])

    def test_network_stats_vosc_dual_and_decoders_use_theme_text(self):
        custom = new_theme("Text contrast")
        custom["colors"]["text"] = [249, 33, 31]
        custom["colors"]["secondary_text"] = [31, 229, 247]
        custom["colors"]["section_heading"] = [237, 208, 41]
        custom["colors"]["ready"] = [37, 244, 68, 255]
        apply_theme(custom)
        with patch.object(ui, "draw_logical_rect") as rectangles, patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_styled_text_button"), patch.object(ui, "draw_settings_leaf_sidebar"), \
                patch.object(ui, "draw_network_status_card"), patch.object(ui, "draw_picker_button"), \
                patch.object(ui, "fit_station_text", side_effect=lambda _cache, value, *_args, **_kwargs: value), \
                patch.object(ui, "draw_text") as text:
            ui.draw_network_manager(None, {"devices": {}, "networks": [], "ok": True}, False, None)
            self.assertIn(("NETWORK", tuple(custom["colors"]["text"])),
                          [(item.args[3], tuple(item.args[4])) for item in text.call_args_list])
            text.reset_mock()
            ui.draw_cpu_utilization_graph(None, (), None, (20, 30, 900, 400))
            self.assertIn(("CPU UTILIZATION", tuple(custom["colors"]["section_heading"])),
                          [(item.args[3], tuple(item.args[4])) for item in text.call_args_list])
            text.reset_mock()
            ui.draw_vosc_live_popup_error(None, (20, 40, 800, 200), "missing key")
            self.assertEqual(tuple(text.call_args.args[4]), tuple(custom["colors"]["secondary_text"]))
            ui.draw_vosc_live_popup_frame(None, (20, 40, 800, 200))
            self.assertEqual(rectangles.call_args.args[-1][-1], 190)
            text.reset_mock()
            ui.draw_dual_vfo_header(None, (0, 0, 800, 60), "A", 7000, "USB", True, "Receiver")
            self.assertIn(("Receiver", tuple(custom["colors"]["text"])),
                          [(item.args[3], tuple(item.args[4])) for item in text.call_args_list])
            text.reset_mock()
            ui.draw_wspr_mrtg_graph(None, (), 3600, "20")
            self.assertIn(("RF AVERAGE", tuple(custom["colors"]["secondary_text"])),
                          [(item.args[3], tuple(item.args[4])) for item in text.call_args_list])
            from sstv_workspace import SSTVWorkspace
            text.reset_mock()
            SSTVWorkspace(ui, MagicMock()).text(None, 10, 10, "Decoder status")
            self.assertEqual(tuple(text.call_args.args[4]), tuple(custom["colors"]["text"]))

    def test_startup_connection_message_uses_active_theme(self):
        custom = new_theme("Connection colors")
        for role, rgb in (("ready", [31, 231, 61]), ("waiting", [225, 176, 37]),
                          ("danger_border", [232, 43, 53]), ("focus", [42, 143, 240]),
                          ("section_surface", [18, 29, 40]), ("danger", [70, 19, 24])):
            custom["colors"][role][:3] = rgb
        apply_theme(custom)
        with patch.object(ui, "draw_logical_rect") as rectangles, \
                patch.object(ui, "draw_logical_line"), patch.object(ui, "draw_text") as text:
            for status, role, alpha in (
                ("connecting", "ready", 228), ("connected", "ready", 228),
                ("retrying", "ready", 228), ("server_timeout", "waiting", 230),
                ("failed", "danger_border", 230), ("paused", "focus", 230),
            ):
                with self.subTest(status=status):
                    rectangles.reset_mock()
                    text.reset_mock()
                    ui.draw_connection_annunciator(None, status)
                    self.assertEqual(tuple(text.call_args.args[4]), tuple(custom["colors"][role][:3]))
                    self.assertEqual(rectangles.call_args_list[0].args[-1][-1], alpha)

    def test_theme_preview_uses_left_column_and_draft_text_size(self):
        editor = ThemeEditor(self.library)
        editor.begin()
        editor.draft["text_scale_percent"] = 120
        editor.draft["sidebar"] = "left"
        with patch.object(ui, "draw_logical_rect") as rectangles, \
                patch.object(ui, "draw_logical_rounded_rect") as rounded, \
                patch.object(ui, "draw_logical_line") as line, \
                patch.object(ui, "draw_sidebar_header"), \
                patch.object(ui, "draw_styled_text_button"), \
                patch.object(ui, "draw_text") as draw_text:
            ui.draw_theme_panel(None, editor)
        labels = {item.args[3]: item.args for item in draw_text.call_args_list}
        self.assertEqual(labels["LIVE PREVIEW"][1], 24)
        self.assertEqual(labels[editor.draft["name"]][1], 536)
        self.assertEqual(labels["1.088.900"][5], 43)
        self.assertEqual(labels["SUBTITLE"][5], 13)
        self.assertEqual(labels["ZOOM  24x"][2], 530)
        units_label = (ui.theme_system.display_distance(100, editor.draft) + "   "
                       + ui.theme_system.display_temperature(40, editor.draft))
        self.assertEqual(labels[units_label][2], 530)
        self.assertIn(call(48, 584, 464, 726, editor.draft["colors"]["background"]),
                      rectangles.call_args_list)
        self.assertEqual([item.args[:4] for item in rounded.call_args_list
                          if item.args[1] == 330],
                         [(48, 330, 146, 394), (154, 330, 252, 394),
                          (260, 330, 358, 394), (366, 330, 464, 394)])
        self.assertTrue(any(item.args[:4] == (48, 584, 152, 584)
                            for item in line.call_args_list))

    def test_browse_rows_have_left_aligned_names_and_own_actions(self):
        editor = ThemeEditor(self.library)
        boxes = theme_screen_boxes(editor)
        self.assertNotIn("edit", boxes)
        self.assertNotIn("delete", boxes)
        self.assertEqual(boxes["new"], (1034, 104, 1270, 168))
        for index in range(7):
            name, edit, delete = (boxes[f"{action}:{index}"]
                                  for action in ("theme", "edit", "delete"))
            self.assertEqual((name[1], name[3]), (edit[1], edit[3]))
            self.assertEqual((edit[1], edit[3]), (delete[1], delete[3]))
            self.assertEqual((name[0], delete[2]), (536, 1000))
        with patch.object(ui, "draw_logical_rect"), \
                patch.object(ui, "draw_logical_rounded_rect"), \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_sidebar_header"), \
                patch.object(ui, "draw_styled_text_button") as buttons, \
                patch.object(ui, "draw_styled_button_frame",
                             return_value=APP_UI_STYLE.button.resolve()), \
                patch.object(ui, "draw_text") as labels:
            ui.draw_theme_panel(None, editor)
        first_name = next(item for item in labels.call_args_list
                          if item.args[3] == "DEFAULT STRAIGHT")
        self.assertEqual(first_name.args[1:3], (548, 132))
        self.assertEqual(first_name.args[8], "lm")
        self.assertEqual([item.args[2] for item in buttons.call_args_list
                          if item.args[2] in ("EDIT", "DELETE")].count("EDIT"), 4)

    def test_row_delete_confirmation_is_tied_to_its_theme(self):
        first = new_theme("First")
        second = new_theme("Second")
        self.library.upsert(first)
        self.library.upsert(second)
        editor = ThemeEditor(self.library)
        def tap(action):
            box = theme_screen_boxes(editor)[action]
            editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

        tap("delete:5")
        self.assertEqual(editor.confirm_delete_id, second["id"])
        tap("previous")
        self.assertIsNone(editor.confirm_delete_id)
        tap("delete:3")
        self.assertEqual(editor.notice_action, "LOCKED")
        tap("delete:4")
        self.assertEqual(editor.confirm_delete_id, first["id"])
        tap("delete:4")
        self.assertIsNone(self.library.get(first["id"]))
        self.assertIsNotNone(self.library.get(second["id"]))
        tap("previous")
        tap("delete:0")
        self.assertEqual(editor.notice_action, "LOCKED")

    def test_delete_active_falls_back_and_default_preserves_existing_units(self):
        custom = new_theme("Delete me")
        self.library.upsert(custom)
        self.library.delete(custom["id"])
        self.assertEqual(self.library.active_id, DEFAULT_THEME_ID)
        self.assertEqual(runtime_theme["sidebar"], "right")
        self.assertEqual(APP_UI_STYLE.button.height, 64)
        self.assertEqual(display_distance(100), "100 km")
        self.assertEqual(display_distance(100, default_unit="mi"), "62 mi")
        self.assertEqual(display_temperature(40), "40 C")
        self.assertEqual(json.loads(self.path.read_text())["themes"], [])

    def test_default_straight_selection_survives_restart(self):
        straight = self.library.get(DEFAULT_THEME_ID)
        self.assertEqual(straight["name"], "Default Straight")
        self.assertEqual(straight["radius"], 0)
        editor = ThemeEditor(self.library)
        self.assertEqual([theme["id"] for theme in editor.themes], list(BUILTIN_THEME_IDS))
        self.library.activate(DEFAULT_THEME_ID)
        restarted = ThemeLibrary(self.path)
        self.assertEqual(restarted.active_id, DEFAULT_THEME_ID)
        self.assertEqual(APP_UI_STYLE.button.radius, 0)
        self.assertEqual(APP_UI_STYLE.button.height, 64)
        self.assertEqual(display_temperature(40), "40 C")
        with self.assertRaises(ValueError):
            restarted.delete(DEFAULT_THEME_ID)

    def test_editing_default_builtin_creates_a_custom_copy(self):
        self.library.activate(DEFAULT_THEME_ID)
        editor = ThemeEditor(self.library)
        box = theme_screen_boxes(editor)["edit:0"]
        editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        self.assertNotEqual(editor.draft["id"], DEFAULT_THEME_ID)
        self.assertEqual(editor.draft["radius"], 0)
        self.assertEqual(editor.draft["colors"], self.library.get(DEFAULT_THEME_ID)["colors"])

    def test_inverted_and_monochrome_builtins_preserve_alpha_and_corner_choices(self):
        self.assertEqual(BUILTIN_THEME_IDS, (
            DEFAULT_THEME_ID, STRAIGHT_INVERTED_THEME_ID,
            GREEN_THEME_ID, INSTRUMENT_THEME_ID,
        ))
        original = self.library.get(DEFAULT_THEME_ID)
        inverted = self.library.get(STRAIGHT_INVERTED_THEME_ID)
        self.assertEqual(inverted["radius"], 0)
        for key, color in original["colors"].items():
            self.assertEqual(inverted["colors"][key][:3], [255 - value for value in color[:3]])
            self.assertEqual(inverted["colors"][key][3:], color[3:])
        green = self.library.get(GREEN_THEME_ID)
        for key, color in green["colors"].items():
            self.assertGreaterEqual(color[1], max(color[:3]))
            self.assertEqual(color[3:], original["colors"][key][3:])
        for identifier in (STRAIGHT_INVERTED_THEME_ID, GREEN_THEME_ID):
            self.library.activate(identifier)
            self.assertEqual(ThemeLibrary(self.path).active_id, identifier)
            with self.assertRaises(ValueError):
                self.library.delete(identifier)

    def test_removed_builtin_ids_migrate_without_reappearing(self):
        for removed_id, replacement_id in REMOVED_THEME_MIGRATIONS.items():
            self.path.write_text(json.dumps({
                "version": 1, "active_id": removed_id, "themes": [],
            }))
            restarted = ThemeLibrary(self.path)
            self.assertEqual(restarted.active_id, replacement_id)
            self.assertNotIn(removed_id, BUILTIN_THEME_IDS)

    def test_instrument_theme_uses_quiet_square_controls(self):
        theme = self.library.get(INSTRUMENT_THEME_ID)
        self.assertEqual(theme["name"], "Instrument Quiet")
        self.assertEqual(theme["radius"], 0)
        self.assertEqual(theme["colors"]["surface"], [0, 0, 0, 255])
        self.assertEqual(theme["colors"]["border"], [46, 46, 46, 255])
        self.assertLess(sum(theme["colors"]["border"][:3]),
                        sum(theme["colors"]["text"][:3]) / 4)
        self.library.activate(INSTRUMENT_THEME_ID)
        self.assertEqual(APP_UI_STYLE.button.label_size, 13)
        self.assertEqual(APP_UI_STYLE.button.font_family,
                         ("Roboto", "Inter", "DejaVu Sans"))
        self.assertEqual(APP_UI_STYLE.button.radius, 0)

    def test_section_divider_is_dark_thin_and_theme_editable(self):
        self.assertEqual(DEFAULT_THEME["colors"]["divider"], [42, 42, 42, 180])
        self.assertIn("divider", next(
            keys for name, keys in ui.COLOR_GROUPS if name == "BASE"))
        custom = new_theme("Quiet rules")
        custom["colors"]["divider"] = [21, 22, 23, 96]
        self.library.upsert(custom)
        with patch.object(ui, "draw_logical_line") as line:
            ui.draw_section_divider(10, 40, 90)
        line.assert_called_once_with(10, 40, 90, 40, (21, 22, 23, 96), 1)

    def test_green_smeter_trace_stands_clear_of_its_rail(self):
        for identifier in (GREEN_THEME_ID,):
            self.library.activate(identifier)
            palette = APP_UI_STYLE.palette
            self.assertGreater(sum(palette.smeter_active[:3]),
                               3 * sum(palette.smeter_rail[:3]))
            for meter_x0 in (320, 675):
                with patch.object(ui, "draw_logical_line") as line, \
                        patch.object(ui, "draw_logical_circle"), \
                        patch.object(ui, "draw_text"):
                    ui.draw_smeter(None, -95, False, meter_x0=meter_x0)
                self.assertEqual(line.call_args_list[0].args[-2:],
                                 (palette.smeter_rail, 8))
                self.assertEqual(line.call_args_list[1].args[-2:],
                                 (palette.smeter_active, 5))

    def test_inverted_top_band_follows_left_and_middle_frequency(self):
        ui.configure_output(True)
        cache = MagicMock()
        cache.font.return_value.size.return_value = (187, 36)
        self.assertIn("top_instrument_band", next(
            keys for name, keys in ui.COLOR_GROUPS if name == "BASE"))
        with ExitStack() as stack:
            rectangles = stack.enter_context(patch.object(ui, "draw_logical_rect"))
            for name in ("draw_ruler", "draw_lower_status",
                         "draw_waterfall_operating_controls", "draw_connection_annunciator",
                         "draw_squelch_closed_annunciator", "draw_lcd_navigation",
                         "draw_band_context_chip", "draw_smeter", "draw_big_frequency"):
                stack.enter_context(patch.object(ui, name))
            stack.enter_context(patch.object(ui, "top_instrument_layout",
                                            return_value=("7.075.000", (0, 0, 1, 1))))
            for theme_id in (STRAIGHT_INVERTED_THEME_ID,):
                self.library.activate(theme_id)
                self.assertEqual(APP_UI_STYLE.palette.top_instrument_band,
                                 (255, 255, 255, 144))
                for position in ("middle", "left"):
                    rectangles.reset_mock()
                    ui.draw_ui(cache, 7075, 20, -95, -95, None, "LSB", "DIG", 100,
                               instrument_layout=position, sidebar_open=True)
                    self.assertIn(call(0, 0, ui.rf_canvas_width(),
                                       ui.LCD_TOP_INSTRUMENT_BAND_H,
                                       (255, 255, 255, 144)),
                                  rectangles.call_args_list)
                rectangles.reset_mock()
                ui.draw_ui(cache, 7075, 20, -95, -95, None, "LSB", "DIG", 100,
                           instrument_layout="right", sidebar_open=True)
                self.assertFalse(rectangles.call_args_list)

    def test_theme_success_notices_use_zoom_panel_data(self):
        editor = ThemeEditor(self.library)
        editor.open = True
        first_box = theme_screen_boxes(editor)["theme:0"]
        editor.tap((first_box[0] + first_box[2]) / 2,
                   (first_box[1] + first_box[3]) / 2)
        self.assertEqual((editor.notice_action, editor.notice_detail),
                         ("APPLIED", "DEFAULT STRAIGHT"))
        self.assertGreater(editor.notice_until, 0)
        with patch.object(ui, "draw_green_osd_panel") as panel, \
                patch.object(ui, "draw_text"), \
                patch.object(ui, "fit_station_text", return_value="DEFAULT STRAIGHT"):
            ui.draw_theme_notice_osd(None, editor.notice_action, editor.notice_detail, 220)
            panel.assert_called_once_with(ui.ZOOM_OSD_BOX, 220)
        custom = new_theme("Delete me")
        self.library.upsert(custom)
        editor.selected_id = custom["id"]
        editor.page = 0
        delete_box = theme_screen_boxes(editor)["delete:4"]
        for _ in range(2):
            editor.tap((delete_box[0] + delete_box[2]) / 2,
                       (delete_box[1] + delete_box[3]) / 2)
        self.assertEqual((editor.notice_action, editor.notice_detail),
                         ("DELETED", "DELETE ME"))

    def test_waterfall_recolors_history_without_clearing_rows(self):
        original = bytes((10, 20, 30, 255, 100, 150, 200, 42))
        self.assertEqual(ui.themed_waterfall_pixels(original), original)
        self.library.activate(STRAIGHT_INVERTED_THEME_ID)
        self.assertEqual(ui.themed_waterfall_pixels(original),
                         bytes((245, 235, 225, 255, 155, 105, 55, 42)))
        for identifier, dominant in ((GREEN_THEME_ID, 1),):
            self.library.activate(identifier)
            recolored = ui.themed_waterfall_pixels(original)
            self.assertEqual(recolored[3::4], original[3::4])
            self.assertGreaterEqual(recolored[dominant], max(recolored[:3]))
        with patch.object(ui, "GL") as gl, patch.object(ui, "WF_TEX_W", 2), \
                patch.object(ui, "WF_TEX_H", 2):
            gl.glGenTextures.return_value = 9
            apply_theme(DEFAULT_THEME)
            texture = ui.WaterfallTexture()
            texture.push_line(original)
            row_before = texture.row
            self.library.activate(STRAIGHT_INVERTED_THEME_ID)
            texture.ensure_theme()
            self.assertEqual(texture.row, row_before)
            self.assertEqual(texture.base_pixels[row_before * 8:(row_before + 1) * 8], original)
            upload = gl.glTexSubImage2D.call_args.args
            self.assertEqual(upload[4:6], (2, 2))
            self.assertEqual(upload[-1][row_before * 8:(row_before + 1) * 8],
                             bytes((245, 235, 225, 255, 155, 105, 55, 42)))

    def test_waterfall_controls_retain_transparency_in_each_theme(self):
        ui.configure_output(True)
        for identifier in BUILTIN_THEME_IDS:
            self.library.activate(identifier)
            with patch.object(ui, "draw_logical_rounded_rect") as frame, \
                    patch.object(ui, "draw_logical_line"), \
                    patch.object(ui, "draw_logical_polyline"), \
                    patch.object(ui, "ui_button_pressed", return_value=False):
                ui.draw_zoom_button(None, ui.ZOOM_MINUS_BOX, "-")
                ui.draw_zoom_button(None, ui.ZOOM_PLUS_BOX, "+")
                ui.draw_stream_waterfall_button(None, False)
                ui.draw_favorite_waterfall_button(False)
            self.assertEqual(len(frame.call_args_list), 4)
            for item in frame.call_args_list:
                self.assertEqual(item.args[5],
                                 (*APP_UI_STYLE.palette.surface[:3], 184))
            with patch.object(ui, "draw_logical_rounded_rect") as frame, \
                    patch.object(ui, "draw_logical_line"), \
                    patch.object(ui, "draw_logical_polyline"), \
                    patch.object(ui, "ui_button_pressed", return_value=True):
                ui.draw_stream_waterfall_button(None, True)
                ui.draw_favorite_waterfall_button(True)
                ui.draw_zoom_button(None, ui.ZOOM_PLUS_BOX, "+", active=True)
            for item in frame.call_args_list:
                self.assertEqual(item.args[5],
                                 (*APP_UI_STYLE.palette.pressed_surface[:3], 216))
        custom = new_theme("Transparent buttons")
        custom["colors"]["surface"] = [20, 30, 40, 80]
        self.library.upsert(custom)
        self.assertEqual(ui.zoom_button_palette()[0], (20, 30, 40, 80))

    def test_empty_waterfall_uses_inverted_background_without_clearing_rows(self):
        with patch.object(ui, "GL") as gl, patch.object(ui, "WF_TEX_W", 2), \
                patch.object(ui, "WF_TEX_H", 2), \
                patch.object(ui, "draw_logical_rect") as background, \
                patch.object(ui.WaterfallTexture, "_draw_frequency_aligned"):
            gl.glGenTextures.return_value = 9
            texture = ui.WaterfallTexture()
            for identifier, expected in ((DEFAULT_THEME_ID, (4, 7, 11, 255)),
                                         (STRAIGHT_INVERTED_THEME_ID, (255, 255, 255, 255))):
                self.library.activate(identifier)
                texture.draw(0, 100, 1024, 800, center_khz=7075, span_khz=20)
                self.assertEqual(background.call_args.args,
                                 (0, 100, 1024, 800, expected))
                self.assertTrue(all(value is None for value in texture.row_center_khz))

    def test_custom_waterfall_and_editor_color_groups_are_connected(self):
        custom = new_theme("RF colors")
        custom["colors"]["waterfall_low"] = [10, 20, 30]
        custom["colors"]["waterfall_high"] = [100, 180, 220]
        self.library.upsert(custom)
        transformed = ui.themed_waterfall_pixels(bytes((0, 0, 0, 255, 255, 255, 255, 42)))
        self.assertEqual(transformed, bytes((10, 20, 30, 255, 100, 180, 220, 42)))
        editor = ThemeEditor(self.library)
        editor.begin(self.library.get(custom["id"]))
        editor.section = "COLORS"
        spectrum_group = next(index for index, group in enumerate(ui.COLOR_GROUPS)
                              if group[0] == "SPECTRUM")
        waterfall_group = next(index for index, group in enumerate(ui.COLOR_GROUPS)
                               if group[0] == "WATERFALL")
        for index, key in ((spectrum_group, "spectrum_field"),
                           (waterfall_group, "waterfall_low")):
            box = theme_screen_boxes(editor)[f"group:{index}"]
            editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            box = theme_screen_boxes(editor)["color:0"]
            editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            self.assertEqual(editor.color_key, key)
            editor.back()

    def test_straight_receivers_and_rf_instruments_use_theme_tokens(self):
        self.library.activate(STRAIGHT_INVERTED_THEME_ID)
        with patch.object(ui, "draw_logical_rounded_rect") as rounded:
            ui.draw_station_list_frame((1, 2, 100, 80), (1, 2, 3), (4, 5, 6))
            self.assertEqual(rounded.call_args.args[4], 0)
            badge = ui.receiver_source_badge("kiwi")
            with patch.object(ui, "draw_text"):
                ui.draw_receiver_badge(MagicMock(), 10, 20, badge)
            self.assertEqual(rounded.call_args.args[4], 0)
        with patch.object(ui, "draw_logical_rect") as rectangle, \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_logical_area"), \
                patch.object(ui, "draw_logical_polyline"):
            ui.draw_spectrum(0, 100, (0.2, 0.8))
            self.assertEqual(rectangle.call_args_list[0].args[-1][:3],
                             APP_UI_STYLE.palette.spectrum_field[:3])
        with patch.object(ui, "draw_logical_rect") as rectangle, \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_text"):
            ui.draw_ruler(None, 1000, 100, height=52)
            self.assertEqual(rectangle.call_args_list[0].args[-1],
                             APP_UI_STYLE.palette.waterfall_ruler_background)
        with patch.object(ui, "draw_text") as draw_text, \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_logical_circle"):
            ui.draw_smeter(None, -95, True)
            s_label = next(item for item in draw_text.call_args_list
                           if item.args[3] == "S")
            self.assertEqual(s_label.args[4], APP_UI_STYLE.palette.smeter_scale)

    def test_footer_and_display_slider_use_active_theme_colors(self):
        self.library.activate(GREEN_THEME_ID)
        with patch.object(ui, "draw_logical_rect") as rectangle, \
                patch.object(ui, "draw_text"), \
                patch.object(ui, "draw_logical_line"):
            ui.draw_display_slider_section(None, (1034, 100, 1270, 160),
                                           "FLOOR", 80, 255, "80", True)
            drawn_colors = [item.args[-1] for item in rectangle.call_args_list]
            self.assertIn(APP_UI_STYLE.palette.slider_track, drawn_colors)
            self.assertIn(APP_UI_STYLE.palette.slider_fill, drawn_colors)
            self.assertIn(APP_UI_STYLE.palette.slider_thumb, drawn_colors)
        cache = MagicMock()
        cache.font.return_value.size.return_value = (120, 13)
        with patch.object(ui, "LCD_800_MODE", True), \
                patch.object(ui, "fit_station_text", return_value="Test Receiver"), \
                patch.object(ui, "read_process_ram_mb", return_value=100), \
                patch.object(ui, "draw_logical_rect"), \
                patch.object(ui, "draw_text") as text_draw:
            ui.draw_lower_status(cache, 37, 42, 720, 800,
                                 station_name="Test Receiver", audio_jitter_depth=3)
            colors = {item.args[3]: item.args[4] for item in text_draw.call_args_list}
            self.assertEqual(colors["Test Receiver"], APP_UI_STYLE.palette.footer_primary)
            self.assertEqual(colors["BUFFER Q3/T6"], APP_UI_STYLE.palette.footer_live)

    def test_audio_volume_uses_the_same_theme_colors_as_home(self):
        self.library.activate(GREEN_THEME_ID)
        ui.configure_output(True)
        controls = dict(mute=False, voice_clean_level=0, hf_enhance_level=0,
                        tone_profile=0, squelch_level=0, agc=True,
                        agc_hang=False, nb_algo=0, denoise_level=0,
                        deemphasis=0, autonotch=False)
        with patch.object(ui, "draw_logical_rect") as rectangles, \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_logical_polyline"), \
                patch.object(ui, "draw_text"), \
                patch.object(ui, "draw_radio_close_button"), \
                patch.object(ui, "draw_lcd_audio_tile"), \
                patch.object(ui, "draw_lcd_audio_slider_tile"), \
                patch.object(ui, "draw_sidebar_header"), \
                patch.object(ui, "draw_styled_button_frame",
                             return_value=APP_UI_STYLE.button.resolve()):
            ui.draw_lcd_audio_drawer(None, 0.5, controls, -400, 400,
                                     True, "am", "pipewire")
            audio_colors = [item.args[-1] for item in rectangles.call_args_list]
            rectangles.reset_mock()
            ui.draw_lcd_home_volume_slider(None, 0.5)
            home_colors = [item.args[-1] for item in rectangles.call_args_list]
        for color in (APP_UI_STYLE.palette.slider_track,
                      APP_UI_STYLE.palette.slider_fill,
                      APP_UI_STYLE.palette.slider_thumb):
            self.assertIn(color, audio_colors)
            self.assertIn(color, home_colors)

    def test_passband_labels_and_each_band_position_follow_theme(self):
        self.library.activate(GREEN_THEME_ID)
        ui.configure_output(True)
        with patch.object(ui, "draw_logical_rect"), \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_logical_area"), \
                patch.object(ui, "draw_logical_polyline"), \
                patch.object(ui, "draw_text") as labels:
            ui.draw_lcd_home_bandwidth(None, -1200, 1200)
        colors = {item.args[3]: item.args[4] for item in labels.call_args_list}
        self.assertEqual(colors["PASSBAND"], APP_UI_STYLE.palette.section_heading)
        for label in ("10 kHz", "−5", "0", "+5"):
            self.assertEqual(colors[label], APP_UI_STYLE.palette.secondary_text)
        self.assertEqual(colors["2.4 kHz"], APP_UI_STYLE.palette.text)
        for compact in (False, True):
            with patch.object(ui, "draw_text") as band:
                ui.draw_band_context_chip(None, (0, 0, 200, 40), 7075, "am",
                                          compact=compact)
            self.assertEqual(band.call_args.args[4], APP_UI_STYLE.palette.secondary_text)

    def test_touch_editor_saves_and_applies_a_new_theme(self):
        editor = ThemeEditor(self.library)
        editor.open = True
        new_box = theme_screen_boxes(editor)["new"]
        editor.tap((new_box[0] + new_box[2]) / 2, (new_box[1] + new_box[3]) / 2)
        self.assertEqual(editor.mode, "edit")
        style_box = theme_screen_boxes(editor)["option:straight"]
        editor.tap((style_box[0] + style_box[2]) / 2, (style_box[1] + style_box[3]) / 2)
        save_box = theme_screen_boxes(editor)["save"]
        editor.tap((save_box[0] + save_box[2]) / 2, (save_box[1] + save_box[3]) / 2)
        self.assertEqual(editor.mode, "browse")
        self.assertEqual(self.library.active_id, editor.selected_id)
        self.assertEqual(APP_UI_STYLE.button.radius, 0)
        self.assertEqual(APP_UI_STYLE.button.height, 64)

    def test_touch_color_keypad_replaces_existing_hex_value(self):
        editor = ThemeEditor(self.library)
        editor.begin()
        editor.section = "COLORS"
        color_box = theme_screen_boxes(editor)["color:0"]
        editor.tap((color_box[0] + color_box[2]) / 2, (color_box[1] + color_box[3]) / 2)
        self.assertEqual(editor.color_key, "background")
        for digit in "AABBCC":
            box = theme_screen_boxes(editor)[f"hex:{digit}"]
            editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        box = theme_screen_boxes(editor)["hex:APPLY"]
        editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        self.assertIsNone(editor.color_key)
        self.assertEqual(editor.draft["colors"]["background"], [170, 187, 204, 255])

    def test_color_preview_cancel_save_and_reopen_match_saved_value(self):
        editor = ThemeEditor(self.library)

        def tap(action):
            box = theme_screen_boxes(editor)[action]
            editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

        tap("new")
        tap("section:COLORS")
        tap("group:5")
        original = list(editor.draft["colors"]["passband_fill"])
        tap("color:0")
        for digit in "AABBCC":
            tap(f"hex:{digit}")
        self.assertEqual(editor.draft["colors"]["passband_fill"],
                         [170, 187, 204, original[3]])
        tap("hex:CANCEL")
        self.assertEqual(editor.draft["colors"]["passband_fill"], original)
        tap("color:0")
        tap("swatch:0")
        self.assertEqual(editor.draft["colors"]["passband_fill"],
                         [255, 255, 255, original[3]])
        tap("hex:APPLY")
        border_alpha = editor.draft["colors"]["passband_border"][3]
        tap("color:1")
        for digit in "AABBCC":
            tap(f"hex:{digit}")
        tap("hex:APPLY")
        tap("save")
        saved_id = editor.selected_id
        restarted = ThemeLibrary(self.path)
        self.assertEqual(restarted.get(saved_id)["colors"]["passband_fill"],
                         [255, 255, 255, original[3]])
        self.assertEqual(restarted.get(saved_id)["colors"]["passband_border"],
                         [170, 187, 204, border_alpha])
        editor = ThemeEditor(restarted)
        editor.page = 0
        tap("edit:4")
        tap("section:COLORS")
        tap("group:5")
        tap("color:0")
        self.assertEqual(editor.hex_value, f"FFFFFF{original[3]:02X}")
        tap("hex:APPLY")
        tap("color:1")
        self.assertEqual(editor.hex_value, f"AABBCC{border_alpha:02X}")

    def test_failed_save_does_not_apply_an_unsaved_theme(self):
        custom = new_theme("Cannot Save")
        custom["sidebar"] = "left"
        with patch.object(self.library, "save", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.library.upsert(custom)
        self.assertEqual(self.library.active_id, DEFAULT_THEME_ID)
        self.assertEqual(self.library.themes, [])
        self.assertEqual(runtime_theme["sidebar"], "right")

    def test_imperial_axis_uses_miles_without_rounding_to_zero_thousand(self):
        custom = new_theme("Miles")
        self.library.upsert(custom)
        self.assertEqual(distance_axis_label(1000), "621")

    def test_legacy_square_theme_keeps_rectangular_home_buttons(self):
        custom = new_theme("Legacy")
        custom["shape"] = "square"
        self.library.upsert(custom)
        items = ui.lcd_nav_items()
        self.assertEqual(items, ui.MENU_ITEMS)
        boxes = [ui.lcd_nav_box(index, len(items)) for index in range(len(items))]
        self.assertTrue(all(box[2] - box[0] == 114 and box[3] - box[1] == 64 for box in boxes))
        self.assertEqual(max(box[3] for box in boxes), 792)

    def test_left_sidebar_composition_uses_matching_touch_and_draw_regions(self):
        with patch.object(ui, "GL") as gl, patch.object(ui, "DESKTOP_MODE", True), \
                patch.object(ui, "NATIVE_W", 1280), patch.object(ui, "NATIVE_H", 800):
            gl.glGenTextures.return_value = 17
            composer = ui.SidebarComposer()
            composer.compose_left()
            gl.glReadBuffer.assert_not_called()
            self.assertLess(
                gl.mock_calls.index(call.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)),
                gl.mock_calls.index(call.glCopyTexSubImage2D(
                    gl.GL_TEXTURE_2D, 0, 0, 0, 0, 0, 1280, 800)),
            )
            self.assertEqual(gl.glVertex2f.call_args_list[0].args, (256, 0))
            self.assertEqual(gl.glVertex2f.call_args_list[4].args, (0, 0))
            self.assertEqual(gl.glTexCoord2f.call_args_list[0].args, (0, 1))
            self.assertEqual(gl.glTexCoord2f.call_args_list[4].args, (0.8, 1))
        with patch.object(ui, "GL") as gl, patch.object(ui, "DESKTOP_MODE", False), \
                patch.object(ui, "DISPLAY_ORIENTATION", "normal"), \
                patch.object(ui, "NATIVE_W", 800), patch.object(ui, "NATIVE_H", 1280):
            gl.glGenTextures.return_value = 18
            ui.SidebarComposer().compose_left()
            self.assertEqual(gl.glVertex2f.call_args_list[0].args, (800, 256))
            self.assertEqual(gl.glTexCoord2f.call_args_list[0].args, (1, 1))


if __name__ == "__main__":
    unittest.main()
