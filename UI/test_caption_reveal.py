import unittest
from caption_reveal import CaptionReveal


class CaptionRevealTests(unittest.TestCase):
    def test_words_appear_one_at_a_time(self):
        r = CaptionReveal()
        self.assertEqual(r.reveal('one two three', now=0), 'one')
        self.assertEqual(r.reveal('one two three', now=.13), 'one two')
        self.assertEqual(r.reveal('one two three', now=.26), 'one two three')

    def test_idle_does_not_bank_time_for_next_batch(self):
        r = CaptionReveal()
        r.reveal('one', now=0)
        self.assertEqual(r.reveal('one two three', now=100), 'one')
        self.assertEqual(r.reveal('one two three', now=100.13), 'one two')

    def test_revised_partial_preserves_stable_prefix(self):
        r = CaptionReveal()
        r.reveal('hello wrong word', now=0)
        r.reveal('hello wrong word', now=.13)
        self.assertEqual(r.reveal('hello radio operator', now=.14), 'hello')
        self.assertEqual(r.reveal('hello radio operator', now=.27), 'hello radio')

    def test_finalizing_unchanged_partial_does_not_replay(self):
        r = CaptionReveal()
        r.reveal('hello radio', now=0)
        r.reveal('hello radio', now=.13)
        self.assertEqual(r.reveal('hello radio', now=.14), 'hello radio')

    def test_rolling_history_preserves_visible_progress(self):
        r = CaptionReveal()
        r.reveal('old phrase newer phrase', now=0)
        r.reveal('old phrase newer phrase', now=1)
        self.assertEqual(r.reveal('newer phrase fresh words', now=1.01), 'newer phrase')

    def test_large_batch_catches_up_within_one_second(self):
        r = CaptionReveal()
        text = ' '.join(str(n) for n in range(100))
        r.reveal(text, now=0)
        for frame in range(1, 34):
            visible = r.reveal(text, now=frame / 30)
        self.assertEqual(visible, text)

    def test_reset_clears_old_session_and_channels_are_independent(self):
        r = CaptionReveal()
        r.reset_for(('vosk', 1))
        r.reveal('old words', now=0)
        self.assertEqual(r.reveal('translated words', 'english', now=.13), 'translated')
        r.reset_for(('vosk', 2))
        self.assertEqual(r.reveal('fresh text', now=10), 'fresh')

    def test_empty_text_clears_display(self):
        r = CaptionReveal()
        r.reveal('hello radio', now=0)
        self.assertEqual(r.reveal('', now=.1), '')
