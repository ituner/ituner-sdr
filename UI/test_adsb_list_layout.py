"""Shared action placement must not obscure receiver and contact lists."""
import unittest
from unittest.mock import Mock

import UI.test_adsb as adsb_tests


class ADSBListLayoutTests(unittest.TestCase):
    def setUp(self):
        self.workspace, self.ui, self.manager, self.state = adsb_tests.WorkspaceTests().dashboard()
        self.cache = Mock()

    def actions(self):
        return {action: box for box, action in self.workspace.actions}

    def test_receiver_and_list_paging_preserve_their_content_layout(self):
        self.workspace.draw_usb(self.cache, self.state)
        self.assertEqual(self.actions()[('dongles', None)], (40,636,420,692))
        self.assertEqual(self.actions()[('page', -1)], (436,636,824,692))
        self.assertEqual(self.actions()[('page', 1)], (840,636,1240,692))
        for draw in (lambda: self.workspace.draw_logs(self.cache),
                     lambda: self.workspace.draw_traffic(self.cache, self.state)):
            self.workspace.actions = []
            draw()
            self.assertEqual(self.actions()[('page', -1)], (40,636,344,692))
            self.assertEqual(self.actions()[('page', 1)], (936,636,1240,692))

    def test_paging_and_sort_stay_inside_list_panel(self):
        for draw in (lambda: self.workspace.draw_usb(self.cache, self.state),
                     lambda: self.workspace.draw_logs(self.cache),
                     lambda: self.workspace.draw_traffic(self.cache, self.state)):
            self.workspace.actions = []
            draw()
            for box, (kind, _) in self.workspace.actions:
                if kind in ('page', 'dongles', 'sort', 'site'):
                    self.assertGreaterEqual(box[0], 40)
                    self.assertLessEqual(box[2], 1240)
                    if kind == 'sort':
                        self.assertEqual(box, (936,162,1240,218))
                    elif kind in ('page', 'dongles'):
                        self.assertEqual((box[1], box[3]), (636,692))

    def test_contacts_remain_reachable_without_overlapping_paging(self):
        planes = [dict(hex=f'{i:06x}', seen=0) for i in range(9)]
        seen = []
        for page in range(2):
            self.workspace.actions = []
            self.workspace.traffic_page = page
            self.workspace.draw_traffic(self.cache, dict(aircraft=planes))
            for box, (kind, value) in self.workspace.actions:
                if kind == 'select':
                    self.assertLess(box[3], 636)
                    self.assertEqual(box[3] - box[1], 72)
                    seen.append(value)
        self.assertEqual(seen, [plane['hex'] for plane in planes])


if __name__ == '__main__':
    unittest.main()
