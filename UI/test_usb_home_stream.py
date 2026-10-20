"""USB source cadence and HOME mode agreement."""
import unittest
from unittest.mock import Mock, patch
import kiwi_gl_display as ui

class USBHomeStreamTests(unittest.TestCase):
    def test_home_fm_tap_selects_real_usb_demodulator(self):
        state=ui.SharedState('http://example.test:8073',100100.,8,-95.,142,245,4,'am',True)
        with patch.object(ui.RTLSDRLab,'probe'):
            receiver=ui.RTLSDRLab(Mock(),state,Mock())
        box=dict(ui.lcd_home_mode_boxes())['FM']
        mode=ui.engage_home_mode(state,(box[0]+box[2])/2,(box[1]+box[3])/2,local_receiver=receiver)
        self.assertIsNotNone(mode)
        self.assertEqual(receiver.demod_snapshot()[0],'fm')
        self.assertTrue(ui.mode_annunciator_active('FM',mode,'DIG'))

    def test_usb_fm_variants_keep_home_fm_highlight(self):
        for mode in ('NFM','WFM','NBFM'):
            with self.subTest(mode=mode):
                self.assertTrue(ui.mode_annunciator_active('FM',mode,'DIG'))

    def test_usb_fast_source_and_presenter_agree(self):
        self.assertEqual(ui.local_waterfall_fps(4),30)
        for speed in range(1,5):
            self.assertEqual(ui.local_waterfall_fps(speed),
                             ui.waterfall_presentation_fps('kiwi',speed,external=True))
        self.assertEqual(ui.waterfall_presentation_fps('kiwi',4),23)

if __name__=='__main__':unittest.main()
