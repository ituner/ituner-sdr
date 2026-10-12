"""Wide-band image geometry and decoder-slot mapping."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from cw_modes import PRESETS,bounds,display_bounds,signal_markers
from cw_decoder import CWDecoder
from cw_monitor import CWSession


class CWViewTests(unittest.TestCase):
    def test_wide_waterfall_does_not_expand_ggmorse_acquisition(self):
        config=dict(PRESETS[3]);engine=Mock()
        with patch('cw_decoder.MorseEngine',return_value=engine):
            decoder=CWDecoder(config)
            # A tone well outside GGMorse's 1 kHz decoding span must still be visible.
            audio=np.sin(np.arange(6000)*2*np.pi*2500/12000)*.3
            decoder.feed((audio*32767).astype('<i2').tobytes())
            self.assertEqual((decoder.low,decoder.high),(200,1200))
            self.assertEqual((decoder.view_low,decoder.view_high),(200,3200))
            hz=200+np.argmax(decoder.waterfall[-1])*3000/767
            self.assertAlmostEqual(hz,2500,delta=15)
            self.assertEqual(decoder.tracks,[])
            decoder.close()
        session=object.__new__(CWSession);session.config=config
        self.assertEqual(session.bandpass(),(150,3250))

    def test_markers_follow_frequency_selection_and_fading(self):
        row=dict(PRESETS[3],tracks=[
            dict(id='low',rf_hz=7024500,active=True),
            dict(id='mid',rf_hz=7026000,tone_hz=1700,active=True),
            dict(id='high',rf_hz=7027500,active=False),
            dict(id='outside',rf_hz=7029000,active=True)])
        markers=signal_markers(row,'mid')
        self.assertEqual([m['fraction'] for m in markers],[0,.5,1])
        self.assertEqual([m['slot'] for m in markers],[1,2,3])
        self.assertEqual([m['selected'] for m in markers],[False,True,False])
        self.assertFalse(markers[-1]['active'])

    def test_both_engines_show_same_overview_with_truthful_decode_range(self):
        self.assertEqual(display_bounds({'engine':'fldigi'}),display_bounds({'engine':'ggmorse'}))
        self.assertEqual(bounds({'engine':'fldigi'}),(200,3200))
        self.assertEqual(bounds({'engine':'ggmorse'}),(200,1200))

if __name__=='__main__':unittest.main()
