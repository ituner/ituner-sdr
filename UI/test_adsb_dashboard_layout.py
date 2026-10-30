"""Touch geometry stays consistent across native Airspace views."""
import unittest
from unittest.mock import Mock

from adsb_coverage_touch import CoverageTouch, BOX
import UI.test_adsb as adsb_tests


class AirspaceLayoutTests(unittest.TestCase):
    def test_dome_preserves_side_controls_with_current_two_mode_toolbar(self):
        workspace = Mock()
        workspace.BG = (0, 0, 0)
        workspace.manager.coverage_error = ''
        view = CoverageTouch(workspace)
        view.data = {'status': 'NO SITE', 'meta': {}}
        view.draw(Mock(), {})
        controls = [call.args for call in workspace.button.call_args_list]
        self.assertGreaterEqual(BOX[0], 152)
        self.assertLessEqual(BOX[2], 1128)
        reset = [box for _, box, _, action in controls if action[0] == "coverage_clock_reset"]
        self.assertEqual(reset, [(832,10,990,72)])
        toolbar = [box for _, box, _, action in controls if action[0] in ('coverage_mode', 'coverage_signal', 'coverage_reset', 'site')]
        self.assertEqual(len(toolbar), 5)
        self.assertTrue(all(box[1:4:2] == (96,152) for box in toolbar))
        self.assertEqual([box for _,box,_,_ in controls[-4:]],
                         [(24,568,152,624),(24,636,152,692),
                          (1128,568,1256,624),(1128,636,1256,692)])
        self.assertEqual([label for _,_,label,_ in controls[-4:]], ['− 30°','+ 30°','Tilt −','Tilt +'])

    def test_dashboard_navigation_retains_original_sizes(self):
        dashboard, ui, manager, state = adsb_tests.WorkspaceTests().dashboard()
        dashboard.header(Mock(), state, [])
        dashboard.draw_map_hud(Mock(), state, [])
        nav = {action: box for box, action in dashboard.actions}
        actions = [('traffic_view', 'live'), ('traffic_view', 'history'),
                   ('coverage', None), ('view_options', None), ('settings', None)]
        self.assertEqual([nav[action] for action in actions],
                         [(216+i*200,16,408+i*200,80) for i in range(5)])
        self.assertEqual(nav[('rx_footprint', None)], (216,88,408,152))
        self.assertEqual(nav[('usb', None)], (416,88,608,152))
        self.assertEqual(nav[('weather', None)], (616,88,808,152))


if __name__ == '__main__':
    unittest.main()
