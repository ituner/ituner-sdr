import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from smeter_picker import SMeterPicker
from smeter_styles import METER_STYLES
from theme_system import ThemeLibrary, DEFAULT_THEME, apply_theme, runtime_theme


class QuickMeterTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / 'themes.json'
        self.library = ThemeLibrary(self.path)
        self.picker = SMeterPicker(self.library)
        self.picker.show()

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def point(self, action):
        a, b, c, d = self.picker.boxes()[action]
        return (a + c) / 2, (b + d) / 2

    def test_selection_applies_and_survives_restart_without_changing_theme(self):
        before = deepcopy(runtime_theme)
        action = next(k for k in self.picker.boxes() if k.startswith('meter:'))
        identifier = action.split(':')[1]
        self.picker.tap(*self.point(action))
        self.assertFalse(self.picker.open)
        self.assertEqual(runtime_theme, {**before, 'smeter_style': identifier})
        self.assertEqual(ThemeLibrary(self.path).smeter_style, identifier)
        self.assertEqual(json.loads(self.path.read_text())['themes'], [])

    def test_six_cards_and_every_style_reachable_without_rail_overlap(self):
        seen = set()
        for page in range(self.picker.page_count):
            self.picker.page = page
            boxes = self.picker.boxes()
            cards = [k for k in boxes if k.startswith('meter:')]
            self.assertLessEqual(len(cards), 6)
            for key in cards:
                a, b, c, d = boxes[key]
                self.assertLess(c, 1024)
                self.assertGreaterEqual(c - a, 56)
                self.assertGreaterEqual(d - b, 56)
                self.assertEqual(self.picker.action_at(*self.point(key)), key)
                seen.add(key.split(':')[1])
        self.assertEqual(seen, set(METER_STYLES))

    def test_cancel_and_cross_card_release_do_not_save(self):
        self.library.set_smeter_style('led')
        before = self.path.read_bytes()
        first, second = [k for k in self.picker.boxes() if k.startswith('meter:')][:2]
        self.picker.tap(*self.point(second), started_at=self.point(first))
        self.assertTrue(self.picker.open)
        self.picker.tap(*self.point('close'))
        self.assertFalse(self.picker.open)
        self.assertEqual(self.path.read_bytes(), before)

    def test_save_failure_keeps_picker_open_and_current_meter(self):
        before = deepcopy(runtime_theme)
        first = next(k for k in self.picker.boxes() if k.startswith('meter:'))
        with patch.object(self.library, 'save', side_effect=OSError('disk full')):
            self.picker.tap(*self.point(first))
        self.assertTrue(self.picker.open)
        self.assertTrue(self.picker.error)
        self.assertEqual(runtime_theme, before)

    def test_meter_target_tracks_height_and_sidebar_theme(self):
        import kiwi_gl_display as ui
        ui.configure_output(True)
        cache = Mock()
        cache.font.return_value.size.return_value = (300, 58)
        for sidebar in ('left', 'right'):
            for identifier in ('led', 'aviation', 'flex_icom'):
                apply_theme({**DEFAULT_THEME, 'sidebar': sidebar, 'smeter_style': identifier})
                a, b, c, d = ui.lcd_compact_smeter_box()
                self.assertTrue(ui.home_smeter_touch(cache, (a + c) / 2, d - 1, 7075, 'right'))
                self.assertFalse(ui.home_smeter_touch(cache, 100, 500, 7075, 'right'))


if __name__ == '__main__':
    unittest.main()
