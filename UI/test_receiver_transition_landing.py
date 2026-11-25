"""Source handoff must land inside the selected Kiwi band, never stale USB RF."""
import unittest
from unittest.mock import Mock, patch
import kiwi_gl_display as ui


class ReceiverTransitionLandingTests(unittest.TestCase):
    def state(self, mode='am'):
        return ui.SharedState('http://kiwi.test:8073',1115,4,-95,142,245,4,mode,True)

    def test_stronger_out_of_band_signal_does_not_hide_am_station(self):
        state=self.state();state.set_server('http://next.test:8073',receiver_type='kiwi')
        values=[.05]*128
        values[5]=1.0  # ~258 kHz, outside AM landing band.
        values[60]=.8  # ~1064 kHz, inside AM landing band.
        result=ui.resolve_kiwi_landing_scan(state,values,.5)
        self.assertIsNotNone(result)
        self.assertEqual(result[0],'tuned')
        self.assertAlmostEqual(result[1],1064,delta=1)

    def test_only_out_of_band_signal_does_not_produce_false_landing(self):
        state=self.state();state.set_server('http://next.test:8073',receiver_type='kiwi')
        values=[.05]*128;values[5]=1.0
        self.assertIsNone(ui.resolve_kiwi_landing_scan(state,values,.5))
        self.assertEqual(ui.resolve_kiwi_landing_scan(state,values,2.1),('no_signal',1115))

    def test_usb_wfm_to_kiwi_arms_am_and_late_usb_restore_cannot_cancel_it(self):
        state=self.state('nbfm')
        with patch.object(ui.RTLSDRLab,'probe'):
            receiver=ui.RTLSDRLab(Mock(),state,Mock())
        receiver._restore_view=(7075,8)
        state.set_external_audio(True);state.set_external_waterfall(True)
        state.set_view(freq_khz=96300,zoom=5)
        state.set_server('http://next.test:8073',receiver_type='kiwi')
        self.assertEqual(state.radio_snapshot()[0],'am')
        self.assertFalse(state.external_audio_snapshot())
        self.assertFalse(state.external_waterfall_snapshot())
        landing=state.kiwi_landing_snapshot()
        self.assertTrue(landing['active']);self.assertEqual(landing['family'],'AM')
        receiver._restore_network_view()
        self.assertEqual(state.kiwi_landing_snapshot(),landing)
        values=[.05]*128;values[60]=.8
        self.assertEqual(ui.resolve_kiwi_landing_scan(state,values,.5)[0],'tuned')
