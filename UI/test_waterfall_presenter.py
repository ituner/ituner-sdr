"""Replay real slow-stream jitter and changing receive conditions."""
import contextlib
import io
import queue
import unittest

from waterfall_presenter import WaterfallPresenter


def replay(arrivals, duration=30, hint=23):
    presenter = WaterfallPresenter()
    pending = queue.Queue()
    index, peak_depth = 0, 0
    shown, rates = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        for frame in range(round(duration * 30) + 1):
            now = frame / 30
            while index < len(arrivals) and arrivals[index] <= now:
                pending.put(index)
                index += 1
            peak_depth = max(peak_depth, pending.qsize())
            rows = presenter.take(pending, now, hint, 'receiver')
            shown.extend((now, value) for value in rows)
            rates.append((now, presenter.source_fps))
    return presenter, shown, peak_depth, rates


class AdaptiveWaterfallTests(unittest.TestCase):
    def assert_ordered_real_rows(self, shown):
        self.assertEqual([value for _, value in shown], list(range(len(shown))))

    def test_five_fps_receiver_does_not_refill_at_twenty_three_fps(self):
        p, shown, depth, _ = replay([n / 5 for n in range(150)])
        self.assertAlmostEqual(p.source_fps, 5, delta=.15)
        self.assertEqual(p.underruns, 0)
        self.assertLessEqual(depth, 3)
        self.assert_ordered_real_rows(shown)
        gaps = [b[0] - a[0] for a, b in zip(shown, shown[1:]) if a[0] > 1]
        self.assertLess(max(gaps), .25)
        self.assertGreaterEqual(len(shown), 148)

    def test_measured_cm5_arrival_jitter_stays_smooth(self):
        # Packet gaps measured passively on CM5's existing Romania stream.
        gaps_ms = (212.4, 231.1, 203.9, 202.5, 178.7, 188.1, 207.8,
                   207.3, 212.7, 209.8, 153.6, 204.8, 225.9, 242.4,
                   213.8, 209.2, 257.0, 200.2, 205.6, 234.1, 220.7,
                   178.4, 236.4, 183.0, 228.8, 214.9, 184.3, 208.2,
                   201.0, 219.2, 228.6, 215.1, 204.0, 193.6, 205.5)
        arrivals = [0.0]
        for gap in gaps_ms * 4:
            arrivals.append(arrivals[-1] + gap / 1000)
        p, shown, depth, _ = replay(arrivals, duration=arrivals[-1] + .05)
        self.assertEqual(p.underruns, 0)
        self.assertLessEqual(depth, 4)
        self.assert_ordered_real_rows(shown)
        self.assertLess(max(b[0] - a[0] for a, b in zip(shown, shown[1:])), .35)

    def test_normal_fast_receiver_keeps_a_small_jitter_reserve(self):
        p, shown, depth, _ = replay([n / 23 for n in range(690)])
        self.assertAlmostEqual(p.source_fps, 23, delta=.3)
        self.assertEqual(p.underruns, 0)
        self.assertLessEqual(depth, 10)
        self.assertGreaterEqual(len(shown), 680)
        self.assert_ordered_real_rows(shown)

    def test_network_batches_are_spread_out_instead_of_drawn_together(self):
        p, shown, depth, _ = replay([n * .5 for n in range(60) for _ in range(12)])
        self.assertAlmostEqual(p.source_fps, 24, delta=.3)
        self.assertLessEqual(depth, 14)
        self.assert_ordered_real_rows(shown)
        self.assertLess(max(b[0] - a[0] for a, b in zip(shown, shown[1:])), .15)

    def test_rate_changes_down_and_up_without_growing_a_backlog(self):
        arrivals = ([n / 23 for n in range(230)] +
                    [10 + n / 5 for n in range(50)] +
                    [20 + n / 13 for n in range(130)])
        p, shown, depth, rates = replay(arrivals)
        rates = dict(rates)
        self.assertAlmostEqual(rates[19], 5, delta=.3)
        self.assertAlmostEqual(rates[29], 13, delta=.3)
        self.assertLessEqual(depth, 16)
        self.assertGreaterEqual(len(shown), len(arrivals) - 8)
        self.assert_ordered_real_rows(shown)
        self.assertLess(max(b[0] - a[0] for a, b in zip(shown, shown[1:])), .35)

    def test_very_slow_receiver_does_not_wait_for_six_rows(self):
        _, shown, _, _ = replay([0, 2, 4, 6], duration=7)
        self.assertEqual(len(shown), 4)
        self.assertLess(shown[0][0], .5)
        self.assert_ordered_real_rows(shown)

    def test_real_outage_preserves_rows_and_resumes_without_catchup_jump(self):
        arrivals = [n / 5 for n in range(25)] + [10 + n / 5 for n in range(50)]
        _, shown, depth, _ = replay(arrivals, duration=21)
        self.assertEqual(len(shown), len(arrivals))
        self.assertLessEqual(depth, 4)
        self.assert_ordered_real_rows(shown)
        per_frame = {}
        for now, _ in shown:
            per_frame[now] = per_frame.get(now, 0) + 1
        self.assertLessEqual(max(per_frame.values()), 2)

    def test_new_receiver_discards_previous_timing_estimate(self):
        p = WaterfallPresenter()
        pending = queue.Queue()
        with contextlib.redirect_stdout(io.StringIO()):
            for frame in range(120):
                if frame % 6 == 0:
                    pending.put(frame)
                p.take(pending, frame / 30, 23, 'slow')
        self.assertAlmostEqual(p.source_fps, 5, delta=.2)
        while not pending.empty():
            pending.get_nowait()
        self.assertEqual(p.take(pending, 4, 13, 'other-receiver'), ())
        self.assertEqual(p.source_fps, 13)
        self.assertEqual(p.received_rows, 0)
        self.assertFalse(p.started)


if __name__ == '__main__':
    unittest.main()
