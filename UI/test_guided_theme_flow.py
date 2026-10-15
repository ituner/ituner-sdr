"""Runtime-facing guided save/discard flows use the unchanged theme store."""
import ast
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import kiwi_gl_display as ui
from theme_editor import ThemeEditor, theme_screen_boxes
import theme_screen_render as render
import theme_system
from ui_style import APP_UI_STYLE


SOURCE = ast.parse(Path(ui.__file__).read_text())


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


class GuidedThemeFlowTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "themes.json"
        self.library = theme_system.ThemeLibrary(self.path)
        self.editor = ThemeEditor(self.library)
        self.editor.open = True

    def tearDown(self):
        theme_system.apply_theme(theme_system.DEFAULT_THEME)
        self.directory.cleanup()

    def tap(self, action):
        self.editor.tap(*center(theme_screen_boxes(self.editor)[action]))

    def render(self):
        labels, text = [], []
        drawing = SimpleNamespace(
            APP_UI_STYLE=APP_UI_STYLE,
            draw_text=lambda *args, **kwargs: text.append(args[3]),
            draw_styled_text_button=lambda *args, **kwargs: labels.append(args[2]),
            draw_logical_rect=lambda *args: None,
            draw_logical_rounded_rect=lambda *args: None,
            draw_logical_line=lambda *args: None,
            draw_selected_smeter=lambda *args, **kwargs: None,
        )
        render.draw_theme_screen(None, self.editor, drawing)
        return labels, text

    def test_runtime_constructor_opens_guided_categories(self):
        assignment = next(node for node in ast.walk(SOURCE)
                          if isinstance(node, ast.Assign) and any(
                              isinstance(target, ast.Name) and target.id == "theme_editor"
                              for target in node.targets))
        namespace = dict(vars(ui), args=SimpleNamespace(theme_file=self.path,
                                                        zoom_osd_seconds=4.25))
        exec(compile(ast.Module([assignment], type_ignores=[]), ui.__file__, "exec"), namespace)
        editor = namespace["theme_editor"]
        editor.open = True
        editor.tap(*center(theme_screen_boxes(editor)["new"]))
        self.assertIsInstance(editor, ThemeEditor)
        self.assertEqual(editor.notice_duration, 4.25)
        self.assertIn("view_app", theme_screen_boxes(editor))

    def test_library_new_view_return_keep_editing_and_save_persist_one_theme(self):
        self.tap("new")
        self.tap("next")
        self.editor.set_color((25, 95, 72))
        self.assertEqual(theme_system.runtime_theme["colors"]["text"], [25, 95, 72])
        draft = deepcopy(self.editor.draft)
        self.tap("view_app")
        self.assertEqual(self.library.themes, [])
        self.tap("return_to_editor")
        self.tap("back")
        self.tap("leave_keep")
        self.assertEqual(self.editor.category_index, 1)
        self.assertEqual(self.editor.selected_family, "TEXT")
        self.assertEqual(self.editor.draft, draft)
        self.tap("back")
        self.tap("leave_save")
        self.assertEqual(self.editor.mode, "browse")
        self.assertTrue(self.editor.open)
        self.assertEqual(self.library.active_id, draft["id"])
        self.assertEqual(self.editor.selected_id, draft["id"])
        restarted = theme_system.ThemeLibrary(self.path)
        self.assertEqual(restarted.themes, [draft])
        self.assertEqual(restarted.active_id, draft["id"])

    def test_discard_after_view_restores_entry_theme_and_clears_guided_state(self):
        self.tap("theme:1")
        entry = deepcopy(theme_system.runtime_theme)
        self.tap("new")
        self.tap("next")
        self.editor.set_color((25, 95, 72))
        self.tap("fine_tune")
        self.tap("view_app")
        self.tap("return_to_editor")
        self.tap("back")
        self.tap("leave_discard")
        self.assertEqual(theme_system.runtime_theme, entry)
        self.assertEqual(self.library.active_id, entry["id"])
        self.assertEqual(self.library.themes, [])
        self.assertEqual(self.editor.mode, "browse")
        self.assertTrue(self.editor.open)
        self.assertFalse(self.editor.view_app)
        self.assertFalse(self.editor.fine_tune)
        self.assertFalse(self.editor.meter_gallery_open)
        self.assertIsNone(self.editor.family_source)

    def test_save_clears_view_and_gallery_state(self):
        self.tap("new")
        self.editor.set_color((25, 95, 72))
        self.editor.view_app = self.editor.fine_tune = self.editor.meter_gallery_open = True
        self.assertTrue(self.editor.save())
        self.assertFalse(self.editor.view_app)
        self.assertFalse(self.editor.fine_tune)
        self.assertFalse(self.editor.meter_gallery_open)
        self.assertIsNone(self.editor.family_source)

    def test_failed_save_retains_draft_confirmation_and_live_appearance(self):
        self.tap("new")
        self.tap("next")
        self.editor.set_color((25, 95, 72))
        self.tap("fine_tune")
        self.tap("view_app")
        self.tap("return_to_editor")
        self.tap("back")
        draft = deepcopy(self.editor.draft)
        live = deepcopy(theme_system.runtime_theme)
        with patch.object(Path, "write_text", side_effect=OSError("DISK FULL")):
            self.tap("leave_save")
        self.assertEqual(self.editor.mode, "edit")
        self.assertTrue(self.editor.open)
        self.assertTrue(self.editor.confirm_back)
        self.assertTrue(self.editor.fine_tune)
        self.assertEqual(self.editor.category_index, 1)
        self.assertEqual(self.editor.draft, draft)
        self.assertEqual(theme_system.runtime_theme, live)
        self.assertEqual(self.library.themes, [])
        self.assertEqual(self.library.active_id, "default")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.editor.notice_action, "ERROR")
        self.assertEqual(self.editor.notice_detail, "DISK FULL")
        self.tap("leave_keep")
        self.tap("back")
        self.tap("leave_save")
        self.assertEqual(self.library.themes, [draft])

    def test_customize_builtin_preserves_builtin_and_creates_new_id(self):
        builtin = deepcopy(self.library.get("default"))
        self.tap("edit:0")
        self.assertNotEqual(self.editor.draft["id"], "default")
        self.editor.set_color((25, 95, 72))
        self.tap("back")
        self.tap("leave_save")
        self.assertEqual(self.library.get("default"), builtin)
        self.assertEqual(len(self.library.themes), 1)
        self.assertNotEqual(self.library.active_id, "default")

    def test_face_sidebar_and_text_size_apply_before_save(self):
        self.tap("new")
        for _ in range(3):
            self.tap("next")
        self.tap("meter_gallery")
        while "meter:aviation" not in theme_screen_boxes(self.editor):
            self.tap("meter_next")
        self.tap("meter:aviation")
        self.assertEqual(theme_system.runtime_theme["smeter_style"], "aviation")
        self.tap("next")
        self.tap("next")
        self.tap("option:left")
        self.assertEqual(theme_system.runtime_theme["sidebar"], "left")
        self.tap("text:larger")
        self.assertEqual(theme_system.runtime_theme["text_scale_percent"], 105)
        self.assertEqual(self.library.themes, [])

    def test_runtime_draw_keeps_library_and_uses_guided_editor_and_confirmation(self):
        labels, text = self.render()
        self.assertIn("NEW THEME", labels)
        self.assertIn("THEMES", text)
        self.tap("new")
        labels, text = self.render()
        self.assertIn("CATEGORY 1 / 6", text)
        self.assertIn("VIEW APP", labels)
        self.assertNotIn("SAVE THEME", labels)
        self.editor.set_color((25, 95, 72))
        self.tap("back")
        labels, text = self.render()
        self.assertIn("SAVE CHANGES?", text)
        self.assertTrue({"SAVE & LEAVE", "DISCARD & LEAVE", "KEEP EDITING"} <= set(labels))
        self.tap("leave_discard")
        labels, text = self.render()
        self.assertIn("NEW THEME", labels)
        self.assertNotIn("VIEW APP", labels)

    def test_name_hex_and_alpha_overlays_use_guided_flow(self):
        self.tap("new")
        self.tap("theme_name")
        labels, text = self.render()
        self.assertIn("NAME THEME", text)
        self.tap("name:CLEAR")
        for letter in "GUIDED":
            self.tap("name:" + letter)
        self.tap("name:DONE")
        for _ in range(3):
            self.tap("next")
        self.tap("family:PASSBAND")
        self.tap("fine_tune")
        self.tap("hex_open")
        labels, text = self.render()
        self.assertIn("EXACT COLOR", text)
        self.tap("hex:CANCEL")
        self.tap("alpha_open")
        labels, text = self.render()
        self.assertIn("TRANSPARENCY  0–100%", text)
        self.tap("alpha:5")
        self.tap("alpha:0")
        self.tap("alpha:DONE")
        self.assertEqual(theme_system.runtime_theme["colors"]["passband_fill"][3], 128)
        self.tap("back")
        self.tap("leave_save")
        self.assertEqual(self.library.themes[0]["name"], "GUIDED")

    def test_display_parent_restores_only_when_library_closes(self):
        release = next(node for node in ast.walk(SOURCE)
                       if isinstance(node, ast.If)
                       and ast.unparse(node.test) == "touch_started and gesture == 'theme'")
        restored = []
        namespace = dict(vars(ui), theme_editor=self.editor, args=SimpleNamespace(tap_px=15),
                         refresh_receiver_list_theme=lambda: None, wake_controls=lambda: None,
                         restore_navigation_parent=restored.append)
        code = compile(ast.fix_missing_locations(ast.Module(release.body, type_ignores=[])),
                       ui.__file__, "exec")
        def release_action(action):
            x, y = center(theme_screen_boxes(self.editor)[action])
            namespace.update(x=x, y=y, start_x=x, start_y=y)
            exec(code, namespace)
        release_action("new")
        release_action("view_app")
        self.assertEqual(restored, [])
        release_action("return_to_editor")
        release_action("back")
        self.assertEqual(self.editor.mode, "browse")
        self.assertEqual(restored, [])
        release_action("back")
        self.assertEqual(restored, ["display"])


if __name__ == "__main__":
    unittest.main()
