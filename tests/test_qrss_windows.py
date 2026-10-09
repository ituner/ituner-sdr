"""Streaming acquisition after interference, cadence changes and long dots."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from qrss_acquisition import AutoAcquisition
from qrss_decoder import MorseTiming
from test_qrss_auto import keying


class WindowTests(unittest.TestCase):
    def make(self):
        self.freq=np.arange(1400.,1600.,1.)
        self.rng=np.random.default_rng(912)
        return AutoAcquisition(self.freq,MorseTiming,.5)

    def feed(self,a,start,end,dot=None,origin=0):
        for t in np.arange(start,end,.5):
            db=self.rng.normal(0,1.5,len(self.freq))
            if dot is not None:
                tone=1550 if keying(t-origin,dot) else 1540
                db[abs(self.freq-tone)<.6]=30
            a.feed(t,db)

    def test_short_burst_acquires_after_long_noise_and_survives_fade(self):
        a=self.make()
        self.feed(a,0,600)
        self.feed(a,600,800,4.3,600)
        self.assertEqual(a.status['state'],'locked')
        self.assertAlmostEqual(a.status['dot_seconds'],4.3,delta=.3)
        self.assertLessEqual(a.status['acquisition_seconds'],240)
        text=''.join(c for _,c in a.events)
        self.assertIn('SOS',text)
        self.feed(a,800,1000)
        self.assertEqual(a.status['state'],'searching')
        self.assertTrue(''.join(c for _,c in a.events).startswith(text))
        settled=list(a.events)
        self.feed(a,1000,1100)
        self.assertEqual(list(a.events),settled)

    def test_new_cadence_reacquires_without_erasing_previous_message(self):
        a=self.make()
        self.feed(a,0,400,4.3)
        old=[e for e in a.events if e[0]<350]
        self.feed(a,400,600)
        self.feed(a,600,930,7.2,600)
        self.assertEqual(a.status['state'],'locked')
        self.assertAlmostEqual(a.status['dot_seconds'],7.2,delta=.4)
        self.assertEqual([e for e in a.events if e[0]<350],old)
        self.assertIn('SOS',''.join(c for t,c in a.events if t>600))

    def test_overlapping_replays_do_not_duplicate_or_drop_letters(self):
        a=self.make()
        self.feed(a,0,1701,4.3)
        reference=MorseTiming(4.3)
        for t in np.arange(0,1700.1,.5):reference.feed(bool(keying(t,4.3)),t)
        self.assertEqual(''.join(c for _,c in a.events),''.join(c for _,c in reference.events))

    def test_slow_cadences_still_use_long_evidence(self):
        for dot in (60,90):
            with self.subTest(dot=dot):
                a=self.make()
                self.feed(a,0,1800,dot)
                self.assertEqual(a.status['state'],'locked')
                self.assertAlmostEqual(a.status['dot_seconds'],dot,delta=1)
                self.assertGreater(a.status['acquisition_seconds'],480)

if __name__=='__main__':unittest.main()
