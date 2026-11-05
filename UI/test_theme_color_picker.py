"""The color sub-editor previews locally and returns to Customize."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from contextlib import ExitStack

import kiwi_gl_display as ui
from theme_editor import ThemeEditor, theme_screen_boxes
from theme_system import ThemeLibrary


class ColorPickerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / 'themes.json'
        self.editor = ThemeEditor(ThemeLibrary(self.path))
        self.editor.show()
        self.editor.select_theme('default')

    def tearDown(self):
        self.temp.cleanup()

    def tap(self, key):
        if key.endswith((':smaller',':larger')) and key.split(':')[0] in ('color_intensity','border_intensity'):
            field,step=key.split(':')
            low,high=(50,150) if field=='color_intensity' else (25,200)
            amount=self.editor.preview[field+'_percent']+(-5 if step=='smaller' else 5)
            a,b,c,d=theme_screen_boxes(self.editor)[field]
            x=a+4+(c-a-8)*(amount-low)/(high-low)
            self.editor.drag(x,(b+d)/2,started_at=((a+c)/2,(b+d)/2))
            return
        a,b,c,d = theme_screen_boxes(self.editor)[key]
        self.editor.tap((a+c)/2, (b+d)/2)

    def test_defaults_and_equal_footer_buttons(self):
        self.assertEqual(self.editor.preview['border_intensity_percent'],25)
        self.assertEqual(self.editor.preview['color_intensity_percent'],100)
        boxes = theme_screen_boxes(self.editor)
        self.assertEqual(boxes['reset'][2]-boxes['reset'][0], boxes['save'][2]-boxes['save'][0])

    def test_customize_drags_are_inert_including_after_color_window_closes(self):
        for side in ('left','right'):
            self.editor.entry_theme['sidebar'] = side
            before = deepcopy(self.editor.preview)
            self.editor.drag(500,550,started_at=(450,520))
            self.assertEqual(self.editor.preview,before)
            self.tap('colors:accent')
            a,b,c,d = theme_screen_boxes(self.editor)['color_intensity']
            self.tap('color:save')
            self.editor.drag(c,b,started_at=((a+c)/2,(b+d)/2))
            self.assertEqual(self.editor.preview,before)

    def test_save_returns_to_customize_and_persists_both_colors_only_on_apply(self):
        self.tap('colors:accent')
        self.tap('color:accent:white')
        self.tap('color:text:black')
        self.tap('color:save')
        self.assertIsNone(self.editor.overlay)
        self.assertTrue(self.editor.open)
        self.assertEqual(self.editor.preview['accent_rgb'],[255,255,255])
        self.assertEqual(self.editor.preview['text_rgb'],[0,0,0])
        self.assertEqual(self.editor.preview['colors']['text'],[0,0,0])
        self.assertFalse(self.path.exists())
        self.tap('save')
        restarted = ThemeEditor(ThemeLibrary(self.path))
        restarted.show(); restarted.select_theme('default')
        self.assertEqual(restarted.preview['accent_rgb'],[255,255,255])
        self.assertEqual(restarted.preview['text_rgb'],[0,0,0])

    def test_cancel_restores_before_picker_and_reset_removes_custom_colors(self):
        before = deepcopy(self.editor.preview)
        self.tap('colors:text'); self.tap('color:accent:black'); self.tap('color:cancel')
        self.assertEqual(self.editor.preview,before)
        self.tap('colors:text'); self.tap('color:text:white'); self.tap('color:save')
        self.tap('reset')
        self.assertEqual(self.editor.preview,before)

    def test_rainbow_drag_clamps_and_does_not_touch_other_row(self):
        self.tap('colors:accent')
        before = deepcopy(self.editor.preview['colors']['text'])
        a,b,c,d = theme_screen_boxes(self.editor)['color:accent:rainbow']
        self.editor.drag(a-100,b,started_at=((a+c)/2,(b+d)/2))
        self.assertEqual(self.editor.preview['accent_rgb'],[255,0,0])
        self.assertEqual(self.editor.preview['colors']['text'],before)
        self.editor.drag(a+(c-a)/3,b,started_at=((a+c)/2,(b+d)/2))
        self.assertGreater(self.editor.preview['accent_rgb'][1],250)

    def test_plus_minus_glyphs_are_half_again_as_large(self):
        with patch.object(ui,'draw_styled_button_frame'), patch.object(ui,'draw_text') as text:
            for label in ('−','-','+'):
                ui.draw_styled_text_button(None,(0,0,64,64),label)
                self.assertEqual(text.call_args.args[5],round(ui.APP_UI_STYLE.button.label_size*1.5))

    def test_picker_targets_stay_inside_panel_for_either_sidebar(self):
        from theme_editor import inspector_box
        for side in ('left','right'):
            self.editor.entry_theme['sidebar'] = side
            self.editor.overlay = 'colors'
            x0,y0,x1,y1 = inspector_box(self.editor)
            boxes = list(theme_screen_boxes(self.editor).values())
            for i,(a,b,c,d) in enumerate(boxes):
                self.assertTrue(x0<=a<c<=x1 and y0<=b<d<=y1)
                self.assertGreaterEqual(d-b,44)
                for e,f,g,h in boxes[i+1:]:
                    self.assertFalse(a<g and c>e and b<h and d>f)

    def test_black_accent_keeps_pressed_labels_readable(self):
        from theme_system import preview_theme
        self.tap('colors:accent'); self.tap('color:accent:black')
        with preview_theme(self.editor.preview):
            self.assertEqual(ui.APP_UI_STYLE.button.resolve(pressed=True).text,(255,255,255))

    def test_intensities_live_only_in_color_window_with_thinner_color_rows(self):
        self.assertNotIn('color_intensity',theme_screen_boxes(self.editor))
        self.assertNotIn('border_intensity',theme_screen_boxes(self.editor))
        self.tap('colors:accent')
        boxes = theme_screen_boxes(self.editor)
        self.assertIn('color_intensity',boxes)
        self.assertIn('border_intensity',boxes)
        self.assertIn('saturation',boxes)
        self.assertFalse(any(k.endswith((':smaller',':larger')) for k in boxes))
        self.assertEqual(boxes['color:accent:black'][1],boxes['color:text:black'][1])
        for key in ('color:accent:black','color:text:white','color:text:rainbow'):
            self.assertLess(boxes[key][3]-boxes[key][1],64)

    def test_saturation_previews_all_palette_colors_and_persists_without_drift(self):
        self.editor.select_theme('green')
        self.tap('colors:accent')
        before = deepcopy(self.editor.preview)
        a,b,c,d = theme_screen_boxes(self.editor)['saturation']
        self.editor.drag(a,(b+d)/2,started_at=((a+c)/2,(b+d)/2))
        self.assertEqual(self.editor.preview['saturation_percent'],0)
        for key in ('text','active_border','spectrum_line','ready'):
            self.assertEqual(len(set(self.editor.preview['colors'][key][:3])),1,key)
            self.assertEqual(self.editor.preview['colors'][key][3:],before['colors'][key][3:])
        self.tap('color:save'); self.tap('save')
        saved = deepcopy(self.editor.preview)
        self.editor = ThemeEditor(ThemeLibrary(self.path))
        self.editor.show(); self.editor.select_theme('green')
        self.assertEqual(self.editor.preview,saved)
        self.tap('reset')
        self.assertEqual(self.editor.preview,before)

    def test_waterfall_saturation_preserves_alpha_and_matches_scalar_path(self):
        pixels = bytes([20,40,80,73,125,170,200,251])
        from theme_system import preview_theme
        with preview_theme({**self.editor.preview,'saturation_percent':0}):
            result = ui.themed_waterfall_pixels(pixels)
            with patch.object(ui,'np',None):
                self.assertEqual(ui.themed_waterfall_pixels(pixels),result)
            self.assertEqual(result[3::4],pixels[3::4])
            for i in range(0,len(result),4):
                self.assertEqual(len(set(result[i:i+3])),1)
            gray_signature = ui.waterfall_theme_signature()
        with preview_theme({**self.editor.preview,'saturation_percent':100}):
            self.assertNotEqual(ui.waterfall_theme_signature(),gray_signature)

    def test_muted_labels_are_a_dimmed_shade_of_selected_text_after_adjustments(self):
        from theme_system import normalize_theme
        for background,rgb in (([0,0,0,255],[240,160,80]),([255,255,255,255],[0,0,0])):
            raw = deepcopy(self.editor.preview)
            raw['colors'].update(background=background,text=rgb,secondary_text=[0,255,0])
            normalized = normalize_theme(raw,allow_default=True)
            muted = normalized['colors']['secondary_text']
            expected = [round(v*.65+bg*.35) for v,bg in zip(rgb,background)]
            self.assertEqual(muted,expected)
            self.assertNotEqual(muted,rgb)
        self.tap('colors:text'); self.tap('color:text:white')
        self.tap('color_intensity:smaller')
        text = self.editor.preview['colors']['text']
        bg = self.editor.preview['colors']['background']
        self.assertEqual(self.editor.preview['colors']['secondary_text'],
                         [round(v*.65+b*.35) for v,b in zip(text,bg)])

    def test_black_white_are_unlabelled_squares_and_rainbow_is_twenty_percent_thinner(self):
        from unittest.mock import Mock
        self.tap('colors:accent')
        self.editor.live_frame = Mock()
        with ExitStack() as stack:
            for name in ('draw_logical_rect','draw_logical_line','draw_logical_circle',
                         'draw_styled_button_frame','draw_styled_text_button'):
                stack.enter_context(patch.object(ui,name))
            shapes = stack.enter_context(patch.object(ui,'draw_logical_rounded_rect'))
            labels = stack.enter_context(patch.object(ui,'draw_text'))
            ui.draw_theme_panel(None,self.editor)
        self.assertTrue({'BLACK','WHITE'}.isdisjoint({call.args[3] for call in labels.call_args_list}))
        small = [call for call in shapes.call_args_list if 0<call.args[3]-call.args[1]<30]
        squares = [call for call in small if abs((call.args[2]-call.args[0])-(call.args[3]-call.args[1]))<.01]
        self.assertEqual(len(squares),4)
        for call in small:
            self.assertAlmostEqual(call.args[3]-call.args[1],24*.8)

    def test_black_white_selection_has_checkmark_and_named_status_even_when_dimmed(self):
        from unittest.mock import Mock
        self.editor.live_frame = Mock()
        self.tap('colors:accent')
        self.tap('color:accent:black'); self.tap('color:text:white')
        self.tap('color_intensity:smaller')
        with ExitStack() as stack:
            for name in ('draw_logical_rect','draw_logical_circle','draw_logical_rounded_rect',
                         'draw_styled_button_frame','draw_styled_text_button'):
                stack.enter_context(patch.object(ui,name))
            lines = stack.enter_context(patch.object(ui,'draw_logical_line'))
            labels = stack.enter_context(patch.object(ui,'draw_text'))
            ui.draw_theme_panel(None,self.editor)
        captions = [c.args[3] for c in labels.call_args_list]
        self.assertIn('Selected: Black · #000000',captions)
        self.assertIn('Selected: White · #FFFFFF',captions)
        # Two strokes per checkmark; Classic sliders add no line calls.
        self.assertEqual(len(lines.call_args_list),4)

    def test_accent_updates_both_passbands_preserving_alpha_and_saves(self):
        roles = ('passband_fill','passband_border','passband_center',
                 'home_passband_fill','home_passband_border','home_passband_center')
        before = deepcopy(self.editor.preview)
        self.tap('colors:accent'); self.tap('color:accent:rainbow')
        rgb = self.editor.preview['accent_rgb']
        for role in roles:
            self.assertEqual(self.editor.preview['colors'][role][:3],rgb,role)
            self.assertEqual(self.editor.preview['colors'][role][3:],before['colors'][role][3:])
        self.tap('color:save'); self.tap('save')
        loaded = ThemeLibrary(self.path).get('default')
        for role in roles:
            self.assertEqual(loaded['colors'][role][:3],rgb,role)

    def test_intensity_dims_selected_and_preset_text_and_cancel_reverts_it(self):
        for custom in (False,True):
            before = deepcopy(self.editor.preview)
            self.tap('colors:text')
            if custom:
                self.tap('color:text:white')
            for _ in range(10):
                self.tap('color_intensity:smaller')
            self.assertEqual(self.editor.preview['colors']['text'],[128,128,128])
            self.tap('border_intensity:larger')
            self.tap('color:cancel')
            self.assertEqual(self.editor.preview,before)
