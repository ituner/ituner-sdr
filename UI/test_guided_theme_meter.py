"""Layout choices and paged meter faces apply directly to the running theme."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from smeter_styles import METER_STYLES
from theme_editor import ThemeEditor, theme_screen_boxes
import theme_screen_render
import theme_system
from theme_system import DEFAULT_THEME, ThemeLibrary, apply_theme, new_theme
from ui_style import APP_UI_STYLE


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


class GuidedLayoutMeterTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.library = ThemeLibrary(Path(self.directory.name) / 'themes.json')
        self.editor = ThemeEditor(self.library)
        self.editor.begin()

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def tap(self, action):
        boxes = theme_screen_boxes(self.editor)
        self.assertIn(action, boxes, f'Missing guided touch action {action}')
        self.editor.tap(*center(boxes[action]))

    def render(self):
        buttons, frames, faces, text = [], [], [], []
        ui = SimpleNamespace(
            APP_UI_STYLE=APP_UI_STYLE,
            draw_text=lambda *args, **kwargs: text.append(args),
            draw_styled_text_button=lambda *args, **kwargs: buttons.append((args, kwargs)),
            draw_logical_rect=lambda *args: None,
            draw_logical_rounded_rect=lambda *args: frames.append(args),
            draw_logical_line=lambda *args: None,
            draw_selected_smeter=lambda *args, **kwargs: faces.append((args, kwargs)),
        )
        theme_screen_render.draw_guided_theme_editor(None, self.editor, ui)
        return buttons, frames, faces, text

    def test_layout_choices_apply_live_and_keep_original_units_until_chosen(self):
        self.editor._select_category(5)
        self.assertEqual(self.editor.draft['units'], 'original')
        self.assertEqual(theme_system.runtime_theme['units'], 'original')
        for action, key, expected in (
                ('option:rounded', 'radius', 8), ('option:straight', 'radius', 0),
                ('option:left', 'sidebar', 'left'), ('option:right', 'sidebar', 'right'),
                ('option:metric', 'units', 'metric'), ('option:imperial', 'units', 'imperial'),
                ('option:original', 'units', 'original')):
            self.tap(action)
            self.assertEqual(self.editor.draft[key], expected)
            self.assertEqual(theme_system.runtime_theme[key], expected)
        self.assertEqual(self.library.themes, [])
        self.assertEqual(self.library.get('default')['units'], 'original')

    def test_text_size_steps_boundaries_and_reset_apply_live(self):
        self.editor._select_category(5)
        for action, values in (
                ('text:smaller', (95, 90, 85, 80, 80)),
                ('text:larger', (85, 90, 95, 100, 105, 110, 115, 120, 120)),
                ('text:reset', (100,))):
            for expected in values:
                self.tap(action)
                self.assertEqual(self.editor.draft['text_scale_percent'], expected)
                self.assertEqual(theme_system.runtime_theme['text_scale_percent'], expected)

    def test_layout_rendering_uses_touch_boxes_and_active_choices(self):
        self.editor._select_category(5)
        self.tap('option:left')
        self.tap('option:rounded')
        buttons, _frames, _faces, _text = self.render()
        boxes = theme_screen_boxes(self.editor)
        painted = {args[2]: (args[1], kwargs) for args, kwargs in buttons}
        for name in ('straight', 'rounded', 'left', 'right', 'original', 'imperial', 'metric'):
            self.assertEqual(painted[name.upper()][0], boxes['option:' + name])
            self.assertEqual(painted[name.upper()][1]['active'], name in ('rounded', 'left', 'original'))
        self.tap('text:smaller')
        for _ in range(3):
            self.tap('text:smaller')
        buttons, _frames, _faces, text = self.render()
        self.assertNotIn('SMALLER', [args[2] for args, _kwargs in buttons])
        self.assertIn('80%', [args[3] for args in text])

    def test_category_reset_restores_saved_meter_face_and_its_colors_only(self):
        baseline = new_theme('Custom baseline')
        baseline['smeter_style'] = 'aviation'
        baseline.update(radius=8, sidebar='left', units='metric', text_scale_percent=110)
        for other_edits in (False, True):
            with self.subTest(other_edits=other_edits):
                self.editor.begin(baseline)
                if other_edits:
                    self.editor.drag('tone', 900, 540)
                for _ in range(3):
                    self.tap('next')
                expected = deepcopy(self.editor.draft)
                self.tap('meter_gallery')
                self.tap('meter:heritage')
                if other_edits:
                    for family in ('S-METER', 'PASSBAND', 'SLIDERS'):
                        self.tap('family:' + family)
                        self.editor.drag('tone', 900, 540)
                with patch.object(self.editor, '_apply_draft', wraps=self.editor._apply_draft) as apply:
                    self.tap('reset_category')
                    self.assertEqual(apply.call_count, 1)
                    self.tap('reset_category')
                    self.assertEqual(apply.call_count, 1)
                self.assertEqual(self.editor.draft, expected)
                self.assertEqual(theme_system.runtime_theme['smeter_style'], 'aviation')
                self.assertEqual(theme_system.runtime_theme['colors'], expected['colors'])
                self.assertEqual(self.editor.dirty, other_edits)
                self.assertEqual(self.editor.family_source, expected['colors'])

    def test_layout_category_reset_restores_saved_settings_and_preserves_other_edits(self):
        baseline = new_theme('Custom baseline')
        baseline.update(radius=8, sidebar='left', units='metric', text_scale_percent=110)
        self.editor.begin(baseline)
        self.editor.drag('tone', 900, 540)
        for _ in range(3):
            self.tap('next')
        self.tap('meter_gallery')
        while 'meter:heritage' not in theme_screen_boxes(self.editor):
            self.tap('meter_next')
        self.tap('meter:heritage')
        expected = deepcopy(self.editor.draft)
        for _ in range(2):
            self.tap('next')
        for action in ('option:straight', 'option:right', 'option:imperial', 'text:reset'):
            self.tap(action)
        self.assertEqual(self.editor.draft['text_scale_percent'], 100)
        with patch.object(self.editor, '_apply_draft', wraps=self.editor._apply_draft) as apply:
            self.tap('reset_category')
            self.assertEqual(apply.call_count, 1)
            self.tap('reset_category')
            self.assertEqual(apply.call_count, 1)
        self.assertEqual(self.editor.draft, expected)
        for key in ('radius', 'sidebar', 'units', 'text_scale_percent'):
            self.assertEqual(theme_system.runtime_theme[key], expected[key])
        self.assertEqual(theme_system.runtime_theme['smeter_style'], 'heritage')
        self.assertEqual(theme_system.runtime_theme['colors'], expected['colors'])

    def test_layout_category_reset_is_painted_at_its_shared_touch_target(self):
        for _ in range(5):
            self.tap('next')
        boxes = theme_screen_boxes(self.editor)
        self.assertIn('reset_category', boxes)
        buttons, _frames, _faces, _text = self.render()
        painted = {args[2]: args[1] for args, _kwargs in buttons}
        self.assertEqual(painted['RESET CATEGORY'], boxes['reset_category'])
        reset = boxes['reset_category']
        self.assertEqual(reset[3] - reset[1], 64)
        for action, box in boxes.items():
            if action != 'reset_category':
                self.assertTrue(reset[2] <= box[0] or reset[0] >= box[2]
                                or reset[3] <= box[1] or reset[1] >= box[3], action)

    def test_guided_gallery_applies_face_live_and_closes_without_saving(self):
        self.editor._select_category(3)
        self.tap('meter_gallery')
        self.assertTrue(self.editor.meter_gallery_open)
        while 'meter:aviation' not in theme_screen_boxes(self.editor):
            self.tap('meter_next')
        self.tap('meter:aviation')
        self.assertEqual(self.editor.draft['smeter_style'], 'aviation')
        self.assertEqual(theme_system.runtime_theme['smeter_style'], 'aviation')
        self.assertFalse(self.editor.meter_gallery_open)
        self.assertEqual(self.library.themes, [])
        self.assertTrue(self.editor.dirty)
        self.tap('meter_gallery')
        self.assertIn('meter:aviation', theme_screen_boxes(self.editor))
        before = deepcopy(self.editor.draft)
        self.tap('meter_close')
        self.assertFalse(self.editor.meter_gallery_open)
        self.assertEqual(self.editor.draft, before)

    def test_gallery_pages_reach_every_face_and_block_underlying_controls(self):
        self.editor._select_category(3)
        boxes = theme_screen_boxes(self.editor)
        self.assertIn('meter_gallery', boxes)
        self.assertFalse(any(key.startswith('meter:') for key in boxes))
        self.tap('meter_gallery')
        for _ in range(5):
            self.tap('meter_previous')
        self.assertEqual(self.editor.meter_page, 0)
        buttons, _frames, _faces, _text = self.render()
        self.assertNotIn('PREV', [args[2] for args, _kwargs in buttons])
        seen = set()
        for _ in range(5):
            boxes = theme_screen_boxes(self.editor)
            self.assertNotIn('next', boxes)
            self.assertNotIn('hue', boxes)
            cards = {key.split(':', 1)[1]: box for key, box in boxes.items() if key.startswith('meter:')}
            self.assertGreater(len(cards), 0)
            self.assertLessEqual(len(cards), 6)
            seen.update(cards)
            for box in cards.values():
                self.assertGreaterEqual(box[1], 100)
                self.assertLessEqual(box[3], boxes['meter_next'][1])
            self.tap('meter_next')
        self.assertEqual(seen, set(METER_STYLES))
        self.assertEqual(self.editor.meter_page, 2)
        buttons, _frames, _faces, _text = self.render()
        self.assertNotIn('NEXT', [args[2] for args, _kwargs in buttons])
        self.assertEqual(self.editor.category_index, 3)

    def test_gallery_and_selected_face_paint_use_shared_card_boxes(self):
        self.editor._select_category(3)
        boxes = theme_screen_boxes(self.editor)
        _buttons, frames, faces, _text = self.render()
        self.assertEqual(len(faces), 1)
        self.assertEqual(faces[0][1]['style_id'], 'led')
        self.assertIn(boxes['meter_gallery'], [frame[:4] for frame in frames])
        self.tap('meter_gallery')
        boxes = theme_screen_boxes(self.editor)
        _buttons, frames, faces, _text = self.render()
        cards = {key.split(':', 1)[1]: box for key, box in boxes.items() if key.startswith('meter:')}
        self.assertEqual({kwargs['style_id'] for _args, kwargs in faces}, set(cards))
        for args, kwargs in faces:
            card = cards[kwargs['style_id']]
            self.assertIn(card, [frame[:4] for frame in frames])
            face = args[1]
            self.assertTrue(card[0] <= face[0] < face[2] <= card[2])
            self.assertTrue(card[1] <= face[1] < face[3] <= card[3])

    def test_gallery_swipe_pages_without_selecting_or_changing_draft(self):
        self.editor._select_category(3)
        self.assertFalse(self.editor.swipe(1000, 300, 400, 300))
        self.tap('meter_gallery')
        before = deepcopy(self.editor.draft)
        for _ in range(4):
            self.assertTrue(self.editor.swipe(1000, 300, 400, 300))
        self.assertEqual(self.editor.meter_page, 2)
        for _ in range(4):
            self.assertTrue(self.editor.swipe(400, 300, 1000, 300))
        self.assertEqual(self.editor.meter_page, 0)
        self.assertFalse(self.editor.swipe(400, 300, 405, 300))
        self.assertEqual(self.editor.draft, before)
        self.assertTrue(self.editor.meter_gallery_open)


if __name__ == '__main__':
    unittest.main()
