import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import kiwi_gl_display as ui
from long_scan import ActivityHistory, KiwiScanSession, LongScan, receiver_address
from long_scan_view import LongScanView
from smart_seek import SeekCandidate
from smart_seek_view import SmartSeekView


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'history.sqlite3'
        self.store = ActivityHistory(self.path)
        self.addCleanup(lambda:self.store.close())
        self.signal = SeekCandidate(7300.04,30)

    def record(self, stamp, hits=True, measured=True, receiver='rx', band='41 m'):
        self.store.record(receiver,band,7200,7450,[self.signal] if hits else [],measured,stamp)

    def test_hour_broadcast_makes_continuous_trace_then_two_misses_end_it(self):
        for stamp in range(1000,4601,360):
            self.record(stamp)
        self.record(4960,hits=False)
        uncertain = self.store.read('rx',hours=1,now=4960)
        self.assertTrue(uncertain['tails'])
        self.record(5320,hits=False)
        ended = self.store.read('rx',hours=1,now=5320)
        self.assertEqual(ended['tails'],[])
        self.assertEqual(max(segment[1] for segment in ended['segments']),4600)
        self.record(5680)
        returned = self.store.read('rx',hours=1,now=5680)
        self.assertFalse(any(segment[0] <= 4600 and segment[1] >= 5680 for segment in returned['segments']))

    def test_one_measured_miss_can_recover_but_unmeasured_outage_does_not_bridge(self):
        self.record(1000)
        self.record(1360,hits=False)
        self.record(1720)
        view = self.store.read('rx',now=1720)
        self.assertEqual(len(view['segments']),1)
        self.record(2080,hits=False,measured=False)
        self.record(2440)
        view = self.store.read('rx',now=2440)
        self.assertEqual(len(view['segments']),1)
        self.assertEqual(view['gaps'],[(2080,'41 m')])

    def test_unvisited_time_and_receiver_changes_never_generate_false_absence(self):
        self.record(1000)
        self.record(1360,receiver='other',hits=False)
        self.assertEqual(len(self.store.read('rx',now=1360)['tails']),1)
        self.assertEqual(self.store.read('other',now=1360)['points'],[])
        self.assertEqual(self.store.read('rx',now=3000)['tails'],[])

    def test_history_survives_reopen_and_ranges_do_not_draw_before_start(self):
        self.record(1000)
        self.record(1360)
        other = ActivityHistory(self.path)
        try:
            result = other.read('rx',hours=1,now=1500)
            self.assertEqual(len(result['points']),2)
            self.assertTrue(all(a <= b for a,b,*_ in result['segments']))
        finally:
            other.close()

    def test_connection_gap_breaks_all_bands_and_old_data_is_pruned(self):
        self.record(1000)
        self.store.record('rx','*',0,30000,(),False,1200)
        self.record(1360)
        self.assertEqual(self.store.read('rx',now=1360)['segments'],[])
        self.record(200000)
        self.assertEqual(self.store.read('rx',hours=24,now=200000)['points'],[(200000,'41 m',7300.04,30)])


class SessionTests(unittest.TestCase):
    def ws(self, messages):
        ws = Mock()
        ws.sock.pending.return_value = 0
        ws.recv.side_effect = messages
        return ws

    def test_session_pairs_audio_and_waterfall_with_own_identity_and_discards_audio(self):
        snd = self.ws([b'MSG badp=0 audio_rate=12000 sample_rate=12000',b'SND'+bytes(12),b'SND'+bytes(12),b'SND'+bytes(12)])
        frame = b'W/F'+bytes(1037)
        wf = self.ws([b'MSG badp=0 bandwidth=32000000 zoom_max=14 zoom_cap=12',frame])
        connect = Mock(side_effect=[snd,wf])
        session = KiwiScanSession('http://example.test:8073',12345,threading.Event(),connect)
        with patch('long_scan.select.select',side_effect=lambda sockets,*args:(sockets,[],[])):
            session.open()
            session.set_view(7325,8)
            self.assertIsNone(session.read())
            self.assertEqual(session.read(),frame)
        self.assertEqual([call.args[1] for call in connect.call_args_list],['SND','W/F'])
        self.assertTrue(all(call.kwargs['session_timestamp']==12345 for call in connect.call_args_list))
        self.assertEqual(session.bandwidth,32000000)
        self.assertEqual(session.zoom_cap,12)
        for ws in (snd,wf):
            self.assertTrue(any('ident_user=' in call.args[0] and '-LongScan' in call.args[0]
                                for call in ws.send_text.call_args_list))
            self.assertFalse(any(call.args[0] == 'SET ident_user='+ui.kiwi.CLIENT_NAME
                                 for call in ws.send_text.call_args_list))
        self.assertTrue(any('cf=7325.000' in call.args[0] for call in wf.send_text.call_args_list))
        session.close()
        snd.sock.close.assert_called_once()
        wf.sock.close.assert_called_once()

    def test_receiver_capacity_error_does_not_open_another_socket(self):
        snd = self.ws([b'MSG badp=5'])
        connect = Mock(return_value=snd)
        session = KiwiScanSession('http://example.test:8073',12345,threading.Event(),connect)
        with patch('long_scan.select.select',side_effect=lambda sockets,*args:(sockets,[],[])):
            with self.assertRaisesRegex(RuntimeError,'badp=5'):
                session.open()
        self.assertEqual(connect.call_count,1)
        session.close()
        self.assertEqual(LongScan.retry_delay(1,'badp=5'),60)
        self.assertEqual(LongScan.retry_delay(1,'timeout'),2)
        self.assertEqual(LongScan.retry_delay(20,'timeout'),60)

    def test_idle_waterfall_stops_rows_and_same_view_resumes_with_only_one_command(self):
        session = KiwiScanSession('http://example.test:8073',1,threading.Event())
        session.snd = Mock()
        session.wf = Mock()
        session.wf_authenticated = True
        session.set_view(7300,8)
        self.assertEqual(session.wf.send_text.call_count,5)
        session.frames.append(b'old frame')
        session.pause_waterfall()
        session.pause_waterfall()
        self.assertEqual(session.wf.send_text.call_count,6)
        self.assertEqual(session.wf.send_text.call_args.args[0],'SET wf_speed=0')
        self.assertEqual(len(session.frames),0)
        session._message(session.wf,b'W/F'+bytes(1037))
        self.assertEqual(len(session.frames),0)
        session.last_frame = 0
        with patch.object(session,'_read_ready'),patch('long_scan.time.monotonic',return_value=100):
            self.assertIsNone(session.read())
            session.set_view(7300,8)
            self.assertEqual(session.last_frame,100)
        self.assertFalse(session.waterfall_paused)
        self.assertEqual(session.wf.send_text.call_count,7)
        self.assertEqual(session.wf.send_text.call_args.args[0],'SET wf_speed=4')
        with patch.object(session,'_read_ready'),patch('long_scan.time.monotonic',return_value=116):
            with self.assertRaises(TimeoutError):
                session.read()


class ControllerViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.controller = LongScan(ui.SW_BROADCAST_BANDS,self.temp.name)
        self.addCleanup(self.controller.close)

    def state(self):
        state = ui.SharedState('http://example.test:8073',7325,8,-95,142,245,4,'am',False)
        state.connection_streams = {'audio':True,'waterfall':True}
        state.start_smart_seek()
        return state

    def test_receiver_validation_and_saved_range(self):
        self.assertEqual(receiver_address('receiver.local:8073'),'http://receiver.local:8073')
        for invalid in ('file:///tmp/test','http://user:pass@receiver','http://receiver/page','http://receiver:bad'):
            with self.assertRaises(ValueError):
                receiver_address(invalid)
        self.controller.configure(receiver='http://example.test:8073',hours=24)
        saved = json.loads(self.controller.config_path.read_text())
        self.assertEqual(saved['hours'],24)
        self.assertFalse(saved['enabled'])
        with self.assertRaises(ValueError):
            self.controller.configure(hours=3)

    def test_hidden_title_opens_setup_and_back_never_tunes_or_stops_listener(self):
        state = self.state()
        view = SmartSeekView(ui,state,self.controller)
        self.addCleanup(view.shutdown)
        before = state.snapshot()
        view.actions = [((10,8,250,66),('long_setup',None))]
        view.press(100,30)
        self.assertIsNone(view.release(100,30))
        self.assertTrue(view.long_view.open)
        self.assertIsNone(view.selected())
        view.long_view.action('view',None)
        view.move(1)
        self.assertEqual(self.controller.snapshot()['hours'],24)
        view.back()
        self.assertEqual(view.long_view.page,'setup')
        view.back()
        self.assertFalse(view.long_view.open)
        self.assertTrue(view.open)
        self.assertEqual(state.snapshot(),before)

    def test_receiver_keyboard_is_shared_and_cancel_keeps_current_receiver(self):
        state = self.state()
        view = SmartSeekView(ui,state,self.controller)
        self.addCleanup(view.shutdown)
        view.long_view.show()
        view.long_view.action('receiver',None)
        self.assertTrue(view.keyboard_open)
        with patch.object(ui,'draw_touch_keyboard') as keyboard:
            view.draw(Mock())
        keyboard.assert_called_once()
        self.assertEqual(keyboard.call_args.args[1],'Long Scan receiver')
        view.long_view.entry = 'http://discarded.test'
        view.back()
        self.assertEqual(self.controller.snapshot()['receiver'],'http://example.test:8073')
        self.assertFalse(view.keyboard_open)

    def test_stop_interrupts_pending_start_and_preserves_history(self):
        self.controller.configure(receiver='http://example.test:8073')
        self.assertTrue(self.controller.start(startup_delay=30))
        self.controller.stop()
        self.controller.thread.join(1)
        self.assertFalse(self.controller.snapshot()['running'])
        self.assertFalse(json.loads(self.controller.config_path.read_text())['enabled'])
        self.controller.history.record('http://example.test:8073','41 m',7200,7450,[SeekCandidate(7300,20)],True,100)
        self.assertEqual(len(self.controller.history.read('http://example.test:8073',now=100)['points']),1)

    def test_closing_smart_scan_does_not_stop_the_dedicated_session(self):
        self.controller.configure(receiver='http://example.test:8073')
        self.controller.start(startup_delay=30)
        state = self.state()
        view = SmartSeekView(ui,state,self.controller)
        self.addCleanup(view.shutdown)
        view.long_view.show()
        view.close()
        self.assertFalse(view.long_view.open)
        self.assertTrue(self.controller.snapshot()['running'])
        self.assertFalse(self.controller.stopped.is_set())

    def test_enabled_setting_survives_app_shutdown_and_resume_defers_to_listener(self):
        self.controller.configure(receiver='http://example.test:8073')
        self.controller.start(startup_delay=30)
        self.controller.close()
        restored = LongScan(ui.SW_BROADCAST_BANDS,self.temp.name)
        try:
            self.assertTrue(restored.snapshot()['enabled'])
            with patch.object(restored,'start') as start:
                restored.resume()
            start.assert_called_once_with(startup_delay=5)
        finally:
            restored.close()

    def test_history_view_discards_a_completed_query_for_another_receiver(self):
        self.controller.configure(receiver='http://one.test')
        self.controller.history.record('http://one.test','41 m',7200,7450,[SeekCandidate(7300,20)],True)
        self.controller.history.record('http://two.test','49 m',5730,6200,[SeekCandidate(6000,20)],True)
        view = LongScanView(ui,self.controller,lambda:'http://one.test')
        self.addCleanup(view.shutdown)
        view._history(self.controller.snapshot())
        view.future.result(1)
        self.controller.configure(receiver='http://two.test')
        self.assertIsNone(view._history(self.controller.snapshot()))
        view.future.result(1)
        result = view._history(self.controller.snapshot())
        self.assertEqual([point[2] for point in result['points']],[6000])


if __name__ == '__main__':
    unittest.main()
