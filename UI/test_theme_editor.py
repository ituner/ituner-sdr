"""Regressions for simplified appearance editing and retained legacy presets."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from theme_editor import ThemeEditor, ACCENTS, accent_colors, contrast, theme_screen_boxes
from theme_system import (BUILTIN_THEMES, DEFAULT_THEME, ThemeLibrary, apply_theme,
                          new_theme, preview_theme, runtime_theme)
from ui_style import APP_UI_STYLE


class ThemeEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory()
        self.path=Path(self.directory.name)/'themes.json'
        self.library=ThemeLibrary(self.path)
        self.editor=ThemeEditor(self.library)
        self.editor.show()

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def tap(self,key):
        a,b,c,d=theme_screen_boxes(self.editor)[key]
        self.editor.tap((a+c)/2,(b+d)/2)

    def test_all_builtin_presets_remain_available(self):
        self.assertEqual([t['id'] for t in self.editor.themes],list(BUILTIN_THEMES))
        self.assertEqual(self.editor.page_count,1)

    def test_saved_themes_remain_reachable_and_update_in_place(self):
        saved=new_theme('My existing theme')
        self.library.upsert(saved)
        self.editor.show()
        self.tap('theme:'+saved['id'])
        self.tap('option:rounded'); self.tap('text:larger'); self.tap('save')
        restarted=ThemeLibrary(self.path)
        self.assertEqual(len(restarted.themes),1)
        self.assertEqual(restarted.active_id,saved['id'])
        self.assertEqual(restarted.get(saved['id'])['text_scale_percent'],105)

    def test_pagination_neither_selects_nor_applies_themes(self):
        for i in range(9): self.library.upsert(new_theme('Saved '+str(i)))
        self.editor.show()
        draft=deepcopy(self.editor.preview)
        before=self.path.read_bytes()
        while self.editor.page > 0: self.tap('theme_previous')
        while self.editor.page + 1 < self.editor.page_count: self.tap('theme_next')
        self.assertEqual(self.editor.preview,draft)
        self.assertEqual(self.path.read_bytes(),before)

    def test_pagination_buttons_remain_visible_on_single_first_and_last_pages(self):
        first = theme_screen_boxes(self.editor)
        self.assertIn('theme_previous', first)
        self.assertIn('theme_next', first)
        draft = deepcopy(self.editor.preview)
        self.editor.status = 'Unchanged'
        self.tap('theme_previous'); self.tap('theme_next')
        self.assertEqual(self.editor.page, 0)
        self.assertEqual(self.editor.status, 'Unchanged')
        self.assertEqual(self.editor.preview, draft)
        self.assertFalse(self.path.exists())
        for i in range(5): self.library.upsert(new_theme('Page '+str(i)))
        self.editor.show()
        for page in (0, self.editor.page_count - 1):
            self.editor.page = page
            boxes = theme_screen_boxes(self.editor)
            for key in ('theme_previous','theme_next'):
                self.assertEqual(boxes[key], first[key])
            self.tap('theme_previous' if page == 0 else 'theme_next')
            self.assertEqual(self.editor.page, page)

    def test_text_size_bounds_and_normal_value(self):
        self.tap('theme:green')
        for _ in range(20): self.tap('text:larger')
        self.assertEqual(self.editor.preview['text_scale_percent'],120)
        for _ in range(40): self.tap('text:smaller')
        self.assertEqual(self.editor.preview['text_scale_percent'],80)
        self.tap('text:reset')
        self.assertEqual(self.editor.preview['text_scale_percent'],100)

    def test_corner_choice_reaches_runtime_style_only_inside_preview_context(self):
        self.tap('theme:green'); self.tap('option:rounded')
        with preview_theme(self.editor.preview): self.assertEqual(APP_UI_STYLE.button.radius,8)
        self.assertEqual(APP_UI_STYLE.button.radius,0)
        self.tap('option:straight')
        with preview_theme(self.editor.preview): self.assertEqual(APP_UI_STYLE.button.radius,0)

    def test_touch_rectangles_do_not_move_with_text_size_or_corners(self):
        self.tap('theme:green')
        boxes=theme_screen_boxes(self.editor)
        self.tap('text:larger'); self.tap('option:rounded')
        self.assertEqual(theme_screen_boxes(self.editor),boxes)

    def test_cancel_does_not_create_a_theme_file_on_first_use(self):
        self.tap('theme:green'); self.tap('option:rounded'); self.tap('back')
        self.assertFalse(self.path.exists())
        self.assertEqual(runtime_theme['id'],'default')

    def test_builtin_get_does_not_expose_mutable_factory_or_saved_data(self):
        self.tap('theme:green'); self.tap('option:rounded'); self.tap('save')
        theme=self.library.get('green')
        theme['colors']['text'][0]=0
        self.assertNotEqual(self.library.get('green')['colors']['text'][0],0)
        self.assertNotEqual(BUILTIN_THEMES['green']['colors']['text'][0],0)

    def test_each_accent_has_readable_frequency_and_paired_focus_text(self):
        for preset in BUILTIN_THEMES.values():
            for key,_name,_rgb in ACCENTS[1:]:
                colors=accent_colors(preset,key)
                self.assertGreaterEqual(contrast(colors['frequency'],preset['colors']['sidebar']),4.5)
                self.assertGreaterEqual(contrast(colors['focus_text'],colors['focus']),4.5)
                self.assertGreaterEqual(contrast((0,0,0),colors['pressed_surface']),4.5)

    def test_multiple_preset_overrides_survive_an_unrelated_meter_update(self):
        for identifier in ('green','black-white'):
            self.editor.show(); self.editor.select_theme(identifier)
            self.tap('option:rounded'); self.tap('save')
        self.library.set_smeter_style('linear_orange')
        restarted=ThemeLibrary(self.path)
        for identifier in ('green','black-white'):
            self.assertEqual(restarted.get(identifier)['radius'],8)
        self.assertEqual(restarted.smeter_style,'linear_orange')


if __name__=='__main__': unittest.main()
