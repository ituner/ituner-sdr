import unittest
from unittest import mock
import system_memory as memory


class SystemMemoryTests(unittest.TestCase):
    def test_reclaimable_cache_is_not_mistaken_for_used_ram(self):
        text = 'MemTotal: 4194304 kB\nMemAvailable: 2621440 kB\nMemFree: 524288 kB\nCached: 2097152 kB\n'
        self.assertEqual(memory.parse_meminfo(text), (1536, 4096))

    def test_missing_available_never_falls_back_to_process_memory(self):
        self.assertIsNone(memory.parse_meminfo('MemTotal: 4194304 kB\nMemFree: 500 kB'))
        self.assertIsNone(memory.parse_meminfo('MemAvailable: 500 kB'))

    def test_sampling_is_bounded_and_unavailable_does_not_leave_old_values(self):
        with mock.patch.object(memory, '_sampled_at', float('-inf')), \
             mock.patch.object(memory, '_sample', None), \
             mock.patch.object(memory.time, 'monotonic', side_effect=[0, 1, 2]), \
             mock.patch.object(memory.Path, 'read_text', side_effect=['MemTotal: 4194304 kB\nMemAvailable: 2621440 kB', OSError()]) as read:
            self.assertEqual(memory.system_ram_label(), 'RAM 1.5/4.0 GB')
            self.assertEqual(memory.system_ram_label(), 'RAM 1.5/4.0 GB')
            self.assertEqual(memory.system_ram_label(), 'RAM --')
            self.assertEqual(read.call_count, 2)
