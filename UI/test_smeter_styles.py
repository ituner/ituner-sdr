import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import kiwi_gl_display as ui
from smeter_styles import (METER_STYLES, SKIN_ASSET_DIR, SKIN_CALIBRATION,
                          dbm_to_microvolts, meter_fraction, needle_point,
                          skin_image_box, skin_needle_segment, skin_tip)
from theme_editor import ThemeEditor, theme_screen_boxes
from theme_system import DEFAULT_THEME, ThemeLibrary, apply_theme, new_theme, normalize_theme


class MeterTests(unittest.TestCase):
    def tearDown(self):
        apply_theme(DEFAULT_THEME)

    def test_calibration_matches_receiver_and_clamps_end_stops(self):
        for dbm in range(-150, 1):
            self.assertAlmostEqual(meter_fraction(dbm), ui.smeter_segment_position(dbm) / 36)
        self.assertEqual(meter_fraction(-73), 22 / 36)
        self.assertEqual(meter_fraction(-53), 28 / 36)
        for missing in (None, float('nan'), float('inf')):
            self.assertEqual(meter_fraction(missing), 0)

    def test_needles_stay_on_their_radius_for_the_entire_sweep(self):
        for style in METER_STYLES.values():
            for dbm in (-200, -121, -97, -73, -53, -33, 20):
                x, y = needle_point(style, dbm, (80, 100), 70)
                self.assertAlmostEqual(math.hypot(x - 80, y - 100), 70)
            self.assertNotEqual(needle_point(style, -121, (0, 0), 1),
                                needle_point(style, -33, (0, 0), 1))

    def test_category_gallery_applies_live_and_persists_saved_selection(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'themes.json'
            editor = ThemeEditor(ThemeLibrary(path))
            def tap(action):
                a, b, c, d = theme_screen_boxes(editor)[action]
                editor.tap((a + c) / 2, (b + d) / 2)
            def choose(identifier):
                for _ in range(3):
                    tap('next')
                self.assertEqual(editor.category_index, 3)
                tap('meter_gallery')
                while f'meter:{identifier}' not in theme_screen_boxes(editor):
                    tap('meter_next' if editor.can_meter_next else 'meter_previous')
                tap(f'meter:{identifier}')
            tap('new')
            choose('aviation')
            self.assertEqual(editor.draft['smeter_style'], 'aviation')
            self.assertEqual(ui.theme_system.runtime_theme['smeter_style'], 'aviation')
            self.assertEqual(editor.library.themes, [])
            tap('back')
            tap('leave_save')
            restarted = ThemeLibrary(path)
            self.assertEqual(restarted.get(restarted.active_id)['smeter_style'], 'aviation')
            # Editing an existing custom theme updates the same saved entry.
            tap('edit:4')
            choose('linear')
            tap('back')
            tap('leave_save')
            self.assertEqual(len(editor.library.themes), 1)
            self.assertEqual(ThemeLibrary(path).get(editor.selected_id)['smeter_style'], 'linear')

    def test_microvolts_are_rms_at_50_ohms_and_follow_power_ratio(self):
        self.assertAlmostEqual(dbm_to_microvolts(-73), 50.059326, places=5)
        self.assertAlmostEqual(dbm_to_microvolts(-53) / dbm_to_microvolts(-73), 10)
        self.assertAlmostEqual(dbm_to_microvolts(-33), 5005.932648, places=3)
        for value in (None, float('nan'), float('inf')):
            self.assertIsNone(dbm_to_microvolts(value))

    def test_original_skin_needle_uses_all_source_calibration_points(self):
        for identifier, skin in SKIN_CALIBRATION.items():
            self.assertTrue((SKIN_ASSET_DIR / skin['file']).is_file())
            self.assertEqual(len(skin['points']), 16)
            for level, point in zip(skin['dbm'], skin['points']):
                self.assertEqual(skin_tip(identifier, level), tuple(point))
            self.assertEqual(skin_tip(identifier, -300), tuple(skin['points'][0]))
            self.assertEqual(skin_tip(identifier, 20), tuple(skin['points'][-1]))
            a, b = skin['points'][9:11]
            self.assertEqual(skin_tip(identifier, -68), tuple((x + y) / 2 for x, y in zip(a, b)))
            bounds = skin_image_box(identifier, (30, 10, 266, 170))
            for level in range(-150, 0):
                segment = skin_needle_segment(identifier, (30, 10, 266, 170), level)
                for x, y in (segment[:2], segment[2:]):
                    self.assertGreaterEqual(x, bounds[0] - 1e-8)
                    self.assertLessEqual(x, bounds[2] + 1e-8)
                    self.assertGreaterEqual(y, bounds[1] - 1e-8)
                    self.assertLessEqual(y, bounds[3] + 1e-8)

    def test_category_gallery_exposes_every_meter_and_stops_at_end(self):
        with TemporaryDirectory() as directory:
            editor = ThemeEditor(ThemeLibrary(Path(directory) / 'themes.json'))
            editor.begin()
            def tap(action):
                x0, y0, x1, y1 = theme_screen_boxes(editor)[action]
                editor.tap((x0 + x1) / 2, (y0 + y1) / 2)
            for _ in range(3):
                tap('next')
            tap('meter_gallery')
            while editor.can_meter_previous:
                tap('meter_previous')
            seen = set()
            for _ in range(5):
                boxes = theme_screen_boxes(editor)
                cards = [key.split(':')[1] for key in boxes if key.startswith('meter:')]
                self.assertLessEqual(len(cards), 6)
                seen.update(cards)
                for identifier in cards:
                    box = theme_screen_boxes(editor)[f'meter:{identifier}']
                    self.assertLessEqual(box[3], boxes['meter_next'][1])
                    tap(f'meter:{identifier}')
                    self.assertEqual(editor.draft['smeter_style'], identifier)
                    tap('meter_gallery')
                tap('meter_next')
            self.assertEqual(seen, set(METER_STYLES))
            self.assertEqual(editor.meter_page, (len(METER_STYLES) - 1) // 6)

    def test_flex_faces_use_full_rail_width_and_integer_pixel_bounds(self):
        box = (1034, 104, 1270, 264)
        for identifier in SKIN_CALIBRATION:
            left, top, right, bottom = skin_image_box(identifier, box)
            self.assertEqual(right - left, 236)
            for value in (left, top, right, bottom):
                self.assertIsInstance(value, int)
            for level in (-127, -73, -13):
                segment = skin_needle_segment(identifier, box, level)
                self.assertLessEqual(segment[1], box[1] + .80 * (box[3] - box[1]) + 1e-8)

    def test_flex_texture_is_cached_at_final_resolution_without_metal_border(self):
        for identifier in SKIN_CALIBRATION:
            cache = Mock()
            cache._cached_texture.return_value = None
            cache.surface_texture.return_value = (1, 236, 160)
            with patch.object(ui, 'draw_textured_quad'), patch.object(ui, 'draw_logical_line'):
                ui.draw_cached_smeter(cache, identifier, (0, 0, 236, 160), -85, None, Mock())
                key, surface = cache.surface_texture.call_args.args
                self.assertEqual(surface.get_size(), (236, 160))
                self.assertNotEqual(tuple(surface.get_at((0, 0))[:3]), METER_STYLES[identifier].metal)
                cache._cached_texture.return_value = (1, 236, 160)
                ui.draw_cached_smeter(cache, identifier, (0, 0, 236, 160), -73, None, Mock())
                cache.surface_texture.assert_called_once()

    def test_legacy_and_invalid_saved_styles_fall_back_to_led(self):
        for value in (None, 'unknown', [], {}):
            theme = new_theme()
            theme['smeter_style'] = value
            self.assertEqual(normalize_theme(theme)['smeter_style'], 'led')

    def test_tall_meters_reclaim_bandpass_space_and_keep_all_controls_clear(self):
        ui.configure_output(True)
        for sidebar in ('left', 'right'):
            for identifier, style in METER_STYLES.items():
                theme = new_theme()
                theme.update(smeter_style=identifier, sidebar=sidebar)
                apply_theme(theme)
                self.assertEqual(ui.home_bandpass_visible(), style.height == 80)
                for compact in (True, False):
                    modes = list(ui.lcd_home_mode_boxes(compact))
                    volume = ui.lcd_home_volume_box(compact)
                    self.assertLessEqual(max(box[3] for _, box in modes), volume[1])
                    self.assertLess(volume[3], ui.lcd_nav_top())
                    if compact:
                        meter = ui.lcd_compact_smeter_box()
                        self.assertEqual(meter[3] - meter[1], style.height)
                        self.assertLess(meter[3], min(box[1] for _, box in modes))
                    elif style.height > 80:
                        meter_top = ui.lcd_home_bandwidth_box(False)[1]
                        self.assertLess(meter_top + style.height, volume[1])

    def test_home_mode_touch_area_follows_each_meter_height(self):
        ui.configure_output(True)
        for identifier in METER_STYLES:
            theme = new_theme()
            theme['smeter_style'] = identifier
            apply_theme(theme)
            for compact in (True, False):
                touch_box = ui.radio_toggle_box(None, 7075, compact)
                for label, button in ui.lcd_home_mode_boxes(compact):
                    with self.subTest(meter=identifier, compact=compact, mode=label):
                        center_x = (button[0] + button[2]) / 2
                        center_y = (button[1] + button[3]) / 2
                        self.assertTrue(ui.contains(touch_box, center_x, center_y))

    def test_default_home_meter_keeps_its_original_theme_background(self):
        apply_theme(DEFAULT_THEME)
        box = (1034, 104, 1270, 184)
        with patch.object(ui, 'draw_logical_rect') as draw_rect, \
                patch.object(ui, 'draw_section_divider'), \
                patch.object(ui, 'draw_logical_line'), \
                patch.object(ui, 'draw_logical_circle'), \
                patch.object(ui, 'draw_text'):
            ui.draw_lcd_compact_smeter(None, box, -85)
        self.assertEqual(draw_rect.call_args_list[0].args,
                         (*box, ui.APP_UI_STYLE.palette.section_surface))


if __name__ == '__main__':
    unittest.main()
