"""Dual-band allocation, process recovery and coherent UAT map ingestion."""
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from adsb_uat import UATReceiver, age_aircraft, merge_aircraft
from sdr_broker import ReceiverBroker

ES = dict(id='serial:11',serial='11',persistent=True,index=0,label='1090 receiver')
UAT = dict(id='serial:978',serial='978',persistent=True,index=1,label='UAT receiver')


class UATTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.broker = ReceiverBroker()
        self.broker.acquire('adsb',ES['id'])
        self.rx = UATReceiver(self.root,self.root,self.broker,binary=shutil.which('true'),tracker=shutil.which('true'))
        self.rx.control('start')
        self.children = [Mock(),Mock()]
        for child in self.children:child.poll.return_value=None

    def tearDown(self):
        self.rx.stop();self.tmp.cleanup()

    def start(self):
        with patch('adsb_uat.subprocess.Popen',side_effect=self.children) as launch:
            self.rx.step([ES,UAT],[ES['id']])
        return launch

    def payload(self, messages=0, aircraft=None, stamp=None):
        value=dict(now=time.time() if stamp is None else stamp,messages=messages,aircraft=aircraft or [])
        (self.rx.data/'aircraft.json').write_text(json.dumps(value))
        return value

    def test_auto_uses_spare_unique_serial_and_loopback_only(self):
        launch=self.start()
        self.assertEqual(self.rx.assigned,UAT)
        first,second=[call.args[0] for call in launch.call_args_list]
        self.assertIn('driver=rtlsdr,serial=978',first)
        self.assertTrue(first[first.index('--raw-port')+1].startswith('127.0.0.1:'))
        self.assertEqual(first[first.index('--raw-port')+1],second[second.index('--connect')+1])
        self.assertEqual(self.broker.snapshot(),{ES['id']:'adsb',UAT['id']:'uat'})

    def test_one_dongle_never_displaces_1090(self):
        with patch('adsb_uat.subprocess.Popen') as launch:self.rx.step([ES],[ES['id']])
        launch.assert_not_called()
        self.assertEqual(self.rx.status,'WAITING FOR SECOND DONGLE')
        self.assertEqual(self.broker.snapshot(),{ES['id']:'adsb'})

    def test_ambiguous_or_1090_assignment_is_rejected(self):
        with self.assertRaises(ValueError):self.rx.control('assign',ES['id'],[ES,UAT],[ES['id']])
        duplicate=dict(UAT,persistent=False,duplicate=True)
        with self.assertRaises(ValueError):self.rx.control('assign',UAT['id'],[duplicate])
        self.rx.control('assign',UAT['id'],[UAT])
        saved=json.loads((self.root/'uat-settings.json').read_text())
        self.assertEqual(saved,dict(enabled=True,selection=UAT['id']))

    def test_running_without_packets_is_listening_not_receiving(self):
        self.start();self.payload()
        self.rx.step([ES,UAT],[ES['id']])
        self.assertEqual(self.rx.status,'LISTENING')
        self.assertEqual(self.rx.snapshot()['messages'],0)
        self.assertIsNone(self.rx.last_message_at)

    def test_valid_packets_are_tagged_uat_and_age_honestly(self):
        self.start();stamp=time.time()
        self.payload(12,[dict(hex='abc123',lat=37.7,lon=-121.8,seen=1,seen_pos=2)],stamp)
        self.rx.step([ES,UAT],[ES['id']])
        self.assertEqual(self.rx.status,'RECEIVING')
        row=self.rx.snapshot(stamp+3)['aircraft'][0]
        self.assertEqual(row['band'],'978');self.assertEqual(row['seen'],4)
        self.assertEqual(row['seen_pos'],5);self.assertEqual(row['position_time'],stamp-2)
        self.assertEqual(self.rx.snapshot(stamp+20)['aircraft'],[])

    def test_packet_totals_and_last_heard_survive_restart_without_double_counting(self):
        self.start();stamp=time.time();self.payload(12,stamp=stamp)
        self.rx.step([ES,UAT],[ES['id']]);self.rx.step([ES,UAT],[ES['id']])
        self.assertEqual(self.rx.snapshot()['messages'],12)
        self.payload(15,stamp=stamp);self.rx.step([ES,UAT],[ES['id']]);self.rx.stop()
        self.assertEqual(self.rx.snapshot()['messages'],15)
        self.assertEqual(self.rx.snapshot()['last_message_at'],stamp)
        fresh=UATReceiver(self.root,self.root,binary=shutil.which('true'),tracker=shutil.which('true'))
        self.assertEqual(fresh.snapshot()['messages'],15)
        self.assertEqual(fresh.snapshot()['aircraft'],[])
        fresh.control('start')
        children=[Mock(),Mock()]
        for child in children:child.poll.return_value=None
        with patch('adsb_uat.subprocess.Popen',side_effect=children):fresh.step([UAT])
        self.payload(2,stamp=stamp);fresh.step([UAT])
        self.assertEqual(fresh.snapshot()['messages'],17);fresh.stop()

    def test_statistics_disk_error_does_not_interrupt_reception(self):
        self.start();self.payload(1)
        with patch('adsb_uat.Path.write_text',side_effect=OSError('disk full')):
            self.rx.step([ES,UAT],[ES['id']])
        self.assertEqual(self.rx.status,'RECEIVING');self.assertEqual(len(self.rx.processes),2)

    def test_same_serial_new_usb_address_reopens_uat_without_claiming_1090(self):
        self.start();self.rx.assigned.update(bus=3,address=10,usb_path='3-1')
        returning=dict(UAT,bus=3,address=11,usb_path='3-1')
        children=[Mock(),Mock()]
        for p in children:p.poll.return_value=None
        with patch('adsb_uat.subprocess.Popen',side_effect=children) as launch:self.rx.step([ES,returning],[ES['id']])
        self.assertEqual(launch.call_count,2);self.assertEqual(self.rx.assigned['address'],11)
        self.assertTrue(self.rx.enabled);self.assertEqual(self.broker.snapshot()[ES['id']],'adsb')

    def test_stop_or_unplug_releases_both_children_but_keeps_1090(self):
        self.start();self.rx.step([ES],[ES['id']])
        for child in self.children:child.terminate.assert_called_once()
        self.assertFalse(self.rx.processes);self.assertIsNone(self.rx.assigned)
        self.assertEqual(self.broker.snapshot(),{ES['id']:'adsb'})

    def test_failed_child_stops_pair_and_retries_with_backoff(self):
        self.start();self.children[0].poll.return_value=1
        with patch('adsb_uat.subprocess.Popen') as launch:self.rx.step([ES,UAT],[ES['id']])
        launch.assert_not_called();self.children[1].terminate.assert_called_once()
        self.assertEqual(self.rx.status,'RETRYING');self.assertFalse(self.rx.processes)

    def test_other_decoder_is_not_displaced(self):
        self.broker.acquire('sensors',UAT['id'])
        with patch('adsb_uat.subprocess.Popen') as launch:self.rx.step([ES,UAT],[ES['id']])
        launch.assert_not_called();self.assertEqual(self.rx.status,'DONGLE BUSY')

    def test_usb_maintenance_does_not_read_old_tracker_output(self):
        self.payload(100,[dict(hex='old',seen=0)])
        self.broker.acquire('dongle-maintenance','maintenance')
        with patch('adsb_uat.subprocess.Popen') as launch:self.rx.step([ES,UAT],[ES['id']])
        launch.assert_not_called();self.assertEqual(self.rx.status,'DONGLE BUSY')
        self.assertEqual(self.rx.snapshot()['aircraft'],[])

    def test_failed_tracker_launch_releases_decoder_and_lease(self):
        with patch('adsb_uat.subprocess.Popen',side_effect=[self.children[0],OSError('failed tracker')]):
            with self.assertRaises(OSError):self.rx.step([ES,UAT],[ES['id']])
        self.children[0].terminate.assert_called_once()
        self.assertEqual(self.broker.snapshot(),{ES['id']:'adsb'})


class DualBandTests(unittest.TestCase):
    def test_native_live_map_shows_both_passive_readouts_and_receiver_shortcut(self):
        from test_adsb import WorkspaceTests
        fixture=WorkspaceTests();w,ui,manager,state=fixture.dashboard()
        state['bands']=[dict(id='1090',name='1090 ES',status='RECEIVING',enabled=True,messages=55,aircraft_count=3),
            dict(id='978',name='978 UAT',status='WAITING FOR SECOND DONGLE',enabled=True,messages=1,aircraft_count=0)]
        w.draw(Mock());labels=[str(c.args[3]) for c in ui.draw_text.call_args_list]
        self.assertIn('978 UAT',labels);self.assertIn('USB disconnected',labels)
        self.assertTrue(any('1 packet · 0 live' in label for label in labels))
        box=next(box for box,action in w.actions if action==('usb',None))
        self.assertGreaterEqual(box[3]-box[1],56)
        fixture.press(w,('usb',None));self.assertEqual(w.current_screen(),'usb')
        w.go_back();self.assertEqual(w.current_screen(),'map')

    def test_band_status_keeps_counters_but_never_calls_a_missing_receiver_live(self):
        from adsb_bands import band_readings
        state=dict(bands=[dict(id='978',status='WAITING FOR SECOND DONGLE',messages=1,aircraft_count=0,last_message_at=100)])
        uat=band_readings(state,160)[1]
        self.assertEqual(uat['status'],'USB disconnected');self.assertEqual(uat['tone'],'warning')
        self.assertEqual(uat['details'],'1 packet · 0 live · heard 1m ago')
        state['status']='OFFLINE';self.assertTrue(all(b['status']=='Offline' for b in band_readings(state,160)))

    def test_band_status_asset_is_served(self):
        from adsb_monitor import ADSBManager
        from urllib.request import urlopen
        with tempfile.TemporaryDirectory() as root:
            manager=ADSBManager(root=root,scanner=lambda:[],port=0)
            try:
                result=urlopen(f'http://127.0.0.1:{manager.port}/adsb_bands.js')
                self.assertEqual(result.status,200);self.assertIn(b'bandReadings',result.read())
            finally:manager.close()

    def test_native_receiver_tabs_assign_and_control_only_the_selected_band(self):
        from test_adsb import WorkspaceTests
        fixture=WorkspaceTests();w,ui,manager,state=fixture.dashboard()
        state.update(devices=[ES,UAT],bands=[dict(id='1090',name='1090 ES',enabled=True,status='RECEIVING',assigned=ES,selection=ES['id']),
            dict(id='978',name='978 UAT',enabled=False,status='STOPPED',assigned=None,selection='auto',installed=True)])
        w.navigate('usb');w.draw(Mock());fixture.press(w,('usb_band','978'));w.draw(Mock())
        self.assertNotIn(('band_assign',ES['id']),[action for _,action in w.actions])
        fixture.press(w,('band_assign',UAT['id']))
        manager.control.assert_called_with('assign',UAT['id'],band='978')
        fixture.press(w,('band_control','start'))
        manager.control.assert_called_with('start',None,band='978')

    def test_duplicate_aircraft_keep_newest_coherent_position_source(self):
        es=dict(hex='abc123',band='1090',lat=37,lon=-121,seen_pos=1,position_time=100,last_seen_at=100,rssi=-10)
        uat=dict(hex='abc123',band='978',lat=38,lon=-122,seen_pos=0,position_time=101,last_seen_at=101,rssi=-20)
        self.assertEqual(merge_aircraft([es],[uat]),[uat])
        speed=dict(hex='abc123',band='978',gs=100,last_seen_at=102)
        self.assertEqual(merge_aircraft([es],[speed]),[es])

    def test_uat_positions_reach_shared_history_logs_and_direct_coverage(self):
        from adsb_monitor import ADSBManager
        with tempfile.TemporaryDirectory() as root:
            with patch('adsb_monitor.threading.Thread.start'):
                manager=ADSBManager(root=root,scanner=lambda:[],port=-1)
            manager.thread=Mock()
            manager.position=dict(lat=37.6624,lon=-121.8747)
            now=time.time()
            plane=dict(hex='abc123',type='adsb_icao',band='978',lat=37.7,lon=-121.8,seen=0,seen_pos=0,alt_baro=4000)
            payload=dict(now=now,messages=1,aircraft=[plane])
            manager.uat.assigned=UAT
            manager.uat.payload=payload
            with patch.object(manager.uat,'step',return_value=payload):manager._step_uat()
            self.assertEqual(manager.snapshot()['aircraft'][0]['band'],'978')
            self.assertEqual(manager.track_snapshot()['abc123'][-1]['band'],'978')
            self.assertFalse((Path(root)/'flights.jsonl').exists())
            logged=json.loads(manager.flight_log.handlers[0].read_log())
            self.assertEqual(logged['device']['serial'],'978')
            self.assertEqual(logged['aircraft']['band'],'978')
            self.assertEqual(manager.coverage.db.execute('SELECT count(*) FROM positions').fetchone()[0],1)
            manager._refresh_logs()
            self.assertEqual(manager.log_snapshot('flights')['entries'][0]['aircraft']['band'],'978')
            manager.close();manager.coverage.close()
            self.assertEqual(json.loads((Path(root)/'flights.jsonl').read_text())['aircraft']['band'],'978')


if __name__=='__main__':unittest.main()
