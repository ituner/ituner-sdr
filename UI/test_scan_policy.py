import unittest

from scan_policy import ScanPolicy, window_count
from smart_seek import SmartSeek, SeekCandidate
from test_smart_seek import rf_frame


class ScanPolicyTests(unittest.TestCase):
    key = (('rx',),7200.,7450.,30000000,14)

    def setUp(self):
        self.policy = ScanPolicy()
        self.signal = SeekCandidate(7300,30)

    def plan(self, key=None, bandwidth=30000000, cap=14):
        return self.policy.plan(key or self.key,bandwidth,cap,7200,7450)

    def test_reference_first_then_three_wider_passes_then_compulsory_audit(self):
        self.assertEqual(self.plan(),8)
        self.policy.finish(self.key,8,14,[self.signal],True)
        for _ in range(3):
            self.assertEqual(self.plan(),7)
            self.assertFalse(self.policy.finish(self.key,7,14,[self.signal],True))
        self.assertEqual(self.plan(),8)

    def test_weak_or_close_stations_stay_narrow_and_width_has_to_save_a_view(self):
        for signals in ([SeekCandidate(7300,12)],[self.signal,SeekCandidate(7305,30)]):
            self.policy.finish(self.key,8,14,signals,True)
            self.assertEqual(self.plan(),8)
        self.policy.finish(self.key,8,14,[self.signal],True)
        self.assertEqual(self.policy.plan(self.key,30000000,14,7290,7310),8)
        self.assertEqual(self.policy.plan(self.key,100000000,14,7200,7450),8)

    def test_local_close_pair_can_be_refined_when_total_cost_still_beats_full_narrow(self):
        key = (('rx',),5730.,6200.,30000000,14)
        signals = [SeekCandidate(5830,30),SeekCandidate(6120,30),SeekCandidate(6125,25)]
        self.policy.finish(key,8,14,signals,True)
        self.assertEqual(self.policy.plan(key,30000000,14,5730,6200),7)
        self.assertTrue(self.policy.finish(key,7,14,signals,True))
        self.policy.finish_refinement(key,signals,True)
        self.assertEqual(self.policy.profiles[key]['cooldown'],0)

    def test_repeated_nonqualifying_line_is_a_schedule_hint_not_a_station_count(self):
        for _ in range(2):
            self.policy.finish(self.key,8,14,[self.signal],True,uncertain=(7350,))
        self.assertEqual(self.plan(),7)
        self.assertFalse(self.policy.finish(self.key,7,14,[self.signal],True,uncertain=(7350,)))
        self.assertEqual(self.policy.profiles[self.key]['reference'],(7300,))

    def test_missing_reference_requires_narrow_retry_and_cooldown(self):
        self.policy.finish(self.key,8,14,[self.signal],True)
        self.assertTrue(self.policy.finish(self.key,7,14,[],True))
        self.assertEqual(self.plan(),8)
        # Only a complete narrow measurement can now confirm an empty band.
        self.policy.finish(self.key,8,14,[],True)
        self.assertEqual(self.policy.profiles[self.key]['reference'],())
        self.assertEqual(self.plan(),8)

    def test_failure_cannot_erase_reference_and_receiver_geometry_is_isolated(self):
        self.policy.finish(self.key,8,14,[self.signal],True)
        self.assertFalse(self.policy.finish(self.key,7,14,[],False))
        self.assertEqual(self.policy.profiles[self.key]['reference'],(7300,))
        self.assertEqual(self.plan((('another',),7200,7450,30000000,14)),8)
        self.assertEqual(self.plan((('rx',),7200,7450,32000000,14),bandwidth=32000000),8)

    def test_uncertain_carrier_forces_narrow_retry_without_becoming_a_station(self):
        self.policy.finish(self.key,8,14,[self.signal],True)
        self.assertTrue(self.policy.finish(self.key,7,14,[self.signal],True,uncertain=True))
        self.assertEqual(self.plan(),8)

    def test_fading_reference_is_watched_for_two_hours_without_fake_presence_or_refresh(self):
        self.policy.finish(self.key,8,14,[self.signal],True,now=100)
        for now in (200,7299):
            self.policy.finish(self.key,8,14,[],True,now=now)
            self.assertEqual(self.policy.profiles[self.key]['reference'],())
            self.assertIn(7300,self.policy.profiles[self.key]['watch'])
            self.assertEqual(self.policy.profiles[self.key]['watch'][7300],100)
            self.assertEqual(self.plan(),8)
        self.policy.finish(self.key,8,14,[],True,now=7300)
        self.assertEqual(self.policy.profiles[self.key]['watch'],{})
        self.assertEqual(self.plan(),7)

    def test_listening_tune_does_not_discard_the_receivers_learned_policy(self):
        engine = SmartSeek(self.policy)
        engine.start(7200,7450,'41 m',('generation',1),100,policy_context=('rx',))
        key = engine.policy_key
        engine.context = ('generation',2)
        engine.request(engine.context,101)
        self.assertEqual(engine.policy_key,key)
        self.assertTrue(engine.active)

    def test_productive_windows_and_bands_move_first_but_every_one_is_retained(self):
        self.policy.finish(self.key,8,14,[SeekCandidate(7400,30)],True)
        original = [7250,7325,7400]
        ordered = self.policy.order_windows(self.key,original,117,7250)
        self.assertEqual(ordered[0],7400)
        self.assertCountEqual(ordered,original)
        bands = [(5730,6200,'49 m'),(7200,7450,'41 m'),(9400,9900,'31 m')]
        ranked = self.policy.rank_bands(('rx',),bands,30000000,14,{'31 m':20})
        self.assertEqual(ranked[0][2],'41 m')
        self.assertCountEqual(ranked,bands)

    def drive(self, noise_at_wide=False,noise_at_fine=False):
        engine = SmartSeek(self.policy)
        engine.start(7200,7450,'41 m',('rx',),100,refresh=True)
        now, sequence, views, previous = 100,0,[],None
        while engine.active and now < 200:
            request = engine.request(('rx',),now)
            if request != previous:
                views.append(request)
                previous = request
            center, zoom = request
            sequence += 1
            now += .125
            engine.feed(rf_frame(center,zoom,7300000,sequence,noise=(noise_at_wide and zoom==7) or (noise_at_fine and zoom>8)),
                        30000000,14,14,now)
        self.assertFalse(engine.active)
        self.assertEqual(engine.skipped,0)
        return engine,views

    def test_actual_engine_refines_uncertainty_after_complete_wider_coverage(self):
        initial, views = self.drive()
        self.assertEqual([zoom for _,zoom in views],[8,8,8])
        repeated, views = self.drive(noise_at_wide=True)
        self.assertEqual([zoom for _,zoom in views],[7,7,10])
        self.assertEqual(len(views),3)
        wider = sorted(center for center,zoom in views if zoom==7)
        self.assertLessEqual(wider[0]-30000/2**7/2+8,7200)
        self.assertGreaterEqual(wider[-1]+30000/2**7/2-8,7450)
        self.assertEqual(len(repeated.pass_candidates),1)
        self.assertAlmostEqual(repeated.pass_candidates[0].tuning_khz,7300,delta=.15)
        # The next sweep must rebuild a full narrow plan, not repeat only
        # the single refinement window when its zoom happens to match.
        repeated.adaptive = repeated.overview_done = True
        repeated.request(('rx',),1000)
        self.assertEqual(len(repeated.windows),3)
        self.assertFalse(repeated.refined_last_pass)

    def test_actual_engine_wider_pass_covers_band_with_fewer_view_changes(self):
        self.drive()
        engine, views = self.drive()
        self.assertEqual([zoom for _,zoom in views],[7,7])
        self.assertEqual(window_count(30000000,7,7200,7450),len(views))
        self.assertEqual(len(engine.pass_candidates),1)

    def test_failed_fine_confirmation_retries_baseline_context_before_declaring_absence(self):
        self.drive()
        engine,views = self.drive(noise_at_wide=True,noise_at_fine=True)
        self.assertEqual([zoom for _,zoom in views],[7,7,10,8])
        self.assertEqual(engine.skipped,0)
        self.assertEqual(len(engine.pass_candidates),1)
        self.assertAlmostEqual(engine.pass_candidates[0].tuning_khz,7300,delta=.15)

    def test_hiccup_retries_the_same_view_once_and_failure_still_cannot_confirm_absence(self):
        engine = SmartSeek(self.policy)
        engine.start(7200,7450,'41 m',('rx',),100)
        original = engine.request(('rx',),100)
        self.assertEqual(engine.request(('rx',),engine.deadline+.1),original)
        self.assertEqual((engine.retries,engine.skipped),(1,0))
        engine.request(('rx',),engine.deadline+.1)
        self.assertEqual(engine.skipped,1)
        self.assertEqual(engine.index,1)
        self.assertIsNone(engine.measured_at)

    def test_geometry_change_starts_fresh_evidence_and_covers_the_full_band(self):
        engine = SmartSeek(self.policy)
        engine.start(7200,7450,'41 m',('rx',),100)
        engine.pass_candidates = [self.signal]
        engine.pass_uncertain = [7350]
        engine.index = 1
        engine.configure(32000000,14,101)
        self.assertEqual(engine.pass_candidates,[])
        self.assertEqual(engine.pass_uncertain,[])
        self.assertEqual(engine.index,0)
        self.assertEqual(engine.zoom,8)

    def test_narrower_measurement_improves_tuning_without_changing_row_key_or_listening(self):
        engine = SmartSeek(self.policy)
        engine.start(7200,7450,'41 m',('rx',),100)
        engine.playing_khz = 7300.12
        engine._merge([SeekCandidate(7300.12,30)],bin_hz=230)
        engine._merge([SeekCandidate(7300.015,29)],accumulate=True,bin_hz=57)
        candidate = engine.snapshot()['candidates'][0]
        self.assertEqual((candidate.frequency_khz,candidate.tuning_khz),(7300.12,7300.015))
        engine._merge([SeekCandidate(7300.2,40)],accumulate=True,bin_hz=230)
        self.assertEqual(engine.snapshot()['candidates'][0].tuning_khz,7300.015)
        self.assertEqual(engine.playing_khz,7300.12)

    def test_refinement_groups_only_points_that_fit_a_narrow_usable_span(self):
        self.policy.finish(self.key,8,14,[self.signal],True)
        windows = self.policy.refinement_windows(self.key,[],[7200,7250,7450],30000000,14)
        self.assertEqual(windows,[7250.59375,7399.40625])
        self.policy.finish_refinement(self.key,[],False)
        self.assertEqual(self.policy.profiles[self.key]['reference'],(7300,))
        self.assertEqual(self.plan(),8)

    def test_finer_recheck_does_not_increase_the_number_of_view_commands(self):
        self.policy.finish(self.key,8,14,[self.signal],True)
        coarse = self.policy.refinement_windows(self.key,[],[],30000000,14)
        windows,zoom = self.policy.refinement_plan(self.key,[],[],30000000,14)
        self.assertEqual(zoom,10)
        self.assertLessEqual(len(windows),len(coarse))
        usable = 30000/2**zoom-16
        self.assertTrue(any(abs(center-7300)<=usable/2 for center in windows))


if __name__ == '__main__':
    unittest.main()
