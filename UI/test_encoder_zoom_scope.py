"""Physical zoom must never retune an invisible HOME waterfall."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

from encoder_zoom import ContinuousHomeZoom, zoom_factor, zoom_workspace


class EncoderZoomScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(Path(__file__).with_name('kiwi_gl_display.py').read_text())
        cls.nodes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def setUp(self):
        names = ('zoom_blocking_screen_open', 'home_screen_visible',
                 'encoder_zoom_context', 'encoder_zoom_feedback_visible', 'apply_encoder_zoom')
        nodes = [copy.deepcopy(self.nodes[name]) for name in names]
        self.flags = {n.id for n in ast.walk(nodes[0]) if isinstance(n, ast.Name) and n.id.endswith('_open')}
        scope = {name: False for name in self.flags}
        for name in ('theme_editor', 'smeter_picker', 'application_update', 'audio_test_workspace',
                     'station_workspace', 'usb_radios_workspace', 'cw_workspace', 'qrss_workspace',
                     'hell_workspace', 'sstv_workspace', 'seek_view', 'vhf_workspace', 'adsb_workspace'):
            scope[name] = NS(open=False)
        scope.update(usb_popup=NS(visible=lambda: False), web_apps=NS(blocks_touch=False, publish_encoder_notice=Mock()),
                     LCD_800_MODE=True, LCD_RADIO_DRAWER_PROGRESS=0, picker_open=False, picker_map_open=False,
                     shared_keyboard_open=lambda: False, wake_controls=Mock(), change_zoom=Mock(), change_home_encoder_zoom=Mock(return_value="HOME  10 kHz"),
                     args=NS(zoom_osd_seconds=1.8), time=NS(monotonic=lambda: 100),
                     state=NS(waterfall_enabled_snapshot=lambda: True, spectrum_snapshot=lambda: (False,)),
                     zoom_workspace=zoom_workspace, zoom_factor=zoom_factor, clamp=lambda x, a, b: max(a, min(b, x)),
                     RADIOGARDEN_ZOOM_TAP_FACTOR=1.10, RADIOGARDEN_ZOOM_MIN=.55, RADIOGARDEN_ZOOM_MAX=50,
                     picker_map_zoom_target=None, picker_map_scale=1, search_open=False,
                     encoder_zoom_osd_context=None, volume_osd_until=105)
        scope['wf_texture'] = NS(history=NS(reviewing=False))
        # Execute the real nested dispatch with a small fake application state.
        class Globals(ast.NodeTransformer):
            def visit_Nonlocal(self, node):
                return ast.copy_location(ast.Global(names=node.names), node)
        module = Globals().visit(ast.Module(body=nodes, type_ignores=[]))
        exec(compile(ast.fix_missing_locations(module), 'encoder-scope', 'exec'), scope)
        self.scope = scope

    def test_home_changes_visible_rf_and_clears_old_volume_feedback(self):
        self.scope['apply_encoder_zoom'](2)
        self.scope['change_home_encoder_zoom'].assert_called_once_with(2)
        self.assertEqual(self.scope['encoder_zoom_osd_title'], 'ZOOM IN')
        self.assertEqual(self.scope['volume_osd_until'], 0)
        self.scope['web_apps'].publish_encoder_notice.assert_not_called()

    def test_home_handler_crops_every_detent_and_only_changes_integer_source_at_boundary(self):
        node = copy.deepcopy(self.nodes['change_home_encoder_zoom'])
        for index, statement in enumerate(node.body):
            if isinstance(statement, ast.Nonlocal):
                node.body[index] = ast.copy_location(ast.Global(names=statement.names), statement)
        current = [7]
        state = NS(snapshot=lambda: ('rx', 7100, current[0], -80, 1, 3),
                   receiver_type_snapshot=lambda: 'kiwi', external_waterfall_snapshot=lambda: False)
        state.set_view = Mock(side_effect=lambda zoom: current.__setitem__(0, zoom))
        span_at = ContinuousHomeZoomTests.span_at
        native = span_at(7)
        scope = dict(state=state, rtl_lab=NS(is_running=lambda: False),
                     continuous_home_zoom=ContinuousHomeZoom(), display_span=native,
                     args=NS(max_zoom=16), receiver_display_span=lambda level, _kind: span_at(level),
                     remember_current_view=Mock(), animate_to=Mock())
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'home-zoom', 'exec'), scope)
        detail = scope['change_home_encoder_zoom'](1)
        self.assertIn('10% STEP', detail)
        state.set_view.assert_not_called()
        self.assertAlmostEqual(scope['animate_to'].call_args.args[1], native / 1.10)
        scope['change_home_encoder_zoom'](-1)
        state.set_view.assert_not_called()
        scope['change_home_encoder_zoom'](-1)
        state.set_view.assert_called_once_with(zoom=6)
        self.assertAlmostEqual(scope['animate_to'].call_args.args[1], native * 1.10)

    def test_every_modal_flag_rejects_zoom_without_changing_home(self):
        for flag in sorted(self.flags):
            with self.subTest(flag=flag):
                self.scope[flag] = True
                self.scope['apply_encoder_zoom'](1)
                self.scope['change_zoom'].assert_not_called()
                self.scope['change_home_encoder_zoom'].assert_not_called()
                self.assertFalse(self.scope['home_screen_visible']())
                self.assertEqual(self.scope['zoom_unavailable_osd_until'], 101.8)
                self.scope[flag] = False

    def test_keyboard_external_browser_and_usb_notice_block_hidden_maps(self):
        self.scope.update(picker_open=True, picker_map_open=True)
        for target, attr in ((self.scope['theme_editor'], 'open'), (self.scope['web_apps'], 'blocks_touch')):
            setattr(target, attr, True)
            self.scope['apply_encoder_zoom'](1)
            self.assertIsNone(self.scope['picker_map_zoom_target'])
            self.scope['change_zoom'].assert_not_called()
            setattr(target, attr, False)
        self.scope['shared_keyboard_open'] = lambda: True
        self.scope['apply_encoder_zoom'](1)
        self.assertIsNone(self.scope['picker_map_zoom_target'])
        self.scope['shared_keyboard_open'] = lambda: False
        self.scope['usb_popup'].visible = lambda: True
        self.scope['apply_encoder_zoom'](1)
        self.assertIsNone(self.scope['picker_map_zoom_target'])

    def test_receiver_globe_zoom_accumulates_without_changing_rf(self):
        self.scope.update(picker_open=True, picker_map_open=True)
        self.scope['apply_encoder_zoom'](2)
        self.scope['apply_encoder_zoom'](1)
        self.assertAlmostEqual(self.scope['picker_map_zoom_target'], 1.10 ** 3)
        self.assertEqual(self.scope['encoder_zoom_osd_title'], 'ZOOM IN')
        self.assertIn('GLOBE', self.scope['encoder_zoom_osd_detail'])
        self.scope['change_zoom'].assert_not_called()
        self.assertFalse(self.scope['home_screen_visible']())

    def test_receiver_list_and_unavailable_rf_do_not_change_hidden_waterfall(self):
        self.scope['picker_open'] = True
        self.scope['apply_encoder_zoom'](1)
        self.scope['picker_open'] = False
        self.scope['state'].waterfall_enabled_snapshot = lambda: False
        self.scope['apply_encoder_zoom'](1)
        self.scope['change_zoom'].assert_not_called()
        self.assertEqual(self.scope['web_apps'].publish_encoder_notice.call_count, 2)

    def test_history_review_does_not_zoom_the_hidden_live_receiver(self):
        self.scope['wf_texture'].history.reviewing = True
        self.scope['apply_encoder_zoom'](1)
        self.scope['change_zoom'].assert_not_called()
        self.scope['web_apps'].publish_encoder_notice.assert_called_once()

    def test_adsb_feedback_expires_on_page_change(self):
        workspace = NS(open=True, current_screen=lambda: 'map', scale=2, zoom=Mock(), coverage_open=False)
        self.scope['adsb_workspace'] = workspace
        self.scope['apply_encoder_zoom'](-1)
        workspace.zoom.assert_called_once_with(1 / 1.10)
        self.scope['change_zoom'].assert_not_called()
        self.assertTrue(self.scope['encoder_zoom_feedback_visible']())
        workspace.current_screen = lambda: 'settings'
        self.assertFalse(self.scope['encoder_zoom_feedback_visible']())
        self.scope['apply_encoder_zoom'](1)
        self.assertEqual(workspace.zoom.call_count, 1)
        self.assertGreater(self.scope['zoom_unavailable_osd_until'], 100)


class WorkspaceZoomTests(unittest.TestCase):
    def test_adsb_map_and_coverage_keep_settings_and_forms_inert(self):
        coverage = NS(window_open=False, wake=NS(set=Mock()), zoom=1)
        workspace = NS(current_screen=lambda: 'coverage', coverage_view=coverage, zoom=Mock(), scale=5)
        self.assertIn('COVERAGE', zoom_workspace(workspace, 'adsb', 2))
        self.assertAlmostEqual(coverage.zoom, 1.10 ** 2)
        coverage.wake.set.assert_called_once()
        coverage.window_open = True
        self.assertIsNone(zoom_workspace(workspace, 'adsb', 1))
        workspace.current_screen = lambda: 'settings'
        self.assertIsNone(zoom_workspace(workspace, 'adsb', 1))
        workspace.current_screen = lambda: 'map'
        workspace.dongles = NS(open=True)
        self.assertIsNone(zoom_workspace(workspace, 'adsb', 1))
        workspace.zoom.assert_not_called()

    def test_vhf_zoom_operates_only_visible_map(self):
        workspace = NS(dongles=NS(open=False), mode='ais', view='map', overlay=None,
                       map=NS(zoom=Mock(), scale=5))
        self.assertIn('AIS MAP', zoom_workspace(workspace, 'vhf', 1))
        workspace.map.zoom.assert_called_once_with(1.10)
        for field, value in (('view', 'data'), ('overlay', 'settings')):
            before = getattr(workspace, field)
            setattr(workspace, field, value)
            self.assertIsNone(zoom_workspace(workspace, 'vhf', 1))
            setattr(workspace, field, before)
        self.assertEqual(workspace.map.zoom.call_count, 1)

    def test_spectrum_only_zoomable_charts_accept_zoom(self):
        spectrum = NS(overlay=None, screen='survey', view=(1e6, 2e6), state={'settings': {'low': 1e6}}, zoom=Mock())
        workspace = NS(dongles=NS(open=False), mode='spectrum', spectrum=spectrum)
        self.assertIn('SPECTRUM', zoom_workspace(workspace, 'vhf', 2))
        spectrum.zoom.assert_called_once_with(1 / 1.10 ** 2)
        for screen in ('signals', 'watch', 'tools', 'reports'):
            spectrum.screen = screen
            self.assertIsNone(zoom_workspace(workspace, 'vhf', 1))
        spectrum.screen = 'survey'
        spectrum.overlay = 'label'
        self.assertIsNone(zoom_workspace(workspace, 'vhf', 1))
        self.assertEqual(spectrum.zoom.call_count, 1)

    def test_scan_history_zooms_plot_center_but_setup_and_keyboard_do_not(self):
        view = NS(open=True, page='history', keyboard=False, plot_box=lambda: (20, 100, 1200, 650), zoom_at=Mock(), zoom=2)
        self.assertIn('SCAN HISTORY', zoom_workspace(view, 'scan', -2))
        view.zoom_at.assert_called_once_with(1.10 ** -2, 610)
        view.page = 'setup'
        self.assertIsNone(zoom_workspace(view, 'scan', 1))
        view.page = 'history'
        view.keyboard = True
        self.assertIsNone(zoom_workspace(view, 'scan', 1))
        self.assertIsNone(zoom_workspace(None, 'scan', 1))
        self.assertEqual(view.zoom_at.call_count, 1)


class ContinuousHomeZoomTests(unittest.TestCase):
    @staticmethod
    def span_at(level):
        return 30000 / 2 ** level if level <= 14 else (30000 / 2 ** 14) / {15: 4, 16: 8}[level]

    def test_one_detent_is_real_ten_percent_crop_without_server_change(self):
        zoom = ContinuousHomeZoom()
        native = self.span_at(7)
        level, span = zoom.step('kiwi', 7, native, 1, 0, 16, self.span_at)
        self.assertEqual(level, 7)
        self.assertAlmostEqual(span, native / 1.10)
        self.assertAlmostEqual(zoom.span('kiwi', 7, native), native / 1.10)

    def test_zoom_out_crosses_source_level_without_doubling_visible_span(self):
        zoom = ContinuousHomeZoom()
        native = self.span_at(7)
        level, span = zoom.step('kiwi', 7, native, -1, 0, 16, self.span_at)
        self.assertEqual(level, 6)
        self.assertAlmostEqual(span, native * 1.10)
        self.assertLess(span, self.span_at(level))
        level, restored = zoom.step('kiwi', level, span, 1, 0, 16, self.span_at)
        self.assertEqual(level, 7)
        self.assertAlmostEqual(restored, native)

    def test_every_level_boundary_and_digital_gap_remains_covered(self):
        zoom = ContinuousHomeZoom()
        level, span = 0, self.span_at(0)
        for direction in (1, -1):
            for _ in range(1500):
                before = span
                level, span = zoom.step('kiwi', level, span, direction, 0, 16, self.span_at)
                self.assertLessEqual(span, self.span_at(level) + 1e-12)
                expected = max(self.span_at(16), min(self.span_at(0), before / zoom_factor(direction)))
                self.assertAlmostEqual(span, expected)
                self.assertGreaterEqual(span, self.span_at(16))
        self.assertAlmostEqual(span, self.span_at(0))

    def test_source_switch_or_explicit_coarse_level_clears_override(self):
        zoom = ContinuousHomeZoom()
        native = self.span_at(7)
        zoom.step('kiwi-a', 7, native, 3, 0, 16, self.span_at)
        self.assertLess(zoom.span('kiwi-a', 7, native), native)
        self.assertEqual(zoom.span('kiwi-b', 7, native), native)
        zoom.step('kiwi-b', 7, native, 3, 0, 16, self.span_at)
        self.assertEqual(zoom.span('kiwi-b', 8, self.span_at(8)), self.span_at(8))

    def test_repeated_detents_accumulate_from_target_not_animation_frame(self):
        zoom = ContinuousHomeZoom()
        native = self.span_at(7)
        zoom.step('kiwi', 7, native, 1, 0, 16, self.span_at)
        # Before animation reaches its target, the prior target remains authoritative.
        current = zoom.span('kiwi', 7, native)
        _level, span = zoom.step('kiwi', 7, current, 1, 0, 16, self.span_at)
        self.assertAlmostEqual(span, native / 1.10 ** 2)


if __name__ == '__main__':
    unittest.main()
