"""Physical zoom uses visible ADS-B controls without retuning the hidden radio."""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock

from adsb_workspace import ADSBWorkspace
from adsb_coverage_touch import CoverageTouch
from adsb_traffic import MAP_ZOOM_MIN, MAP_ZOOM_MAX


class WorkspaceZoomTests(unittest.TestCase):
    def setUp(self):
        self.w = ADSBWorkspace.__new__(ADSBWorkspace)
        self.w.open = True
        self.w.radio_info = self.w.dongles = None
        self.w.scale = 5.0
        self.w.centered = False
        for _, flag in self.w.screen_flags():
            setattr(self.w, flag, False)
        self.w.coverage_view = CoverageTouch.__new__(CoverageTouch)
        self.w.coverage_view.zoom = 1.0
        self.w.coverage_view.window_open = False
        self.w.coverage_view.wake = threading.Event()

    def test_map_clicks_match_buttons_and_reverse(self):
        self.assertTrue(self.w.zoom_knob(2))
        self.assertAlmostEqual(self.w.scale, 5 * 1.6 * 1.6)
        self.assertTrue(self.w.centered)
        self.w.zoom_knob(-2)
        self.assertAlmostEqual(self.w.scale, 5)
        self.assertEqual(self.w.coverage_view.zoom, 1)

    def test_map_clamps_large_batches(self):
        self.w.zoom_knob(10000)
        self.assertEqual(self.w.scale, MAP_ZOOM_MAX)
        self.w.zoom_knob(-10000)
        self.assertEqual(self.w.scale, MAP_ZOOM_MIN)

    def test_coverage_clicks_use_existing_action_and_limits(self):
        self.w.coverage_open = True
        self.assertTrue(self.w.zoom_knob(2))
        self.assertEqual(self.w.coverage_view.zoom, 1.5)
        self.assertTrue(self.w.coverage_view.wake.is_set())
        self.w.zoom_knob(100)
        self.assertEqual(self.w.coverage_view.zoom, 4)
        self.w.zoom_knob(-100)
        self.assertEqual(self.w.coverage_view.zoom, .5)
        self.assertEqual(self.w.scale, 5)

    def test_nonzoom_pages_and_popups_do_not_change_hidden_views(self):
        for _, flag in self.w.screen_flags():
            if flag == 'coverage_open':
                continue
            setattr(self.w, flag, True)
            self.assertFalse(self.w.zoom_knob(1), flag)
            setattr(self.w, flag, False)
        self.w.coverage_open = True
        self.w.coverage_view.window_open = True
        self.assertFalse(self.w.zoom_knob(1))
        self.w.coverage_open = False
        self.w.radio_info = SimpleNamespace(open=True)
        self.assertFalse(self.w.zoom_knob(1))
        self.w.radio_info = None
        self.w.dongles = SimpleNamespace(open=True)
        self.assertFalse(self.w.zoom_knob(1))
        self.assertEqual(self.w.scale, 5)
        self.assertEqual(self.w.coverage_view.zoom, 1)

    def test_closed_workspace_ignores_input(self):
        self.w.open = False
        self.assertFalse(self.w.zoom_knob(1))
        self.assertEqual(self.w.scale, 5)


class UIRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(Path(__file__).with_name('kiwi_gl_display.py').read_text())
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'apply_zoom_knob')
        cls.code = compile(ast.Module(body=[handler], type_ignores=[]), 'knob-routing', 'exec')

    def setUp(self):
        self.workspace = Mock(open=True)
        self.env = dict(shared_keyboard_open=Mock(return_value=False),
                        web_apps=SimpleNamespace(blocks_touch=False),
                        adsb_workspace=self.workspace, wake_controls=Mock(), change_zoom=Mock())
        exec(self.code, self.env)

    def test_visible_adsb_gets_counts_without_radio_commands(self):
        self.env['apply_zoom_knob'](-3)
        self.workspace.zoom_knob.assert_called_once_with(-3)
        self.env['change_zoom'].assert_not_called()
        self.env['wake_controls'].assert_called_once()

    def test_adsb_nonzoom_page_does_not_fall_through(self):
        self.workspace.zoom_knob.return_value = False
        self.env['apply_zoom_knob'](1)
        self.env['change_zoom'].assert_not_called()
        self.env['wake_controls'].assert_not_called()

    def test_radio_keeps_original_zoom(self):
        self.workspace.open = False
        self.env['apply_zoom_knob'](2)
        self.env['change_zoom'].assert_called_once_with(2)
        self.workspace.zoom_knob.assert_not_called()

    def test_keyboard_and_web_modal_block_knob(self):
        self.env['shared_keyboard_open'].return_value = True
        self.env['apply_zoom_knob'](1)
        self.env['shared_keyboard_open'].return_value = False
        self.env['web_apps'].blocks_touch = True
        self.env['apply_zoom_knob'](1)
        self.workspace.zoom_knob.assert_not_called()
        self.env['change_zoom'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
