"""User journeys for the preview-first Themes screen."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from smeter_styles import METER_STYLES
from theme_editor import (ThemeEditor, theme_screen_boxes, COLOR_GROUPS, CARDS_PER_PAGE,
                          METER_CARDS_PER_PAGE, FULLSCREEN_BOX)
from theme_system import (BUILTIN_THEME_IDS, DEFAULT_THEME, DEFAULT_THEME_ID,
                          ThemeLibrary, apply_theme, new_theme, runtime_theme)


class ThemeEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / 'themes.json'
        self.library = ThemeLibrary(self.path)
        self.original = new_theme('My Radio')
        self.original['colors']['frequency'] = [245, 180, 40]
        self.original['smeter_style'] = 'flex_vintage_hd_white'
        self.library.upsert(self.original)
        self.library.set_smeter_style(self.original["smeter_style"])
        self.editor = ThemeEditor(self.library)
        self.editor.show()
        self.initial_bytes = self.path.read_bytes()
        self.initial_runtime = deepcopy(runtime_theme)

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def tap(self, action):
        if action.startswith(('theme:', 'meter:')):
            prefix, identifier = action.split(':', 1)
            items = [t['id'] for t in self.editor.themes] if prefix == 'theme' else self.editor.meter_ids
            count = CARDS_PER_PAGE if prefix == 'theme' else METER_CARDS_PER_PAGE
            target = items.index(identifier) // count
            current = lambda: self.editor.page if prefix == 'theme' else self.editor.meter_page
            while current() != target:
                self.tap(prefix + ('_next' if current() < target else '_previous'))
        boxes = theme_screen_boxes(self.editor)
        self.assertIn(action, boxes)
        box = boxes[action]
        self.editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    def meter(self, identifier):
        self.tap('tab:meters')
        self.tap('filter:all')
        self.tap('meter:' + identifier)

    def test_open_shows_actual_saved_theme_and_selected_meter(self):
        self.assertEqual(self.editor.preview, self.library.get(self.library.active_id))
        self.tap('tab:meters')
        self.assertIn('meter:flex_vintage_hd_white', theme_screen_boxes(self.editor))
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)

    def test_selecting_theme_previews_without_applying_or_writing(self):
        self.tap('theme:green')
        self.assertEqual(self.editor.preview['colors'], self.library.get('green')['colors'])
        self.assertEqual(self.editor.preview['smeter_style'], 'flex_vintage_hd_white')
        self.assertEqual(runtime_theme, self.initial_runtime)
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)

    def test_meter_selection_previews_without_applying_or_writing(self):
        self.meter('linear_orange')
        self.assertEqual(self.editor.preview['smeter_style'], 'linear_orange')
        self.assertEqual(runtime_theme, self.initial_runtime)
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)

    def test_apply_saves_meter_and_closes_directly_to_home(self):
        self.meter('linear_orange')
        self.tap('save')
        self.assertFalse(self.editor.open)
        self.assertEqual(self.editor.exit_surface, 'home')
        saved = ThemeLibrary(self.path)
        self.assertEqual(saved.get(saved.active_id)['smeter_style'], 'linear_orange')
        self.assertEqual(saved.active_id, self.original['id'])
        self.assertEqual(len(saved.themes), 1)

    def test_apply_from_theme_tab_works_without_entering_an_editor(self):
        self.tap('theme:black-white')
        self.tap('save')
        self.assertFalse(self.editor.open)
        self.assertEqual(self.editor.exit_surface, 'home')
        current = self.library.get(self.library.active_id)
        self.assertEqual(current['colors'], self.library.get('black-white')['colors'])
        self.assertEqual(current['smeter_style'], self.original['smeter_style'])

    def test_no_change_apply_returns_home_without_creating_a_copy(self):
        self.tap('save')
        self.assertFalse(self.editor.open)
        self.assertEqual(len(self.library.themes), 1)
        self.assertEqual(self.library.active_id, self.original['id'])

    def test_cancel_discards_all_preview_changes_in_one_tap(self):
        self.meter('oe3ide_eye_plain')
        self.tap('tab:themes')
        self.tap('theme:straight-inverted')
        self.tap('tab:customize')
        self.tap('option:left')
        self.tap('colors')
        self.tap('back')
        self.assertFalse(self.editor.open)
        self.assertEqual(self.editor.exit_surface, 'home')
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)
        self.assertEqual(runtime_theme, self.initial_runtime)

    def test_filtering_and_arrows_preview_without_saving_or_changing_live_settings(self):
        self.tap('tab:meters')
        for category in ('digital', 'analog', 'eye', 'all'):
            self.tap('filter:' + category)
            for _ in range(self.editor.meter_page_count + 2):self.tap('meter_next')
            self.assertEqual(self.editor.meter_page, self.editor.meter_page_count - 1)
            for _ in range(self.editor.meter_page_count + 2):self.tap('meter_previous')
            self.assertEqual(self.editor.meter_page, 0)
            self.assertIn(self.editor.preview['smeter_style'], self.editor.meter_ids[:METER_CARDS_PER_PAGE])
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)
        self.assertEqual(runtime_theme, self.initial_runtime)

    def test_filters_cover_every_meter_once_and_make_original_led_easy_to_find(self):
        self.tap('tab:meters')
        categories = []
        for category in ('digital', 'analog', 'eye'):
            self.tap('filter:' + category)
            categories.append(set(self.editor.meter_ids))
        self.assertEqual(set.union(*categories), set(METER_STYLES))
        self.assertFalse(categories[0] & categories[1] | categories[1] & categories[2] | categories[0] & categories[2])
        self.tap('filter:digital')
        self.assertIn('meter:led', theme_screen_boxes(self.editor))
        self.tap('meter:linear_orange')
        self.assertEqual(self.editor.preview['smeter_style'], 'linear_orange')

    def test_all_meter_cards_are_reachable_without_changing_palette(self):
        self.tap('tab:meters')
        self.tap('filter:all')
        colors = deepcopy(self.editor.preview['colors'])
        for _ in range(self.editor.meter_page):self.tap('meter_previous')
        seen = set()
        for _ in range(self.editor.meter_page_count):
            for action in theme_screen_boxes(self.editor):
                if action.startswith('meter:'):
                    self.tap(action)
                    seen.add(action.split(':')[1])
            self.tap('meter_next')
        self.assertEqual(seen, set(METER_STYLES))
        self.assertEqual(self.editor.preview['colors'], colors)

    def test_switching_tabs_keeps_the_same_preview(self):
        self.meter('linear_orange')
        expected = deepcopy(self.editor.preview)
        for tab in ('themes', 'customize', 'meters'):
            self.tap('tab:' + tab)
            self.assertEqual(self.editor.preview, expected)

    def test_choosing_another_palette_keeps_newly_chosen_meter(self):
        self.meter('led')
        self.tap('tab:themes')
        self.tap('theme:green')
        self.assertEqual(self.editor.preview['smeter_style'], 'led')

    def test_saved_theme_card_preserves_pending_meter_and_restores_appearance(self):
        self.meter('led')
        self.tap('tab:themes')
        self.tap('theme:' + self.original['id'])
        expected = {**self.library.get(self.original['id']), 'smeter_style': 'led'}
        self.assertEqual(self.editor.preview, expected)

    def test_builtin_meter_change_with_existing_new_theme_creates_no_copy(self):
        self.library.upsert(new_theme())
        self.library.activate(DEFAULT_THEME_ID)
        self.editor.show('meters')
        self.tap('filter:digital')
        self.tap('meter:linear_orange')
        self.tap('save')
        self.assertFalse(self.editor.open, self.editor.error)
        self.assertEqual(len(self.library.themes), 2)
        self.assertEqual(self.library.active_id, DEFAULT_THEME_ID)
        names = [t['name'].casefold() for t in self.library.themes]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(self.library.get(self.library.active_id)['smeter_style'], 'linear_orange')

    def test_builtin_without_modifications_does_not_create_custom_theme(self):
        self.library.activate(DEFAULT_THEME_ID)
        self.editor.show()
        self.tap('save')
        self.assertEqual(self.library.active_id, DEFAULT_THEME_ID)
        self.assertEqual(len(self.library.themes), 1)

    def test_failed_save_preserves_preview_and_current_settings_for_retry(self):
        self.meter('linear_orange')
        with patch.object(self.library, 'save', side_effect=OSError('Storage unavailable')):
            self.tap('save')
        self.assertTrue(self.editor.open)
        self.assertIn('Storage unavailable', self.editor.error)
        self.assertEqual(self.editor.preview['smeter_style'], 'linear_orange')
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)
        self.assertEqual(runtime_theme, self.initial_runtime)
        self.tap('save')
        self.assertFalse(self.editor.open)

    def test_customization_is_preview_only_until_applied(self):
        self.tap('tab:customize')
        self.tap('option:left')
        self.tap('option:rounded')
        self.tap('text:larger')
        self.tap('option:metric')
        self.assertEqual(runtime_theme, self.initial_runtime)
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)
        self.tap('save')
        saved = self.library.get(self.library.active_id)
        self.assertEqual((saved['sidebar'], saved['radius'], saved['text_scale_percent'], saved['units']), ('left', 8, 105, 'metric'))

    def test_text_size_controls_clamp_and_reset(self):
        self.tap('tab:customize')
        for _ in range(12):self.tap('text:larger')
        self.assertEqual(self.editor.preview['text_scale_percent'], 120)
        for _ in range(15):self.tap('text:smaller')
        self.assertEqual(self.editor.preview['text_scale_percent'], 80)
        self.tap('text:reset')
        self.assertEqual(self.editor.preview['text_scale_percent'], 100)

    def test_rename_can_cancel_or_save_without_affecting_current_theme(self):
        self.tap('tab:customize')
        self.tap('theme_name');self.tap('name:CLEAR');self.tap('name:a');self.tap('name:CANCEL')
        self.assertEqual(self.editor.preview['name'], 'My Radio')
        self.tap('theme_name');self.tap('name:CLEAR')
        self.tap('name:CAPS')
        for key in 'ORANGE':self.tap('name:' + key)
        self.tap('name:DONE');self.tap('save')
        self.assertEqual(self.library.get(self.library.active_id)['name'], 'ORANGE')
        self.assertEqual(self.library.active_id, self.original['id'])

    def test_name_keyboard_supports_lowercase_symbols_and_back(self):
        self.tap('tab:customize');self.tap('theme_name');self.tap('name:CLEAR')
        self.tap('name:a');self.tap('name:MODE');self.tap('name:1')
        self.tap('name:CAPS');self.tap('name:?')
        self.assertEqual(self.editor.buffer,'a1?')
        self.tap('name:MODE');self.tap('name:BACK')
        self.assertEqual(self.editor.buffer,'a1')
        self.tap('name:CANCEL')
        self.assertIsNone(self.editor.overlay)
        self.assertEqual(self.editor.preview['name'],'My Radio')

    def test_name_keyboard_has_no_invisible_sidebar_cancel_target(self):
        self.tap('tab:customize');self.tap('theme_name');self.tap('name:CLEAR')
        self.tap('name:a')
        self.assertNotIn('name:rail_cancel', theme_screen_boxes(self.editor))
        # This was inside the old right-rail BACK button, below the keyboard's
        # visible command row. It must not dismiss an editor after rail removal.
        self.editor.tap(1250, 780)
        self.assertEqual(self.editor.overlay, 'name')
        self.assertEqual(self.editor.buffer, 'a')
        self.tap('name:CANCEL')
        self.assertIsNone(self.editor.overlay)
        self.assertEqual(self.editor.preview['name'], 'My Radio')

    def test_duplicate_explicit_name_is_an_inline_error_without_closing(self):
        self.library.upsert(new_theme('Other'))
        self.editor.draft['name'] = 'OTHER'
        self.tap('save')
        self.assertTrue(self.editor.open)
        self.assertIn('already exists', self.editor.error)

    def test_make_copy_preserves_original_and_names_copy_automatically(self):
        self.tap('tab:customize');self.tap('copy')
        self.meter('linear_orange');self.tap('save')
        self.assertFalse(self.editor.open)
        original = next(t for t in self.library.themes if t['id'] == self.original['id'])
        self.assertNotIn('smeter_style', original)
        self.assertEqual(original['colors'], self.original['colors'])
        self.assertNotEqual(self.library.active_id, self.original['id'])
        self.assertEqual(self.library.smeter_style, 'linear_orange')
        self.assertEqual(len(self.library.themes), 2)

    def test_all_palette_parts_remain_editable(self):
        self.tap('tab:customize');self.tap('colors')
        seen = set()
        for _ in COLOR_GROUPS:
            for _ in range((len(self.editor.family_keys) + 3) // 4):
                for action in theme_screen_boxes(self.editor):
                    if action.startswith('part:'):
                        self.tap(action);seen.add(self.editor.color_key)
                self.tap('part_next')
            self.tap('group_next')
        self.assertEqual(seen, set(self.editor.preview['colors']))

    def test_color_entry_preserves_alpha_and_cancel_does_not_change_color(self):
        self.tap('tab:customize');self.tap('colors')
        before = list(self.editor.current_color)
        self.tap('hex_open')
        for key in 'AABBCC':self.tap('hex:' + key)
        self.tap('hex:CANCEL')
        self.assertEqual(self.editor.current_color, before)
        self.tap('hex_open')
        for key in 'AABBCC':self.tap('hex:' + key)
        self.tap('hex:APPLY')
        self.assertEqual(self.editor.current_color, [170, 187, 204, *before[3:]])
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)

    def test_transparency_validation_keeps_overlay_open_for_correction(self):
        self.tap('tab:customize');self.tap('colors');self.tap('alpha_open')
        for key in '101':self.tap('alpha:' + key)
        self.tap('alpha:DONE')
        self.assertEqual(self.editor.overlay, 'alpha')
        self.tap('alpha:CLEAR');self.tap('alpha:5');self.tap('alpha:0');self.tap('alpha:DONE')
        self.assertIsNone(self.editor.overlay)
        self.assertEqual(self.editor.current_color[3], 128)

    def test_delete_requires_confirmation_and_names_only_selected_saved_theme(self):
        self.tap('tab:customize');self.tap('delete');self.tap('delete_cancel')
        self.assertIsNotNone(self.library.get(self.original['id']))
        self.tap('delete');self.tap('delete_confirm')
        self.assertIsNone(self.library.get(self.original['id']))
        self.assertEqual(self.editor.tab, 'themes')
        self.assertTrue(self.editor.open)

    def test_visible_touch_targets_stay_inside_screen_and_do_not_overlap(self):
        def check():
            boxes = theme_screen_boxes(self.editor)
            for name, b in boxes.items():
                self.assertTrue(0 <= b[0] < b[2] <= 1280 and 0 <= b[1] < b[3] <= 800, name)
            for index, (name, a) in enumerate(boxes.items()):
                for other, b in list(boxes.items())[index + 1:]:
                    self.assertFalse(min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]), (name, other))
        for tab in ('themes', 'meters', 'customize'):
            self.tap('tab:' + tab);check()
        self.tap('colors');check()
        for overlay in ('hex_open', 'alpha_open'):
            self.tap(overlay);check();self.editor.overlay = None
        self.tap('appearance');self.tap('theme_name');check()

    def test_theme_cards_are_compact_and_paging_aligns_with_fullscreen_preview(self):
        boxes = theme_screen_boxes(self.editor)
        cards = [box for name, box in boxes.items() if name.startswith('theme:')]
        self.assertTrue(cards)
        self.assertTrue(all(box[3] - box[1] == 72 for box in cards))
        for name in ('theme_previous', 'theme_next'):
            self.assertEqual(boxes[name][1:4:2], FULLSCREEN_BOX[1:4:2])

        self.tap('tab:meters')
        boxes = theme_screen_boxes(self.editor)
        meter_bottom = max(box[3] for name, box in boxes.items() if name.startswith('meter:'))
        self.assertLess(meter_bottom, boxes['meter_previous'][1])

    def test_fullscreen_continue_and_hide_controls_preserve_unsaved_draft(self):
        self.meter('flex_vintage_hd')
        draft = deepcopy(self.editor.preview)
        self.tap('fullscreen')
        self.assertTrue(self.editor.fullscreen)
        self.editor.tap(100, 100)
        self.assertFalse(self.editor.fullscreen_controls)
        self.assertEqual(theme_screen_boxes(self.editor), {})
        self.editor.tap(100, 100)
        self.assertTrue(self.editor.fullscreen_controls)
        self.tap('continue')
        self.assertFalse(self.editor.fullscreen)
        self.assertEqual(self.editor.preview, draft)
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)
        self.assertEqual(runtime_theme, self.initial_runtime)
        self.tap('back')
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)

    def test_fullscreen_save_returns_home_and_keeps_meter_independent(self):
        self.meter('linear_orange')
        self.tap('preview_image')
        self.tap('save')
        self.assertFalse(self.editor.open)
        self.assertEqual(self.editor.exit_surface, 'home')
        self.assertEqual(self.library.smeter_style, 'linear_orange')
        self.assertEqual(len(self.library.themes), 1)

    def test_back_from_fullscreen_continues_choosing_without_cancelling(self):
        self.meter('linear_orange')
        self.tap('fullscreen')
        self.editor.back()
        self.assertTrue(self.editor.open)
        self.assertFalse(self.editor.fullscreen)
        self.assertEqual(self.editor.preview['smeter_style'], 'linear_orange')
        self.assertEqual(self.path.read_bytes(), self.initial_bytes)

    def test_main_touch_handler_uses_explicit_home_destination(self):
        import kiwi_gl_display as ui
        code = Path(ui.__file__).read_text()
        self.assertIn('restore_navigation_parent(theme_editor.exit_surface)', code)
        self.assertNotIn('theme_editor.mode = "browse"', code)


if __name__ == '__main__':unittest.main()
