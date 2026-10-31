"""Connection-scoped waterfall command suppression, including failure recovery."""
import unittest

import kiwi_live_display_fb as kiwi


class Transport:
    def __init__(self):
        self.commands = []
        self.fail = None

    def send_text(self, command):
        if command == self.fail:
            raise OSError('injected write failure')
        self.commands.append(command)


class WaterfallProtocolTests(unittest.TestCase):
    def test_first_setup_then_only_changed_wire_values(self):
        ws = Transport()
        kiwi.send_wf_setup(ws, 7300, 8, 4)
        self.assertEqual(len(ws.commands), 5)
        kiwi.send_wf_setup(ws, 7300.0001, 8, 4)
        self.assertEqual(len(ws.commands), 5)
        kiwi.send_wf_setup(ws, 7400, 8, 4)
        self.assertEqual(ws.commands[5:], ['SET zoom=8 cf=7400.000'])
        kiwi.send_wf_setup(ws, 7400, 7, 4)
        self.assertEqual(ws.commands[-1], 'SET zoom=7 cf=7400.000')

    def test_rate_changes_restore_after_capture_and_are_not_resent(self):
        ws = Transport()
        kiwi.send_wf_setup(ws, 7300, 8, 2)
        kiwi.send_wf_setup(ws, 7400, 8, 4)
        kiwi.send_wf_speed(ws, 4)
        self.assertEqual(len(ws.commands), 7)
        kiwi.send_wf_setup(ws, 7300, 8, 2)
        self.assertEqual(ws.commands[-2:], ['SET zoom=8 cf=7300.000', 'SET wf_speed=2'])

    def test_each_connection_and_reauthentication_receives_complete_setup(self):
        first, second = Transport(), Transport()
        for ws in (first, second):
            kiwi.send_wf_setup(ws, 7300, 8, 4)
            self.assertEqual(len(ws.commands), 5)
        kiwi.send_kiwi_setup(first, 'kiwi', 'test')
        first.commands.clear()
        kiwi.send_wf_setup(first, 7300, 8, 4)
        self.assertEqual(len(first.commands), 5)

    def test_failed_write_is_retried_without_repeating_successful_settings(self):
        ws = Transport()
        ws.fail = 'SET wf_comp=0'
        with self.assertRaises(OSError):
            kiwi.send_wf_setup(ws, 7300, 8, 4)
        self.assertEqual(len(ws.commands), 3)
        ws.fail = None
        kiwi.send_wf_setup(ws, 7300, 8, 4)
        self.assertEqual(len(ws.commands), 5)

    def test_local_only_zoom_does_not_send_another_remote_zoom(self):
        ws = Transport()
        for zoom in (14, 15, 16):
            kiwi.send_wf_setup(ws, 7300, zoom, 4)
        self.assertEqual(len(ws.commands), 5)


if __name__ == '__main__':
    unittest.main()
