"""Theme slider selection and shared native rendering."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import kiwi_gl_display as ui
from theme_editor import ThemeEditor, theme_screen_boxes
from theme_system import ThemeLibrary, SLIDER_STYLES, normalize_theme, DEFAULT_THEME, preview_theme


class SliderStyleTests(unittest.TestCase):
    def tap(self, editor, action):
        x0,y0,x1,y1 = theme_screen_boxes(editor)[action]
        editor.tap((x0+x1)/2,(y0+y1)/2)

    def test_picker_previews_cancel_reset_and_persists_per_theme(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp)/'themes.json'
            library = ThemeLibrary(path)
            editor = ThemeEditor(library)
            editor.show()
            self.tap(editor,'theme:green')
            self.tap(editor,'sliders')
            self.tap(editor,'slider:precision')
            self.assertEqual(editor.preview['slider_style'],'precision')
            self.assertFalse(path.exists())
            self.tap(editor,'slider:cancel')
            self.assertEqual(editor.preview['slider_style'],'classic')
            self.tap(editor,'sliders')
            self.tap(editor,'slider:studio')
            self.tap(editor,'slider:save')
            self.assertEqual(editor.preview['slider_style'],'studio')
            self.tap(editor,'save')
            self.assertEqual(ThemeLibrary(path).get('green')['slider_style'],'studio')
            editor.show()
            self.tap(editor,'theme:green')
            self.tap(editor,'reset')
            self.assertEqual(editor.preview['slider_style'],'classic')
            editor.cancel()
            self.assertEqual(ThemeLibrary(path).get('green')['slider_style'],'studio')

    def test_three_styles_render_distinct_notches_from_one_theme_setting(self):
        with TemporaryDirectory() as tmp:
            base = ThemeLibrary(Path(tmp)/'themes.json').get('default')
            ui.configure_output(True)
            outputs = []
            for style in ('classic','precision','studio'):
                with preview_theme({**base,'slider_style':style}), \
                     patch.object(ui,'draw_logical_rect') as rects, \
                     patch.object(ui,'draw_logical_line') as lines, \
                     patch.object(ui,'draw_logical_circle') as circles:
                    ui.draw_theme_slider(1044,1260,280,.5)
                    outputs.append((len(rects.call_args_list),len(lines.call_args_list),
                                    len(circles.call_args_list)))
        self.assertEqual(outputs[0],(3,0,0))
        self.assertGreater(outputs[1][1],outputs[0][1])
        self.assertGreater(outputs[2][0],outputs[0][0])
        self.assertEqual(outputs[2][2],2)

    def test_all_twelve_styles_are_reachable_and_use_theme_accent(self):
        self.assertEqual(len(SLIDER_STYLES),12)
        self.assertNotIn('capsule',{identifier for identifier,_ in SLIDER_STYLES})
        with TemporaryDirectory() as tmp:
            library = ThemeLibrary(Path(tmp)/'themes.json')
            editor = ThemeEditor(library)
            editor.show()
            self.tap(editor,'theme:green')
            editor.choose_accent('amber')
            self.assertEqual(editor.preview['colors']['slider_fill'][:3],
                             editor.preview['colors']['slider_marker'][:3])
            self.tap(editor,'sliders')
            available = set()
            for page in range(3):
                available.update(key[7:] for key in theme_screen_boxes(editor)
                                 if key.startswith('slider:') and key not in
                                 ('slider:previous','slider:next','slider:cancel','slider:save'))
                if page < 2:
                    self.tap(editor,'slider:next')
            self.assertEqual(available,{identifier for identifier,_ in SLIDER_STYLES})
            self.assertEqual(len([key for key in theme_screen_boxes(editor)
                                  if key.startswith('slider:') and key not in
                                  ('slider:previous','slider:next','slider:cancel','slider:save')]),4)
            self.tap(editor,'slider:bubble')
            self.tap(editor,'slider:save')
            self.tap(editor,'save')
            self.assertEqual(ThemeLibrary(library.path).get('green')['slider_style'],'bubble')

    def test_saved_capsule_style_maps_to_halo(self):
        theme = normalize_theme({**DEFAULT_THEME,'slider_style':'capsule'},allow_default=True)
        self.assertEqual(theme['slider_style'],'halo')

    def test_new_large_knobs_have_thin_tracks_and_distinct_shapes(self):
        with TemporaryDirectory() as tmp:
            theme = ThemeLibrary(Path(tmp)/'themes.json').get('default')
            shapes = {}
            for identifier in ('arrows','diamond','bubble'):
                with preview_theme({**theme,'slider_style':identifier}), \
                     patch.object(ui,'draw_logical_rect') as rects, \
                     patch.object(ui,'draw_logical_area') as areas, \
                     patch.object(ui,'draw_logical_line'), \
                     patch.object(ui,'draw_logical_circle') as circles, \
                     patch.object(ui,'draw_logical_rounded_rect') as rounded, \
                     patch.object(ui,'draw_logical_polyline') as outlines:
                    ui.draw_theme_slider(1044,1260,280,.5)
                    self.assertEqual(rects.call_args_list[0].args[3]-rects.call_args_list[0].args[1],2)
                    shapes[identifier] = (len(rounded.call_args_list),len(outlines.call_args_list),
                                          len(circles.call_args_list))
                    if identifier == 'arrows':
                        self.assertEqual([call.args[1] for call in outlines.call_args_list],
                                         [(0,0,0,255)]*2)
                    if identifier == 'diamond':
                        self.assertEqual(len(areas.call_args_list),2)
                    if identifier == 'bubble':
                        self.assertEqual(len(circles.call_args_list),2)
                        self.assertFalse(outlines.called)
            self.assertEqual(len(set(shapes.values())),3)

    def test_arrows_reverse_ink_for_dark_accent(self):
        with TemporaryDirectory() as tmp:
            theme = ThemeLibrary(Path(tmp)/'themes.json').get('default')
            theme['colors']['slider_fill'] = [16,32,48,255]
            with preview_theme({**theme,'slider_style':'arrows'}), \
                 patch.object(ui,'draw_logical_rect'), patch.object(ui,'draw_logical_rounded_rect'), \
                 patch.object(ui,'draw_logical_polyline') as outlines:
                ui.draw_theme_slider(1044,1260,280,.5)
            self.assertEqual([call.args[1] for call in outlines.call_args_list],
                             [(255,255,255,255)]*2)

    def test_picker_cards_and_page_buttons_fit_both_sidebar_positions(self):
        with TemporaryDirectory() as tmp:
            editor = ThemeEditor(ThemeLibrary(Path(tmp)/'themes.json'))
            editor.show()
            self.tap(editor,'theme:default')
            for side in ('left','right'):
                editor.entry_theme['sidebar'] = side
                self.tap(editor,'sliders')
                for page in range(3):
                    boxes = theme_screen_boxes(editor)
                    self.assertIn('slider:previous',boxes)
                    self.assertIn('slider:next',boxes)
                    for key,box in boxes.items():
                        self.assertTrue(0 <= box[0] < box[2] <= 1280,key)
                        self.assertTrue(0 <= box[1] < box[3] <= 800,key)
                        self.assertTrue(box[0] >= 256 if side=='left' else box[2] <= 1024,key)
                    if page < 2:
                        self.tap(editor,'slider:next')
                self.tap(editor,'slider:cancel')

    def test_every_style_draws_with_shared_range_and_theme_colors(self):
        with TemporaryDirectory() as tmp:
            theme = ThemeLibrary(Path(tmp)/'themes.json').get('default')
            for identifier,_label in SLIDER_STYLES:
                with self.subTest(identifier=identifier), preview_theme({**theme,'slider_style':identifier}), \
                     patch.object(ui,'draw_logical_rect'), patch.object(ui,'draw_logical_line'), \
                     patch.object(ui,'draw_logical_circle'), patch.object(ui,'draw_logical_rounded_rect'), \
                     patch.object(ui,'draw_logical_polyline'), patch.object(ui,'draw_logical_area'):
                    self.assertEqual(ui.draw_theme_slider(1044,1260,280,.4),1130.4)


if __name__ == '__main__':
    unittest.main()
