"""Touch geometry stays consistent across native Airspace views."""
import unittest
from unittest.mock import Mock

from adsb_coverage_touch import CoverageTouch, BOX
from adsb_layout import action_box
from adsb_touch import AirspaceDashboard


class AirspaceLayoutTests(unittest.TestCase):
    def test_dome_controls_share_receiver_width_and_clear_scene_and_footer(self):
        workspace = Mock()
        workspace.BG = (0, 0, 0)
        workspace.manager.coverage_error = ''
        view = CoverageTouch(workspace)
        view.data = {'status': 'NO SITE', 'meta': {}}
        view.draw(Mock(), {})
        controls = [call.args for call in workspace.button.call_args_list]
        self.assertEqual(len(controls), 10)
        for _, box, _, _ in controls:
            self.assertEqual((box[2]-box[0], box[3]-box[1]), (236, 56))
            self.assertTrue(box[3] <= BOX[1] or box[1] >= BOX[3])
        for index, (_, box, _, action) in enumerate(controls[-4:]):
            self.assertEqual(box, action_box(index))
            self.assertIn(action[0], ('coverage_turn', 'coverage_tilt'))

    def test_dashboard_navigation_matches_receiver_action_columns(self):
        dashboard = AirspaceDashboard()
        dashboard.ui = Mock()
        dashboard.PANEL = dashboard.LINE = dashboard.MUTED = (0, 0, 0)
        dashboard.ink = dashboard.text = dashboard.button = Mock()
        dashboard.logs_open = dashboard.usb_open = dashboard.traffic_open = False
        dashboard.last_count = None
        dashboard.header(Mock(), {'enabled': False, 'status': 'STOPPED', 'messages': 0}, [])
        buttons = [call.args for call in dashboard.button.call_args_list
                   if len(call.args) > 3 and isinstance(call.args[3], tuple)]
        self.assertEqual([args[1] for args in buttons[-4:]], [action_box(i,y=88) for i in range(4)])
        self.assertTrue(all(args[1][2]-args[1][0] == 236 for args in buttons))


if __name__ == '__main__':
    unittest.main()
