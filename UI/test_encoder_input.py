import unittest
from cm5_encoder_input import Quadrature


class DecoderTests(unittest.TestCase):
    def test_clockwise_and_counterclockwise(self):
        q = Quadrature(0)
        self.assertEqual(sum(q.feed(s) for s in [2, 3, 1, 0] * 10), 10)
        self.assertEqual(sum(q.feed(s) for s in [1, 3, 2, 0] * 10), -10)

    def test_contact_bounce_does_not_add_steps(self):
        q = Quadrature(0)
        self.assertEqual(sum(q.feed(s) for s in [2, 0, 2, 3, 2, 3, 1, 3, 1, 0]), 1)

    def test_partial_reversal_cancels(self):
        q = Quadrature(0)
        self.assertEqual(sum(q.feed(s) for s in [2, 3, 2, 0]), 0)

    def test_illegal_transition_and_resync_discard_partial(self):
        q = Quadrature(0)
        q.feed(2)
        self.assertEqual(q.feed(1), 0)
        self.assertEqual(q.partial, 0)
        q.feed(0)
        q.reset(3)
        self.assertEqual(q.partial, 0)
        self.assertEqual(sum(q.feed(s) for s in [1, 0, 2, 3]), 1)


if __name__ == '__main__':
    unittest.main()
