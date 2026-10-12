import socket
import struct
import unittest

import kiwi_live_display_fb as kiwi


class ScriptedSocket:
    def __init__(self, events):
        self.events = list(events)

    def recv(self, _count):
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


class KiwiTransportTests(unittest.TestCase):
    def test_zero_external_capacity_is_a_permanent_access_policy_error(self):
        with self.assertRaises(kiwi.KiwiExternalApiDisabledError):
            kiwi.raise_for_kiwi_server_message({'too_busy': '0'})

    def test_positive_external_capacity_is_a_temporary_busy_error(self):
        with self.assertRaises(kiwi.KiwiServerBusyError) as raised:
            kiwi.raise_for_kiwi_server_message({'too_busy': '4'})
        self.assertEqual(raised.exception.capacity, 4)

    def test_unrelated_server_message_is_ignored(self):
        self.assertIsNone(kiwi.raise_for_kiwi_server_message({'sample_rate': '12000'}))

    def test_partial_frame_read_survives_socket_timeout(self):
        sock = ScriptedSocket((b'ab', socket.timeout(), b'cd'))
        self.assertEqual(kiwi.recv_exact(sock, 4), b'abcd')

    def test_idle_socket_timeout_still_returns_control_to_worker(self):
        sock = ScriptedSocket((socket.timeout(),))
        with self.assertRaises(socket.timeout):
            kiwi.recv_exact(sock, 2)

    def test_corrupt_huge_frame_length_is_rejected_before_payload_read(self):
        declared = kiwi.WEBSOCKET_MAX_FRAME_BYTES + 1
        sock = ScriptedSocket((b'\x82\x7f', struct.pack('>Q', declared)))
        with self.assertRaisesRegex(ValueError, 'frame too large'):
            kiwi.KiwiWebSocket(sock).recv()


class KiwiOccupancyTransportTests(unittest.TestCase):
    def message(self, payload):
        payload = b'MSG ' + payload
        return (bytes((0x82, len(payload))), payload)

    def test_only_authenticated_connections_request_users(self):
        from unittest.mock import patch
        from kiwi_occupancy import OccupancyCache
        cache = OccupancyCache()
        sock = ScriptedSocket(self.message(b'badp=1') + self.message(b'badp=0'))
        ws = kiwi.KiwiWebSocket(sock, 'http://kiwi', 'SND')
        with patch.object(kiwi, 'occupancy', cache), patch.object(ws, 'send_text') as send:
            ws.recv()
            send.assert_not_called()
            ws.recv()
            send.assert_called_once_with('SET GET_USERS')

    def test_sound_and_waterfall_share_requests_and_publish_counts(self):
        from unittest.mock import patch
        from kiwi_occupancy import OccupancyCache
        cache = OccupancyCache()
        snd = kiwi.KiwiWebSocket(ScriptedSocket(self.message(b'badp=0') +
            self.message(b'user_cb=[{"i":0,"n":""},{"i":1}]')), 'http://kiwi', 'SND')
        wf = kiwi.KiwiWebSocket(ScriptedSocket(self.message(b'badp=0')), 'http://kiwi', 'W/F')
        with patch.object(kiwi, 'occupancy', cache), patch.object(snd, 'send_text') as sound_send, patch.object(wf, 'send_text') as wf_send:
            snd.recv()
            wf.recv()
            snd.recv()
            sound_send.assert_called_once_with('SET GET_USERS')
            wf_send.assert_not_called()
            self.assertEqual(cache.snapshot('http://kiwi'), (1, 2))
