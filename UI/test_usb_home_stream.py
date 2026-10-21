"""USB source cadence and HOME mode agreement."""
import unittest
from unittest.mock import Mock, patch
import kiwi_gl_display as ui

class USBHomeStreamTests(unittest.TestCase):
    def test_home_fm_tap_selects_real_usb_demodulator(self):
        state=ui.SharedState('http://example.test:8073',100100.,8,-95.,142,245,4,'am',True)
        with patch.object(ui.RTLSDRLab,'probe'):
            receiver=ui.RTLSDRLab(Mock(),state,Mock())
        receiver.set_home_mode('AM')
        box=dict(ui.lcd_home_mode_boxes())['FM']
        mode=ui.engage_home_mode(state,(box[0]+box[2])/2,(box[1]+box[3])/2,local_receiver=receiver)
        self.assertIsNotNone(mode)
        self.assertEqual(receiver.demod_snapshot()[0],'fm')
        self.assertTrue(ui.mode_annunciator_active('FM',mode,'DIG'))

    def test_usb_fm_variants_keep_home_fm_highlight(self):
        for mode in ('NFM','WFM','NBFM'):
            with self.subTest(mode=mode):
                self.assertTrue(ui.mode_annunciator_active('FM',mode,'DIG'))

    def test_usb_unavailable_modes_are_dimmed_and_ignore_taps(self):
        state=ui.SharedState('http://example.test:8073',100100.,8,-95.,142,245,4,'am',True)
        receiver=Mock()
        buttons=list(ui.lcd_home_mode_boxes())
        with patch.object(ui,'draw_styled_button_frame') as frame, patch.object(ui,'draw_text') as text:
            ui.draw_home_mode_buttons(Mock(),buttons,'AM','DIG',usb_receiver=True)
            for (label,box),draw in zip(buttons,text.call_args_list):
                enabled=label in ('AM','FM')
                self.assertEqual(ui.home_mode_enabled(label,True),enabled)
                self.assertTrue(ui.home_mode_enabled(label,False))
                if not enabled:
                    self.assertEqual(draw.args[4],ui.APP_UI_STYLE.button.palette.untested_text)
                    self.assertIsNone(ui.engage_home_mode(state,(box[0]+box[2])/2,(box[1]+box[3])/2,local_receiver=receiver))
            receiver.set_home_mode.assert_not_called()

    def test_usb_peak_hold_expires_and_resets_on_resolution_change(self):
        state=ui.SharedState('http://example.test:8073',100100.,8,-95.,142,245,4,'am',True)
        with patch.object(ui.time,'monotonic',return_value=0):
            state.update_spectrum_values([0.9,0.2])
        with patch.object(ui.time,'monotonic',return_value=5):
            state.update_spectrum_values([0.1,0.8])
        self.assertEqual(state.spectrum_snapshot()[2],(0.9,0.8))
        with patch.object(ui.time,'monotonic',return_value=11):
            state.update_spectrum_values([0.3,0.4])
        self.assertEqual(state.spectrum_snapshot()[2],(0.3,0.8))
        with patch.object(ui.time,'monotonic',return_value=12):
            state.update_spectrum_values([0.5]*1024)
        self.assertEqual(state.spectrum_snapshot()[2],(0.5,)*1024)

    def test_usb_nfm_family_cycles_wfm_and_reopening_preserves_it(self):
        state=ui.SharedState('http://example.test:8073',100100.,8,-95.,142,245,4,'am',True)
        with patch.object(ui.RTLSDRLab,'probe'):
            receiver=ui.RTLSDRLab(Mock(),state,Mock())
        modes=dict(receiver.mode_families())['NFM']
        self.assertEqual(modes,('NFM','WFM'))
        self.assertEqual(ui.next_radio_mode_variant('NFM',modes),'WFM')
        self.assertEqual(ui.next_radio_mode_variant('WFM',modes),'NFM')
        self.assertTrue(receiver.set_home_mode('WFM'))
        box=dict(ui.lcd_home_mode_boxes())['FM']
        self.assertEqual(ui.engage_home_mode(state,(box[0]+box[2])/2,(box[1]+box[3])/2,local_receiver=receiver),'WFM')
        self.assertEqual(receiver.demod_snapshot()[0],'wbfm')

    def test_usb_fast_source_and_presenter_agree(self):
        self.assertEqual(ui.local_waterfall_fps(4),30)
        for speed in range(1,5):
            self.assertEqual(ui.local_waterfall_fps(speed),
                             ui.waterfall_presentation_fps('kiwi',speed,external=True))
        self.assertEqual(ui.waterfall_presentation_fps('kiwi',4),23)

if __name__=='__main__':unittest.main()
