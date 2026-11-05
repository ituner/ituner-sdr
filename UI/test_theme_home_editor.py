"""Approved preset → full-size HOME workflow, including non-visual state safety."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import kiwi_gl_display as ui
from theme_editor import ThemeEditor, theme_screen_boxes, inspector_box
from theme_system import BUILTIN_THEMES, DEFAULT_THEME, ThemeLibrary, apply_theme, new_theme, runtime_theme, preview_theme


class HomeThemeTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / 'themes.json'
        self.library = ThemeLibrary(self.path)
        self.library.activate('default')
        self.editor = ThemeEditor(self.library)
        self.editor.show()
        self.before = self.path.read_bytes()
        self.runtime = deepcopy(runtime_theme)

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def tap(self, action):
        boxes = theme_screen_boxes(self.editor)
        self.assertIn(action, boxes)
        a,b,c,d = boxes[action]
        self.editor.tap((a+c)/2, (b+d)/2)

    def test_sidebar_headers_and_gaps_do_not_dismiss_theme_views(self):
        for sidebar in ('left', 'right'):
            for screen in ('chooser', 'customize', 'colors', 'hidden'):
                self.editor.show()
                self.editor.entry_theme['sidebar'] = sidebar
                self.editor.draft['sidebar'] = sidebar
                if screen != 'chooser':
                    self.editor.fullscreen = True
                if screen == 'colors':
                    self.tap('colors:text')
                if screen == 'hidden':
                    self.tap('hide')
                before = (deepcopy(self.editor.preview), self.editor.fullscreen,
                          self.editor.fullscreen_controls, self.editor.overlay)
                x = 128 if sidebar == 'left' else 1152
                for y in (16, 48, 96, 224, 400, 620, 716):
                    with self.subTest(sidebar=sidebar, screen=screen, y=y):
                        self.editor.tap(x, y)
                        self.assertTrue(self.editor.open)
                        self.assertEqual((self.editor.preview, self.editor.fullscreen,
                                          self.editor.fullscreen_controls, self.editor.overlay), before)
                self.assertEqual(self.path.read_bytes(), self.before)

    def test_preset_tap_enters_full_size_customization_without_saving(self):
        self.tap('theme:green')
        self.assertTrue(self.editor.fullscreen)
        self.assertEqual(self.editor.selected_id, 'green')
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(runtime_theme, self.runtime)

    def test_only_approved_customizations_are_exposed(self):
        self.tap('theme:green')
        keys = set(theme_screen_boxes(self.editor))
        self.assertTrue({'colors:accent','colors:text','text:smaller','text:larger',
                         'option:straight','option:rounded',
                         'reset','back','save','hide','choose'} <= keys)
        self.assertFalse(any(k.startswith(('tab:','part:','filter:','meter:')) for k in keys))
        self.assertTrue(keys.isdisjoint({'colors','copy','delete','theme_name','hex_open','alpha_open'}))

    def test_reset_restores_accent_text_and_corners_without_applying(self):
        self.tap('theme:green')
        baseline = deepcopy(self.editor.preview)
        self.editor.choose_accent('mint'); self.tap('text:larger'); self.tap('option:rounded')
        self.assertNotEqual(self.editor.preview, baseline)
        self.tap('reset')
        self.assertEqual(self.editor.preview, baseline)
        self.assertTrue(self.editor.open)
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_hide_show_preserves_draft_and_background_taps_do_nothing(self):
        self.tap('theme:green'); self.tap('option:rounded')
        draft = deepcopy(self.editor.preview)
        self.tap('hide')
        self.assertEqual(set(theme_screen_boxes(self.editor)), {'show'})
        self.editor.tap(20, 20)
        self.assertFalse(self.editor.fullscreen_controls)
        self.assertEqual(self.editor.preview, draft)
        self.tap('show')
        self.assertTrue(self.editor.fullscreen_controls)
        self.assertEqual(self.editor.preview, draft)

    def test_cancel_restores_entry_even_after_resetting_another_preset(self):
        self.tap('theme:green'); self.tap('text:larger'); self.tap('reset'); self.tap('back')
        self.assertFalse(self.editor.open)
        self.assertEqual(self.editor.preview, self.editor.entry_theme)
        self.assertEqual(self.path.read_bytes(), self.before)
        self.assertEqual(runtime_theme, self.runtime)

    def test_choose_again_retains_each_preset_draft_and_back_retraces(self):
        self.tap('theme:green'); self.tap('option:rounded')
        green = deepcopy(self.editor.preview)
        self.editor.back()
        self.assertTrue(self.editor.open)
        self.assertFalse(self.editor.fullscreen)
        self.tap('theme:black-white'); self.tap('text:larger'); self.tap('choose')
        self.tap('theme:green')
        self.assertEqual(self.editor.preview, green)

    def test_apply_and_repeated_edits_keep_builtin_identity_without_copy_proliferation(self):
        factory = deepcopy(BUILTIN_THEMES)
        self.tap('theme:green'); self.editor.choose_accent('mint'); self.tap('option:rounded'); self.tap('text:larger')
        self.tap('save')
        self.assertFalse(self.editor.open)
        restarted = ThemeLibrary(self.path)
        self.assertEqual(restarted.active_id, 'green')
        self.assertEqual(restarted.get('green')['radius'], 8)
        self.assertEqual(restarted.get('green')['text_scale_percent'], 105)
        self.assertEqual(restarted.themes, [])
        self.assertEqual(BUILTIN_THEMES, factory)
        self.editor = ThemeEditor(restarted); self.editor.show(); self.tap('theme:green')
        self.tap('text:larger'); self.tap('save')
        document = json.loads(self.path.read_text())
        self.assertEqual(set(document['builtin_overrides']), {'green'})
        self.assertEqual(document['themes'], [])
        self.assertEqual(ThemeLibrary(self.path).get('green')['text_scale_percent'], 110)

    def test_reset_reopened_builtin_uses_factory_not_last_saved_edits(self):
        self.tap('theme:green'); self.tap('option:rounded'); self.tap('text:larger'); self.tap('save')
        self.editor.show(); self.tap('theme:green'); self.tap('reset')
        self.assertEqual(self.editor.preview['radius'], 0)
        self.assertEqual(self.editor.preview['text_scale_percent'], 100)
        self.tap('back')
        self.assertEqual(ThemeLibrary(self.path).get('green')['radius'], 8)

    def test_save_error_retains_visible_draft_and_rolls_back_active_library(self):
        self.tap('theme:green'); self.tap('option:rounded')
        draft = deepcopy(self.editor.preview)
        with patch.object(self.library,'save',side_effect=OSError('Disk full')):
            self.tap('save')
        self.assertTrue(self.editor.open)
        self.assertTrue(self.editor.fullscreen_controls)
        self.assertEqual(self.editor.preview,draft)
        self.assertIn('Disk full',self.editor.error)
        self.assertEqual(self.library.active_id,'default')
        self.assertEqual(self.path.read_bytes(),self.before)
        self.assertEqual(runtime_theme,self.runtime)
        self.tap('save')
        self.assertEqual(ThemeLibrary(self.path).active_id,'green')

    def test_theme_choice_preserves_operation_but_recolors_spectrum_and_waterfall(self):
        legacy = new_theme('Existing left layout')
        legacy['sidebar']='left'; legacy['units']='metric'
        legacy['colors']['waterfall_low']=[5,12,18]
        legacy['colors']['waterfall_high']=[230,201,96]
        legacy['colors']['spectrum_line']=[100,170,210,208]
        self.library.upsert(legacy,smeter_style='linear_orange')
        self.editor.show()
        entry=deepcopy(self.editor.entry_theme)
        pixels=bytes([20,40,80,255,125,170,200,255])
        expected=bytes([235,215,175,255,130,85,55,255])
        self.tap('theme_previous')
        self.tap('theme:straight-inverted')
        for key in ('sidebar','units','smeter_style'):
            self.assertEqual(self.editor.preview[key],entry[key])
        for key in entry['colors']:
            if key.startswith(('spectrum_','waterfall_')):
                self.assertEqual(self.editor.preview['colors'][key],BUILTIN_THEMES['straight-inverted']['colors'][key])
        with preview_theme(self.editor.preview):
            self.assertEqual(ui.themed_waterfall_pixels(pixels),expected)
        self.tap('save')
        self.assertEqual(ui.themed_waterfall_pixels(pixels),expected)
        self.assertIsNotNone(ThemeLibrary(self.path).get(legacy['id']))

    def test_accent_changes_neither_warning_colors_nor_signal_colors(self):
        self.tap('theme:green')
        before=deepcopy(self.editor.preview)
        self.editor.choose_accent('amber')
        for key in ('ready','waiting','danger','danger_border','spectrum_line','waterfall_high'):
            self.assertEqual(self.editor.preview['colors'][key],before['colors'][key])
        self.assertNotEqual(self.editor.preview['colors']['frequency'],before['colors']['frequency'])
        self.editor.choose_accent('original')
        self.assertEqual(self.editor.preview,before)

    def test_targets_fit_both_sides_without_overlap_and_keep_touch_height(self):
        for side in ('left','right'):
            self.editor.entry_theme['sidebar']=side
            for state in ('chooser','editor','hidden'):
                self.editor.fullscreen=state!='chooser'
                self.editor.fullscreen_controls=state!='hidden'
                boxes=theme_screen_boxes(self.editor)
                for name,a in boxes.items():
                    self.assertTrue(0<=a[0]<a[2]<=1280 and 0<=a[1]<a[3]<=800,name)
                    self.assertGreaterEqual(a[3]-a[1],56,name)
                for i,(name,a) in enumerate(boxes.items()):
                    for other,b in list(boxes.items())[i+1:]:
                        self.assertFalse(a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1],(name,other))
                for a in boxes.values():
                    self.assertTrue(a[0]>=256 if side=='left' else a[2]<=1024)

    def test_draws_complete_home_and_restores_runtime_after_themed_controls(self):
        self.tap('theme:green')
        self.editor.live_frame=Mock()
        before=deepcopy(runtime_theme)
        names=('draw_text','draw_logical_rect','draw_logical_line','draw_logical_circle',
               'draw_logical_rounded_rect','draw_styled_text_button','draw_styled_two_line_button',
               'draw_styled_button_frame')
        with ExitStack() as stack:
            for name in names: stack.enter_context(patch.object(ui,name))
            ui.draw_theme_panel(None,self.editor)
        self.editor.live_frame.draw.assert_called_once_with((0,0,1280,800))
        self.assertEqual(runtime_theme,before)

    def test_customize_panel_is_taller_with_space_between_control_sections(self):
        self.tap('theme:green')
        a,b,c,d=inspector_box(self.editor)
        self.assertGreaterEqual(d-b,480)
        boxes=theme_screen_boxes(self.editor)
        self.assertNotIn('color_intensity',boxes)
        self.assertNotIn('border_intensity',boxes)
        self.assertGreaterEqual(boxes['reset'][1]-boxes['text:reset'][3],96)
        for box in boxes.values():
            self.assertTrue(a<=box[0]<box[2]<=c and b<=box[1]<box[3]<=d)

    def test_customize_panel_previews_its_own_palette_radius_and_text_scale(self):
        self.tap('theme:green');self.editor.choose_accent('mint');self.tap('option:rounded')
        self.tap('text:larger');self.tap('text:larger')
        self.editor.live_frame=Mock()
        seen=[]
        def observe(*args,**kwargs):
            seen.append((runtime_theme['text_scale_percent'],ui.APP_UI_STYLE.palette.text))
        before=deepcopy(runtime_theme)
        with ExitStack() as stack:
            for name in ('draw_logical_rect','draw_logical_line','draw_logical_circle',
                         'draw_styled_button_frame','draw_styled_two_line_button'):
                stack.enter_context(patch.object(ui,name))
            background=stack.enter_context(patch.object(ui,'draw_logical_rounded_rect'))
            buttons=stack.enter_context(patch.object(ui,'draw_styled_text_button'))
            stack.enter_context(patch.object(ui,'draw_text',side_effect=observe))
            ui.draw_theme_panel(None,self.editor)
        panel=next(call for call in background.call_args_list if call.args[:4]==inspector_box(self.editor))
        self.assertEqual(panel.args[4],8)
        self.assertEqual(tuple(panel.args[5][:3]),tuple(self.editor.preview['colors']['background'][:3]))
        self.assertTrue(200<=panel.args[5][3]<255)
        self.assertTrue(seen)
        self.assertTrue(all(scale==110 and tuple(color)==tuple(self.editor.preview['colors']['text']) for scale,color in seen))
        self.assertTrue(all(c.kwargs['style'].radius==8 and c.kwargs['style'].palette.text==tuple(self.editor.preview['colors']['text']) for c in buttons.call_args_list))
        self.assertEqual(runtime_theme,before)

    def test_light_popup_intensity_values_use_readable_theme_text(self):
        self.editor.select_theme('straight-inverted')
        self.tap('colors:accent')
        self.editor.live_frame=Mock()
        with ExitStack() as stack:
            for name in ('draw_logical_rect','draw_logical_line','draw_logical_circle',
                         'draw_logical_rounded_rect','draw_styled_button_frame',
                         'draw_styled_text_button','draw_styled_two_line_button'):
                stack.enter_context(patch.object(ui,name))
            text=stack.enter_context(patch.object(ui,'draw_text'))
            ui.draw_theme_panel(None,self.editor)
        values=[c.args[4] for c in text.call_args_list if c.args[3] in ('100%','25%')]
        self.assertEqual(len(values),3)
        self.assertTrue(all(tuple(c)==tuple(self.editor.preview['colors']['text']) for c in values))

    def test_theme_list_and_customize_share_position_and_floating_theme_style(self):
        self.tap('theme:green');self.tap('option:rounded')
        self.editor.live_frame=Mock()
        for side in ('left','right'):
            self.editor.entry_theme['sidebar']=side
            for fullscreen in (False,True):
                self.editor.fullscreen=fullscreen
                with ExitStack() as stack:
                    for name in ('draw_logical_rect','draw_logical_line','draw_logical_circle',
                                 'draw_styled_button_frame','draw_styled_text_button',
                                 'draw_styled_two_line_button','draw_text'):
                        stack.enter_context(patch.object(ui,name))
                    shapes=stack.enter_context(patch.object(ui,'draw_logical_rounded_rect'))
                    ui.draw_theme_panel(None,self.editor)
                panels=[c for c in shapes.call_args_list if c.args[:4]==inspector_box(self.editor)]
                self.assertEqual(len(panels),1)
                self.assertEqual(panels[0].args[4],8)
                self.assertEqual(tuple(panels[0].args[5]),(*self.editor.preview['colors']['background'][:3],228))
                for box in theme_screen_boxes(self.editor).values():
                    a,b,c,d=inspector_box(self.editor)
                    self.assertTrue(a<=box[0]<box[2]<=c and b<=box[1]<box[3]<=d)

    def test_largest_text_keeps_passband_title_clear_of_numeric_readout(self):
        theme=deepcopy(DEFAULT_THEME)
        theme['text_scale_percent']=120
        cache=ui.TextCache()
        bounds={}
        def record(cache,x,y,caption,color,size,x_scale=1.0,bold=False,mono=False,anchor='lt',**kwargs):
            width=cache.font(size,bold=bold,mono=mono,family=kwargs.get('family')).size(caption)[0]*x_scale
            left=x-width/2 if 'c' in anchor else x-width if 'r' in anchor else x
            bounds[caption]=(left,left+width)
        def ordinary(cache,x,y,caption,color,size,bold=False,mono=False,anchor='lt',**kwargs):
            record(cache,x,y,caption,color,size,1.0,bold,mono,anchor,**kwargs)
        with preview_theme(theme), ExitStack() as stack:
            for name in ('draw_logical_rect','draw_section_divider','draw_logical_line',
                         'draw_logical_area','draw_logical_polyline'):
                stack.enter_context(patch.object(ui,name))
            stack.enter_context(patch.object(ui,'draw_text',side_effect=ordinary))
            stack.enter_context(patch.object(ui,'draw_text_scaled_x',side_effect=record))
            ui.draw_lcd_home_bandwidth(cache,-4900,4900,box=(1034,288,1270,384))
        self.assertLessEqual(bounds['PASSBAND'][1]+8,bounds['9.8 kHz'][0])
        cache.close()


if __name__=='__main__': unittest.main()
