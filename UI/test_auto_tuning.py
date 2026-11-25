import unittest
from optical_tuning import OpticalTuning, step_hz
from cm5_encoder_input import Quadrature


class AutoTuningTests(unittest.TestCase):
    def setUp(self):
        self.tuner = OpticalTuning()

    def target(self, frequency, counts, span=3800000, mode='auto', sensitivity='normal', manual=100):
        return self.tuner.target(frequency, counts, span, mode, sensitivity, manual, 'kiwi', 0, 30000)

    def test_full_edge_resolution(self):
        decoder = Quadrature(0, edges_per_step=1)
        self.assertEqual(sum(decoder.feed(s) for s in [2, 3, 1, 0] * 360), 1440)
        self.assertEqual(sum(decoder.feed(s) for s in [1, 3, 2, 0] * 360), -1440)

    def test_one_turn_matches_quarter_span_at_every_zoom(self):
        for span in (3800000, 38000, 3800, 37):
            with self.subTest(span=span):
                self.tuner.reset()
                f = 1000.
                for _ in range(1440):
                    f = self.target(f, 1, span=span)
                self.assertAlmostEqual(f, 1000 + int(span / 4) / 1000, places=7)

    def test_manual_independent_of_zoom_with_sensitivity(self):
        self.assertEqual(step_hz(3800000, 'manual', 'fine', 10), 1)
        self.assertEqual(step_hz(38, 'manual', 'fine', 10), 1)
        self.assertEqual(step_hz(38, 'manual', 'coarse', 10), 40)
        self.assertAlmostEqual(self.target(1000, 1440, mode='manual', manual=10), 1014.4)

    def test_one_hertz_manual_fine_accumulates_and_reverses(self):
        f = 1000.
        for _ in range(9):
            f = self.target(f, 1, mode='manual', sensitivity='fine', manual=1)
        self.assertEqual(f, 1000.)
        f = self.target(f, 1, mode='manual', sensitivity='fine', manual=1)
        self.assertAlmostEqual(f, 1000.001)
        for _ in range(10):
            f = self.target(f, -1, mode='manual', sensitivity='fine', manual=1)
        self.assertAlmostEqual(f, 1000.)
        self.assertAlmostEqual(self.tuner.remainder, 0.)

    def test_manual_coarse_and_sensitivity_change_clear_fraction(self):
        self.target(1000., 9, mode='manual', sensitivity='fine', manual=1)
        f = self.target(1000., 1, mode='manual', sensitivity='coarse', manual=1)
        self.assertAlmostEqual(f, 1000.004)
        self.assertAlmostEqual(self.tuner.remainder, 0.)

    def test_fmdx_fine_retains_receiver_grid(self):
        f = 100000.
        for _ in range(10):
            f = self.tuner.target(f, 1, 100, 'manual', 'fine', 50000,
                                  'fmdx', 64000, 108000, quantum_hz=50000)
        self.assertEqual(f, 100050.)

    def test_auto_does_not_depend_on_manual_step(self):
        self.assertEqual(step_hz(3800000, manual_hz=1), step_hz(3800000, manual_hz=100000))

    def test_fine_and_coarse(self):
        normal = step_hz(3800000)
        self.assertAlmostEqual(step_hz(3800000, sensitivity='fine'), normal / 10)
        self.assertAlmostEqual(step_hz(3800000, sensitivity='coarse'), normal * 4)

    def test_fractional_movement_and_reverse_correction(self):
        f = 1000.
        for _ in range(100):
            f = self.target(f, 1, span=38)
        self.assertEqual(f, 1000.)
        for _ in range(100):
            f = self.target(f, -1, span=38)
        self.assertAlmostEqual(self.tuner.remainder, 0)
        self.assertEqual(f, 1000.)

    def test_external_retune_discards_old_fraction(self):
        self.target(1000, 100, span=38)
        self.target(2000, 1, span=38)
        self.assertAlmostEqual(self.tuner.remainder, step_hz(38))

    def test_zoom_change_discards_old_fraction(self):
        self.target(1000, 100, span=38)
        self.target(1000, 1, span=3.8)
        self.assertAlmostEqual(self.tuner.remainder, step_hz(3.8))

    def test_limit_has_no_backlog(self):
        f = self.target(29999, 1440)
        self.assertEqual(f, 30000)
        self.assertEqual(self.tuner.remainder, 0)
        self.assertLess(self.target(f, -1), f)

    def test_receiver_quantization(self):
        f = self.tuner.target(100000, 1, 100, 'manual', 'normal', 50000,
                              'fmdx', 64000, 108000, quantum_hz=50000)
        self.assertEqual(f, 100050)


if __name__ == '__main__':
    unittest.main()
