from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from qrss_decoder import MorseTiming
from qrss_text import presentation
from qrss_acquisition import AutoAcquisition


class PartialTests(unittest.TestCase):
    def test_unfinished_elements_are_not_guessed_letters(self):
        m=MorseTiming(3)
        m.feed(False,0);m.feed(True,3);m.feed(False,6)
        self.assertEqual(m.partial(),'.');self.assertFalse(m.events)
        m.feed(True,9)
        self.assertEqual(m.partial(),'. …');self.assertFalse(m.events)
        m.feed(False,18);self.assertEqual(m.partial(),'.-')
        m.feed(False,24)
        self.assertEqual(list(m.events),[(24,'A')]);self.assertEqual(m.partial(),'')

    def test_mid_mark_and_carrier_loss_do_not_invent_partials(self):
        m=MorseTiming(3);m.feed(True,0);m.feed(True,1)
        self.assertEqual(m.partial(),'')
        m.feed(False,3);self.assertEqual(m.partial(),'')
        m.feed(True,6);m.feed(False,9);self.assertEqual(m.partial(),'.')
        m.feed(None,10);self.assertEqual(m.partial(),'');self.assertFalse(m.events)

    def test_saved_vs_live_and_recognized_fragments(self):
        row=dict(mode='AUTO',kind='saved',tracks=[],tentative_text='',acquisition=dict(detail='Searching: waiting for consistent Morse transitions'))
        self.assertIn('no Morse timing lock',presentation(row)['text_message'])
        self.assertNotIn('waiting',presentation(row)['reception_detail'])
        self.assertIn('Searching',presentation(dict(row,kind='receiving'))['text_message'])
        self.assertEqual(presentation(dict(row,tentative_text='AB'))['text_message'],'AB')
        partial=presentation(dict(row,tracks=[dict(tentative_text='AB',partial_morse='.-')]))
        self.assertEqual(partial['tracks'][0]['display_text'],'AB  |  Unfinished Morse: .-')
        self.assertIn('disabled',presentation(dict(row,mode='VISUAL'))['text_message'])

    def test_partial_only_belongs_to_its_capture(self):
        a=AutoAcquisition([100,101,102],MorseTiming,1)
        a.tracks=[dict(id='T1',mode='CW',tone_hz=101,shift_hz=0,dot=3,timing_fit=.9,reverse=False,active=True,
                      events=[],partial_morse='.-',partial_when=150)]
        self.assertEqual(a.snapshot(100,160)[0]['partial_morse'],'.-')
        self.assertEqual(a.snapshot(0,100)[0]['partial_morse'],'')

if __name__=='__main__':unittest.main()
