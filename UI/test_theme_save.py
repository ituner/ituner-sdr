"""Saving meter choices must work when the default draft name is already used."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from theme_editor import ThemeEditor, theme_screen_boxes
from theme_system import BUILTIN_THEME_IDS, DEFAULT_THEME, ThemeLibrary, apply_theme, new_theme
from smeter_styles import METER_STYLES


class ThemeSaveTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "themes.json"
        self.library = ThemeLibrary(self.path)

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    @staticmethod
    def tap(editor, action):
        box = theme_screen_boxes(editor)[action]
        editor.tap((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    def choose_meter(self, editor, identifier):
        for _ in range((len(METER_STYLES) + 5) // 6):
            if f"meter:{identifier}" in theme_screen_boxes(editor):
                self.tap(editor, f"meter:{identifier}")
                return
            self.tap(editor, "meter_next")
        self.fail(f"Meter unavailable: {identifier}")

    def test_meter_copy_from_every_builtin_saves_without_renaming(self):
        original = new_theme()
        self.library.upsert(original)
        preserved = deepcopy(self.library.get(original["id"]))
        designs = ("linear_orange", "flex_vintage_hd_white", "flex_vintage_hd", "flex_orange")
        for index, builtin in enumerate(BUILTIN_THEME_IDS):
            with self.subTest(builtin=builtin):
                self.library.activate(builtin)
                editor = ThemeEditor(self.library)
                self.tap(editor, "meters")
                identifier = designs[index % len(designs)]
                self.choose_meter(editor, identifier)
                self.tap(editor, "save")
                self.assertEqual(editor.mode, "browse", editor.notice)
                saved = ThemeLibrary(self.path)
                self.assertEqual(saved.get(saved.active_id)["smeter_style"], identifier)
                self.assertEqual(saved.get(original["id"]), preserved)
                self.assertEqual(saved.get(builtin)["smeter_style"], "led")
        self.assertEqual(len(self.library.themes), 1 + len(BUILTIN_THEME_IDS))

    def test_repeated_meter_edits_update_the_same_saved_theme(self):
        original = new_theme()
        self.library.upsert(original)
        editor = ThemeEditor(self.library)
        for identifier in ("flex_icom", "linear_orange"):
            self.tap(editor, "meters")
            self.choose_meter(editor, identifier)
            self.tap(editor, "save")
            self.assertEqual(editor.mode, "browse", editor.notice)
            saved = ThemeLibrary(self.path)
            self.assertEqual(saved.active_id, original["id"])
            self.assertEqual(saved.get(saved.active_id)["name"], original["name"])
            self.assertEqual(saved.get(saved.active_id)["smeter_style"], identifier)
            self.assertEqual(len(saved.themes), 1)

    def test_new_draft_skips_existing_names_case_insensitively(self):
        for name in ("NEW THEME", "new theme 2", "New Theme 4"):
            self.library.upsert(new_theme(name))
        editor = ThemeEditor(self.library)
        self.tap(editor, "new")
        self.assertEqual(editor.draft["name"], "New Theme 3")
        self.tap(editor, "save")
        self.assertEqual(editor.mode, "browse", editor.notice)
        saved = ThemeLibrary(self.path)
        self.assertEqual(saved.get(saved.active_id)["name"], "New Theme 3")
        self.assertEqual(len(saved.themes), 4)

    def test_explicit_duplicate_name_still_protects_saved_themes(self):
        original = new_theme("My Radio")
        self.library.upsert(original)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.library.upsert(new_theme("MY RADIO"))
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
