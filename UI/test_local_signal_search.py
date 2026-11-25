import unittest
from types import SimpleNamespace
import numpy as np
from local_signal_search import candidates, LocalSignalSearch

class SignalSearchTests(unittest.TestCase):
    def test_wfm_rejects_narrow_carrier_but_finds_broad_signal(self):
        power=np.full(2048,-60.);power[1040]=0
        self.assertEqual(candidates(power,94900,1024,'WFM'),[])
        power[1250:1430]=-40
        found=candidates(power,94900,1024,'WFM')
        self.assertTrue(any(abs(f-95100)<100 for f in found))
    def test_am_peak_and_bounds(self):
        power=np.full(2048,-60.);power[1200]=-30
        self.assertEqual(candidates(power,25000,1024,'AM'),[25088.])
    def make_search(self):
        class State:
            freq=94900.;generation=0
            def snapshot(self):return '',self.freq,4,0,self.generation,0
            def set_view(self,freq_khz):self.freq=freq_khz;self.generation+=1
            def stream_paused_snapshot(self):return False
        state=State();lab=SimpleNamespace(current_home_mode=lambda:'WFM',source_id='rtl-sdr',receiver_selection='a',tuning_bounds=lambda:(24000,1700000),source_span_khz=lambda:1024.,snapshot=lambda:{'status':'LIVE'},signal_snapshot=lambda:None)
        return LocalSignalSearch(lab,state),state,lab
    def test_scan_cancel_restores_and_manual_change_cancels_without_overwrite(self):
        search,state,lab=self.make_search();search.toggle_scan(1)
        self.assertTrue(search.active);self.assertNotEqual(state.freq,94900)
        search.toggle_scan(2);self.assertFalse(search.active);self.assertEqual(state.freq,94900)
        search.toggle_scan(3);state.set_view(freq_khz=97000);search.poll(4)
        self.assertFalse(search.active);self.assertEqual(state.freq,97000)
    def test_new_scan_clears_results_but_stop_does_not(self):
        from unittest.mock import Mock
        search,state,lab=self.make_search();search.clear_catalog=Mock()
        search.toggle_scan(1);search.clear_catalog.assert_called_once()
        search.toggle_scan(2);search.clear_catalog.assert_called_once()
        search.toggle_scan(3);self.assertEqual(search.clear_catalog.call_count,2)

    def test_am_scan_reports_unsupported_medium_wave_without_retuning(self):
        search,state,lab=self.make_search();lab.current_home_mode=lambda:'AM'
        search.toggle_scan(1)
        self.assertFalse(search.active);self.assertEqual(state.freq,94900.)
        title,detail=search.pop_notice()
        self.assertEqual(title,'AM SCAN UNAVAILABLE')
        self.assertIn('531–1602',detail);self.assertIn('24 MHz',detail)

    def test_source_handoff_cancels_pending_scan_and_audio_gate_without_retuning(self):
        from unittest.mock import Mock
        search,state,lab=self.make_search();search.audio_gate=Mock()
        search.toggle_scan(1);search.pending_band=('old',531,1602)
        state.set_view(freq_khz=1115);generation=state.generation
        search.cancel_for_handoff()
        self.assertFalse(search.active);self.assertFalse(search.open)
        self.assertIsNone(search.pending_band);self.assertFalse(search.silent)
        search.audio_gate.assert_called_with(False)
        self.assertEqual((state.freq,state.generation),(1115,generation))

    def test_timeout_restores_origin(self):
        search,state,lab=self.make_search();search.toggle_scan(1);search.poll(100)
        self.assertFalse(search.active);self.assertEqual(state.freq,94900)
    def test_stale_frame_does_not_tune(self):
        search,state,lab=self.make_search();power=np.full(2048,-60.);power[1100:1300]=-35
        lab.signal_snapshot=lambda:(1,94900.,1024.,power)
        self.assertFalse(search.tune(94900,1024,now=5));self.assertEqual(state.freq,94900)

    def test_scan_collects_signal_and_continues_to_next_window(self):
        search,state,lab=self.make_search();search.toggle_scan(1)
        power=np.full(2048,-60.);power[1000:1200]=-35
        for now in (1.2,1.3,1.4):
            lab.signal_snapshot=lambda now=now:(now,search.target,1024.,power)
            search.poll(now)
        self.assertTrue(search.active)
        self.assertTrue(search.best)
        self.assertGreater(state.freq,search.low)
        self.assertTrue(search.open)
    def test_usb_buttons_route_locally_without_kiwi_scan(self):
        import kiwi_gl_display as ui
        from unittest.mock import Mock
        state=ui.SharedState('http://example.test:8073',94900.,8,-95.,142,245,4,'am',True)
        local=Mock();local.available.return_value=True;local.active=True
        state.local_signal_search=local;state.set_external_waterfall(True)
        self.assertTrue(ui.waterfall_action_enabled(state,'TUNE'))
        self.assertTrue(ui.waterfall_action_enabled(state,'SCAN'))
        self.assertFalse(ui.waterfall_action_enabled(state,'SCAN',reviewing=True))
        state.start_smart_seek();local.toggle_scan.assert_called_once()
        self.assertFalse(state.smart_seek.open)
        state.apply_prepared_carrier();local.tune.assert_called_once()

    def test_signal_ranking_prefers_broad_fm_over_a_tall_narrow_spur(self):
        from local_signal_search import ranked_candidates
        power=np.full(2048,-60.);power[400:590]=-44;power[1300:1490]=-33;power[1040]=0
        found=ranked_candidates(power,95000,1024,'WFM')
        self.assertGreaterEqual(len(found),2)
        best=max(found,key=lambda item:item[1])[0]
        self.assertGreater(best,95000)
        self.assertFalse(any(abs(freq-95008)<25 for freq,_ in found))

    def test_medium_wave_rejected_without_retuning_unsupported_rtl(self):
        search,state,lab=self.make_search();lab.current_home_mode=lambda:'AM'
        search.request_mode_band('AM')
        self.assertIsNone(search.pending_band);self.assertFalse(search.active)
        self.assertEqual(state.freq,94900.)
        self.assertIn('outside',search.pop_notice()[1])

    def test_full_fm_sweep_selects_best_without_synthetic_waterfall(self):
        search,state,lab=self.make_search();search.toggle_scan(1)
        self.assertTrue(search.active);self.assertTrue(search.full_band);self.assertTrue(search.open)
        seen=[];now=1.3
        while search.active:
            center=search.target;seen.append(center)
            power=np.full(2048,-60.)
            power[900:1100]=-30 if abs(center-96000)<500 else -43
            for _ in range(3):
                lab.signal_snapshot=lambda now=now,center=center,power=power:(now,center,1024.,power)
                search.poll(now);now+=.1
            now+=.2
        self.assertGreater(len(seen),20)
        self.assertTrue(95500<state.freq<96500)
        self.assertFalse(hasattr(search,'overview'))

    def test_supported_medium_wave_band_and_no_signal_landing(self):
        search,state,lab=self.make_search();lab.current_home_mode=lambda:'AM'
        lab.capabilities=SimpleNamespace(frequency_ranges_khz=((.5,31000),(60000,260000)))
        search.request_mode_band('AM');search.poll(1)
        self.assertEqual((search.low,search.high),(531,1602))
        search.positions=[];search.advance(2)
        self.assertFalse(search.active);self.assertTrue(531<=state.freq<=1602)
        self.assertIn('No qualifying',search.pop_notice()[1])

    def test_scan_silence_releases_only_after_fresh_final_frequency(self):
        from unittest.mock import Mock,patch
        search,state,lab=self.make_search();search.audio_gate=Mock()
        search.toggle_scan(1);self.assertTrue(search.silent)
        search.best={96300:20}
        with patch('local_signal_search.time.monotonic',return_value=10):search.finish_band()
        lab.signal_snapshot=lambda:(10.3,95000,1024,[])
        search.poll(10.4);self.assertTrue(search.silent)
        lab.signal_snapshot=lambda:(10.1,96300,1024,[])
        search.poll(10.4);self.assertTrue(search.silent)
        lab.signal_snapshot=lambda:(10.3,96300,1024,[])
        search.poll(10.4);self.assertFalse(search.silent)
        self.assertEqual([c.args[0] for c in search.audio_gate.call_args_list],[True,False])

    def test_no_station_stays_silent_until_manual_tuning_settles(self):
        from unittest.mock import patch
        search,state,lab=self.make_search();search.toggle_scan(1)
        with patch('local_signal_search.time.monotonic',return_value=10):search.finish_band()
        lab.signal_snapshot=lambda:(11,state.freq,1024,[])
        search.poll(11);self.assertTrue(search.silent)
        state.set_view(freq_khz=96300)
        with patch('local_signal_search.time.monotonic',return_value=12):search.poll(12)
        lab.signal_snapshot=lambda:(12.4,96300,1024,[])
        search.poll(12.5);self.assertFalse(search.silent)

