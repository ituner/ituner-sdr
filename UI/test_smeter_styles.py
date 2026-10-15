import math
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import kiwi_gl_display as ui
from smeter_styles import (METER_STYLES, SKIN_ASSET_DIR, SKIN_CALIBRATION,
                          dbm_to_microvolts, meter_fraction, needle_point,
                          skin_image_box, skin_needle_segment, skin_source_bounds, skin_tip,
                          aviation_image_box, aviation_needle_segment)
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

    def test_removed_tr7_and_transparent_styles_use_led_without_creating_themes(self):
        import json
        from smeter_styles import COMMUNITY_ARTWORK, normalize_meter_style
        for identifier, relative in (('ke9ns_tr7', 'community/ke9ns_tr7.jpg'), ('flex_transparent', 'flexible/flex_transparent.png')):
            self.assertNotIn(identifier, METER_STYLES)
            self.assertNotIn(identifier, SKIN_CALIBRATION)
            self.assertNotIn(identifier, COMMUNITY_ARTWORK)
            self.assertFalse((SKIN_ASSET_DIR.parent / relative).exists())
            self.assertEqual(normalize_meter_style(identifier), 'led')
            theme = new_theme(); theme['smeter_style'] = identifier
            self.assertEqual(normalize_theme(theme)['colors'], theme['colors'])
            with TemporaryDirectory() as directory:
                path = Path(directory) / 'themes.json'
                path.write_text(json.dumps({'version':1, 'active_id':'green', 'themes':[], 'smeter_style':identifier}))
                library = ThemeLibrary(path)
                self.assertEqual(library.smeter_style, 'led')
                library.set_smeter_style('led')
                saved = json.loads(path.read_text())
                self.assertEqual(saved['smeter_style'], 'led')
                self.assertEqual(saved['active_id'], 'green')
                self.assertEqual(saved['themes'], [])

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

    def test_peppy_gas_uses_vfd_green_for_cells_readouts_scale_and_peak(self):
        from meter_artwork import linear_strip_image
        background = (3, 9, 12, 255)
        for active in (False, True):
            image = linear_strip_image('peppy_gas', (228, 30), active)
            colors = [color for count, color in image.getcolors(228*30) if color != background]
            self.assertTrue(colors)
            for r, g, b, alpha in colors:
                self.assertGreater(g, r)
                self.assertGreater(g, b)
                if active: self.assertGreaterEqual(g, 220)
        cache = Mock(); cache._cached_texture.return_value = (1, 228, 30)
        labels = Mock()
        with patch.object(ui, 'draw_textured_quad'), patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line') as peak:
            ui.draw_linear_skin_smeter(cache, 'peppy_gas', (0, 0, 236, 80), -53, -33, labels)
            for call in labels.call_args_list:
                r, g, b = call.args[3]
                self.assertGreater(g, max(r, b))
            r, g, b = peak.call_args.args[-2]
            self.assertGreater(g, max(r, b))

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

    def test_retired_round_eyes_migrate_to_plain_without_reappearing(self):
        from smeter_styles import REMOVED_METER_MIGRATIONS, normalize_meter_style
        import json
        self.assertEqual(set(EYE_ARTWORK), {'oe3ide_eye_plain'})
        for identifier in (key for key in REMOVED_METER_MIGRATIONS if key.startswith('oe3ide_eye_')):
            self.assertNotIn(identifier, METER_STYLES)
            self.assertEqual(normalize_meter_style(identifier), 'oe3ide_eye_plain')
            self.assertFalse((SKIN_ASSET_DIR.parent/'community'/f'{identifier}.png').exists())
            with TemporaryDirectory() as directory:
                path = Path(directory)/'themes.json'
                path.write_text(json.dumps({'version':1,'active_id':'default','themes':[], 'smeter_style':identifier}))
                library=ThemeLibrary(path)
                self.assertEqual(library.smeter_style,'oe3ide_eye_plain')
                library.activate('green')
                self.assertEqual(json.loads(path.read_text())['smeter_style'],'oe3ide_eye_plain')
                self.assertEqual(library.themes,[])

    def test_magic_band_closes_symmetrically_and_missing_signal_has_no_phosphor(self):
        from smeter_styles import magic_band_geometry, draw_magic_band
        previous = float('inf')
        for dbm in range(-127,-12):
            a,left,right,b=magic_band_geometry((0,0,236,80),dbm)
            self.assertLessEqual(a,left)
            self.assertLessEqual(left,right)
            self.assertLessEqual(right,b)
            self.assertAlmostEqual(left-a,b-right)
            self.assertLessEqual(right-left,previous)
            previous=right-left
        self.assertEqual(previous,0)
        colors=[]
        draw_magic_band((0,0,236,80),None,rect=lambda *args:colors.append(args[-1]),circle=lambda *args:colors.append(args[-1]),text=Mock())
        self.assertFalse(any(g>150 for r,g,b in colors))
        self.assertEqual(METER_STYLES['magic_band_em84'].height,80)

    def test_peppy_strips_are_cached_and_clipped_to_the_rx_scale(self):
        from smeter_styles import LINEAR_ARTWORK
        for identifier in LINEAR_ARTWORK:
            cache=Mock();textures={}
            cache._cached_texture.side_effect=textures.get
            def retain(key,surface):
                result=(len(textures)+1,*surface.get_size())
                textures[('surface',key)]=result
                return result
            cache.surface_texture.side_effect=retain
            with patch.object(ui,'draw_textured_quad') as quad, patch.object(ui,'draw_logical_rect'), patch.object(ui,'draw_logical_line'):
                ui.draw_linear_skin_smeter(cache,identifier,(0,0,236,80),-73,None,Mock())
                self.assertEqual(cache.surface_texture.call_count,2)
                self.assertEqual(quad.call_args.args[3],4+round(228*meter_fraction(-73)))
                for value in (-121,-53,None,float('nan'),float('inf')):
                    quad.reset_mock()
                    ui.draw_linear_skin_smeter(cache,identifier,(0,0,236,80),value,None,Mock())
                    if value is None or not math.isfinite(value):self.assertEqual(quad.call_count,1)
                self.assertEqual(cache.surface_texture.call_count,2)

    def test_linear_skin_scale_aligns_with_signal_in_wide_top_instrument(self):
        cache=Mock();cache._cached_texture.return_value=(1,400,30)
        labels=Mock()
        with patch.object(ui,'draw_textured_quad') as quad, patch.object(ui,'draw_logical_rect'), patch.object(ui,'draw_logical_line'):
            ui.draw_linear_skin_smeter(cache,'peppy_bar',(0,0,400,80),-73,None,labels)
        s9=next(c.args[0] for c in labels.call_args_list if c.args[2]=='9')
        self.assertAlmostEqual(s9,4+392*meter_fraction(-73))
        self.assertAlmostEqual(quad.call_args.args[3],s9,delta=.5)
        reading=next(c.args[0] for c in labels.call_args_list if c.args[2]=='-73 dBm')
        self.assertEqual(reading,396)

    def test_peppy_native_cells_keep_dark_gaps_in_both_states(self):
        from meter_artwork import linear_cell_boxes, linear_strip_image
        for identifier in ('peppy_bar', 'peppy_dash', 'peppy_gas'):
            for size in ((228, 30), (392, 30), (157, 21)):
                cells = linear_cell_boxes(identifier, size)
                mask = ui.PILImage.new('1', size)
                from PIL import ImageDraw
                draw = ImageDraw.Draw(mask)
                for cell in cells:
                    self.assertTrue(all(isinstance(v, int) for v in cell))
                    draw.rectangle(cell, fill=1)
                for active in (False, True):
                    image = linear_strip_image(identifier, size, active)
                    self.assertEqual(image.size, size)
                    # Off and on states share exactly the same black pixel gaps.
                    for position, pixel in enumerate(image.getdata()):
                        expected_cell = mask.getpixel((position % size[0], position // size[0]))
                        self.assertEqual(pixel != (3, 9, 12, 255), bool(expected_cell))
                    # No resampling halos or blurry intermediate grid colours.
                    self.assertLessEqual(len(image.getcolors(size[0] * size[1])), 5)

    def test_aviation_dial_stays_square_and_needle_uses_printed_scale_geometry(self):
        for identifier in ('aviation', 'heritage'):
            self.assertTrue(meter_asset_path(identifier).is_file())
            self.assertEqual(METER_STYLES[identifier].height, 236)
            self.assertEqual(aviation_image_box((1034, 104, 1270, 340), footer=False), (1034, 104, 1270, 340))
            for box in ((1034, 104, 1270, 340), (0, 0, 400, 80), (701.5, 187, 858.5, 326.7)):
                a, b, c, d = aviation_image_box(box, footer=False)
                self.assertEqual(c-a, d-b)
                self.assertTrue(all(isinstance(v, int) for v in (a, b, c, d)))
                for level in (-200, -121, -97, -73, -53, -33, None, float('nan')):
                    px, py, tx, ty = aviation_needle_segment(identifier, box, level)
                    self.assertEqual((tx, ty), needle_point(METER_STYLES[identifier], level,
                                                         (px, py), (c-a)*.315))
                    self.assertLessEqual(math.hypot(tx-px, ty-py), (c-a)*.34)

    def test_aviation_signal_changes_reuse_face_and_hub_but_move_live_needle(self):
        ui.pygame.font.init()
        for identifier in ('aviation', 'heritage'):
            cache = Mock(); textures = {}
            cache._cached_texture.side_effect = textures.get
            cache.font.side_effect = lambda size, **kwargs: ui.pygame.font.Font(None, size)
            def retain(key, surface):
                result = (len(textures)+1, *surface.get_size())
                textures[('surface', key)] = result
                return result
            cache.surface_texture.side_effect = retain
            with patch.object(ui, 'draw_textured_quad'), patch.object(ui, 'draw_logical_line') as line:
                box = (0, 0, 236, 210)
                ui.draw_aviation_smeter(cache, identifier, box, -109, None, Mock())
                first_tip = line.call_args.args[2:4]
                line.reset_mock()
                ui.draw_aviation_smeter(cache, identifier, box, -73, -53, Mock())
                self.assertNotEqual(first_tip, line.call_args.args[2:4])
                self.assertEqual(line.call_args.args[:4], aviation_needle_segment(identifier, box, -73))
                # Only one static face and one centre cap are ever rasterized.
                self.assertEqual(cache.surface_texture.call_count, 2)

    def test_missing_aviation_artwork_falls_back_without_interrupting_receiver(self):
        cache = Mock(); cache._cached_texture.return_value = None
        with patch.object(ui.PILImage, 'open', side_effect=OSError('Missing asset')), \
                patch.object(ui, 'draw_selected_smeter') as fallback:
            ui.draw_aviation_smeter(cache, 'heritage', (0, 0, 236, 210), -73, None, Mock())
            self.assertEqual(fallback.call_args.kwargs['style_id'], 'precision')

    def test_full_width_aviation_keeps_readouts_inside_and_volume_touch_targets_clear(self):
        ui.configure_output(True)
        for identifier in ('aviation', 'heritage'):
            theme = new_theme(); theme.update(smeter_style=identifier, text_scale_percent=120)
            apply_theme(theme)
            box = ui.lcd_compact_smeter_box()
            self.assertEqual(aviation_image_box(box, footer=False), box)
            self.assertEqual((box[2]-box[0], box[3]-box[1]), (236, 236))
            modes = list(ui.lcd_home_mode_boxes(True))
            volume, mute, track = (fn(True) for fn in (ui.lcd_home_volume_box, ui.lcd_home_volume_mute_box, ui.lcd_home_volume_track_box))
            self.assertLess(box[3], min(bounds[1] for _, bounds in modes))
            self.assertLess(max(bounds[3] for _, bounds in modes), volume[1])
            self.assertGreaterEqual(volume[3]-volume[1], 60)
            self.assertGreaterEqual(mute[1], volume[1]+21)
            self.assertLess(mute[2], track[0])
            self.assertEqual(ui.home_volume_at_x(track[0], True), 0)
            self.assertEqual(ui.home_volume_at_x(track[2], True), 1)
            self.assertLess(volume[3], ui.lcd_nav_top())
            cache = Mock(); cache._cached_texture.return_value = (1, 236, 236)
            with patch.object(ui, 'draw_textured_quad'), patch.object(ui, 'draw_logical_line'):
                labels = Mock()
                ui.draw_aviation_smeter(cache, identifier, box, -73, None, labels)
                self.assertEqual(labels.call_count, 2)
                for call in labels.call_args_list:
                    x, y = call.args[:2]
                    self.assertEqual(x, (box[0]+box[2])/2)
                    self.assertGreater(y, box[1]+236*.68)
                    self.assertLess(y, box[1]+236*.82)

    def test_bakelite_reference_photos_keep_transparency_and_scales_on_paper(self):
        from smeter_styles import BAKELITE_CALIBRATION, bakelite_point
        for identifier, data in BAKELITE_CALIBRATION.items():
            with ui.PILImage.open(meter_asset_path(identifier)) as image:
                self.assertEqual(image.mode, 'RGBA')
                self.assertEqual(image.getchannel('A').getextrema(), (0, 255))
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                size = image.width
                # Exclude the footer reservation from the source-coordinate box.
                box = (0, 0, size, size * 236 / 216)
                for level in (-121, -109, -97, -85, -73, -53, -33):
                    for radius in (data['arc_radius'], data['label_radius']):
                        x, y = bakelite_point(identifier, box, level, radius)
                        r, g, b, alpha = image.getpixel((round(x), round(y)))
                        self.assertGreater(r, 140, (identifier, level, radius))
                        self.assertGreater(g, 100, (identifier, level, radius))
                        self.assertGreaterEqual(alpha, 250)

    def test_bakelite_live_pointer_matches_marks_and_emerges_above_front_cover(self):
        from smeter_styles import BAKELITE_CALIBRATION, bakelite_point, bakelite_needle_segment, bakelite_front_edge
        for identifier, data in BAKELITE_CALIBRATION.items():
            for box in ((1034, 104, 1270, 314), (0, 0, 400, 80), (745, 474, 902, 614)):
                a, b, c, d = aviation_image_box(box)
                previous_angle = -200
                for level in range(-127, -12):
                    x, y, tx, ty = bakelite_needle_segment(identifier, box, level)
                    self.assertEqual((tx, ty), bakelite_point(identifier, box, level, data['needle_radius']))
                    px, py = bakelite_point(identifier, box, level, 0)
                    angle = math.degrees(math.atan2(tx-px, py-ty))
                    self.assertGreaterEqual(angle + 1e-8, previous_angle)
                    previous_angle = angle
                    if data['front_lip']:
                        self.assertLess((y-b)/(d-b), bakelite_front_edge(identifier, (x-a)/(c-a)))
                        self.assertLess(math.hypot(tx-x, ty-y), math.hypot(tx-px, ty-py))
                    else:
                        self.assertEqual((x, y), (px, py))
                for missing in (None, float('nan'), float('inf')):
                    self.assertEqual(bakelite_needle_segment(identifier, box, missing),
                                     bakelite_needle_segment(identifier, box, -121))

    def test_bakelite_vu_print_and_pivot_stay_cached_while_the_pointer_moves(self):
        ui.pygame.font.init()
        from smeter_styles import BAKELITE_CALIBRATION, bakelite_needle_segment
        for identifier, data in BAKELITE_CALIBRATION.items():
            cache = Mock(); textures = {}
            cache._cached_texture.side_effect = textures.get
            cache.font.side_effect = lambda size, **kwargs: ui.pygame.font.Font(None, size)
            def retain(key, surface):
                result = (len(textures)+1, *surface.get_size())
                textures[('surface', key)] = result
                if key[0] == 'bakelite-face-v1':
                    self.assertEqual(surface.get_at((0, 0)).a, 0)
                return result
            cache.surface_texture.side_effect = retain
            box = (0, 0, 236, 210)
            with patch.object(ui, 'draw_textured_quad'), patch.object(ui, 'draw_logical_line'), \
                    patch.object(ui, 'draw_bakelite_pointer') as pointer:
                for level in (-121, -85, -73, -33, None):
                    ui.draw_bakelite_smeter(cache, identifier, box, level, -33, Mock())
                    self.assertEqual(pointer.call_args.args[0], bakelite_needle_segment(identifier, box, level))
                self.assertEqual(cache.surface_texture.call_count, 2 if data['pivot_cap'] else 1)
                self.assertTrue(cache.font.call_args_list)
                for call in cache.font.call_args_list:
                    self.assertEqual(call.kwargs['family'], 'Liberation Sans Narrow')
                    self.assertFalse(call.kwargs['bold'])

    def test_missing_bakelite_face_or_uncached_pivot_falls_back_safely(self):
        for cached_face in (None, (1, 192, 192)):
            cache = Mock()
            cache._cached_texture.side_effect = lambda key: cached_face if key[1][0] == 'bakelite-face-v1' else None
            with patch.object(ui.PILImage, 'open', side_effect=OSError('Missing asset')), \
                    patch.object(ui, 'draw_selected_smeter') as fallback, \
                    patch.object(ui, 'draw_bakelite_pointer'), patch.object(ui, 'draw_textured_quad'):
                ui.draw_bakelite_smeter(cache, 'bakelite_square', (0, 0, 236, 210), -73, None, Mock())
                self.assertEqual(fallback.call_args.kwargs['style_id'], 'precision')

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
                        mute = ui.lcd_home_volume_mute_box(compact)
                        self.assertGreaterEqual(mute[1], volume[1] + 21)
                        meter = ui.lcd_compact_smeter_box()
                        self.assertEqual(meter[3] - meter[1], style.height)
                        self.assertLess(meter[3], min(box[1] for _, box in modes))
                    elif style.height > 80:
                        meter_top = ui.lcd_home_bandwidth_box(False)[1]
                        self.assertLess(meter_top + style.height, volume[1])


if __name__ == '__main__':
    unittest.main()
