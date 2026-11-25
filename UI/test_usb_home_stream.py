"""USB source cadence and HOME mode agreement."""
import unittest
from unittest.mock import Mock, patch
import kiwi_gl_display as ui

class USBHomeStreamTests(unittest.TestCase):
    def test_scan_silence_blocks_already_queued_pcm_at_output(self):
        from types import SimpleNamespace
        player=object.__new__(ui.BufferedAudioPlayer)
        player.player=Mock();player.state=Mock();player.state.external_audio_snapshot.return_value=True
        player.state.local_signal_search=SimpleNamespace(silent=True)
        player._smooth_concealment_edge=lambda audio,*args:audio
        player._write(b'\x11\x22'*64,comfort_noise=True)
        player.player.stdin.write.assert_called_once_with(bytes(128))

    def test_scan_silence_gates_pcm_without_changing_user_mute(self):
        from types import SimpleNamespace
        state=ui.SharedState('http://example.test:8073',94900.,8,-95.,142,245,4,'am',True)
        state.local_signal_search=SimpleNamespace(silent=True)
        with patch.object(ui.RTLSDRLab,'probe'):receiver=ui.RTLSDRLab(Mock(),state,Mock())
        pcm=b'\x01\x02'*100
        self.assertEqual(receiver._apply_local_squelch(pcm),bytes(len(pcm)))
        self.assertFalse(state.audio_controls_snapshot()[0]['mute'])
        state.local_signal_search.silent=False
        self.assertEqual(receiver._apply_local_squelch(pcm),pcm)

    def test_restored_usb_modes_light_home_family_indicator(self):
        for mode in ('AM', 'NFM', 'WFM'):
            with patch.object(ui, 'draw_radio_family_option') as draw, patch.object(ui, 'draw_styled_two_line_button'):
                ui.draw_home_mode_buttons(Mock(), list(ui.lcd_home_mode_boxes()), mode, 'DIG', usb_receiver=True, family_selector=True)
            active=[call.args[2] for call in draw.call_args_list if call.args[4] in call.args[3]]
            self.assertEqual(active, ['AM' if mode=='AM' else 'FM'])
            fm=next(call for call in draw.call_args_list if call.args[2]=='FM')
            self.assertEqual(fm.args[3], ('NFM','WFM'))

    def test_selected_mode_survives_stop_start_and_saved_restore(self):
        import threading
        for mode in ('AM', 'NFM', 'WFM'):
            state=ui.SharedState('http://example.test:8073',94900.,8,-95.,142,245,4,'am',True)
            with patch.object(ui.RTLSDRLab,'probe'):
                receiver=ui.RTLSDRLab(Mock(),state,Mock())
                restored=ui.RTLSDRLab(Mock(),state,Mock())
            receiver.present=True
            receiver.receiver_selection='serial:abc'
            receiver.set_home_mode(mode)
            with patch.object(threading,'Thread'):
                receiver.start(94900.,8)
                self.assertEqual(receiver.current_home_mode(),mode)
                saved=receiver.validate_remembered_receiver(receiver.remembered_receiver())
                self.assertEqual(saved['mode'],mode)
                receiver.thread=None
                receiver.start(94900.,8)
                self.assertEqual(receiver.current_home_mode(),mode)
                restored.source_inventory={restored.source_id:dict(present=True,device='Test',tuner='',detail='')}
                self.assertTrue(restored.restore_receiver(saved))
                self.assertEqual(restored.current_home_mode(),mode)

    def test_failed_usb_open_releases_lease_without_resuming_kiwi(self):
        import threading
        from sdr_broker import ReceiverBroker
        state=ui.SharedState('http://example.test:8073',1104.7,7,-95.,142,245,4,'am',True)
        state.set_external_audio(True);state.set_external_waterfall(True)
        with patch.object(ui.RTLSDRLab,'probe'):
            receiver=ui.RTLSDRLab(Mock(),state,Mock())
        receiver.receiver_broker=ReceiverBroker()
        receiver.receiver_devices=lambda:[dict(id='serial:abc',serial='abc',persistent=True,index=0)]
        receiver._restore_view=(1104.7,7)
        receiver._remembered_usb_receiver=dict(source_id=receiver.source_id,freq_khz=100100,zoom=8,preset_index=0)
        library=Mock();library.rtlsdr_get_index_by_serial.return_value=0;library.rtlsdr_open.return_value=-1
        with patch.object(receiver,'_librtlsdr',return_value=library),patch.object(ui,'configure_realtime_audio_path'),patch.object(ui,'release_realtime_audio_thread'),patch('builtins.print'):
            receiver._iq_worker('Test',12000)
        self.assertEqual(receiver.snapshot()['status'],'ERROR')
        self.assertTrue(state.external_audio_snapshot());self.assertTrue(state.external_waterfall_snapshot())
        self.assertEqual(receiver.receiver_broker.snapshot(),{})
        receiver.stop()
        self.assertFalse(state.external_audio_snapshot());self.assertFalse(state.external_waterfall_snapshot())

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
