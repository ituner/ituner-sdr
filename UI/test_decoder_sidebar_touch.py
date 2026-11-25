"""Blank decoder sidebar space must never behave as HOME or BACK."""
from copy import deepcopy
import unittest
from unittest.mock import Mock

import test_adsb
import test_vhf
import test_spectrum_workspace
import test_digital_navigation_layout
from digital_navigation import install_navigation
from cw_workspace import CWWorkspace
from qrss_workspace import QRSSWorkspace
from sstv_workspace import SSTVWorkspace
from hell_workspace import HellWorkspace
from vhf_workspace import VHFWorkspace


def blank_sidebar_points(workspace):
    """Probe header, margins and vertical gaps, excluding painted controls."""
    for x in (1025, 1030, 1040, 1152, 1268, 1278):
        for y in (16, 32, 48, *range(80, 728, 16)):
            if not any(workspace.ui.contains(box, x, y) for box, _ in workspace.actions):
                yield x, y


class DecoderSidebarTouchTests(unittest.TestCase):
    def assert_blank_taps_keep_route(self, workspace, route, *args):
        before = deepcopy(route())
        points = list(blank_sidebar_points(workspace))
        self.assertTrue(points, 'Fixture must include blank sidebar space')
        for point in points:
            workspace.tap(*point, *args)
            self.assertEqual(route(), before, point)

    def test_adsb_map_receiver_traffic_logs_view_settings_and_history(self):
        for page in ('map', 'traffic', 'logs', 'usb', 'settings', 'options', 'history_window'):
            with self.subTest(page=page):
                w, _ui, manager, _state = test_adsb.WorkspaceTests().dashboard()
                w.show()
                if page != 'map':w.navigate(page)
                w.draw(Mock())
                self.assert_blank_taps_keep_route(w, lambda: (w.open, w.current_screen(), w.navigation))
                manager.control.assert_not_called()
                # The title itself is never registered as a navigation target.
                if page in ('settings', 'options'):
                    self.assertFalse(any(w.ui.contains(box, 1152, 32) for box, _ in w.actions))

    def test_cw_qrss_sstv_and_hell_gallery_receivers_history_and_forms(self):
        for cls in (CWWorkspace, QRSSWorkspace, SSTVWorkspace, HellWorkspace):
            pages = ('main', 'receivers', 'add', 'history') if cls is CWWorkspace else ('main', 'receivers', 'add')
            for page in pages:
                with self.subTest(screen=cls.__name__, page=page):
                    ui = test_digital_navigation_layout.ui_fixture()
                    manager = Mock()
                    manager.configs=[];manager.snapshot.return_value=[];manager.image_snapshot.return_value=[]
                    manager.history.return_value=[]
                    w=cls(ui,manager);w.open=True;install_navigation(w)
                    w.decoders_open=page=='receivers';w.add_open=page=='add'
                    if cls is CWWorkspace:w.history_open=page=='history'
                    w.draw(None, [])
                    route=lambda: (w.open,w.decoders_open,w.add_open,w.enlarged,w.page,getattr(w,'history_open',False))
                    self.assert_blank_taps_keep_route(w,route,[])

    def test_vhf_each_decoder_data_map_products_and_receiver_settings(self):
        fixture=test_vhf.TouchTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        ui=test_digital_navigation_layout.ui_fixture()
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        w=VHFWorkspace(ui,fixture.hub)
        for mode in fixture.hub.sessions:
            for view,overlay in (('data',None),('map',None),('products',None),('data','usb'),('data','profiles')):
                with self.subTest(mode=mode,view=view,overlay=overlay):
                    w.show(mode);w.view=view;w.overlay=overlay
                    w.draw(Mock())
                    self.assert_blank_taps_keep_route(w,lambda:(w.open,w.view,w.overlay,w.page,w.navigation_history))

    def test_spectrum_scan_signals_tools_and_nested_settings(self):
        fixture=test_spectrum_workspace.NativeSpectrumTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        w=fixture.workspace;w.open=True;w.state=fixture.hub.spectrum.native_snapshot()
        for screen,overlay in (('survey',None),('signals',None),('tools',None),('activity',None),
                               ('compare',None),('watch',None),('reports',None),('survey','settings'),
                               ('survey','advanced'),('survey','usb'),('survey','presets')):
            with self.subTest(screen=screen,overlay=overlay):
                w.screen=screen;w.overlay=overlay;w.draft=dict(fixture.hub.spectrum.settings)
                w.draw(Mock())
                self.assert_blank_taps_keep_route(w,lambda:(w.open,w.screen,w.overlay,w.exit_target))


if __name__=='__main__':unittest.main()
