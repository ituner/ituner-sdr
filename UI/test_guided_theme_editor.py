"""Guided category navigation uses the real draft and Theme Library."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from theme_editor import (BACK_BOX, COLOR_GROUPS, GUIDED_CATEGORIES,
                          ThemeEditor, theme_screen_boxes)
from theme_system import COLOR_NAMES, DEFAULT_THEME, ThemeLibrary, apply_theme, new_theme
from ui_style import APP_UI_STYLE


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


class ThemeEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.library = ThemeLibrary(Path(self.directory.name) / "themes.json")
        self.editor = ThemeEditor(self.library)

    def tearDown(self):
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def tap(self, action):
        self.editor.tap(*center(theme_screen_boxes(self.editor)[action]))

    def test_guided_category_navigation_and_geometry(self):
        expected = (
            ("Surfaces", ("SURFACES", "FOOTER")),
            ("Text", ("TEXT",)),
            ("Buttons & states", ("BUTTONS", "STATES")),
            ("S-meter & passband", ("S-METER", "PASSBAND", "SLIDERS")),
            ("Spectrum & waterfall", ("SPECTRUM", "WATERFALL")),
            ("Layout & sizing", ()),
        )
        self.assertEqual(GUIDED_CATEGORIES, expected)
        families = [family for _label, names in GUIDED_CATEGORIES for family in names]
        self.assertCountEqual(families, [name for name, _keys in COLOR_GROUPS])
        self.editor.begin()
        baseline = deepcopy(self.editor.draft)
        self.tap("previous")
        for index, (_label, names) in enumerate(expected):
            self.assertEqual(self.editor.category_index, index)
            self.assertEqual(self.editor.category_families, names)
            self.assertEqual(self.editor.visible_family_rows, names)
            self.assertLessEqual(len(self.editor.visible_family_rows), 3)
            self.assertEqual(self.editor.selected_family, names[0] if names else None)
            boxes = theme_screen_boxes(self.editor)
            self.assertEqual(boxes["back"], BACK_BOX)
            self.assertEqual(boxes["previous"], (24, 728, 260, 792))
            self.assertEqual(boxes["next"], (268, 728, 504, 792))
            self.assertEqual(boxes["view_app"], (512, 728, 748, 792))
            rows = [box for key, box in boxes.items() if key.startswith("family:")]
            self.assertEqual(len(rows), len(names))
            for key, box in boxes.items():
                if key != "back":
                    self.assertTrue(box[2] <= BACK_BOX[0] or box[0] >= BACK_BOX[2]
                                    or box[3] <= BACK_BOX[1] or box[1] >= BACK_BOX[3], key)
            for row in rows:
                self.assertGreaterEqual(row[1], 120)
                self.assertLessEqual(row[3], 328)
            self.tap("next")
        self.assertEqual(self.editor.category_index, 5)
        self.assertEqual(self.editor.draft, baseline)
        self.assertFalse(self.editor.dirty)
        self.assertEqual(self.library.themes, [])
        for _ in range(7):
            self.tap("previous")
        self.assertEqual(self.editor.category_index, 0)

    def test_every_palette_key_is_reachable_once_through_fine_tune(self):
        grouped = [key for _family, keys in COLOR_GROUPS for key in keys]
        self.assertCountEqual(grouped, COLOR_NAMES)
        self.editor.begin()
        reached = []
        for category, (_label, families) in enumerate(GUIDED_CATEGORIES):
            self.assertEqual(self.editor.category_index, category)
            for family in families:
                self.tap(f"family:{family}")
                self.tap("fine_tune")
                keys = dict(COLOR_GROUPS)[family]
                for page in range((len(keys) + 2) // 3):
                    boxes = theme_screen_boxes(self.editor)
                    actions = [action for action in boxes if action.startswith("key:")]
                    self.assertLessEqual(len(actions), 3)
                    for action in actions:
                        self.tap(action)
                        key = action.split(":", 1)[1]
                        self.assertEqual(self.editor.color_key, key)
                        self.assertEqual(self.editor.current_color, self.editor.draft["colors"][key])
                        reached.append(key)
                    self.tap("key_next")
                self.tap("fine_tune_close")
            self.tap("next")
        self.assertCountEqual(reached, COLOR_NAMES)

    def test_view_app_preserves_selection_and_blocks_editor_controls(self):
        self.editor.begin()
        self.tap("family:FOOTER")
        self.assertEqual(self.editor.selected_family, "FOOTER")
        baseline = deepcopy(self.editor.draft)
        self.tap("view_app")
        self.assertEqual(theme_screen_boxes(self.editor),
                         {"return_to_editor": (522, 728, 758, 792)})
        self.editor.tap(*center(BACK_BOX))
        self.assertEqual(self.editor.mode, "edit")
        self.tap("return_to_editor")
        self.assertFalse(self.editor.view_app)
        self.assertEqual(self.editor.selected_family, "FOOTER")
        self.assertEqual(self.editor.draft, baseline)

    def test_begin_resets_guided_state(self):
        self.editor.begin()
        self.tap("next")
        self.editor.fine_tune = self.editor.meter_gallery_open = True
        self.editor.view_app = True
        self.editor.begin()
        self.assertEqual(self.editor.category_index, 0)
        self.assertEqual(self.editor.selected_family, "SURFACES")
        self.assertFalse(self.editor.view_app)
        self.assertFalse(self.editor.fine_tune)
        self.assertFalse(self.editor.meter_gallery_open)

    def test_keypad_and_confirmation_take_priority(self):
        self.editor.begin()
        self.tap("theme_name")
        self.assertIn("name:A", theme_screen_boxes(self.editor))
        self.assertNotIn("next", theme_screen_boxes(self.editor))
        self.editor.tap(*center((268, 728, 504, 792)))
        self.assertEqual(self.editor.category_index, 0)
        self.tap("name:A")
        self.tap("name:DONE")
        self.tap("back")
        self.assertTrue(self.editor.confirm_back)
        self.assertEqual(set(theme_screen_boxes(self.editor)),
                         {"leave_save", "leave_discard", "leave_keep"})
        self.assertIn("next", theme_screen_boxes(self.editor, ignore_overlay=True))
        self.tap("leave_keep")
        self.assertFalse(self.editor.confirm_back)

    def test_browse_keeps_library_paging_and_new_action(self):
        for index in range(9):
            self.library.upsert(new_theme(f"Saved {index}"))
        self.assertEqual(theme_screen_boxes(self.editor), theme_screen_boxes(self.editor))
        self.tap("next")
        self.assertEqual(self.editor.page, 1)
        self.tap("next")
        self.assertEqual(self.editor.page, 1)
        self.tap("previous")
        self.assertEqual(self.editor.page, 0)
        self.tap("new")
        self.assertEqual(self.editor.mode, "edit")
        self.assertEqual(self.editor.category_index, 0)

    def test_live_family_picker_preserves_alpha_and_other_families(self):
        self.editor.begin()
        self.editor.category_index = 2
        self.tap("family:BUTTONS")
        old = deepcopy(self.editor.draft["colors"])
        boxes = theme_screen_boxes(self.editor)
        self.assertIn("tone", boxes)
        self.assertNotIn("hex_open", boxes)
        self.assertNotIn("alpha_open", boxes)
        self.editor.drag("tone", boxes["tone"][2], boxes["tone"][1] + 90)
        self.editor.drag("hue", boxes["hue"][0] + 300, 0)
        self.assertNotEqual(self.editor.draft["colors"]["surface"][:3], old["surface"][:3])
        buttons = dict(COLOR_GROUPS)["BUTTONS"]
        for key, value in old.items():
            if key in buttons:
                self.assertEqual(self.editor.draft["colors"][key][3:], value[3:])
            else:
                self.assertEqual(self.editor.draft["colors"][key], value)
        self.assertEqual(APP_UI_STYLE.palette.surface,
                         tuple(self.editor.draft["colors"]["surface"]))
        self.editor.drag("tone", boxes["tone"][0], (boxes["tone"][1] + boxes["tone"][3]) / 2)
        for key in buttons:
            rgb = self.editor.draft["colors"][key][:3]
            self.assertEqual(len(set(rgb)), 1, key)

    def test_drag_uses_family_snapshot_and_ignores_repeated_samples(self):
        self.editor.begin()
        self.tap("family:FOOTER")
        box = theme_screen_boxes(self.editor)["tone"]
        target = (box[0] + 240, box[1] + 120)
        self.editor.drag("tone", *target)
        expected = deepcopy(self.editor.draft["colors"])
        self.editor.drag("tone", box[2], box[1])
        self.editor.drag("tone", *target)
        self.assertEqual(self.editor.draft["colors"], expected)
        with patch.object(self.editor, "_apply_draft", wraps=self.editor._apply_draft) as apply:
            self.editor.drag("tone", *target)
            self.assertEqual(apply.call_count, 0)
        self.tap("theme_name")
        self.editor.drag("tone", box[0], box[3])
        self.assertEqual(self.editor.draft["colors"], expected)

    def test_reset_restores_current_category_and_picker_source_only(self):
        self.editor.begin()
        self.tap("family:FOOTER")
        self.editor.drag("tone", *center(theme_screen_boxes(self.editor)["tone"]))
        footer = deepcopy(self.editor.draft["colors"]["footer_live"])
        self.editor._select_category(2)
        self.editor.drag("tone", *center(theme_screen_boxes(self.editor)["tone"]))
        self.tap("family:STATES")
        self.editor.drag("tone", *center(theme_screen_boxes(self.editor)["tone"]))
        self.tap("reset_category")
        for family in ("BUTTONS", "STATES"):
            for key in dict(COLOR_GROUPS)[family]:
                self.assertEqual(self.editor.draft["colors"][key], self.editor.baseline["colors"][key])
        self.assertEqual(self.editor.draft["colors"]["footer_live"], footer)
        self.assertEqual(self.editor.family_source, self.editor.draft["colors"])
        self.assertEqual(APP_UI_STYLE.palette.ready, tuple(self.editor.baseline["colors"]["ready"]))

    def test_fine_tune_alpha_cancel_hex_and_three_key_pages(self):
        self.editor.begin()
        self.editor._select_category(3)
        self.tap("family:PASSBAND")
        self.tap("fine_tune")
        boxes = theme_screen_boxes(self.editor)
        self.assertEqual(len([key for key in boxes if key.startswith("key:")]), 3)
        self.tap("key:passband_fill")
        self.assertIn("hex_open", theme_screen_boxes(self.editor))
        self.tap("alpha_open")
        self.tap("alpha:4")
        self.tap("alpha:0")
        self.assertEqual(self.editor.current_color[3], 153)
        self.assertEqual(APP_UI_STYLE.palette.passband_fill[3], 153)
        self.tap("alpha:DONE")
        self.tap("alpha_open")
        self.tap("alpha:9")
        self.tap("alpha:0")
        self.tap("alpha:CANCEL")
        self.assertEqual(self.editor.current_color[3], 153)
        old = deepcopy(self.editor.draft["colors"])
        self.editor.drag("tone", *center(theme_screen_boxes(self.editor)["tone"]))
        for key in old:
            if key != "passband_fill":
                self.assertEqual(self.editor.draft["colors"][key], old[key])
        self.assertEqual(self.editor.current_color[3], 153)
        self.tap("hex_open")
        for action in ("CLEAR", "1", "2", "3", "4", "5", "6", "9", "9", "APPLY"):
            self.tap("hex:" + action)
        self.assertEqual(self.editor.current_color, [18, 52, 86, 153])
        self.tap("key_next")
        self.assertIn("key:home_passband_fill", theme_screen_boxes(self.editor))
        self.tap("fine_tune_close")
        self.editor._select_category(1)
        self.tap("fine_tune")
        self.assertNotIn("alpha_open", theme_screen_boxes(self.editor))

    def test_guided_renderer_uses_fixed_chrome_and_has_no_simulated_preview(self):
        import theme_screen_render
        self.assertTrue(callable(getattr(theme_screen_render, "draw_guided_theme_editor", None)))
        self.editor.begin()
        self.editor.draft["colors"]["text"] = [0, 0, 0]
        self.editor.draft["colors"]["surface"] = [0, 0, 0, 255]
        self.editor._apply_draft()
        text, buttons = [], []
        ui = SimpleNamespace(
            APP_UI_STYLE=APP_UI_STYLE,
            draw_text=lambda *args, **kwargs: text.append(args),
            draw_styled_text_button=lambda *args, **kwargs: buttons.append((args, kwargs)),
            draw_logical_rect=lambda *args: None,
            draw_logical_rounded_rect=lambda *args: None,
            draw_logical_line=lambda *args: None,
        )
        theme_screen_render.draw_guided_theme_editor(None, self.editor, ui)
        labels = [args[4] for args in text] + [args[2] for args, _kwargs in buttons]
        self.assertIn("FINE TUNE", labels)
        self.assertIn("RESET CATEGORY", labels)
        self.assertFalse(any("PREVIEW" in str(label) or "APPLY" in str(label) or "HEX" in str(label)
                             for label in labels))
        self.assertTrue(all(kwargs["style"].palette.text == (255, 255, 255)
                            for _args, kwargs in buttons))


if __name__ == "__main__":
    unittest.main()
