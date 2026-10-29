import random
import struct
import unittest
from unittest.mock import patch

from am_carrier import CarrierSearch, carrier_available, carrier_peak, rf_view_center_hz
import kiwi_gl_display as ui


def rf_frame(center_khz, zoom, carrier_hz, sequence, cap=14, bandwidth=30000000,
             neighbour=None, noise=False, broad=False):
    zoom = min(zoom, cap)
    bin_hz = bandwidth / (1024 * 2**zoom)
    start = max(0, round((center_khz*1000 - bin_hz*512) * (1024 * 2**14) / bandwidth))
    start = min(start, (1024 << 14) - (1024 << (14-zoom)))
    first = start * bandwidth / (1024 * 2**14)
    rng = random.Random(sequence)
    row = []
    for i in range(1024):
        value = 110 + rng.randrange(-2, 3)
        for hz in (() if noise else (carrier_hz,) + (() if neighbour is None else (neighbour,))):
            distance = (first + i*bin_hz - hz) / bin_hz
            value = max(value, 210 - (1 if broad else 45) * distance**2)
        row.append(max(0, min(255, round(value))))
    return b'W/F\0' + struct.pack('<III', start, zoom, sequence) + bytes(row)


def complete(search, now=1, cap=14, carrier_hz=10000037, **kwargs):
    result = None
    for sequence in range(1, 25):
        candidate = search.feed(rf_frame(search.center_hz/1000, search.zoom, carrier_hz,
                                     sequence, cap=cap, **kwargs), 30000000, 14, cap,
                             now + sequence*.04)
        if candidate is not None:
            result = candidate
        if not search.active:
            break
    return result


class CarrierTests(unittest.TestCase):
    def test_two_stage_acquisition_at_native_and_capped_zoom(self):
        for cap in (11, 14):
            for offset in (-1437, -37, 0, 37, 1487):
                with self.subTest(cap=cap, offset=offset):
                    search = CarrierSearch()
                    search.start(10000, 9800, ('rx', 1), 1)
                    found = complete(search, cap=cap, carrier_hz=10000000+offset)
                    self.assertIsNotNone(found)
                    self.assertLess(abs(found*1000 - (10000000+offset)), 2)
                    self.assertFalse(search.active)
                    self.assertEqual(search.status, 'READY')

    def test_noise_broad_signal_and_equal_competing_carriers_do_not_tune(self):
        for options in ({'noise': True}, {'broad': True}, {'neighbour': 10000737}):
            with self.subTest(options=options):
                search = CarrierSearch()
                search.start(10000, 9800, ('rx',), 1)
                self.assertIsNone(complete(search, **options))
                self.assertTrue(search.active)
                self.assertFalse(search.poll(('rx',), 11))
                self.assertEqual(search.status, 'NO CARRIER')

    def test_strong_adjacent_station_outside_search_window_is_ignored(self):
        search = CarrierSearch()
        search.start(10000, 9800, (), 1)
        found = complete(search, neighbour=10005000)
        self.assertAlmostEqual(found, 10000.037, places=3)

    def test_carrier_outside_window_does_not_tune(self):
        search = CarrierSearch()
        search.start(10000, 9800, (), 1)
        self.assertIsNone(complete(search, carrier_hz=10004000))

    def test_transient_spike_is_not_a_carrier(self):
        frame = rf_frame(10000, 11, 10000037, 1)
        start = struct.unpack_from('<I', frame, 4)[0]
        bin_hz = 30000000 / (1024 * 2**11)
        first = start * 30000000 / (1024 * 2**14)
        self.assertIsNone(carrier_peak([frame[16:]] + [bytes([110]*1024)]*4,
                                       first, bin_hz, 10000000, 2500))

    def test_stale_duplicate_wrong_zoom_pan_and_compressed_rows_are_rejected(self):
        search = CarrierSearch()
        search.start(10000, 9800, (), 1)
        frame = rf_frame(10000, 11, 10000037, 10)
        search.feed(frame, 30000000, 14, 14, 1.1)
        for message in (frame, rf_frame(10000, 11, 10000037, 9),
                        rf_frame(10000, 14, 10000037, 11),
                        rf_frame(10005, 11, 10000037, 11),
                        frame[:8] + struct.pack('<I', 11 | 0x10000) + frame[12:],
                        b'bad', frame[:-1]):
            search.feed(message, 30000000, 14, 14, 1.2)
            self.assertEqual(len(search.rows), 1)

    def test_sequence_wrap_and_32mhz_receiver_metadata(self):
        search = CarrierSearch()
        search.start(10000, 9800, (), 1)
        for seq in (0xfffffffe, 0xffffffff, 0, 1):
            search.feed(rf_frame(10000, 11, 10000037, seq, bandwidth=32000000),
                        32000000, 14, 14, 1.2)
        self.assertEqual(len(search.rows), 4)

    def test_search_and_restoration_respect_sampling_band_edges(self):
        self.assertEqual(rf_view_center_hz(60000, 30000000, 0), 15000000)
        self.assertEqual(rf_view_center_hz(29990000, 30000000, 6), 29765625)
        self.assertEqual(rf_view_center_hz(10000000, 30000000, 6), 10000000)
        for frequency in (1.0, 29999.0):
            search = CarrierSearch()
            search.start(frequency, 9800, (), 1)
            found = complete(search, carrier_hz=frequency*1000+37)
            self.assertIsNotNone(found)
            self.assertLess(abs(found*1000 - frequency*1000 - 37), 2)

    def test_context_change_cancels_without_failure_notice(self):
        search = CarrierSearch()
        search.start(10000, 9800, ('rx1',), 1)
        self.assertFalse(search.poll(('rx2',), 1.1))
        self.assertEqual(search.status, '')

    def test_only_plain_am_family_is_available(self):
        for mode in ('AM', 'AMN', 'AMW'):
            self.assertTrue(carrier_available(mode))
        for mode in ('SAM', 'SAL', 'SAU', 'SAS', 'QAM', 'USB', 'LSB', 'CW', 'IQ', 'DRM', 'NBFM'):
            self.assertFalse(carrier_available(mode))
        for source in ('fmdx', 'openwebrx', 'rtl-sdr', 'airspy-hf'):
            self.assertFalse(carrier_available('AM', source))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        clock = patch.object(ui.time, 'monotonic', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def begin_idle(self, state):
        self.assertIsNone(state.carrier_capture_request())
        self.now += .29
        self.assertIsNone(state.carrier_capture_request())
        self.now += .02
        self.assertIsNotNone(state.carrier_capture_request())

    def prepare(self, state):
        self.begin_idle(state)
        for seq in range(1, 30):
            request = state.carrier_capture_request()
            if request is None:
                break
            self.now += .04
            state.feed_carrier_frame(rf_frame(*request, 10000037, seq), 30000000, 14, 14)
        self.assertTrue(state.carrier_ready_snapshot())
        self.assertFalse(state.carrier_search.active)

    def state(self):
        state = ui.SharedState('http://example.test:8073', 10000, 6, -95,
                               142, 245, 3, 'am', False)
        state.connection_streams = {'audio': True, 'waterfall': True}
        return state

    def test_tuning_preserves_cuts_zoom_and_visible_rf_center_without_channel_snap(self):
        state = self.state()
        state.set_filter(-1900, 5100)
        before = state.radio_snapshot()
        self.prepare(state)
        self.assertEqual(state.snapshot()[1:3], (10000, 6))
        self.assertIsNone(state.take_carrier_result())
        self.assertTrue(ui.carrier_button_visible(state))
        self.assertTrue(state.apply_prepared_carrier())
        self.assertEqual(state.snapshot()[1:3], (10000.037, 6))
        self.assertEqual(state.radio_snapshot(), before)
        self.assertEqual(state.waterfall_view_center_snapshot(), 10000)
        self.assertEqual(state.take_carrier_result(), 10000.037)
        self.assertIsNone(state.take_carrier_result())
        self.assertFalse(state.carrier_ready_snapshot())
        self.now += 1
        self.assertIsNone(state.carrier_capture_request())
        self.assertFalse(state.spectrum_enabled_snapshot())

    def test_manual_actions_disconnect_and_receiver_switch_cancel_search(self):
        for change in (lambda s:s.set_view(freq_khz=9999),
                       lambda s:s.set_radio_mode('USB'),
                       lambda s:s.set_filter(-1500, 1500),
                       lambda s:s.set_stream_paused(True),
                       lambda s:s.set_server('http://other.test:8073'),
                       lambda s:s.set_external_waterfall(True),
                       lambda s:s.connection_streams.update(waterfall=False)):
            state = self.state()
            self.prepare(state)
            change(state)
            self.assertFalse(state.carrier_ready_snapshot())
            self.assertFalse(state.apply_prepared_carrier())
            self.assertIsNone(state.carrier_capture_request())
            self.assertIsNone(state.take_carrier_result())

    def test_no_live_stream_never_tunes(self):
        state = self.state()
        state.connection_streams['waterfall'] = False
        self.assertFalse(state.apply_prepared_carrier())
        self.assertEqual(state.carrier_status_snapshot(), '')
        self.assertEqual(state.snapshot()[1], 10000)

    def test_openwebrx_compatibility_endpoints_do_not_offer_kiwi_capture(self):
        state = self.state()
        with patch.object(ui.owrx, 'is_openwebrx_endpoint', return_value=True):
            self.assertFalse(ui.carrier_button_visible(state))
            self.assertFalse(state.apply_prepared_carrier())

    def test_frequency_changes_and_held_gestures_restart_idle_timer(self):
        state = self.state()
        self.begin_idle(state)
        state.set_view(freq_khz=10001)
        self.assertIsNone(state.carrier_capture_request())
        self.now += .2
        state.note_carrier_activity()
        self.assertIsNone(state.carrier_capture_request())
        self.now += .29
        self.assertIsNone(state.carrier_capture_request())
        self.now += .02
        self.assertEqual(state.carrier_capture_request(), (10001, 11))

    def test_first_fine_result_is_ready_while_refining_without_retuning(self):
        state = self.state()
        self.begin_idle(state)
        for seq in range(1, 11):
            request = state.carrier_capture_request()
            self.now += .04
            state.feed_carrier_frame(rf_frame(*request, 10000037, seq), 30000000, 14, 14)
        self.assertTrue(state.carrier_ready_snapshot())
        self.assertTrue(state.carrier_search.active)
        self.assertEqual(state.snapshot()[1], 10000)
        # The time budget ends refinement even if no more rows arrive.
        self.now += 2.1
        self.assertIsNone(state.carrier_capture_request())
        self.assertTrue(state.apply_prepared_carrier())
        self.assertAlmostEqual(state.snapshot()[1], 10000.037, places=3)

    def test_no_carrier_timeout_stays_hidden_without_repeated_scans(self):
        state = self.state()
        self.begin_idle(state)
        self.now += 10
        self.assertIsNone(state.carrier_capture_request())
        self.assertFalse(ui.carrier_button_visible(state))
        self.now += 100
        self.assertIsNone(state.carrier_capture_request())

    def test_tap_before_ready_does_not_start_search(self):
        state = self.state()
        self.assertFalse(state.apply_prepared_carrier())
        self.assertFalse(state.carrier_search.active)
        self.assertEqual(state.snapshot()[1], 10000)

    def test_pending_result_is_discarded_by_manual_tune(self):
        state = self.state()
        state.carrier_tuned_khz = 10000.037
        state.set_view(freq_khz=10010)
        self.assertIsNone(state.take_carrier_result())

    def test_control_is_clear_of_frequency_favorite_pause_and_retry_notice(self):
        ui.configure_output(True)
        box = ui.carrier_waterfall_box()
        self.assertGreaterEqual(box[1], ui.favorite_waterfall_box()[3]+10)
        self.assertGreater(box[0], ui.rf_canvas_width()/2)
        self.assertLessEqual(box[2], ui.rf_canvas_width())
        self.assertGreaterEqual(box[2]-box[0], 150)
        self.assertGreaterEqual(box[3]-box[1], 58)
        state = self.state()
        self.assertFalse(ui.carrier_button_visible(state))
        self.prepare(state)
        self.assertTrue(ui.carrier_button_visible(state))
        state.set_radio_mode('SAM')
        self.assertFalse(ui.carrier_button_visible(state))
        with patch.object(ui, 'draw_styled_button_frame') as frame:
            ui.draw_carrier_waterfall_button(None, alpha=0)
            frame.assert_not_called()


if __name__ == '__main__':
    unittest.main()
