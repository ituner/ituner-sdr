import struct
import unittest

from am_carrier import rf_view_center_hz
from smart_seek_waterfall import SeekWaterfall, PreviewLeveler


def frame(center=9455, zoom=9, sequence=1, bandwidth=30000000, zoom_max=14):
    first = rf_view_center_hz(center*1000, bandwidth, zoom)-bandwidth/(2**zoom)/2
    start = round(first*1024*2**zoom_max/bandwidth)
    samples = bytearray([120]*1024)
    index = round((center*1000-first)/(bandwidth/(2**zoom)/1024))
    samples[max(0, index-2):min(1024, index+3)] = bytes([240])*5
    return b'W/F\0'+struct.pack('<III', start, zoom, sequence)+bytes(samples)


class WaterfallTests(unittest.TestCase):
    def test_weak_sidebands_get_visible_contrast_in_the_first_row(self):
        samples = bytes([100]*400+[110]*100+[145]*12)
        floor, ceiling = PreviewLeveler().levels_for(samples)
        def brightness(value):
            return max(0, min(255, (value-floor)*255/(ceiling-floor)))
        self.assertGreater(brightness(110), 70)
        self.assertGreater(brightness(145), brightness(110))
        self.assertLess(brightness(100), brightness(110))

    def test_preview_levels_stay_bounded_and_follow_rf_changes_smoothly(self):
        leveler = PreviewLeveler()
        low, high = leveler.levels_for(bytes([100]*512))
        next_low, next_high = leveler.levels_for(bytes([140]*512))
        self.assertTrue(low < next_low < 135)
        self.assertTrue(high < next_high < 163)
        for value in (0, 255):
            floor, ceiling = PreviewLeveler().levels_for(bytes([value]*512))
            self.assertTrue(0 <= floor < ceiling <= 255)
            self.assertGreaterEqual(ceiling-floor, 28)

    def preview(self):
        preview = SeekWaterfall()
        preview.set(True, 9455, ('receiver',))
        self.assertEqual(preview.request(30000000, 14), (9455, 9))
        return preview

    def test_tuned_carrier_stays_at_center_and_queue_is_bounded(self):
        preview = self.preview()
        for i in range(100):
            preview.feed(frame(sequence=i), 30000000, 14, 14, i)
        generation, rows, center, span, updated = preview.take()
        self.assertEqual(len(rows), 32)
        self.assertEqual((center, span, updated), (9455, 50, 99))
        self.assertTrue(all(row[256] == 240 and row[0] == 120 and len(row) == 512 for row in rows))
        self.assertEqual(preview.take()[1], ())

    def test_inflight_scanner_rows_wrong_zoom_flags_and_duplicates_are_rejected(self):
        preview = self.preview()
        for packet in (frame(center=11900), frame(zoom=8), b'bad',
                       frame()[:8]+struct.pack('<I', 9 | (1 << 16))+frame()[12:]):
            preview.feed(packet, 30000000, 14, 14, 1)
        self.assertEqual(preview.take()[1], ())
        for sequence in (2, 2, 1, 3):
            preview.feed(frame(sequence=sequence), 30000000, 14, 14, 2)
        self.assertEqual(len(preview.take()[1]), 2)

    def test_retune_and_off_clear_history_and_invalidate_old_frames(self):
        preview = self.preview()
        preview.feed(frame(), 30000000, 14, 14, 1)
        generation = preview.generation
        preview.set(True, 9700, ('receiver', 'retuned'))
        preview.request(30000000, 14)
        preview.feed(frame(), 30000000, 14, 14, 2)
        self.assertGreater(preview.generation, generation)
        self.assertEqual(preview.take()[1], ())
        preview.set(False)
        self.assertIsNone(preview.request(30000000, 14))
        self.assertIsNone(preview.last_frame_at)

    def test_zoom_cap_is_respected_without_widening_the_display(self):
        preview = self.preview()
        self.assertEqual(preview.request(30000000, 8), (9455, 8))
        preview.feed(frame(zoom=8), 30000000, 14, 8, 1)
        self.assertEqual(len(preview.take()[1]), 1)


if __name__ == '__main__':
    unittest.main()
