import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import kiwi_gl_display as ui
from theme_editor import ThemeEditor,theme_screen_boxes
from theme_system import ThemeLibrary
import theme_screen_render as render

class ThemeModalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.editor=ThemeEditor(ThemeLibrary(Path(self.temp.name)/'themes.json'));self.editor.show()
    def tearDown(self):self.temp.cleanup()
    def test_close_exits_without_saving_theme(self):
        active=self.editor.library.active_id
        box=theme_screen_boxes(self.editor)['close']
        self.editor.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
        self.assertFalse(self.editor.open);self.assertEqual(self.editor.library.active_id,active)
    def test_outside_tap_keeps_chooser_open_and_does_not_select(self):
        selected=self.editor.selected_id
        self.editor.tap(10,10)
        self.assertTrue(self.editor.open);self.assertEqual(self.editor.selected_id,selected)
    def test_chooser_draws_dim_after_home_and_before_panel(self):
        calls=[]
        fake=Mock();fake.draw_modal_backdrop.side_effect=lambda:calls.append('dim')
        with patch.object(render,'_home',side_effect=lambda *a:calls.append('home')),patch.object(render,'_chooser',side_effect=lambda *a:calls.append('chooser')):
            render.draw_theme_screen(Mock(),self.editor,fake)
        self.assertEqual(calls,['home','dim','chooser'])
    def test_live_customization_preview_is_not_dimmed(self):
        self.editor.select_theme(self.editor.selected_id)
        fake=Mock()
        with patch.object(render,'_home'),patch.object(render,'_inspector'):
            render.draw_theme_screen(Mock(),self.editor,fake)
        fake.draw_modal_backdrop.assert_not_called()
    def test_background_pointer_feedback_is_suspended_until_capture(self):
        source=Path(ui.__file__).read_text()
        start=source.index('            theme_background_press_point = UI_PRESS_POINT')
        capture=source.index('                theme_live_frame.capture()',start)
        restore=source.index('                set_ui_press_point(*(theme_background_press_point',capture)
        draw=source.index('                draw_theme_panel(',restore)
        self.assertIn('set_ui_press_point()',source[start:capture])
        self.assertLess(capture,restore);self.assertLess(restore,draw)
        point=(900,245);box=(884,230,988,262)
        ui.set_ui_press_point(*point)
        try:
            saved=ui.UI_PRESS_POINT
            ui.set_ui_press_point()
            self.assertFalse(ui.ui_button_pressed(box))
            ui.set_ui_press_point(*(saved or (None,None)))
            self.assertTrue(ui.ui_button_pressed(box))
        finally:ui.set_ui_press_point()

    def test_theme_capture_precedes_hidden_home_controls(self):
        source=Path(ui.__file__).read_text()
        start=source.index('                            if theme_editor.open:\n                                gesture = "theme"')
        end=source.index('                            elif home_rail_restore_at',start)
        self.assertLess(start,end)

if __name__=='__main__':unittest.main()
