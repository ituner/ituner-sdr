import unittest
from cm5_encoder_input import Quadrature, DetentQuadrature, EncoderReader


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


class DetentDecoderTests(unittest.TestCase):
    def test_both_directions_from_every_starting_phase(self):
        cycle = [0, 2, 3, 1]
        for start in range(4):
            for direction in (1, -1):
                decoder = DetentQuadrature(cycle[start])
                states = [cycle[(start + direction * i) % 4] for i in range(1, 41)]
                self.assertEqual([decoder.feed(state) for state in states],
                                 [0, 0, 0, direction] * 10)

    def test_bounce_on_each_contact_does_not_reverse_direction(self):
        for direction, cycle in ((1, [0, 2, 3, 1, 0]), (-1, [0, 1, 3, 2, 0])):
            decoder = DetentQuadrature(0)
            result=[]
            for _ in range(50):
                for before, after in zip(cycle, cycle[1:]):
                    for state in (after, before, after, before, after):
                        result.append(decoder.feed(state))
            self.assertEqual([step for step in result if step], [direction] * 50)

    def test_skipped_phase_discards_partial_until_detent_then_recovers(self):
        decoder = DetentQuadrature(0)
        # Two bits change: an incomplete cycle must never turn into a step
        # at another phase, even when the following edges look legitimate.
        self.assertEqual([decoder.feed(s) for s in [2, 1, 0, 2, 3, 1]], [0] * 6)
        self.assertEqual(decoder.feed(0), 1)
        self.assertEqual(decoder.invalid_transitions, 1)
        self.assertEqual([decoder.feed(s) for s in [1, 3, 2, 0]], [0, 0, 0, -1])

    def test_partial_reversal_and_explicit_resync_do_not_emit_steps(self):
        decoder = DetentQuadrature(3)
        self.assertEqual([decoder.feed(s) for s in [1, 0, 1, 3]], [0] * 4)
        decoder.feed(1)
        decoder.reset(2)
        self.assertEqual([decoder.feed(s) for s in [3, 1, 0, 2]], [0, 0, 0, 1])

    def test_mechanical_reader_does_not_independently_debounce_channels(self):
        import inspect
        self.assertEqual(inspect.signature(EncoderReader).parameters['debounce_us'].default, 0)

    def test_reader_selects_full_detents_only_for_mechanical_inputs(self):
        from types import SimpleNamespace
        for edges, expected in ((4, DetentQuadrature), (1, Quadrature)):
            reader = EncoderReader.__new__(EncoderReader)
            reader.PAIRS = {'knob': (1, 2)}
            reader._lines = [1, 2]
            reader._edges_per_step = edges
            reader._value = SimpleNamespace(ACTIVE=1)
            reader._request = SimpleNamespace(get_values=lambda lines: [1, 1])
            reader._decoders = {}
            reader._resync()
            self.assertIsInstance(reader._decoders['knob'], expected)
            reader._decoders['knob'].feed(1)
            reader._resync()
            self.assertEqual(reader._decoders['knob'].partial, 0)


if __name__ == '__main__':
    unittest.main()
