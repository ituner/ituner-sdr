"""Live-view ownership and the actual main-loop theme/navigation branches."""
import ast
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, Mock, patch

import kiwi_gl_display as ui
from theme_editor import ThemeEditor
from theme_system import DEFAULT_THEME, ThemeLibrary, apply_theme


SOURCE = ast.parse(Path(ui.__file__).read_text())


def nested_function(name, values):
    """Run a real main-loop closure with explicit state, without opening GL/audio."""
    function = deepcopy(next(node for node in ast.walk(SOURCE)
                             if isinstance(node, ast.FunctionDef) and node.name == name))
    namespace = dict(vars(ui))
    for node in function.body:
        if isinstance(node, ast.Nonlocal):
            for variable in node.names:
                namespace[variable] = False
    function.body = [ast.copy_location(ast.Global(node.names), node)
                     if isinstance(node, ast.Nonlocal) else node for node in function.body]
    namespace.update(values)
    exec(compile(ast.fix_missing_locations(ast.Module([function], type_ignores=[])),
                 ui.__file__, "exec"), namespace)
    return namespace[name], namespace


class GuidedThemeViewAppTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.library = ThemeLibrary(Path(self.directory.name) / "themes.json")
        self.editor = ThemeEditor(self.library)
        self.editor.begin()
        self.editor.open = True

    def tearDown(self):
        ui.set_ui_press_point()
        apply_theme(DEFAULT_THEME)
        self.directory.cleanup()

    def test_view_app_keeps_live_controls_and_return_target(self):
        self.assertTrue(ui.theme_editor_captures_touch(self.editor, 100, 300))
        self.editor.view_app = True
        before = dict(vars(self.editor))
        for point in ((100, 300), (521, 760), (759, 760), (640, 727), (640, 793)):
            self.assertFalse(ui.theme_editor_captures_touch(self.editor, *point), point)
        for point in ((522, 728), (640, 760), (758, 792)):
            self.assertTrue(ui.theme_editor_captures_touch(self.editor, *point), point)
        self.assertEqual(vars(self.editor), before)
        self.editor.open = False
        self.assertFalse(ui.theme_editor_captures_touch(self.editor, 640, 760))

    def test_view_app_navigation_preserves_draft_and_return_restores_category(self):
        self.editor._select_category(4)
        self.editor.drag("tone", 1100, 520)
        draft = deepcopy(self.editor.draft)
        family = self.editor.selected_family
        self.editor.tap(640, 760)
        navigation, state = nested_function("activate_navigation_item", {
            "theme_editor": self.editor, "wake_controls": Mock(),
            **{name: SimpleNamespace(open=False) for name in
               ("sstv_workspace", "hell_workspace", "qrss_workspace", "cw_workspace")},
        })
        navigation(0, (("settings", "SETTINGS"),))
        self.assertTrue(state["settings_menu_open"])
        self.assertTrue(self.editor.open)
        self.assertTrue(self.editor.view_app)
        self.editor.tap(640, 760)
        self.assertFalse(self.editor.view_app)
        self.assertEqual(self.editor.category_index, 4)
        self.assertEqual(self.editor.selected_family, family)
        self.assertEqual(self.editor.draft, draft)
        self.assertEqual(self.library.themes, [])

    def test_opening_theme_navigation_while_viewing_returns_to_existing_draft(self):
        self.editor._select_category(2)
        self.editor.view_app = True
        draft = self.editor.draft
        navigation, _state = nested_function("activate_navigation_item", {
            "theme_editor": self.editor, "wake_controls": Mock(),
            **{name: SimpleNamespace(open=False) for name in
               ("sstv_workspace", "hell_workspace", "qrss_workspace", "cw_workspace")},
        })
        navigation(0, (("theme", "THEMES"),))
        self.assertFalse(self.editor.view_app)
        self.assertEqual(self.editor.mode, "edit")
        self.assertEqual(self.editor.category_index, 2)
        self.assertIs(self.editor.draft, draft)

    def test_view_app_overlay_draws_only_return_without_covering_live_app(self):
        self.editor.view_app = True
        with patch.object(ui, "draw_theme_panel") as panel, \
                patch.object(ui, "draw_styled_text_button") as buttons, \
                patch.object(ui, "draw_logical_rect") as rectangles:
            ui.draw_theme_editor_overlay(None, self.editor)
        panel.assert_not_called()
        rectangles.assert_not_called()
        buttons.assert_called_once_with(None, (522, 728, 758, 792), "RETURN TO EDITOR", style=ANY)
        self.editor.view_app = False
        with patch.object(ui, "draw_theme_panel") as panel:
            ui.draw_theme_editor_overlay(None, self.editor)
        panel.assert_called_once_with(None, self.editor)

    def test_runtime_return_uses_explicit_fixed_style_under_low_contrast_draft(self):
        self.editor.draft['colors']['text'] = [80, 80, 80]
        self.editor.draft['colors']['surface'] = [80, 80, 80, 255]
        self.editor.draft['colors']['border'] = [80, 80, 80, 255]
        self.editor._apply_draft()
        self.editor.view_app = True
        with patch.object(ui, 'draw_styled_text_button', wraps=ui.draw_styled_text_button) as button, \
                patch.object(ui, 'draw_logical_rounded_rect') as frame, \
                patch.object(ui, 'draw_text') as text:
            ui.draw_theme_editor_overlay(None, self.editor)
        self.assertIn('style', button.call_args.kwargs)
        self.assertEqual(button.call_args.args, (None, (522, 728, 758, 792), 'RETURN TO EDITOR'))
        self.assertEqual(frame.call_args.args[:4], (522, 728, 758, 792))
        self.assertEqual(frame.call_args.args[5], (0, 0, 0, 255))
        self.assertEqual(text.call_args.args[3:5], ('RETURN TO EDITOR', (255, 255, 255)))
        self.assertTrue(ui.theme_editor_captures_touch(self.editor, 640, 760))
        self.editor.tap(640, 760)
        self.assertFalse(self.editor.view_app)

    def test_frame_draws_return_after_left_sidebar_composition(self):
        self.editor.view_app = True
        body = next(node.body for node in ast.walk(SOURCE) if hasattr(node, "body")
                    and isinstance(node.body, list) and any(
                        isinstance(item, ast.Expr) and isinstance(item.value, ast.Call)
                        and isinstance(item.value.func, ast.Name)
                        and item.value.func.id == "draw_theme_editor_overlay"
                        for item in node.body))
        index = next(index for index, node in enumerate(body)
                     if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                     and isinstance(node.value.func, ast.Name)
                     and node.value.func.id == "draw_theme_editor_overlay")
        operations = ["live app"]
        namespace = dict(vars(ui), theme_editor=self.editor, text_cache=None, now=0,
                         rail_relocation_active=lambda: True,
                         sidebar_composer=SimpleNamespace(
                             compose_left=lambda: operations.append("left rail")))
        with patch.object(ui, "draw_theme_panel") as panel, \
                patch.object(ui, "draw_styled_text_button",
                             side_effect=lambda *_, **_kwargs: operations.append("return")):
            exec(compile(ast.fix_missing_locations(ast.Module(body[index - 1:index + 2],
                                                             type_ignores=[])),
                         ui.__file__, "exec"), namespace)
        panel.assert_not_called()
        self.assertEqual(operations, ["live app", "left rail", "return"])

    def test_desktop_mapping_scales_window_and_preserves_the_physical_return_box(self):
        self.editor.view_app = True
        self.editor.draft["sidebar"] = "left"
        self.editor._apply_draft()
        point, _state = nested_function("desktop_logical_point", {
            "theme_editor": self.editor, "rail_relocation_active": lambda: True,
            "DESKTOP_MODE": True, "NATIVE_W": 1280, "NATIVE_H": 800,
        })
        with patch.object(ui.pygame.display, "get_window_size", return_value=(640, 400)):
            self.assertEqual(point((50, 150)), (1124, 300))
            self.assertEqual(point((320, 380)), (640, 760))
            self.assertEqual(point((50, 150), apply_theme=False), (100, 300))

    def test_left_sidebar_maps_live_controls_but_leaves_return_in_canvas_coordinates(self):
        self.editor.draft["sidebar"] = "left"
        self.editor._apply_draft()
        self.editor.view_app = True
        relocation, _state = nested_function("rail_relocation_active", {
            "theme_editor": self.editor, "wspr_panel_open": False,
            "font_lab_open": False, "rtl_lab_open": False,
            "picker_open": False, "globe_open": False,
        })
        self.assertTrue(relocation())
        self.assertEqual(ui.theme_editor_touch_point(self.editor, 100, 300, True), (1124, 300))
        self.assertEqual(ui.theme_editor_touch_point(self.editor, 500, 300, True), (244, 300))
        self.assertEqual(ui.theme_editor_touch_point(self.editor, 640, 760, True), (640, 760))
        self.editor.view_app = False
        self.assertFalse(relocation())
        self.assertEqual(ui.theme_editor_touch_point(self.editor, 100, 300, False), (100, 300))

    def test_left_rail_live_touch_cannot_become_return_after_coordinate_mapping(self):
        self.editor.view_app = True
        self.editor.draft["sidebar"] = "left"
        self.editor._apply_draft()
        frame = next(node for node in ast.walk(SOURCE) if isinstance(node, ast.If)
                     and ast.unparse(node.test) == "event_type == kiwi.EV_SYN and code == kiwi.SYN_REPORT")
        stop = next(index for index, node in enumerate(frame.body)
                    if isinstance(node, ast.If)
                    and ast.unparse(node.test).startswith("is_active and picker_open"))
        namespace = dict(vars(ui), theme_editor=self.editor, raw_x=896, raw_y=760,
                         active=True, mt_slots={}, args=None, touch_started=False, gesture=None,
                         rail_relocation_active=lambda: True,
                         kiwi=SimpleNamespace(touch_points=lambda *_: ((896, 760),)))
        exec(compile(ast.fix_missing_locations(ast.Module(frame.body[:stop], type_ignores=[])),
                     ui.__file__, "exec"), namespace)
        self.assertEqual((namespace["x"], namespace["y"]), (640, 760))
        self.assertFalse(namespace.get("theme_touch_owned",
                         ui.theme_editor_captures_touch(self.editor, 640, 760)))

    def test_return_ownership_stays_with_gesture_when_finger_leaves_button(self):
        self.editor.view_app = True
        self.editor.draft["sidebar"] = "left"
        self.editor._apply_draft()
        self.assertEqual(ui.theme_editor_touch_point(self.editor, 800, 760, True,
                                                    editor_owns_touch=True), (800, 760))
        self.assertEqual(ui.theme_editor_touch_point(self.editor, 640, 760, True,
                                                    editor_owns_touch=False), (384, 760))

    def test_hue_and_tone_drags_keep_start_control_and_do_not_reset_waterfall(self):
        state = ui.SharedState("test:8073", 7100, 4, -90, -120, -20, 1, "USB", True)
        initial = state.waterfall_snapshot()
        before = deepcopy(self.editor.draft)
        with patch.object(state, "set_waterfall") as reset, \
                patch.object(ui.WaterfallTexture, "clear") as clear_buffer:
            ui.drag_theme_editor(self.editor, 800, 420, 1256, 644)
            ui.drag_theme_editor(self.editor, 800, 520, 1100, 490)
        self.assertNotEqual(self.editor.draft, before)
        self.assertEqual(self.editor.hue, 1.0)
        self.assertGreater(self.editor.strength, 0.8)
        self.assertGreater(self.editor.lightness, 0.9)
        reset.assert_not_called()
        clear_buffer.assert_not_called()
        self.assertEqual(state.waterfall_snapshot(), initial)

    def test_main_release_routes_gallery_swipe_without_selecting_a_face(self):
        self.editor._select_category(3)
        self.editor._open_meter_gallery()
        self.editor.meter_page = 0
        before = self.editor.draft["smeter_style"]
        node = next(node for node in ast.walk(SOURCE) if isinstance(node, ast.If)
                    and ast.unparse(node.test) == "touch_started and gesture == 'theme'")
        namespace = dict(vars(ui), theme_editor=self.editor, x=100, y=230,
                         start_x=900, start_y=230, args=SimpleNamespace(tap_px=15),
                         refresh_receiver_list_theme=Mock(), wake_controls=Mock())
        exec(compile(ast.fix_missing_locations(ast.Module(node.body, type_ignores=[])),
                     ui.__file__, "exec"), namespace)
        self.assertEqual(self.editor.meter_page, 1)
        self.assertEqual(self.editor.draft["smeter_style"], before)

    def test_public_editor_drag_routes_the_original_picker_control(self):
        editor = ThemeEditor(self.library)
        editor.begin()
        from theme_editor import theme_screen_boxes
        box = theme_screen_boxes(editor)["hue"]
        with patch.object(editor, "drag") as drag:
            ui.drag_theme_editor(editor, box[0], box[1], 700, 420)
        drag.assert_called_once_with("hue", 700, 420)


if __name__ == "__main__":
    unittest.main()
