import json
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, call, patch

from theme_editor import ThemeEditor, theme_screen_boxes
from theme_system import (
    BUILTIN_THEME_IDS, DEFAULT_THEME, DEFAULT_THEME_ID, GREEN_THEME_ID, BLACK_WHITE_THEME_ID,
    REMOVED_THEME_MIGRATIONS, STRAIGHT_INVERTED_THEME_ID,
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
        custom["colors"]["sidebar_header"] = [19, 29, 39, 255]
        apply_theme(custom)
        with patch.object(ui, "draw_logical_rect") as rectangles, patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_styled_text_button"), patch.object(ui, "draw_settings_leaf_sidebar"), \
                patch.object(ui, "draw_network_status_card"), patch.object(ui, "draw_picker_button"), \
                patch.object(ui, "fit_station_text", side_effect=lambda _cache, value, *_args, **_kwargs: value), \
                patch.object(ui, "draw_text") as text:
            ui.draw_network_manager(None, {"devices": {}, "networks": [], "ok": True}, False, None)
            self.assertIn(("Network", tuple(custom["colors"]["text"])),
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
            rectangles.reset_mock()
            ui.draw_dual_vfo_header(None, (0, 0, 800, 60), "A", 7000, "USB", True, "Receiver")
            self.assertIn(call(0, 0, 800, 60, tuple(custom["colors"]["sidebar_header"])),
                          rectangles.call_args_list)
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

    def test_frequency_drawer_readout_and_header_use_theme_roles(self):
        custom = new_theme("Frequency surfaces")
        custom["colors"]["top_instrument_band"] = [13, 23, 33, 211]
        custom["colors"]["sidebar_header"] = [43, 53, 63, 255]
        custom["colors"]["sidebar_title"] = [173, 183, 193]
        apply_theme(custom)
        with patch.object(ui, "draw_logical_rect") as rectangles, \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_big_frequency"), \
                patch.object(ui, "draw_styled_text_button"), \
                patch.object(ui, "draw_picker_button"), \
                patch.object(ui, "draw_radio_close_button"), \
                patch.object(ui, "draw_text") as text:
            ui.draw_frequency_drawer(None, 7075, 100, "Oxanium")
        readout = ui.frequency_drawer_boxes()["readout"]
        self.assertIn(call(*readout, tuple(custom["colors"]["top_instrument_band"])),
                      rectangles.call_args_list)
        self.assertIn(call(ui.LCD_NAV_X0, 0, ui.LOGICAL_W, ui.LCD_DRAWER_HEADER_H,
                           tuple(custom["colors"]["sidebar_header"])),
                      rectangles.call_args_list)
        self.assertIn(("FREQUENCY", tuple(custom["colors"]["sidebar_title"])),
                      [(item.args[3], tuple(item.args[4])) for item in text.call_args_list])

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
        self.assertEqual(straight["name"], "Default")
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

    def test_inverted_and_monochrome_builtins_preserve_alpha_and_corner_choices(self):
        self.assertEqual(BUILTIN_THEME_IDS, (
            DEFAULT_THEME_ID, STRAIGHT_INVERTED_THEME_ID, GREEN_THEME_ID, BLACK_WHITE_THEME_ID,
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

    def test_default_theme_uses_quiet_square_controls(self):
        theme = self.library.get(DEFAULT_THEME_ID)
        self.assertEqual(theme["name"], "Default")
        self.assertEqual(theme["radius"], 0)
        self.assertEqual(theme["colors"]["surface"], [0, 0, 0, 255])
        self.assertEqual(theme["colors"]["border"], [46, 46, 46, 255])
        self.assertLess(sum(theme["colors"]["border"][:3]),
                        sum(theme["colors"]["text"][:3]) / 4)
        self.library.activate(DEFAULT_THEME_ID)
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
            for identifier, expected in ((DEFAULT_THEME_ID, (0, 0, 0, 255)),
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
        covered = {key for _name, keys in ui.COLOR_GROUPS for key in keys}
        self.assertIn("spectrum_field", covered)
        self.assertIn("waterfall_low", covered)
        self.assertIn("waterfall_high", covered)

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

    def test_failed_save_does_not_apply_an_unsaved_theme(self):
        custom = new_theme("Cannot Save")
        custom["sidebar"] = "left"
        with patch.object(self.library, "save", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.library.upsert(custom)
        self.assertEqual(self.library.active_id, DEFAULT_THEME_ID)
        self.assertEqual(self.library.themes, [])
        self.assertEqual(runtime_theme["sidebar"], "right")

    def test_live_preview_context_restores_runtime_and_style_after_failure(self):
        import theme_system
        from copy import deepcopy
        before, revision = deepcopy(runtime_theme), theme_system.runtime_revision
        palette = APP_UI_STYLE.palette
        with self.assertRaisesRegex(RuntimeError, 'Render failed'):
            with theme_system.preview_theme({**self.library.get('green'), 'smeter_style': 'flex_vintage_hd'}):
                self.assertEqual(runtime_theme['smeter_style'], 'flex_vintage_hd')
                self.assertNotEqual(APP_UI_STYLE.palette, palette)
                raise RuntimeError('Render failed')
        self.assertEqual(runtime_theme, before)
        self.assertEqual(APP_UI_STYLE.palette, palette)
        self.assertEqual(theme_system.runtime_revision, revision)
        self.assertFalse(self.path.exists())

    def test_live_preview_revision_is_stable_between_frames_and_changes_with_draft(self):
        import theme_system
        revisions = []
        for identifier in ('green', 'green', 'black-white'):
            with theme_system.preview_theme(self.library.get(identifier)):
                revisions.append(theme_system.runtime_revision)
        self.assertEqual(revisions[0], revisions[1])
        self.assertNotEqual(revisions[0], revisions[2])
        self.assertFalse(self.path.exists())

    def test_live_frame_copies_gpu_and_preserves_rotated_complete_screen(self):
        from theme_live_preview import LiveHomeFrame
        with patch.object(ui, 'GL') as gl, patch.object(ui, 'NATIVE_W', 800), \
                patch.object(ui, 'NATIVE_H', 1280), patch.object(ui, 'DESKTOP_MODE', False), \
                patch.object(ui, 'DISPLAY_ORIENTATION', 'normal'):
            frame = LiveHomeFrame(ui)
            frame.capture()
            frame.draw((24, 156, 704, 581))
            gl.glReadPixels.assert_not_called()
            gl.glCopyTexSubImage2D.assert_called_once_with(gl.GL_TEXTURE_2D,0,0,0,0,0,800,1280)
            self.assertEqual([c.args for c in gl.glTexCoord2f.call_args_list],
                             [(1.0,1.0),(1.0,0.0),(0.0,0.0),(0.0,1.0)])
            frame.close()
            gl.glDeleteTextures.assert_called_once()

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
        self.assertTrue(all(box[2] - box[0] == 114 and box[3] - box[1] == ui.LCD_HOME_NAV_TILE_H for box in boxes))
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
