"""Font presets preview, persist and render without changing frequency faces."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import kiwi_gl_display as ui
from theme_editor import ThemeEditor, theme_screen_boxes
from theme_system import ThemeLibrary, DEFAULT_THEME, apply_theme, normalize_theme, preview_theme, runtime_theme


class ThemeFontTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'themes.json'
        self.editor = ThemeEditor(ThemeLibrary(self.path))
        self.editor.show(); self.editor.select_theme('default')

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.temp.cleanup()

    def tap(self,key):
        a,b,c,d = theme_screen_boxes(self.editor)[key]
        self.editor.tap((a+c)/2,(b+d)/2)

    def test_preview_does_not_save_and_cancel_restores_entry(self):
        before = deepcopy(runtime_theme)
        self.tap('font:instrument')
        self.assertEqual(self.editor.preview['font_style'],'instrument')
        with preview_theme(self.editor.preview):
            self.assertEqual(ui.APP_UI_STYLE.button.font_family,'theme-style:instrument')
        self.assertEqual(runtime_theme,before)
        self.assertFalse(self.path.exists())
        self.tap('back')
        self.assertEqual(self.editor.preview,self.editor.entry_theme)

    def test_apply_restart_and_reset(self):
        self.tap('font:clean'); self.tap('save')
        self.editor = ThemeEditor(ThemeLibrary(self.path))
        self.editor.show(); self.editor.select_theme('default')
        self.assertEqual(self.editor.preview['font_style'],'clean')
        self.tap('reset')
        self.assertEqual(self.editor.preview['font_style'],'current')
        self.assertEqual(ThemeLibrary(self.path).get('default')['font_style'],'clean')

    def test_unknown_font_falls_back_to_current(self):
        for value in ('missing',None,42,{},[]):
            self.assertEqual(normalize_theme({**DEFAULT_THEME,'font_style':value},allow_default=True)['font_style'],'current')

    def test_font_choices_keep_frequency_and_monospace_readouts_unchanged(self):
        from theme_fonts import resolve_font_path
        for style in ('current','clean','instrument','classic','readable'):
            self.assertIsNone(resolve_font_path(style,family='Oxanium'))
            self.assertIsNone(resolve_font_path(style,mono=True))
        for style in ('clean','instrument','classic','readable'):
            for bold in (False,True):
                path = resolve_font_path(style,family='Liberation Sans',bold=bold)
                self.assertTrue(Path(path).is_file())

    def test_font_cache_uses_selected_bundled_file_and_reuses_previous_face(self):
        cache = ui.TextCache()
        with patch.object(ui.pygame.font,'Font') as font:
            self.tap('font:clean')
            with preview_theme(self.editor.preview):
                clean = cache.font(14,family='Liberation Sans')
            self.assertIn('LiberationSans',str(font.call_args.args[0]))
            self.tap('font:instrument')
            with preview_theme(self.editor.preview):
                cache.font(14,family='Liberation Sans')
            self.assertIn('LiberationMono',str(font.call_args.args[0]))
            self.tap('font:clean')
            with preview_theme(self.editor.preview):
                self.assertIs(cache.font(14,family='Liberation Sans'),clean)
            self.assertEqual(font.call_count,2)

    def test_picker_buttons_have_equal_width_and_fit_both_sidebar_sides(self):
        from theme_editor import inspector_box
        for side in ('left','right'):
            self.editor.entry_theme['sidebar'] = side
            a,b,c,d = inspector_box(self.editor)
            boxes = theme_screen_boxes(self.editor)
            for style in ('current','clean','instrument','classic','readable'):
                x,y,z,w = boxes['font:'+style]
                self.assertEqual(z-x,boxes['save'][2]-boxes['save'][0])
                self.assertTrue(a<=x<z<=c and b<=y<w<=d)
