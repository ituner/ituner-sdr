import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from knob_input import AXES, BUTTON_DEVICE, EVENT, KnobDecoder, KnobEvent, LinuxKnobReader


class KnobInputTests(unittest.TestCase):
    def test_only_matching_named_device_axis_is_accepted(self):
        decoder = KnobDecoder()
        for name, (role, axis) in AXES.items():
            self.assertEqual(decoder.feed(name, 2, axis, -3, 1), [KnobEvent(role, 'turn', -3)])
            self.assertEqual(decoder.feed('mouse', 2, axis, 1, 1), [])
            self.assertEqual(decoder.feed(name, 2, 99, 1, 1), [])

    def test_short_and_long_press_do_not_double_activate(self):
        decoder = KnobDecoder()
        decoder.feed(BUTTON_DEVICE, 1, 256, 1, 0)
        self.assertEqual(decoder.feed(BUTTON_DEVICE, 1, 256, 0, .2), [KnobEvent('VIEW', 'click')])
        decoder.feed(BUTTON_DEVICE, 1, 257, 1, 1)
        self.assertEqual(decoder.poll(1.7), [KnobEvent('NAV', 'hold')])
        self.assertEqual(decoder.poll(2), [])
        self.assertEqual(decoder.feed(BUTTON_DEVICE, 1, 257, 0, 2), [])

    def test_repeat_and_unpaired_release_are_ignored(self):
        decoder = KnobDecoder()
        self.assertEqual(decoder.feed(BUTTON_DEVICE, 1, 256, 0, 0), [])
        decoder.feed(BUTTON_DEVICE, 1, 256, 1, 1)
        decoder.feed(BUTTON_DEVICE, 1, 256, 2, 1.3)
        self.assertEqual(decoder.feed(BUTTON_DEVICE, 1, 256, 0, 1.8), [KnobEvent('VIEW', 'hold')])

    def test_disconnect_and_dropped_sync_cancel_pending_buttons(self):
        for disconnect in (True, False):
            decoder = KnobDecoder()
            decoder.feed(BUTTON_DEVICE, 1, 257, 1, 1)
            if disconnect:
                decoder.disconnect(BUTTON_DEVICE)
            else:
                decoder.feed(BUTTON_DEVICE, 0, 3, 0, 1.1)
                decoder.feed(BUTTON_DEVICE, 1, 257, 1, 1.2)
                decoder.feed(BUTTON_DEVICE, 0, 0, 0, 1.3)
            self.assertEqual(decoder.poll(2), [])
            self.assertEqual(decoder.feed(BUTTON_DEVICE, 1, 257, 0, 2), [])

    def test_reader_discovers_stable_names_and_recovers_after_disconnect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            node = root / 'event9/device'
            node.mkdir(parents=True)
            (node / 'name').write_text('ituner-tune-encoder\n')
            reader = LinuxKnobReader(root, '/test/input')
            read_fd, write_fd = os.pipe()
            os.set_blocking(read_fd, False)
            with patch('knob_input.os.open', return_value=read_fd), patch('knob_input.fcntl.ioctl'):
                self.assertEqual(reader.poll(0), [])
                os.write(write_fd, EVENT.pack(0, 0, 2, 7, 2))
                self.assertEqual(reader.poll(.1), [KnobEvent('TUNE', 'turn', 2)])
                os.close(write_fd)
                reader.poll(.2)
                self.assertEqual(reader.devices, {})
            replacement_fd, replacement_writer = os.pipe()
            os.set_blocking(replacement_fd, False)
            with patch('knob_input.os.open', return_value=replacement_fd), patch('knob_input.fcntl.ioctl'):
                reader.poll(3)
                os.write(replacement_writer, EVENT.pack(3, 0, 2, 7, -1))
                self.assertEqual(reader.poll(3.1), [KnobEvent('TUNE', 'turn', -1)])
            reader.close()
            os.close(replacement_writer)

    def test_permission_failure_does_not_stop_ui(self):
        with tempfile.TemporaryDirectory() as directory:
            node = Path(directory) / 'event7/device'
            node.mkdir(parents=True)
            (node / 'name').write_text(BUTTON_DEVICE)
            reader = LinuxKnobReader(directory)
            with patch('knob_input.os.open', side_effect=PermissionError('denied')):
                self.assertEqual(reader.poll(0), [])
            self.assertTrue(reader.errors)
            reader.close()
