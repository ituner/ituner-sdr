"""Saving meter choices must work when the default draft name is already used."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json
from unittest.mock import patch

from theme_editor import ThemeEditor
from theme_system import BUILTIN_THEME_IDS, DEFAULT_THEME, ThemeLibrary, apply_theme, new_theme, theme_appearance, runtime_theme
from smeter_styles import METER_STYLES


class ThemeSaveTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "themes.json"
        self.library = ThemeLibrary(self.path)

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def test_meter_changes_from_every_builtin_preserve_all_saved_themes(self):
        original = new_theme()
        self.library.upsert(original)
        preserved = deepcopy(self.library.themes)
        for builtin in BUILTIN_THEME_IDS:
            self.library.activate(builtin)
            self.library.set_smeter_style('linear_orange')
            saved = ThemeLibrary(self.path)
            self.assertEqual(saved.smeter_style, 'linear_orange')
            self.assertEqual(saved.themes, preserved)
            self.assertEqual(saved.active_id, builtin)
            self.assertTrue(all('smeter_style' not in t for t in json.loads(self.path.read_text())['themes']))

    def test_repeated_meter_edits_leave_saved_theme_untouched(self):
        original = new_theme()
        self.library.upsert(original)
        preserved = deepcopy(self.library.themes)
        for identifier in ('flex_icom', 'linear_orange'):
            self.library.set_smeter_style(identifier)
            saved = ThemeLibrary(self.path)
            self.assertEqual(saved.active_id, original['id'])
            self.assertEqual(saved.smeter_style, identifier)
            self.assertEqual(saved.themes, preserved)

    def test_legacy_active_meter_migrates_and_other_themes_cannot_restore_theirs(self):
        first, active = new_theme("First"), new_theme("Active")
        first["smeter_style"], active["smeter_style"] = "flex_icom", "linear_orange"
        self.path.write_text(json.dumps({"version": 1, "active_id": active["id"], "themes": [first, active]}))
        migrated = ThemeLibrary(self.path)
        self.assertEqual(migrated.smeter_style, "linear_orange")
        migrated.activate(first["id"])
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["smeter_style"], "linear_orange")
        self.assertTrue(all("smeter_style" not in t for t in saved["themes"]))
        restarted = ThemeLibrary(self.path)
        restarted.activate("green")
        self.assertEqual(restarted.smeter_style, "linear_orange")
        restarted.delete(first["id"])
        restarted.activate(active["id"])
        restarted.delete(active["id"])
        self.assertEqual(ThemeLibrary(self.path).smeter_style, "linear_orange")

    def test_root_meter_overrides_legacy_values_and_invalid_root_falls_back(self):
        legacy = new_theme("Legacy")
        legacy["smeter_style"] = "flex_icom"
        for value, expected in (("linear_orange", "linear_orange"), ("invalid", "led")):
            self.path.write_text(json.dumps({"version": 1, "active_id": legacy["id"],
                                            "smeter_style": value, "themes": [legacy]}))
            self.assertEqual(ThemeLibrary(self.path).smeter_style, expected)

    def test_palette_edit_saves_builtin_override_and_keeps_meter_separate(self):
        self.library.set_smeter_style('linear_orange')
        editor = ThemeEditor(self.library)
        editor.show()
        editor.select_theme('default')
        editor.draft['colors']['frequency'] = [240, 120, 30]
        before = deepcopy(runtime_theme)
        with patch.object(self.library, 'save', side_effect=OSError('Full disk')):
            self.assertFalse(editor.save())
        self.assertEqual(self.library.themes, [])
        self.assertEqual(self.library.builtin_overrides, {})
        self.assertEqual(self.library.active_id, 'default')
        self.assertEqual(self.library.smeter_style, 'linear_orange')
        self.assertEqual(runtime_theme, before)
        self.assertTrue(editor.save())
        document = json.loads(self.path.read_text())
        self.assertEqual(document['themes'], [])
        self.assertEqual(document['builtin_overrides']['default']['colors']['frequency'], [240, 120, 30])
        self.assertNotIn('smeter_style', document['builtin_overrides']['default'])
        self.assertEqual(document['smeter_style'], 'linear_orange')
        self.assertEqual(document['active_id'], 'default')

    def test_new_draft_skips_existing_names_case_insensitively(self):
        for name in ("NEW THEME", "new theme 2", "New Theme 4"):
            self.library.upsert(new_theme(name))
        draft = self.library.new_theme()
        self.assertEqual(draft["name"], "New Theme 3")
        self.library.upsert(draft)
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
