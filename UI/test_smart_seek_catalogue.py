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

    def drive(self, catalogue, end, now=100):
        sequence = 0
        visits = []
        while now < end:
            request = catalogue.request(('rx',),now)
            if request is None:
                break
            label = catalogue._current_label
            if not visits or visits[-1][0] != label:
                visits.append((label,now))
            center,zoom = request
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
        # A background band never gets two consecutive observation turns.
        for (label,start),(_,end) in zip(visits,visits[1:]):
            if label not in ('41 m','spectrum'):
                self.assertLessEqual(end-start,5)

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

    def test_scanned_count_survives_reopen_refresh_and_dimmed_requalification_for_one_hour(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30),SeekCandidate(7350,28)],accumulate=True)
        catalogue.measured_at = 101
        self.assertEqual(catalogue.snapshot(101)['band_counts']['41 m'],2)
        catalogue.start(9400,9900,'31 m',('rx',),102)
        catalogue.start(7200,7450,'41 m',('rx',),103)
        self.assertTrue(catalogue.stale)
        self.assertEqual(catalogue.snapshot(103)['band_counts']['41 m'],2)
        catalogue.close()
        catalogue.start(7200,7450,'41 m',('rx',),3500)
        self.assertEqual(catalogue.candidates,[])
        self.assertEqual(catalogue.snapshot(3500)['band_counts']['41 m'],2)
        catalogue.start(7200,7450,'41 m',('rx',),3600,refresh=True)
        self.assertEqual(catalogue.snapshot(3600)['band_counts']['41 m'],2)
        # Reading, reopening and refresh do not renew the measurement age.
        self.assertIsNone(catalogue.snapshot(3701)['band_counts']['41 m'])

    def test_counts_expire_independently_for_each_band(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30)],accumulate=True)
        catalogue.measured_at = 101
        catalogue.start(9400,9900,'31 m',('rx',),200)
        catalogue._merge([SeekCandidate(9700,30)],accumulate=True)
        catalogue.measured_at = 201
        catalogue.close()
        catalogue.start(7200,7450,'41 m',('rx',),3701)
        counts = catalogue.snapshot(3701)['band_counts']
        self.assertIsNone(counts['41 m'])
        self.assertEqual(counts['31 m'],1)
        self.assertIsNone(catalogue.snapshot(3801)['band_counts']['31 m'])

    def test_cache_is_isolated_by_receiver_but_survives_tuning_context_changes(self):
        catalogue = self.start()
        catalogue._merge([SeekCandidate(7300,30)],accumulate=True)
        catalogue.measured_at = 101
        catalogue.start(7200,7450,'41 m',('other receiver',),102)
        self.assertIsNone(catalogue.snapshot(102)['band_counts']['41 m'])
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

    def test_cached_candidates_still_follow_minimum_signal_filter(self):
        catalogue = self.start()
        catalogue.sensitivity = 100
        catalogue._merge([SeekCandidate(7300,9),SeekCandidate(7350,30)],accumulate=True)
        catalogue.measured_at = 101
        self.assertEqual(catalogue.snapshot(101)['band_counts']['41 m'],2)
        catalogue.close()
        catalogue.start(7200,7450,'41 m',('rx',),102)
        catalogue.sensitivity = 0
        self.assertEqual(catalogue.snapshot(102)['band_counts']['41 m'],1)

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
        catalogue._foreground_turns = 2
        catalogue._paused['41 m'] = 100
        catalogue.request(('rx',),100)
        self.assertEqual(catalogue._current_label,'31 m')
        catalogue.poll(('rx',),110)
        self.assertIsNotNone(catalogue.request(('rx',),111))
        self.assertEqual(catalogue._current_label,'41 m')
        self.assertEqual(catalogue.skipped,0)

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
