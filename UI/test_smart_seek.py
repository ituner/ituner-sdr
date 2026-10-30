import struct
import math
import unittest
from concurrent.futures import Future
from unittest.mock import patch, Mock

import kiwi_gl_display as ui
from smart_seek import SmartSeek, SeekCandidate, detect_stations
from smart_seek_view import SmartSeekView, BroadcastMatch, schedule_matches, station_detail_lines, station_frequency, frequency_label
from test_am_carrier import rf_frame as carrier_frame


def rf_frame(center_khz, zoom, carrier_hz, sequence, unmodulated=False, **options):
    """Synthetic AM: a carrier plus broad, varying programme sidebands."""
    frame = carrier_frame(center_khz, zoom, carrier_hz, sequence, **options)
    if unmodulated or options.get('noise'):
        return frame
    bandwidth = options.get('bandwidth', 30000000)
    actual_zoom = min(zoom, options.get('cap', 14))
    first = struct.unpack_from('<I', frame, 4)[0]*bandwidth/(1024*2**14)
    bin_hz = bandwidth/(1024*2**actual_zoom)
    row = list(frame[16:])
    carriers = [carrier_hz]
    if options.get('neighbour') is not None:
        carriers.append(options['neighbour'])
    envelope = 15+5*math.sin(sequence*.7)
    for index in range(1024):
        hz = first+index*bin_hz
        if any(300 <= abs(hz-carrier) <= 2300 for carrier in carriers):
            row[index] = max(row[index], round(110+envelope))
    return frame[:16]+bytes(row)


class DetectorTests(unittest.TestCase):
    def wide_am_rows(self, clipped=False, adjacent=False):
        rows = []
        centers = [500]+([550] if adjacent else [])
        for sequence in range(24):
            row = [110]*1024
            for center in centers:
                for i in range(center-45,center+46):
                    if abs(i-center) >= 2:
                        row[i] = max(row[i],round(135+8*math.sin(sequence*.7)))
                for i in range(center-2,center+3):
                    row[i] = max(row[i],round((255 if clipped else 220)-45*(i-center)**2))
                # Persistent music-tone lobes in both modulation sidebands.
                for side in (-28,28):
                    for i in range(center+side-2,center+side+3):
                        row[i] = max(row[i],round(180+5*math.sin(sequence*.7)-45*(i-center-side)**2))
            rows.append(bytes(row))
        return rows

    def test_strong_wide_am_station_does_not_publish_music_lobes_as_stations(self):
        for clipped in (False,True):
            found = detect_stations(self.wide_am_rows(clipped),7200000,100,7200,7300)
            self.assertEqual(len(found),1)
            self.assertAlmostEqual(found[0].frequency_khz,7250,delta=.1)

    def test_sideband_suppression_keeps_a_real_station_five_khz_away(self):
        found = detect_stations(self.wide_am_rows(adjacent=True),7200000,100,7200,7300)
        self.assertEqual([p.frequency_khz for p in found],[7250,7255])

    def detect(self, **options):
        frames = [rf_frame(7325, 7, 7300000, seq, **options) for seq in range(1, 10)]
        start = struct.unpack_from('<I', frames[0], 4)[0]
        return detect_stations([frame[16:] for frame in frames],
                               start*30000000/(1024*2**14),
                               30000000/(1024*2**7), 7200, 7450)

    def test_multiple_equal_carriers_are_stations(self):
        found = self.detect(neighbour=7350000)
        self.assertEqual(len(found), 2)
        self.assertAlmostEqual(found[0].frequency_khz, 7300, delta=.12)
        self.assertAlmostEqual(found[1].frequency_khz, 7350, delta=.12)
        self.assertGreater(found[0].prominence, 20)

    def test_noise_and_broad_energy_are_rejected(self):
        self.assertEqual(self.detect(noise=True), [])
        # A broad plateau is not a narrow AM carrier.
        row = bytes([110]*400+[175]*200+[110]*424)
        self.assertEqual(detect_stations([row]*8, 7200000, 230, 7200, 7450), [])

    def test_strong_unmodulated_carrier_is_not_a_listening_candidate(self):
        self.assertEqual(self.detect(unmodulated=True), [])

    def test_stationary_carrier_with_static_noise_sidebands_is_rejected(self):
        frame = rf_frame(7325, 7, 7300000, 1)
        first = struct.unpack_from('<I', frame, 4)[0]*30000000/(1024*2**14)
        self.assertEqual(detect_stations([frame[16:]]*10, first,
                                        30000000/(1024*2**7), 7200, 7450), [])

    def test_one_sided_signal_and_changing_noise_floor_are_rejected(self):
        frames = [rf_frame(7325, 7, 7300000, seq) for seq in range(1, 11)]
        first = struct.unpack_from('<I', frames[0], 4)[0]*30000000/(1024*2**14)
        bin_hz = 30000000/(1024*2**7)
        index = round((7300000-first)/bin_hz)
        one_sided = []
        for frame in frames:
            row = bytearray(frame[16:])
            for i in range(index+2, min(1024, index+12)):
                row[i] = 110
            one_sided.append(bytes(row))
        self.assertEqual(detect_stations(one_sided, first, bin_hz, 7200, 7450), [])
        stationary = list(frames[0][16:])
        rows = [bytes(min(252, value+shift) for value in stationary) for shift in range(10)]
        self.assertEqual(detect_stations(rows, first, bin_hz, 7200, 7450), [])

    def test_single_row_spike_and_insufficient_observation_are_rejected(self):
        row = bytearray([110]*1024)
        row[400] = 220
        self.assertEqual(detect_stations([bytes(row)]+[bytes([110]*1024)]*7,
                                        7200000, 230, 7200, 7450), [])
        self.assertEqual(detect_stations([row]*5, 7200000, 230, 7200, 7450), [])


class SurveyTests(unittest.TestCase):
    def start(self):
        search = SmartSeek()
        search.start(7200, 7450, '41 m', ('receiver',), 100)
        return search

    def recorded(self):
        search = SmartSeek()
        context = ('receiver',)
        search.start(7200, 7450, '41 m', context, 100, cache_key=('rx', '41 m'))
        now, sequence = 100, 0
        while search.active:
            center, zoom = search.request(context, now)
            now += .08
            sequence += 1
            search.feed(rf_frame(center, zoom, 7300000, sequence, neighbour=7350000),
                        30000000, 14, 14, now)
        self.assertEqual(len(search.candidates), 2)
        return search, now

    def test_reopen_reuses_results_selection_and_does_not_request_capture(self):
        search, now = self.recorded()
        search.snapshot(now)
        search.move(1)
        selection = search.selection
        candidates = tuple(search.candidates)
        search.close()
        search.start(7200, 7450, '41 m', ('new tuning context',), now+200,
                     cache_key=('rx', '41 m'))
        self.assertTrue(search.snapshot(now+200)['cached'])
        self.assertEqual(tuple(search.candidates), candidates)
        self.assertEqual(search.selection, selection)
        self.assertIsNone(search.request(('new tuning context',), now+200))

    def test_expiry_is_five_minutes_from_measurement_not_last_open(self):
        search, now = self.recorded()
        measured_at = search.measured_at
        search.close()
        for age in (100, 200, 299):
            search.start(7200, 7450, '41 m', ('receiver',), measured_at+age,
                         cache_key=('rx', '41 m'))
            self.assertTrue(search.cached)
            self.assertFalse(search.active)
            search.close()
        search.start(7200, 7450, '41 m', ('receiver',), measured_at+300,
                     cache_key=('rx', '41 m'))
        self.assertFalse(search.cached)
        self.assertTrue(search.active)

    def test_refresh_bypasses_cache_and_receiver_band_keys_do_not_mix(self):
        search, now = self.recorded()
        search.close()
        search.start(7200, 7450, '41 m', ('receiver',), now+1,
                     cache_key=('other rx', '41 m'))
        self.assertTrue(search.active)
        self.assertFalse(search.cached)
        search.close()
        search.start(7200, 7450, '41 m', ('receiver',), now+2,
                     cache_key=('rx', '41 m'))
        self.assertTrue(search.cached)
        search.close()
        search.start(9400, 9900, '31 m', ('receiver',), now+3,
                     cache_key=('rx', '31 m'))
        self.assertTrue(search.active)
        search.close()
        search.start(7200, 7450, '41 m', ('receiver',), now+4,
                     cache_key=('rx', '41 m'), refresh=True)
        self.assertTrue(search.active)
        self.assertFalse(search.cached)

    def test_partial_results_survive_closing_but_unmeasured_timeouts_do_not(self):
        search = self.start()
        center, zoom = search.request(('receiver',), 100)
        for seq in range(1, 12):
            search.feed(rf_frame(center, zoom, 7300000, seq), 30000000, 14, 14, 100+seq*.08)
        self.assertEqual(search.index, 0)
        self.assertGreater(len(search.candidates), 0)
        search.close()
        search.start(7200, 7450, '41 m', ('receiver',), 101)
        self.assertTrue(search.cached)
        self.assertIsNone(search.request(('receiver',), 101))
        search = self.start()
        search.request(('receiver',), 104)
        search.close()
        search.start(7200, 7450, '41 m', ('receiver',), 105)
        self.assertFalse(search.cached)
        self.assertTrue(search.active)

    def test_band_range_is_independent_of_user_zoom_and_covers_edges(self):
        search = self.start()
        span = 30000000/(2**search.zoom*1000)
        self.assertLessEqual(search.windows[0]-span/2, 7200)
        self.assertGreaterEqual(search.windows[-1]+span/2, 7450)
        self.assertGreater(len(search.windows), 1)

    def test_band_edge_carriers_have_room_for_sideband_confirmation(self):
        for carrier in (7200000, 7450000):
            with self.subTest(carrier=carrier):
                search = self.start()
                now, sequence = 100, 0
                while search.active:
                    center, zoom = search.request(('receiver',), now)
                    now += .08
                    sequence += 1
                    search.feed(rf_frame(center, zoom, carrier, sequence), 30000000, 14, 14, now)
                self.assertTrue(any(abs(candidate.frequency_khz-carrier/1000) < .12
                                    for candidate in search.candidates))

    def test_real_rows_publish_before_completion_without_retuning(self):
        search = self.start()
        center, zoom = search.request(('receiver',), 100)
        for seq in range(1, 15):
            search.feed(rf_frame(center, zoom, 7300000, seq), 30000000, 14, 14, 100+seq*.07)
        self.assertTrue(search.active)
        self.assertEqual(len(search.snapshot()['candidates']), 1)
        self.assertEqual(search.index, 0)
        for seq in range(15, 25):
            search.feed(rf_frame(center, zoom, 7300000, seq), 30000000, 14, 14, 100+seq*.07)
        self.assertEqual(search.index, 1)

    def test_old_duplicate_wrong_pan_compressed_and_wrong_zoom_rows_are_ignored(self):
        search = self.start()
        center, zoom = search.request(('receiver',), 100)
        valid = rf_frame(center, zoom, 7300000, 10)
        search.feed(valid, 30000000, 14, 14, 100.1)
        invalid = [valid, rf_frame(center, zoom, 7300000, 9),
                   rf_frame(center+100, zoom, 7300000, 11),
                   rf_frame(center, zoom+1, 7300000, 11),
                   valid[:8]+struct.pack('<I', zoom|0x10000)+valid[12:], b'bad']
        for frame in invalid:
            search.feed(frame, 30000000, 14, 14, 100.2)
        self.assertEqual(len(search.rows), 1)

    def test_metadata_replans_once_and_timeouts_report_incomplete_coverage(self):
        search = self.start()
        search.request(('receiver',), 100.1, 32000000, 6)
        self.assertEqual(search.bandwidth_hz, 32000000)
        self.assertEqual(search.zoom, 6)
        search.request(('receiver',), 104, 32000000, 6)
        snapshot = search.snapshot()
        self.assertFalse(snapshot['active'])
        self.assertEqual(snapshot['skipped'], 1)
        self.assertTrue(snapshot['open'])

    def test_context_change_closes_and_releases_capture(self):
        search = self.start()
        self.assertIsNone(search.request(('different receiver',), 100.1))
        self.assertFalse(search.open)

    def test_sensitivity_filters_without_new_measurement(self):
        search = self.start()
        search._merge([SeekCandidate(7300, 8), SeekCandidate(7350, 30)])
        search.sensitivity = 0
        self.assertEqual(len(search.snapshot()['candidates']), 1)
        search.sensitivity = 100
        self.assertEqual(len(search.snapshot()['candidates']), 2)
        search.move(1)
        self.assertEqual(search.selection, 7350)

    def test_overlap_deduplicates_and_new_cards_do_not_move_selection(self):
        search = self.start()
        search._merge([SeekCandidate(7300, 20), SeekCandidate(7350, 25)])
        search.snapshot()
        search.move(1)
        search._merge([SeekCandidate(7300.1, 25), SeekCandidate(7340, 28)])
        self.assertEqual(len(search.candidates), 3)
        self.assertEqual(search.selection, 7350)
        self.assertEqual(search.candidates[0].frequency_khz, 7300)


class AdaptiveSurveyTests(unittest.TestCase):
    def start(self):
        search = SmartSeek()
        search.start(7200,7450,'41 m',('rx',),100,refresh=True,adaptive=True)
        return search

    def drive(self, search, end, carrier=7300000, unmodulated=False, noise=False):
        now, sequence = 100,0
        while now < end:
            request = search.request(('rx',),now)
            now += .125
            sequence += 1
            if request:
                center,zoom = request
                search.feed(rf_frame(center,zoom,carrier,sequence,
                                     unmodulated=unmodulated,noise=noise),30000000,14,14,now)
        return now

    def test_one_overview_then_continuous_local_passes_preserve_rows(self):
        search = self.start()
        center,zoom = search.request(('rx',),100)
        self.assertEqual(zoom,6)
        self.drive(search,125)
        self.assertTrue(search.overview_done)
        self.assertGreaterEqual(search.pass_count,1)
        self.assertEqual(len(search.candidates),1)
        self.assertAlmostEqual(search.candidates[0].tuning_khz,7300,delta=.12)
        self.assertEqual(search.evidence[search.candidates[0].frequency_khz]['status'],'AM signal')
        self.assertEqual((search.low,search.high),(7200,7450))
        search.close()
        self.assertIsNone(search.request(('rx',),126))

    def test_overview_orders_fine_windows_by_strength_without_publishing_coarse_peaks(self):
        search = self.start()
        search.request(('rx',),100)
        search.worker.candidates = [SeekCandidate(7400,40),SeekCandidate(7205,10)]
        search._finish_worker(102)
        self.assertGreater(search.windows[0],7350)
        self.assertEqual(search.candidates,[])

    def review(self, unmodulated=False, noise=False, target=7302.8):
        search = self.start()
        search.overview_done = True
        search.active = False
        search.index = len(search.windows)
        search.next_pass_at = 1000
        search._merge([SeekCandidate(target,20)])
        search.note_identity(target,False)
        self.drive(search,107,unmodulated=unmodulated,noise=noise)
        return search

    def test_long_recheck_corrects_a_sideband_in_place(self):
        search = self.review()
        self.assertEqual(search.candidates[0].frequency_khz,7302.8)
        self.assertAlmostEqual(search.candidates[0].tuning_khz,7300,delta=.04)
        self.assertEqual(search.evidence[7302.8]['status'],'AM signal')
        self.assertNotIn(7302.8,search.identities)

    def test_long_recheck_distinguishes_unmodulated_carrier_from_unconfirmed_noise(self):
        carrier = self.review(unmodulated=True,target=7300)
        self.assertEqual(carrier.evidence[7300]['status'],'Carrier only')
        noise = self.review(noise=True,target=7300)
        self.assertEqual(noise.evidence[7300]['status'],'Unconfirmed')

    def test_rechecks_are_bounded_and_context_change_cancels_every_phase(self):
        search = self.start()
        search.request(('rx',),100)
        self.assertIsNone(search.request(('other receiver',),100.2))
        self.assertFalse(search.open)
        self.assertIsNone(search.worker)
        search = self.start()
        search.overview_done = True
        search.active = False
        search.index = len(search.windows)
        search.next_pass_at = 1000
        search._merge([SeekCandidate(7300,30)])
        search.note_identity(7300,False)
        first = search.request(('rx',),100)
        self.assertEqual(first[1],10)
        self.assertEqual(search.request(('rx',),101),first)
        self.assertIsNone(search.request(('other receiver',),101.1))

    def test_signal_strength_accumulates_without_reordering_or_holding_peak_forever(self):
        search = self.start()
        search._merge([SeekCandidate(7300,40)],accumulate=True)
        search._merge([SeekCandidate(7300.05,20)],accumulate=True)
        self.assertEqual(search.candidates[0].frequency_khz,7300)
        self.assertGreater(search.candidates[0].prominence,20)
        self.assertLess(search.candidates[0].prominence,40)

    def test_strong_discoveries_precede_weak_and_existing_meters_wait_for_full_observation(self):
        search = self.start()
        search._merge([SeekCandidate(7300,15),SeekCandidate(7350,35)])
        self.assertEqual([c.frequency_khz for c in search.candidates],[7350,7300])
        search._merge([SeekCandidate(7300,45)])
        self.assertEqual(search.candidates[1].prominence,15)
        search._merge([SeekCandidate(7300,45)],accumulate=True)
        self.assertGreater(search.candidates[1].prominence,15)
        self.assertLess(search.candidates[1].prominence,45)
        self.assertEqual([c.frequency_khz for c in search.candidates],[7350,7300])

    def test_two_reviews_per_pass_and_cooldown_leave_time_for_band_coverage(self):
        search = self.start()
        search.overview_done = True
        search._merge([SeekCandidate(7300+i*10,30-i) for i in range(4)])
        for candidate in search.candidates:
            search.note_identity(candidate.frequency_khz,False)
        for now in (100,106):
            search.active = False
            search._start_review(now)
            self.assertIsNotNone(search.worker)
            search.worker.close()
            search._finish_worker(now+5)
        search._start_review(112)
        self.assertIsNone(search.worker)
        self.assertEqual(len(search.reviewed_at),2)
        search.reviews_this_pass = 0
        search._start_review(113)
        self.assertEqual(search.review_target,7320)

    def test_stalled_short_capture_does_not_claim_a_completed_five_second_review(self):
        search = self.start()
        search.overview_done = True
        search.active = False
        search.index = len(search.windows)
        search._merge([SeekCandidate(7300,30)])
        search.note_identity(7300,False)
        center,zoom = search.request(('rx',),100)
        for sequence in range(1,10):
            search.feed(rf_frame(center,zoom,7300000,sequence,unmodulated=True),
                        30000000,14,14,100+sequence*.125)
        search.poll(('rx',),109)
        self.assertNotIn(7300,search.evidence)


class IntegrationTests(unittest.TestCase):
    def state(self, zoom=14):
        state = ui.SharedState('http://example.test:8073', 7325, zoom, -95, 142, 245, 4, 'am', False)
        state.connection_streams = {'audio': True, 'waterfall': True}
        return state

    def test_capture_does_not_change_audio_tuning_filters_or_display_zoom(self):
        state = self.state()
        before = state.snapshot(), state.radio_snapshot()
        self.assertTrue(state.start_smart_seek())
        self.assertIsNotNone(state.smart_seek_capture_request())
        self.assertIsNone(state.carrier_capture_request())
        self.assertFalse(state.carrier_ready_snapshot())
        state.close_smart_seek()
        self.assertEqual((state.snapshot(), state.radio_snapshot()), before)
        self.assertFalse(state.smart_seek_snapshot()['open'])

    def test_nominal_frequency_display_keeps_measured_carrier_for_listening(self):
        state = self.state()
        state.start_smart_seek()
        state.smart_seek._merge([SeekCandidate(7298.8,30)])
        matches = schedule_matches([dict(frequency_khz=7300,station='BBC',country='United Kingdom',
                                         time='0000-2400')],ui._frequency_identity_schedule_active)
        self.assertEqual(station_frequency(7298.8,matches),(7300,False))
        self.assertEqual(frequency_label(7300),'7,300 kHz')
        self.assertTrue(state.tune_smart_seek_candidate(7298.8))
        self.assertEqual(state.freq_khz,7298.8)

    def test_background_carrier_refinement_waits_for_explicit_tap_to_retune(self):
        state = self.state()
        state.start_smart_seek()
        state.smart_seek._merge([SeekCandidate(7302.8,30)])
        self.assertTrue(state.tune_smart_seek_candidate(7302.8))
        state.smart_seek.candidates[0] = SeekCandidate(7302.8,32,7300)
        snapshot = state.smart_seek_snapshot()
        self.assertEqual(snapshot['playing_khz'],7302.8)
        self.assertTrue(state.tune_smart_seek_candidate(7302.8))
        self.assertEqual(state.freq_khz,7300)
        self.assertEqual(state.smart_seek.selection,7302.8)
        self.assertTrue(state.smart_seek.open)

    def test_names_follow_refined_carrier_and_cached_names_still_guide_new_scan(self):
        state = self.state()
        state.start_smart_seek()
        view = SmartSeekView(ui,state)
        self.addCleanup(view.shutdown)
        candidate = SeekCandidate(7302.8,30)
        view.matches[7302.8] = ()
        view.lookup_targets[7302.8] = 7302.8
        view._names_for_page([candidate])
        self.assertEqual(state.smart_seek.identities[7302.8],(False,()))
        candidate = SeekCandidate(7302.8,30,7300)
        view.executor.submit = Mock(return_value=Future())
        view._names_for_page([candidate])
        self.assertNotIn(7302.8,view.matches)
        view.executor.submit.assert_called_once_with(ui.lookup_smart_seek_frequency,7300)

    def test_unknown_channel_is_marked_approximate_and_ambiguous_matches_keep_rf_value(self):
        self.assertEqual(station_frequency(5879.891,()),(5880,True))
        self.assertEqual(station_frequency(5882.5,()),(5882.5,False))
        matches = (BroadcastMatch('A','China',frequency_khz=7300),
                   BroadcastMatch('B','Romania',frequency_khz=7300.8))
        self.assertEqual(station_frequency(7300.4,matches),(7300.4,False))

    def test_band_chooser_starts_only_chosen_band_and_refresh_keeps_that_band(self):
        state = self.state()
        state.start_smart_seek()
        state.smart_seek._merge([SeekCandidate(7300,30)])
        before = state.freq_khz, state.radio_snapshot()
        view = SmartSeekView(ui,state)
        self.addCleanup(view.shutdown)
        view.actions = [((0,0,100,70),('band','31 m'))]
        view.press(20,20)
        self.assertIsNone(view.release(20,20))
        self.assertEqual(state.smart_seek_snapshot()['label'],'31 m')
        self.assertEqual((state.smart_seek.low,state.smart_seek.high),(9400,9900))
        self.assertEqual(state.smart_seek.candidates,[])
        self.assertEqual((state.freq_khz,state.radio_snapshot()),before)
        state.start_smart_seek(refresh=True)
        self.assertEqual(state.smart_seek_snapshot()['label'],'31 m')
        self.assertFalse(state.start_smart_seek(band_label='not a band'))
        self.assertEqual(state.smart_seek_snapshot()['label'],'31 m')

    def test_pages_and_drag_scroll_viewport_without_tuning_and_back_restores_listening(self):
        state = self.state()
        state.start_smart_seek()
        state.smart_seek._merge([SeekCandidate(7205+i*5,30) for i in range(30)])
        before = state.freq_khz
        view = SmartSeekView(ui,state)
        self.addCleanup(view.shutdown)
        view.scroll_rows(10)
        self.assertEqual(view.first_visible,10)
        view.scroll_rows(-10)
        self.assertEqual(view.first_visible,0)
        view.actions = [((0,100,1200,156),('tune',7205))]
        view.press(20,120)
        self.assertTrue(view.drag(20,0))
        self.assertGreater(view.first_visible,0)
        self.assertIsNone(view.release(20,0))
        self.assertEqual(state.freq_khz,before)
        view.actions = [(ui.RAIL_BACK_BOX,('close',None))]
        view.press(1100,750)
        self.assertIsNone(view.release(1100,750))
        self.assertFalse(view.open)
        self.assertEqual(state.freq_khz,before)

    def test_frequency_identity_uses_offline_lookup_and_never_queries_web_pages(self):
        with patch.object(ui.offline_schedules,'lookup',return_value=(7300,[],None)) as lookup, \
             patch.object(ui,'urlopen') as network:
            self.assertEqual(ui.lookup_shortwave_frequency(7300),(7300,[],None))
            ui.prefetch_frequency_identity_neighbours(7300)
            lookup.assert_called_once()
            network.assert_not_called()

    def test_unknown_row_research_has_priority_and_never_tunes(self):
        state = self.state()
        state.start_smart_seek()
        state.smart_seek._merge([SeekCandidate(7300,30)])
        view = SmartSeekView(ui,state)
        self.addCleanup(view.shutdown)
        pending = Future()
        with patch.object(view.executor,'submit',return_value=pending) as submit:
            view.actions = [((20,100,1260,156),('tune',7300)),
                            ((1088,100,1260,156),('research',7300))]
            before = state.freq_khz
            view.press(1150,125)
            self.assertIsNone(view.release(1150,125))
            self.assertEqual(view.research_frequency,7300)
            self.assertEqual(state.freq_khz,before)
            submit.assert_called_once_with(ui.research_shortwave_frequency,7300)
            self.assertIsNone(view.selected())
            view.back()
            self.assertTrue(view.open)
            self.assertIsNone(view.research_frequency)
            view.press(100,125)
            self.assertEqual(view.release(100,125),7300)

    def test_online_research_is_explicit_and_keeps_nearby_suggestions(self):
        document = ('<h2>Test schedules</h2><table class="results"><tr>'+
                    ''.join('<td>'+value+'</td>' for value in
                    ('7302','0000-2400','Example Radio','Romania','English','daily','100','Galbeni'))+
                    '</tr></table>')
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = document.encode()
        with patch.object(ui,'urlopen',return_value=response) as network:
            frequency,rows,error = ui.research_shortwave_frequency(7300)
        self.assertEqual(network.call_count,2)
        self.assertEqual(frequency,7300)
        self.assertEqual(rows[0]['frequency_khz'],7302)
        self.assertEqual(rows[0]['station'],'Example Radio')
        self.assertIsNone(error)

    def test_online_research_failure_leaves_offline_browsing_usable(self):
        with patch.object(ui,'urlopen',side_effect=OSError('offline')):
            frequency,rows,error = ui.research_shortwave_frequency(7300)
        self.assertEqual((frequency,rows),(7300,[]))
        self.assertTrue(error)

    def test_live_context_changes_cancel_and_prevent_stale_capture(self):
        for action in (lambda s:s.set_view(freq_khz=7400), lambda s:s.set_radio_mode('USB'),
                       lambda s:s.set_filter(-2000, 2000), lambda s:s.set_stream_paused(True),
                       lambda s:s.set_server('http://another.test:8073'),
                       lambda s:s.set_external_waterfall(True),
                       lambda s:s.connection_streams.update(waterfall=False)):
            with self.subTest(action=action):
                state = self.state()
                state.start_smart_seek()
                action(state)
                self.assertFalse(state.smart_seek_snapshot()['open'])
                self.assertIsNone(state.smart_seek_capture_request())

    def test_unconnected_and_other_receiver_modes_cannot_start(self):
        state = self.state()
        state.connection_streams['waterfall'] = False
        self.assertFalse(state.start_smart_seek())
        state.connection_streams['waterfall'] = True
        state.set_radio_mode('USB')
        self.assertFalse(state.start_smart_seek())
        state = self.state()
        with patch.object(ui.owrx, 'is_openwebrx_endpoint', return_value=True):
            self.assertFalse(state.start_smart_seek())

    def test_outside_broadcast_bands_starts_in_nearest_broadcast_allocation(self):
        for frequency in (4200, 4500, 7075, 10000, 14200, 27000):
            with self.subTest(frequency=frequency):
                state = self.state()
                state.set_view(freq_khz=frequency)
                before = state.snapshot()
                self.assertTrue(state.smart_seek_available())
                self.assertTrue(state.start_smart_seek())
                band = min(ui.SW_BROADCAST_BANDS,
                           key=lambda b:max(b[0]-frequency, frequency-b[1], 0))
                self.assertEqual((state.smart_seek.low, state.smart_seek.high), band[:2])
                self.assertEqual(state.smart_seek_snapshot()['label'], band[2])
                self.assertEqual(state.snapshot(), before)

    def test_every_broadcast_band_uses_its_exact_boundaries(self):
        for low, high, label in ui.SW_BROADCAST_BANDS:
            with self.subTest(band=label):
                state = self.state()
                state.set_view(freq_khz=(low+high)/2)
                self.assertTrue(state.smart_seek_available())
                self.assertTrue(state.start_smart_seek())
                self.assertEqual((state.smart_seek.low, state.smart_seek.high), (low, high))
                self.assertEqual(state.smart_seek_snapshot()['label'], label)

    def test_encoder_selection_and_safe_press_do_not_tune_implicitly(self):
        state = self.state()
        state.start_smart_seek()
        state.smart_seek._merge([SeekCandidate(7300, 20), SeekCandidate(7350, 20)])
        view = SmartSeekView(ui, state)
        self.addCleanup(view.shutdown)
        view.move(1)
        self.assertEqual(view.selected(), 7350)
        self.assertEqual(state.snapshot()[1], 7325)

        view.actions = [((0, 0, 100, 100), ('tune', 7350))]
        view.press(20, 20)
        view.actions = [((0, 0, 100, 100), ('tune', 7300))]
        self.assertIsNone(view.release(20, 20))
        view.press(20, 20)
        self.assertEqual(view.release(20, 20), 7300)
        self.assertEqual(state.snapshot()[1], 7325)

    def test_schedule_matches_handle_all_day_colon_times_and_ambiguity(self):
        state = self.state()
        view = SmartSeekView(ui, state)
        self.addCleanup(view.shutdown)
        for frequency, rows, names in (
            (7300, [dict(time='0000-2400', station='Example')], ['Example']),
            (7310, [dict(time='00:00–24:00', station='Example')], ['Example']),
            (7320, [dict(time='0000-2400', station='A'), dict(time='0000-2400', station='B')], ['A', 'B']),
            (7330, [], []),
        ):
            future = Future()
            future.set_result((frequency, rows, None))
            view.pending[frequency] = future
            view._names_for_page([])
            self.assertEqual([match.name for match in view.matches[frequency]], names)

    def test_multiple_countries_remain_distinct_and_duplicate_schedules_merge(self):
        rows = [dict(time='0000-2400', station='Radio Example', country=country)
                for country in ('China', 'Romania', 'China')]
        matches = schedule_matches(rows, ui._frequency_identity_schedule_active)
        self.assertEqual(matches, (BroadcastMatch('Radio Example', 'China', schedule='0000-2400'),
                                   BroadcastMatch('Radio Example', 'Romania', schedule='0000-2400')))

    def test_old_schedule_marker_is_preserved_with_the_station_name(self):
        rows = [dict(time='0000-2400',station='Voice of Korea',country='North Korea',
                     frequency_khz=9435,schedule_stale=True)]
        match = schedule_matches(rows,ui._frequency_identity_schedule_active)[0]
        self.assertEqual(match.name,'Voice of Korea')
        self.assertTrue(match.old_schedule)
        self.assertEqual(match.frequency_khz,9435)
        rows[0].pop('schedule_stale')
        self.assertFalse(schedule_matches(rows,ui._frequency_identity_schedule_active)[0].old_schedule)

    def test_old_schedule_fallback_is_requested_only_for_smart_seek(self):
        with patch.object(ui.offline_schedules,'lookup',return_value=(9435,[],None)) as lookup:
            ui.lookup_shortwave_frequency(9435)
            lookup.assert_called_once_with(9435.0,tolerance=ui.FREQUENCY_ID_TOLERANCE_KHZ)
            lookup.reset_mock()
            ui.lookup_smart_seek_frequency(9435)
            lookup.assert_called_once_with(9435.0,tolerance=ui.FREQUENCY_ID_TOLERANCE_KHZ,
                                          allow_old_season=True)

    def test_schedule_metadata_is_retained_for_the_playing_row(self):
        rows = [dict(station='Radio Example', country='Romania', transmitter='Galbeni',
                     power_kw='300', language='English', time='0000-2400')]
        match = schedule_matches(rows, ui._frequency_identity_schedule_active)[0]
        self.assertEqual(station_detail_lines(match),
                         ('Romania · Galbeni', 'Power: 300 kW · English', 'UTC 0000-2400'))
        unknown = station_detail_lines(BroadcastMatch('Unknown', ''))
        self.assertEqual(unknown, ('Country not listed', 'Power not listed', 'Schedule not listed'))
        self.assertEqual(station_detail_lines(BroadcastMatch('Example', 'China', power_kw='0'))[1],
                         'Power not listed')

    def test_expanded_last_row_scrolls_only_enough_to_keep_it_visible(self):
        view = SmartSeekView(ui, self.state())
        self.addCleanup(view.shutdown)
        candidates = tuple(SeekCandidate(7205+i*5, 20) for i in range(12))
        initial = view.visible_rows(candidates, candidates[0].frequency_khz, 7325)
        self.assertEqual(initial, candidates[:10])
        playing = candidates[9].frequency_khz
        expanded = view.visible_rows(candidates, playing, playing)
        self.assertEqual(view.first_visible, 1)
        self.assertEqual(expanded, candidates[1:10])
        appended = candidates+(SeekCandidate(7400, 30),)
        self.assertEqual(view.visible_rows(appended, playing, playing), expanded)
        self.assertEqual(view.first_visible, 1)

    def test_compact_rows_return_when_the_playing_station_is_offscreen(self):
        view = SmartSeekView(ui, self.state())
        self.addCleanup(view.shutdown)
        candidates = tuple(SeekCandidate(7205+i*5, 20) for i in range(18))
        first = view.visible_rows(candidates, candidates[0].frequency_khz, candidates[0].frequency_khz)
        self.assertEqual(len(first), 9)
        later = view.visible_rows(candidates, candidates[15].frequency_khz, candidates[0].frequency_khz)
        self.assertEqual(len(later), 10)
        self.assertIn(candidates[15], later)

    def test_minimum_signal_slider_filters_weak_to_strong_without_tuning_or_sorting(self):
        state = self.state()
        state.start_smart_seek()
        state.smart_seek._merge([SeekCandidate(7300, 9), SeekCandidate(7350, 30)])
        view = SmartSeekView(ui, state)
        self.addCleanup(view.shutdown)
        box = view.signal_slider_box()
        view.actions = [(box, ('signal', None))]
        y = (box[1]+box[3])/2
        view.press(32, y)
        self.assertEqual([item.frequency_khz for item in state.smart_seek_snapshot()['candidates']], [7350, 7300])
        self.assertTrue(view.drag(320, y))
        self.assertEqual([item.frequency_khz for item in state.smart_seek_snapshot()['candidates']], [7350])
        self.assertIsNone(view.release(320, y))
        self.assertIsNone(view.press_action)
        view.press(32, y)
        view.release(32, y)
        self.assertEqual([item.frequency_khz for item in state.smart_seek_snapshot()['candidates']], [7350, 7300])
        self.assertEqual(state.snapshot()[1], 7325)
        self.assertTrue(view.open)

    def test_repeated_quick_selection_keeps_list_and_active_survey_open(self):
        with patch.object(ui.time, 'monotonic', return_value=100):
            state = self.state()
            state.start_smart_seek()
            state.smart_seek._merge([SeekCandidate(7300, 20), SeekCandidate(7350, 25)])
            state.smart_seek.measured_at = 100
            candidates = tuple(state.smart_seek.candidates)
            for frequency in (7300, 7350, 7300):
                self.assertTrue(state.tune_smart_seek_candidate(frequency))
                self.assertEqual(state.snapshot()[1], frequency)
                self.assertTrue(state.smart_seek_snapshot()['open'])
                self.assertTrue(state.smart_seek_snapshot()['active'])
                self.assertIsNotNone(state.smart_seek_capture_request())
                self.assertEqual(tuple(state.smart_seek.candidates), candidates)
            self.assertFalse(state.tune_smart_seek_candidate(7400))
            state.close_smart_seek()
        with patch.object(ui.time, 'monotonic', return_value=250):
            self.assertTrue(state.start_smart_seek())
            self.assertFalse(state.smart_seek_snapshot()['cached'])
            self.assertEqual(tuple(state.smart_seek.candidates), ())
            self.assertIsNotNone(state.smart_seek_capture_request())

    def test_local_pass_repeats_without_other_bands_and_reopen_is_empty(self):
        with patch.object(ui.time, 'monotonic') as clock:
            clock.return_value = 100
            state = self.state()
            state.start_smart_seek()
            initial_frequency = state.freq_khz
            now, sequence = 100, 0
            while state.smart_seek.active:
                clock.return_value = now
                center, zoom = state.smart_seek_capture_request()
                now += .08
                clock.return_value = now
                sequence += 1
                state.feed_smart_seek_frame(rf_frame(center, zoom, 7300000, sequence),
                                            30000000, 14, 14)
            self.assertTrue(state.smart_seek.candidates)
            self.assertTrue(all(7200 <= p.frequency_khz <= 7450 for p in state.smart_seek.candidates))
            clock.return_value = now+60
            self.assertIsNotNone(state.smart_seek_capture_request())
            self.assertTrue(state.smart_seek_snapshot()['open'])
            self.assertEqual(state.freq_khz, initial_frequency)
            state.close_smart_seek()
            state.start_smart_seek()
            self.assertEqual(state.smart_seek_snapshot()['candidates'], ())
            self.assertFalse(state.smart_seek_snapshot()['cached'])
            self.assertIsNotNone(state.smart_seek_capture_request())

    def test_progress_tracks_received_rows_in_the_current_local_window(self):
        with patch.object(ui.time, 'monotonic') as clock:
            clock.return_value = 100
            state = self.state()
            state.start_smart_seek()
            self.assertEqual(state.smart_seek_snapshot()['window_progress'], 0)
            center, zoom = state.smart_seek_capture_request()
            clock.return_value = 100.1
            state.feed_smart_seek_frame(rf_frame(center, zoom, 7300000, 1), 30000000, 14, 14)
            clock.return_value = 100.4
            snapshot = state.smart_seek_snapshot()
            self.assertGreater(snapshot['window_progress'], 0)
            self.assertEqual(snapshot['scanning_khz'], center)



if __name__ == '__main__':
    unittest.main()
