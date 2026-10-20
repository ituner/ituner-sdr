"""Shared action placement must not obscure receiver and contact lists."""
import unittest
from unittest.mock import Mock

from adsb_layout import NEXT_BOX, PREVIOUS_BOX, SCAN_USB_BOX
from adsb_workspace import ADSBWorkspace


class ADSBListLayoutTests(unittest.TestCase):
    def setUp(self):
        ui = Mock()
        ui.fit_station_text.side_effect = lambda cache, text, *args: text
        self.manager = Mock()
        self.workspace = ADSBWorkspace(ui, self.manager)
        self.cache = Mock()

    def actions(self):
        return {action: box for box, action in self.workspace.actions}

    def test_receiver_logs_and_traffic_share_paging_controls(self):
        state = dict(selection='auto', devices=[], aircraft=[])
        self.manager.log_snapshot.return_value = dict(lines=[])
        self.workspace.draw_usb(self.cache, state)
        self.assertEqual(self.actions()[('scan', None)], SCAN_USB_BOX)
        for draw in (lambda: self.workspace.draw_usb(self.cache, state),
                     lambda: self.workspace.draw_logs(self.cache),
                     lambda: self.workspace.draw_traffic(self.cache, state)):
            self.workspace.actions = []
            draw()
            self.assertEqual(self.actions()[('page', -1)], PREVIOUS_BOX)
            self.assertEqual(self.actions()[('page', 1)], NEXT_BOX)
        for box in (SCAN_USB_BOX, PREVIOUS_BOX, NEXT_BOX):
            self.assertEqual(box[2] - box[0], 236)
            self.assertEqual(box[1:], (632, box[2], 688))

    def test_paging_and_sort_stay_inside_list_panel(self):
        state = dict(selection='auto', devices=[], aircraft=[])
        self.manager.log_snapshot.return_value = dict(lines=[])
        for draw in (lambda: self.workspace.draw_usb(self.cache, state),
                     lambda: self.workspace.draw_logs(self.cache),
                     lambda: self.workspace.draw_traffic(self.cache, state)):
            self.workspace.actions = []
            draw()
            for box, (kind, _) in self.workspace.actions:
                if kind in ('page', 'scan', 'sort', 'site'):
                    self.assertGreaterEqual(box[0], 32)
                    self.assertLessEqual(box[2], 992)
                    self.assertEqual(box[2]-box[0], 236)

    def test_contacts_remain_reachable_without_overlapping_paging(self):
        planes = [dict(hex=f'{i:06x}', seen=0) for i in range(9)]
        seen = []
        for page in range(3):
            self.workspace.actions = []
            self.workspace.traffic_page = page
            self.workspace.draw_traffic(self.cache, dict(aircraft=planes))
            for box, (kind, value) in self.workspace.actions:
                if kind == 'select':
                    self.assertLess(box[3], PREVIOUS_BOX[1])
                    self.assertEqual(box[3] - box[1], 64)
                    seen.append(value)
        self.assertEqual(seen, [plane['hex'] for plane in planes])


if __name__ == '__main__':
    unittest.main()
