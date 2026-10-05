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
