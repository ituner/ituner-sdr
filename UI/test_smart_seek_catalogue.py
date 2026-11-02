import struct
import unittest
from unittest.mock import patch

from smart_seek import SeekCandidate
from smart_seek_catalogue import SmartSeekCatalogue,SpectrumSurvey
from test_smart_seek import rf_frame
import kiwi_gl_display as ui


BANDS = ((5730,6200,'49 m'),(7200,7450,'41 m'),(9400,9900,'31 m'),(11600,12100,'25 m'))


class CatalogueTests(unittest.TestCase):
    def start(self):
        catalogue = SmartSeekCatalogue(BANDS)
        catalogue.start(7200,7450,'41 m',('rx',),100)
        return catalogue

    def drive(self, catalogue, end, now=100, samples=None):
        sequence = 0
        visits = []
        while now < end:
            starting_turn = catalogue._current is None
            request = catalogue.request(('rx',),now)
            if request is None:
                break
            label = catalogue._current_label
            if starting_turn or not visits or visits[-1][0] != label:
                visits.append((label,now))
            center,zoom = request
            if samples is not None:
                samples.append((label,center,zoom,catalogue._current.worker_kind))
            now += .25
            sequence += 1
            carrier = {'49 m':6000000,'31 m':9700000}.get(label,7300000)
            catalogue.feed(rf_frame(center,zoom,carrier,sequence,noise=label=='25 m'),
                           30000000,14,14,now)
        return visits

    def test_first_band_then_wide_survey_and_background_counts_without_changing_view(self):
        catalogue = self.start()
        visits = self.drive(catalogue,300)
        labels = [label for label,_ in visits]
        self.assertEqual(labels[:2],['41 m','spectrum'])
        self.assertIn('49 m',labels)
        self.assertIn('31 m',labels)
        self.assertIn('25 m',labels)
        result = catalogue.snapshot(300)
        self.assertEqual(result['label'],'41 m')
        self.assertEqual(result['band_counts']['41 m'],1)
        self.assertGreaterEqual(result['band_counts']['49 m'],1)
        self.assertGreaterEqual(result['band_counts']['31 m'],1)
        self.assertEqual(result['band_counts']['25 m'],0)
        self.assertTrue(all(7200 <= c.tuning_khz <= 7450 for c in result['candidates']))
    def test_first_complete_sweep_then_one_selected_sweep_per_four_others(self):
        catalogue = self.start()
        visits = self.drive(catalogue,600)
        labels = [label for label,_ in visits if label!='spectrum']
        self.assertEqual(labels[0],'41 m')
        following = labels[1:]
        self.assertGreater(len(following),15)
        for index in range(0,len(following)-4,5):
            group = following[index:index+5]
            self.assertNotIn('41 m',group[:4])
            self.assertEqual(group[4],'41 m')
        # Switching band grants one complete first sweep before rotating away.
        catalogue.start(9400,9900,'31 m',('rx',),600)
        switched = [label for label,_ in self.drive(catalogue,660,now=600) if label!='spectrum']
        self.assertEqual(switched[0],'31 m')
        self.assertNotEqual(switched[1],'31 m')

    def test_first_visit_covers_every_detailed_window_before_leaving_each_band(self):
        catalogue = self.start()
        samples = []
        self.drive(catalogue,300,samples=samples)
        for label,engine in catalogue._models.items():
            first = next(i for i,sample in enumerate(samples) if sample[0]==label)
            end = next((i for i in range(first+1,len(samples)) if samples[i][0]!=label),len(samples))
            detailed = sorted({center for _,center,zoom,kind in samples[first:end] if not kind and zoom==8})
            span = 30000/2**8
            self.assertTrue(detailed,label)
            self.assertLessEqual(detailed[0]-span/2+8,engine.low,label)
            self.assertGreaterEqual(detailed[-1]+span/2-8,engine.high,label)
            self.assertTrue(all(b-a <= span-16 for a,b in zip(detailed,detailed[1:])),label)
            self.assertEqual(engine.skipped,0,label)
        self.assertGreater(len({center for label,center,zoom,kind in samples if label=='41 m' and zoom==8 and not kind}),2)

    def test_uncertain_signal_review_does_not_count_as_another_band_sweep(self):
        catalogue = self.start()
        from smart_seek import SmartSeek
        background = SmartSeek()
        background.start(9400,9900,'31 m',('rx',),100,refresh=True,adaptive=True)
        background.index = len(background.windows)
        background.active = False
        catalogue._models['31 m'] = background
        catalogue._queue = ['31 m']
        catalogue._background_passes = 3
        catalogue._scan_completed['31 m'] = id(background),background.pass_count
        catalogue._current,catalogue._current_label = background,'31 m'
        catalogue._token = None
        catalogue._finish_turn(101)
        self.assertEqual(catalogue._background_passes,3)
        self.assertEqual(catalogue._queue,['31 m'])
        background.pass_count += 1
        catalogue._current,catalogue._current_label = background,'31 m'
        catalogue._finish_turn(102)
        self.assertEqual(catalogue._background_passes,4)
        self.assertEqual(catalogue._queue,[])

    def test_empty_background_queue_restarts_other_bands_without_extra_selected_turns(self):
        catalogue = self.start()
        catalogue._initial_done = True
        catalogue._survey_at = 100
        self.assertEqual(catalogue._queue,[])
        catalogue.request(('rx',),100)
        self.assertNotEqual(catalogue._current_label,'41 m')
        self.assertIn(catalogue._current_label,('49 m','31 m','25 m'))

    def test_band_menu_scans_other_bands_without_repeating_selected_then_resumes_list(self):
        catalogue = self.start()
        catalogue.request(('rx',),100)
        self.assertEqual(catalogue._current_label,'41 m')
        catalogue.set_band_menu(True,100.1)
        now,sequence = 100.1,0
        visits = []
        while now < 220:
            request = catalogue.request(('rx',),now)
            if request is None:
                break
            label = catalogue._current_label
            visits.append(label)
            center,zoom = request
            now += .25
            sequence += 1
            carrier = {'49 m':6000000,'31 m':9700000}.get(label,7300000)
            catalogue.feed(rf_frame(center,zoom,carrier,sequence,noise=label=='25 m'),
                           30000000,14,14,now)
        self.assertEqual(visits[0],'spectrum')
        self.assertNotIn('41 m',visits)
        self.assertTrue({'49 m','31 m','25 m'}.issubset(visits))
        self.assertIsNone(catalogue.request(('rx',),now+.5))
        self.assertEqual(catalogue.snapshot(now+.5)['phase'],'catalogue_wait')
        self.assertIsNone(catalogue.snapshot(now+.5)['scanning_band'])
        catalogue.set_band_menu(False,now+1)
        self.assertIsNotNone(catalogue.request(('rx',),now+1))
        self.assertEqual(catalogue._current_label,'41 m')
        self.assertEqual(catalogue.skipped,0)

    def test_touchable_band_graph_switches_band_without_changing_playback(self):
        from types import SimpleNamespace
        from smart_seek_view import SmartSeekView
        with patch.object(ui.time,'monotonic',return_value=100):
            state = ui.SharedState('http://example.test:8073',7325,14,-95,142,245,4,'am',False)
            state.connection_streams = {'audio':True,'waterfall':True}
            state.start_smart_seek()
            view = SmartSeekView(ui,state)
            self.addCleanup(view.shutdown)
            before = state.freq_khz,state.radio_snapshot()
            with patch.object(ui,'draw_styled_button_frame',return_value=SimpleNamespace(text=(205,221,229))), \
                 patch.object(ui,'draw_text'),patch.object(ui,'draw_logical_rect'):
                view.draw_band_activity(None,state.smart_seek_snapshot())
            self.assertEqual([action[1] for _,action in view.actions],
                             list(state.smart_seek_snapshot()['bands']))
            self.assertTrue(all(box[2]-box[0]>=56 and box[3]-box[1]==90 for box,_ in view.actions))
            box = next(box for box,action in view.actions if action==('band','31 m'))
            x,y = (box[0]+box[2])/2,(box[1]+box[3])/2
            view.press(x,y);view.release(x,y)
            self.assertEqual(state.smart_seek.label,'31 m')
            self.assertEqual((state.freq_khz,state.radio_snapshot()),before)
            # Crossing into an adjacent band during a press does not select it.
            view.press(x,y);view.release(x+80,y)
            self.assertEqual(state.smart_seek.label,'31 m')

    def test_activity_then_proximity_orders_bands_and_quiet_bands_go_last(self):
        catalogue = self.start()
        catalogue._scores = {'49 m':12,'31 m':24,'25 m':0}
        catalogue._rank_bands()
        self.assertEqual(catalogue._queue,['31 m','49 m','25 m'])
        catalogue._scores = {'49 m':24,'31 m':24,'25 m':24}
        catalogue._rank_bands()
        self.assertEqual(catalogue._queue[-1],'25 m')

    def test_broad_energy_is_a_priority_hint_not_a_confirmed_station(self):
        survey = SpectrumSurvey()
        survey.bands = BANDS
        frames = [rf_frame(7500,1,9700000,sequence) for sequence in range(1,10)]
        first = struct.unpack_from('<I',frames[0],4)[0]*30000000/(1024*2**14)
        self.assertEqual(survey.detect([f[16:] for f in frames],first,30000000/2048,0,15000),[])
        self.assertGreater(survey.scores['31 m'],survey.scores['49 m'])

    def test_switch_keeps_dimmed_rows_and_counts_other_bands_then_requalifies_in_place(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30)],accumulate=True)
        catalogue.measured_at = 101
        catalogue.start(9400,9900,'31 m',('rx',),102)
        catalogue._merge([SeekCandidate(9700,35)],accumulate=True)
        catalogue.measured_at = 103
        catalogue.start(7200,7450,'41 m',('rx',),104)
        result = catalogue.snapshot(104)
        self.assertEqual([c.frequency_khz for c in result['candidates']],[7300])
        self.assertEqual(result['stale'],(7300,))
        self.assertEqual(result['band_counts']['31 m'],1)
        catalogue._merge([SeekCandidate(7300.04,28)])
        self.assertIn(7300,catalogue.stale)
        catalogue._merge([SeekCandidate(7300.04,28)],accumulate=True)
        self.assertFalse(catalogue.stale)
        self.assertEqual(catalogue.candidates[0].frequency_khz,7300)

    def test_close_reopen_and_explicit_refresh_start_fresh(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30)],accumulate=True)
        catalogue.start(7200,7450,'41 m',('rx',),101,refresh=True)
        self.assertEqual(catalogue.candidates,[])
        catalogue._merge([SeekCandidate(7300,30)],accumulate=True)
        catalogue.close()
        catalogue.start(7200,7450,'41 m',('rx',),102)
        self.assertEqual(catalogue.candidates,[])
        self.assertIsNone(catalogue.snapshot(102)['band_counts']['31 m'])

    def test_scanned_count_survives_reopen_refresh_and_dimmed_requalification_for_two_hours(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30),SeekCandidate(7350,28)],accumulate=True)
        catalogue.measured_at = 101
        self.assertEqual(catalogue.snapshot(101)['band_counts']['41 m'],2)
        catalogue.start(9400,9900,'31 m',('rx',),102)
        catalogue.start(7200,7450,'41 m',('rx',),103)
        self.assertTrue(catalogue.stale)
        self.assertEqual(catalogue.snapshot(103)['band_counts']['41 m'],2)
        catalogue.close()
        catalogue.start(7200,7450,'41 m',('rx',),7100)
        self.assertEqual(catalogue.candidates,[])
        self.assertEqual(catalogue.snapshot(7100)['band_counts']['41 m'],2)
        catalogue.start(7200,7450,'41 m',('rx',),7200,refresh=True)
        self.assertEqual(catalogue.snapshot(7200)['band_counts']['41 m'],2)
        # Reading, reopening and refresh do not renew the measurement age.
        self.assertIsNone(catalogue.snapshot(7301)['band_counts']['41 m'])

    def test_counts_expire_independently_for_each_band(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30)],accumulate=True)
        catalogue.measured_at = 101
        catalogue.start(9400,9900,'31 m',('rx',),200)
        catalogue._merge([SeekCandidate(9700,30)],accumulate=True)
        catalogue.measured_at = 201
        catalogue.close()
        catalogue.start(7200,7450,'41 m',('rx',),7301)
        counts = catalogue.snapshot(7301)['band_counts']
        self.assertIsNone(counts['41 m'])
        self.assertEqual(counts['31 m'],1)
        self.assertIsNone(catalogue.snapshot(7401)['band_counts']['31 m'])

    def test_cache_is_isolated_by_receiver_but_survives_tuning_context_changes(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30)],accumulate=True)
        catalogue.measured_at = 101
        catalogue.start(7200,7450,'41 m',('other receiver',),102)
        self.assertIsNone(catalogue.snapshot(102)['band_counts']['41 m'])
        self.assertEqual(catalogue.snapshot(102)['catalogue'],())
        catalogue.start(7200,7450,'41 m',('rx','new tuning'),103)
        self.assertEqual(catalogue.snapshot(103)['band_counts']['41 m'],1)

    def test_incomplete_or_failed_scan_keeps_count_and_completed_empty_scan_replaces_it(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30),SeekCandidate(7350,28)],accumulate=True)
        catalogue.measured_at = 101
        catalogue.start(7200,7450,'41 m',('rx',),102,refresh=True)
        catalogue.measured_at = 103  # An observed empty window, not a full band.
        self.assertEqual(catalogue.snapshot(103)['band_counts']['41 m'],2)
        catalogue.skipped = 1
        catalogue._remember_count('41 m',catalogue._engine,104,complete=True)
        self.assertEqual(catalogue.snapshot(104)['band_counts']['41 m'],2)
        catalogue.pass_count += 1
        catalogue.measured_at = 105
        catalogue._remember_count('41 m',catalogue._engine,105,complete=True)
        self.assertEqual(catalogue.snapshot(105)['band_counts']['41 m'],0)

    def test_cached_weak_candidates_remain_in_counts_and_activity(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,9),SeekCandidate(7350,30)],accumulate=True)
        catalogue.measured_at = 101
        self.assertEqual(catalogue.snapshot(101)['band_counts']['41 m'],2)
        catalogue.close()
        catalogue.start(7200,7450,'41 m',('rx',),102)
        self.assertEqual(catalogue.snapshot(102)['band_counts']['41 m'],2)

    def test_activity_banner_keeps_measured_strengths_in_sync_with_counts_and_expiry(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7350,30),SeekCandidate(7300,9)],accumulate=True)
        catalogue.measured_at = 101
        catalogue.start(9400,9900,'31 m',('rx',),102)
        result = catalogue.snapshot(102)
        self.assertEqual([(c.frequency_khz,c.prominence) for c in result['band_signals']['41 m']],
                         [(7300,9),(7350,30)])
        self.assertEqual(len(result['band_signals']['41 m']),result['band_counts']['41 m'])
        self.assertIsNone(result['band_signals']['31 m'])  # Unmeasured differs from empty.
        catalogue.start(7200,7450,'41 m',('rx',),103)
        self.assertTrue(catalogue.stale)
        self.assertEqual([c.frequency_khz for c in catalogue.snapshot(103)['band_signals']['41 m']],
                         [7300,7350])
        self.assertIsNone(catalogue.snapshot(7301)['band_signals']['41 m'])

    def test_context_change_cancels_background_and_tuning_propagates_to_paused_models(self):
        catalogue = self.start()
        self.drive(catalogue,124)
        catalogue.context = ('explicit menu tune',)
        self.assertTrue(all(model.context==('explicit menu tune',) for model in catalogue._models.values()))
        self.assertIsNotNone(catalogue.request(('explicit menu tune',),124.1))
        self.assertIsNone(catalogue.request(('other receiver',),124.2))
        self.assertFalse(catalogue.open)
        self.assertTrue(all(not model.open for model in catalogue._models.values()))

    def test_suspended_foreground_time_budget_does_not_expire_during_background_work(self):
        catalogue = self.start()
        catalogue._initial_done = True
        catalogue._survey_at = 100
        catalogue._queue = ['31 m']
        catalogue._background_passes = 3
        catalogue._paused['41 m'] = 100
        deadline = catalogue._engine.deadline
        visits = self.drive(catalogue,125)
        self.assertEqual(visits[0][0],'31 m')
        self.assertIn('41 m',[label for label,_ in visits])
        self.assertGreater(catalogue._engine.deadline,deadline)
        self.assertEqual(catalogue.skipped,0)

    def test_preview_pause_preserves_scan_and_worker_deadlines(self):
        catalogue = self.start()
        catalogue.request(('rx',), 100)
        worker = catalogue._engine.worker
        deadline = worker.deadline
        catalogue.set_capture_paused(True, 101)
        catalogue.poll(('rx',), 301)
        self.assertIsNone(catalogue.request(('rx',), 301))
        self.assertEqual(catalogue.skipped, 0)
        self.assertEqual(worker.deadline, deadline)
        catalogue.set_capture_paused(False, 301)
        self.assertIsNotNone(catalogue.request(('rx',), 301))
        self.assertEqual(worker.deadline, deadline+200)
        self.assertEqual(catalogue.skipped, 0)

    def test_receiver_change_still_closes_paused_scan(self):
        catalogue = self.start()
        catalogue.set_capture_paused(True, 100)
        catalogue.poll(('other rx',), 200)
        self.assertFalse(catalogue.open)
        self.assertFalse(catalogue._capture_paused)

    def test_waterfall_is_opt_in_and_does_not_change_tuning_or_home_zoom(self):
        with patch.object(ui.time, 'monotonic', return_value=100):
            state = ui.SharedState('http://example.test:8073', 9435, 3, -95, 142, 245, 4, 'am', False)
            state.connection_streams = {'audio': True, 'waterfall': True}
            state.start_smart_seek()
            state.smart_seek._merge([SeekCandidate(9435, 30), SeekCandidate(9455, 25)])
            before = state.snapshot(), state.radio_snapshot(), state.waterfall_snapshot()
            self.assertFalse(state.smart_seek_snapshot()['waterfall'])
            state.toggle_seek_waterfall()
            self.assertEqual(state.smart_seek_capture_request(), (9435, 8))
            self.assertEqual(state.smart_seek_snapshot()['phase'], 'preview')
            self.assertEqual((state.snapshot(), state.radio_snapshot(), state.waterfall_snapshot()), before)
            state.tune_smart_seek_candidate(9455)
            self.assertEqual(state.smart_seek_capture_request(), (9455, 8))
            state.toggle_seek_waterfall()
            self.assertIsNotNone(state.smart_seek_capture_request())
            self.assertFalse(state.smart_seek_snapshot()['waterfall'])
            state.toggle_seek_waterfall()
            state.close_smart_seek()
            self.assertFalse(state.seek_waterfall.enabled)
            state.start_smart_seek()
            self.assertFalse(state.smart_seek_snapshot()['waterfall'])

    def test_background_does_not_change_audio_and_switch_uses_previously_found_rows(self):
        with patch.object(ui.time,'monotonic') as clock:
            clock.return_value = 100
            state = ui.SharedState('http://example.test:8073',7325,14,-95,142,245,4,'am',False)
            state.connection_streams = {'audio':True,'waterfall':True}
            state.start_smart_seek()
            context = state._carrier_context()
            for low,high,label in BANDS:
                if label=='41 m':continue
                engine = type(state.smart_seek._engine)()
                engine.start(low,high,label,context,100,refresh=True,adaptive=True)
                engine._merge([SeekCandidate((low+high)/2,30)],accumulate=True)
                engine.measured_at = 101
                state.smart_seek._models[label] = engine
            clock.return_value = 102
            before = state.freq_khz,state.radio_snapshot()
            state.start_smart_seek(band_label='31 m')
            result = state.smart_seek_snapshot()
            self.assertTrue(result['candidates'])
            self.assertTrue(result['stale'])
            self.assertEqual((state.freq_khz,state.radio_snapshot()),before)


if __name__ == '__main__':
    unittest.main()
