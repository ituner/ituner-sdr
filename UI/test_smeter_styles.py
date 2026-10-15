import math
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import kiwi_gl_display as ui
from smeter_styles import (METER_STYLES, SKIN_ASSET_DIR, SKIN_CALIBRATION,
                          dbm_to_microvolts, meter_fraction, needle_point,
                          skin_image_box, skin_needle_segment, skin_source_bounds, skin_tip)
from smeter_styles import EYE_ARTWORK, meter_asset_path, eye_closure, eye_image_box, draw_eye_signal
from theme_editor import ThemeEditor, theme_screen_boxes, METER_CARDS_PER_PAGE, PREVIEW_BOX
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

    def test_chooser_persists_selection_without_changing_live_theme_before_save(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'themes.json'
            editor = ThemeEditor(ThemeLibrary(path))
            def tap(action):
                a, b, c, d = theme_screen_boxes(editor)[action]
                editor.tap((a + c) / 2, (b + d) / 2)
            editor.show('meters')
            self.assertEqual(editor.section, 'METERS')
            for _ in range(editor.meter_page_count):
                if 'meter:aviation' in theme_screen_boxes(editor):break
                tap('meter_next')
            tap('meter:aviation')
            self.assertEqual(editor.preview['smeter_style'], 'aviation')
            self.assertEqual(ui.theme_system.runtime_theme['smeter_style'], 'led')
            tap('save')
            restarted = ThemeLibrary(path)
            self.assertEqual(restarted.get(restarted.active_id)['smeter_style'], 'aviation')
            # Repeated meter changes never create themes.
            editor.show('meters')
            tap('filter:digital')
            tap('meter_next')
            tap('meter:linear')
            tap('save')
            self.assertEqual(len(editor.library.themes), 0)

    def test_microvolts_are_rms_at_50_ohms_and_follow_power_ratio(self):
        self.assertAlmostEqual(dbm_to_microvolts(-73), 50.059326, places=5)
        self.assertAlmostEqual(dbm_to_microvolts(-53) / dbm_to_microvolts(-73), 10)
        self.assertAlmostEqual(dbm_to_microvolts(-33), 5005.932648, places=3)
        for value in (None, float('nan'), float('inf')):
            self.assertIsNone(dbm_to_microvolts(value))

    def test_original_skin_needle_uses_all_source_calibration_points(self):
        for identifier, skin in SKIN_CALIBRATION.items():
            self.assertTrue(meter_asset_path(identifier).is_file())
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

    def test_every_meter_is_reachable_and_pages_stop_at_end(self):
        with TemporaryDirectory() as directory:
            editor = ThemeEditor(ThemeLibrary(Path(directory) / 'themes.json'))
            editor.show('meters')
            editor.meter_page = 0
            seen = set()
            for _ in range(editor.meter_page_count + 1):
                boxes = theme_screen_boxes(editor)
                cards = [key.split(':')[1] for key in boxes if key.startswith('meter:')]
                self.assertLessEqual(len(cards), METER_CARDS_PER_PAGE)
                seen.update(cards)
                for key in [key for key in boxes if key.startswith('meter:')]:
                    x0, y0, x1, y1 = boxes[key]
                    self.assertLess(y1, boxes['meter_next'][1])
                    editor.tap((x0 + x1) / 2, (y0 + y1) / 2)
                    self.assertEqual(editor.draft['smeter_style'], key.split(':')[1])
                box = boxes['meter_next']
                editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            self.assertEqual(seen, set(METER_STYLES))
            self.assertEqual(editor.meter_page, (len(METER_STYLES) - 1) // METER_CARDS_PER_PAGE)

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
                if identifier.startswith('flex_'):
                    self.assertNotEqual(tuple(surface.get_at((0, 0))[:3]), METER_STYLES[identifier].metal)
                cache._cached_texture.return_value = (1, 236, 160)
                ui.draw_cached_smeter(cache, identifier, (0, 0, 236, 160), -73, None, Mock())
                cache.surface_texture.assert_called_once()

    def test_tr7_pointer_tracks_s_marks_vertically(self):
        for dbm in (-127, -121, -73, -53, -13):
            a, b, c, d = skin_needle_segment('ke9ns_tr7', (0, 0, 236, 160), dbm)
            self.assertEqual(a, c)
            self.assertGreater(b, d)

    def test_magic_eye_shadow_closes_monotonically_and_missing_signal_turns_it_off(self):
        values = [eye_closure(dbm) for dbm in range(-150, 0)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(eye_closure(-127), 0)
        self.assertEqual(eye_closure(-73), 1)
        for identifier in EYE_ARTWORK:
            self.assertTrue(meter_asset_path(identifier).is_file())
            a, b, c, d = eye_image_box(identifier, (0, 0, 236, 210))
            self.assertLessEqual(d, 168)
            circle, polygon = Mock(), Mock()
            draw_eye_signal(identifier, (0, 0, 236, 210), -109, circle=circle, polygon=polygon)
            self.assertEqual(polygon.call_count, 1)
            draw_eye_signal(identifier, (0, 0, 236, 210), -73, circle=circle, polygon=polygon)
            self.assertEqual(polygon.call_count, 1)
            for missing in (None, float('nan'), float('inf')):
                circle.reset_mock(); polygon.reset_mock()
                draw_eye_signal(identifier, (0, 0, 236, 210), missing, circle=circle, polygon=polygon)
                circle.assert_called_once(); polygon.assert_not_called()

    def test_eye_glass_stays_transparent_and_signal_changes_do_not_rebake_it(self):
        for identifier in EYE_ARTWORK:
            cache = Mock()
            cache._cached_texture.return_value = None
            cache.surface_texture.return_value = (1, 236, 210)
            with patch.object(ui, 'draw_textured_quad'), patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_eye_signal') as signal:
                ui.draw_cached_smeter(cache, identifier, (0, 0, 236, 210), -121, None, Mock())
                _, surface = cache.surface_texture.call_args.args
                self.assertLess(surface.get_at((118, 84)).a, 255)
                cache._cached_texture.return_value = (1, 236, 210)
                ui.draw_cached_smeter(cache, identifier, (0, 0, 236, 210), -73, None, Mock())
                cache.surface_texture.assert_called_once()
                self.assertEqual(signal.call_count, 2)

    def test_transparent_skin_keeps_background_clear_and_printed_scale_visible(self):
        cache = Mock()
        cache._cached_texture.return_value = None
        cache.surface_texture.return_value = (1, 236, 160)
        with patch.object(ui, 'draw_textured_quad'), patch.object(ui, 'draw_logical_line'):
            ui.draw_cached_smeter(cache, 'flex_transparent', (0, 0, 236, 160), -73, None, Mock())
            _, surface = cache.surface_texture.call_args.args
            self.assertEqual(surface.get_at((118, 140)).a, 0)
            self.assertGreater(ui.pygame.mask.from_surface(surface, 32).count(), 0)

    def test_icom_fills_the_face_area_and_orange_keeps_its_approved_geometry(self):
        self.assertEqual(skin_image_box('flex_icom', (0, 0, 236, 160)), (0, 0, 236, 128))
        self.assertEqual(skin_source_bounds('flex_icom'), (17, 15, 464, 186))
        self.assertEqual(skin_image_box('flex_orange', (0, 0, 236, 160)), (0, 10, 236, 129))
        self.assertEqual(skin_source_bounds('flex_orange'), (0, 0, 397, 200))

    def test_picker_uses_complete_home_frame_beside_meter_thumbnails(self):
        with TemporaryDirectory() as directory:
            editor = ThemeEditor(ThemeLibrary(Path(directory) / 'themes.json'))
            editor.show('meters')
            editor.meter_page = list(METER_STYLES).index('flex_icom') // METER_CARDS_PER_PAGE
            editor.live_frame = Mock()
            editor.draft['smeter_style'] = 'flex_icom'
            with ExitStack() as stack:
                mocks = {name: stack.enter_context(patch.object(ui, name)) for name in (
                    'draw_logical_rect', 'draw_logical_line', 'draw_logical_circle',
                    'draw_logical_rounded_rect', 'draw_text', 'draw_sidebar_header',
                    'draw_styled_text_button', 'draw_styled_button_frame', 'draw_selected_smeter')}
                ui.draw_theme_panel(None, editor)
                mocks['draw_styled_button_frame'].assert_not_called()
                editor.live_frame.draw.assert_called_once_with(PREVIEW_BOX)
                self.assertEqual(mocks['draw_selected_smeter'].call_count, METER_CARDS_PER_PAGE)
                icom = next(c for c in mocks['draw_selected_smeter'].call_args_list if c.kwargs['style_id']=='flex_icom')
                box = icom.args[1]
                self.assertEqual((box[2]-box[0],box[3]-box[1]),(236,160))
                labels = [call.args for call in mocks['draw_text'].call_args_list]
                self.assertTrue(any(call[3] == METER_STYLES['flex_icom'].name.split(' · ')[0]
                                    and call[4] == __import__('theme_screen_render').ACCENT for call in labels))

    def test_legacy_and_invalid_saved_styles_fall_back_to_led(self):
        for value in (None, 'unknown', [], {}):
            theme = new_theme()
            theme['smeter_style'] = value
            self.assertEqual(normalize_theme(theme)['smeter_style'], 'led')

    def test_removed_vintage_selection_migrates_to_hd_without_changing_theme_colors(self):
        theme = new_theme()
        theme['smeter_style'] = 'flex_vintage'
        normalized = normalize_theme(theme)
        self.assertEqual(normalized['smeter_style'], 'flex_vintage_hd')
        self.assertEqual(normalized['colors'], theme['colors'])
        self.assertNotIn('flex_vintage', METER_STYLES)

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


if __name__ == '__main__':
    unittest.main()
