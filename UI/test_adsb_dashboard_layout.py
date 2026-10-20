"""Touch geometry stays consistent across native Airspace views."""
import unittest
from unittest.mock import Mock

from adsb_coverage_touch import CoverageTouch, BOX
from adsb_touch import AirspaceDashboard


class AirspaceLayoutTests(unittest.TestCase):
    def test_dome_preserves_original_toolbar_and_side_controls(self):
        workspace = Mock()
        workspace.BG = (0, 0, 0)
        workspace.manager.coverage_error = ''
        view = CoverageTouch(workspace)
        view.data = {'status': 'NO SITE', 'meta': {}}
        view.draw(Mock(), {})
        controls = [call.args for call in workspace.button.call_args_list]
        self.assertEqual(BOX, (180,154,1100,712))
        self.assertEqual(len(controls), 10)
        self.assertTrue(all(box[1:4:2] == (96,152) for _,box,_,_ in controls[:6]))
        self.assertEqual([box for _,box,_,_ in controls[-4:]],
                         [(24,568,152,624),(24,636,152,692),
                          (1128,568,1256,624),(1128,636,1256,692)])
        self.assertEqual([label for _,_,label,_ in controls[-4:]], ['− 30°','+ 30°','Tilt −','Tilt +'])

    def test_dashboard_navigation_retains_original_sizes(self):
        dashboard = AirspaceDashboard()
        dashboard.ui = Mock()
        dashboard.PANEL = dashboard.LINE = dashboard.MUTED = (0, 0, 0)
        dashboard.ink = dashboard.text = dashboard.button = Mock()
        dashboard.logs_open = dashboard.usb_open = dashboard.traffic_open = False
        dashboard.last_count = None
        dashboard.header(Mock(), {'enabled': False, 'status': 'STOPPED', 'messages': 0}, [])
        buttons = [call.args for call in dashboard.button.call_args_list
                   if len(call.args) > 3 and isinstance(call.args[3], tuple)]
        self.assertEqual([args[1] for args in buttons[-4:]], [(16+i*250,88,258+i*250,144) for i in range(4)])
        self.assertTrue(all(args[1][2]-args[1][0] == 242 for args in buttons[-4:]))


if __name__ == '__main__':
    unittest.main()
