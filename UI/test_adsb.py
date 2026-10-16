"""Receiver allocation, stale data, process recovery and HTTP control boundaries."""
import json
import gzip
from pathlib import Path
import tempfile
import shutil
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from adsb_monitor import ADSBManager, aircraft_rows


DEVICE = dict(id='serial:123', index=0, serial='123', label='Test RTL', persistent=True)
OTHER = dict(id='serial:456', index=1, serial='456', label='Other RTL', persistent=True)


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Keep the supervisor deterministic; tests call one step at a time.
        with patch('adsb_monitor.threading.Thread.start'):
            self.manager = ADSBManager(root=self.tmp.name, scanner=lambda:[DEVICE,OTHER], binary=shutil.which('true'), port=-1)
        self.manager.thread = Mock()
        self.manager._step()

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def child(self, returncode=None):
        p=Mock()
        p.poll.return_value=returncode
        p.returncode=returncode
        return p

    def test_assignment_is_persisted_and_rejects_unknown_device(self):
        self.manager.control('assign',OTHER['id'])
        self.manager.control('start')
        data=json.loads((Path(self.tmp.name)/'settings.json').read_text())
        self.assertEqual(data,dict(enabled=True,selection=OTHER['id'],position=None))
        with self.assertRaises(ValueError):self.manager.control('assign','serial:missing')

    def test_auto_skips_busy_dongle_and_uses_next(self):
        self.manager.enabled=True
        with patch('adsb_monitor.subprocess.Popen',return_value=self.child(1)):
            self.manager._step()
        (self.manager.root/'readsb.txt').write_text('usb_claim_interface: device busy')
        with patch('adsb_monitor.subprocess.Popen',return_value=self.child()) as launch:
            self.manager._step()
        self.assertEqual(self.manager.assigned['id'],OTHER['id'])
        self.assertIn('--device=1',launch.call_args.args[0])

    def test_stop_releases_device_and_clears_live_map(self):
        child=self.child()
        self.manager.process=child
        self.manager.assigned=DEVICE
        self.manager.planes=[dict(hex='123456')]
        self.manager._step()
        child.terminate.assert_called_once()
        self.assertEqual(self.manager.snapshot()['aircraft'],[])
        self.assertEqual(json.loads((self.manager.data/'aircraft.json').read_text())['aircraft'],[])

    def test_missing_saved_device_does_not_claim_another(self):
        self.manager.enabled=True
        self.manager.selection='serial:missing'
        with patch('adsb_monitor.subprocess.Popen') as launch:self.manager._step()
        launch.assert_not_called()
        self.assertEqual(self.manager.status,'WAITING FOR DONGLE')

    def test_disconnect_terminates_child_and_clears_aircraft(self):
        child=self.child()
        self.manager.process=child
        self.manager.assigned=DEVICE
        self.manager.enabled=True
        self.manager.selection=DEVICE['id']
        self.manager.scanner=lambda:[]
        self.manager.next_scan=0
        self.manager._step()
        child.terminate.assert_called_once()
        self.assertEqual(self.manager.status,'WAITING FOR USB')

    def test_live_aircraft_written_as_jsonl(self):
        self.manager.enabled=True
        self.manager.process=self.child()
        self.manager.assigned=DEVICE
        self.manager.started=time.monotonic()
        plane=dict(hex='abc123',lat=45,lon=25,seen=1)
        (self.manager.data/'aircraft.json').write_text(json.dumps(dict(now=time.time(),messages=10,aircraft=[plane])))
        self.manager._step()
        self.assertEqual(self.manager.status,'RECEIVING')
        logged=json.loads((self.manager.root/'flights.jsonl').read_text())
        self.assertEqual(logged['aircraft'],plane)
        self.assertEqual(logged['device']['serial'],'123')

    def test_message_activity_and_position_activity_are_distinct(self):
        manager=self.manager;manager.enabled=True;manager.process=self.child();manager.assigned=DEVICE
        manager.started=time.monotonic();base=time.time()
        def receive(offset,messages,planes):
            stamp=base+offset
            (manager.data/'aircraft.json').write_text(json.dumps(dict(now=stamp,messages=messages,aircraft=planes)))
            with patch('adsb_monitor.time.time',return_value=stamp):manager._step();return manager.snapshot()
        plane=dict(hex='abc123',seen=0,alt_baro=1200,gs=120)
        first=receive(0,10,[plane])
        self.assertEqual(first['last_message_at'],base);self.assertIsNone(first['last_position_at'])
        idle=receive(2,10,[])
        self.assertEqual(idle['last_message_at'],base)
        later=receive(3,11,[plane])
        self.assertEqual(later['last_message_at'],base+3);self.assertIsNone(later['last_position_at'])
        located=receive(4,12,[dict(plane,lat=44.4,lon=26.1,seen_pos=0)])
        self.assertEqual(located['last_position_at'],base+4)
        unlocated=receive(5,13,[plane])
        self.assertEqual(unlocated['last_message_at'],base+5)
        self.assertEqual(unlocated['last_position_at'],base+4)
        self.assertEqual(manager.track_snapshot()['abc123'][-1]['time'],base+4)

    def test_stale_json_and_stale_aircraft_are_hidden(self):
        self.assertEqual(aircraft_rows(dict(now=1,aircraft=[dict(seen=0)]),now=100),[])
        rows=aircraft_rows(dict(now=100,aircraft=[dict(hex='a',seen=1),dict(hex='b',seen=19)]),now=101)
        self.assertEqual([r['hex'] for r in rows],['a'])


class HTTPTests(unittest.TestCase):
    def test_token_origin_and_path_boundaries(self):
        with tempfile.TemporaryDirectory() as root:
            map_root=Path(root)/'map'
            (map_root/'db2').mkdir(parents=True)
            (map_root/'db2'/'C.js').write_bytes(gzip.compress(b'{"test":true}'))
            manager=ADSBManager(root=root,scanner=lambda:[],port=0,map_root=map_root)
            try:
                base=f'http://127.0.0.1:{manager.port}'
                response=urlopen(base+'/map/db2/C.js')
                self.assertEqual(response.headers['Content-Encoding'],'gzip')
                self.assertEqual(json.loads(gzip.decompress(response.read())),dict(test=True))
                (manager.data/'receiver.json').write_text('{"binCraft":true,"zstd":true,"history":1}')
                receiver=json.load(urlopen(base+'/map/data/receiver.json'))
                self.assertFalse(receiver['binCraft'])
                self.assertFalse(receiver['zstd'])
                self.assertEqual(receiver['history'],0)
                state=json.load(urlopen(base+'/api/state'))
                for headers in ({},{'X-ADSB-Token':state['control_token'],'Origin':'http://evil.example'}):
                    request=Request(base+'/api/control',data=b'{"action":"start"}',headers=headers)
                    with self.assertRaises(HTTPError) as caught:urlopen(request)
                    self.assertEqual(caught.exception.code,403)
                request=Request(base+'/api/control',data=b'{"action":"stop"}',headers={'X-ADSB-Token':state['control_token']})
                self.assertTrue(json.load(urlopen(request))['ok'])
                with self.assertRaises(HTTPError):urlopen(base+'/map/%2e%2e/settings.json')
            finally:manager.close()


class WorkspaceTests(unittest.TestCase):
    def test_startup_notice_expires_after_five_seconds_without_hiding_history(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock();ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        manager=Mock();manager.track_snapshot.return_value={}
        workspace=ADSBWorkspace(ui,manager)
        state=dict(enabled=True,started_at=100,aircraft=[])
        for stamp,visible in ((100,True),(104.99,True),(105,False),(1000,False)):
            with self.subTest(stamp=stamp):
                ui.draw_text.reset_mock()
                with patch('adsb_workspace.time.time',return_value=stamp):workspace.draw_map(Mock(),state,[])
                labels=[str(call.args[3]) for call in ui.draw_text.call_args_list]
                self.assertEqual('LISTENING FOR AIRCRAFT' in labels,visible)
        # VHF modes supply their own explanatory panels, unaffected by this timer.
        state.update(empty_title='METEOR RECEPTION')
        with patch('adsb_workspace.time.time',return_value=1000):workspace.draw_map(Mock(),state,[])
        self.assertIn('METEOR RECEPTION',[str(call.args[3]) for call in ui.draw_text.call_args_list])

    def test_touchscreen_trails_cycle_through_24_hours_and_off(self):
        from adsb_workspace import ADSBWorkspace
        from adsb_traffic import TRAIL_WINDOWS,trail_label
        ui=Mock();ui.contains.return_value=True
        workspace=ADSBWorkspace(ui,Mock())
        self.assertEqual(workspace.trail_seconds,86400)
        workspace.actions=[((0,0,10,10),('trails',None))]
        values=[]
        for _ in TRAIL_WINDOWS:
            workspace.tap(5,5);values.append(workspace.trail_seconds)
        self.assertEqual(values,list(TRAIL_WINDOWS))
        self.assertEqual(trail_label(86400),'24 H')

    def test_start_stop_are_accessible_on_map_and_every_drawer(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock()
        ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        ui.contains.side_effect=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3]
        manager=Mock();manager.track_snapshot.return_value={}
        manager.log_snapshot.return_value=dict(entries=[],lines=[])
        state=dict(enabled=False,status='STOPPED',aircraft=[],messages=0,detail='',port=8090,devices=[],selection='auto')
        manager.snapshot.side_effect=lambda:dict(state)
        def control(action,value):state.update(enabled=action=='start')
        manager.control.side_effect=control
        workspace=ADSBWorkspace(ui,manager);workspace.show()
        for drawer in (None,'usb_open','logs_open','traffic_open'):
            workspace.usb_open=workspace.logs_open=workspace.traffic_open=False
            if drawer:setattr(workspace,drawer,True)
            for action in ('start','stop'):
                workspace.draw(Mock())
                box=next(box for box,item in workspace.actions if item==(action,None))
                workspace.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
                manager.control.assert_called_with(action,None)
                self.assertEqual(state['enabled'],action=='start')

    def test_aircraft_render_select_and_drag(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock()
        ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.radiogarden_project.return_value=(400,300,1)
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800
        ui.GL.GL_SCISSOR_BIT=1
        ui.GL.GL_ENABLE_BIT=2
        ui.contains.side_effect=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3]
        manager=Mock()
        manager.snapshot.return_value=dict(enabled=True,status='RECEIVING',aircraft=[dict(hex='abc123',lat=45,lon=25,seen_pos=0,flight='TEST123',track=90)],messages=100,detail='Test',port=8090,devices=[],selection='auto')
        workspace=ADSBWorkspace(ui,manager)
        workspace.show()
        workspace.draw(Mock())
        self.assertEqual(len(workspace.points),1)
        workspace.tap(400,300)
        self.assertEqual(workspace.selected,'abc123')
        workspace.drag_begin(400,300)
        ui.radiogarden_pan_angles.return_value=(1,2)
        workspace.drag_move(400,300,460,320)
        self.assertTrue(workspace.swipe())
        self.assertFalse(workspace.dragged)
        self.assertEqual((workspace.yaw,workspace.pitch),(1,2))
        workspace.draw(Mock())
        labels=[str(call.args[3]) for call in ui.draw_text.call_args_list]
        self.assertTrue(any('ICAO ABC123' in label for label in labels))


class LogsAndHistoryTests(unittest.TestCase):
    def test_trails_keep_a_full_day_with_bounded_points_and_recent_detail(self):
        from adsb_traffic import TrafficHistory
        history=TrafficHistory()
        start=100000
        for elapsed in range(0,86401,60):
            history.ingest([dict(hex='abc',lat=45,lon=25+elapsed/864000,seen_pos=0)],start+elapsed)
        points=history.snapshot()['abc']
        self.assertEqual(points[0]['time'],start)
        self.assertEqual(points[-1]['time'],start+86400)
        self.assertGreater(len(points),512)
        self.assertLessEqual(len(points),2048)
        for elapsed in (86404,86408,86412):
            history.ingest([dict(hex='abc',lat=45,lon=26,seen_pos=0)],start+elapsed)
        self.assertEqual([p['time'] for p in history.snapshot()['abc'][-3:]],[start+86404,start+86408,start+86412])
        self.assertTrue(all(p['time']>=start+12 for p in history.snapshot()['abc']))
        history.ingest([],start+2*86400+13)
        self.assertEqual(history.snapshot(),{})

    def test_day_trails_are_bounded_and_reload_after_manager_restart(self):
        from adsb_traffic import TrafficHistory
        now=time.time()
        history=TrafficHistory(limit=3,max_points=4)
        for n in range(6):
            history.ingest([dict(hex=str(n),lat=45,lon=25,seen_pos=0)],now-3600+n)
        self.assertLessEqual(len(history.snapshot()),3)
        self.assertLessEqual(sum(map(len,history.snapshot().values())),4)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'trails.json.gz'
            history.save(path,now)
            with patch('adsb_monitor.threading.Thread.start'):
                manager=ADSBManager(root=root,scanner=lambda:[],port=-1)
            manager.thread=Mock()
            try:
                self.assertEqual(manager.track_snapshot(),history.snapshot())
                manager._save_history(force=True)
                restored=TrafficHistory();restored.load(path,now+86400)
                self.assertEqual(restored.snapshot(),{})
                path.write_bytes(b'broken checkpoint')
                restored.load(path,now)
                self.assertEqual(restored.snapshot(),{})
            finally:manager.close()

    def test_rotated_tail_skips_partial_writes_and_keeps_newest_entries(self):
        from adsb_logs import read_log_tail
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'receiver.jsonl.1').write_text(json.dumps(dict(time=1,event='old'))+'\n')
            (root/'receiver.jsonl').write_text(json.dumps(dict(time=2,event='new'))+'\n{"partial":')
            data=read_log_tail(root,'receiver')
            self.assertEqual([r['event'] for r in data['entries']],['old','new'])
            self.assertIn('UTC',data['lines'][-1])
            with self.assertRaises(ValueError):read_log_tail(root,'../settings')

    def test_trail_history_retains_departed_aircraft_and_expires_old_tracks(self):
        from adsb_traffic import TrafficHistory
        history=TrafficHistory(limit=2,points=3,retention=30)
        for stamp in (100,105,110,115):
            history.ingest([dict(hex='abc',lat=45,lon=25+stamp/1000,seen_pos=0)],stamp)
        self.assertEqual(len(history.snapshot()['abc']),3)
        history.ingest([],120)
        self.assertIn('abc',history.snapshot())
        history.ingest([],146)
        self.assertEqual(history.snapshot(),{})

    def test_invalid_positions_are_not_turned_into_trails(self):
        from adsb_traffic import TrafficHistory, receiver_position
        history=TrafficHistory()
        history.ingest([dict(hex='bad',lat=float('nan'),lon=25),dict(hex='stale',lat=45,lon=25,seen_pos=90)],100)
        self.assertEqual(history.snapshot(),{})
        for value in (dict(lat=91,lon=0),dict(lat=0,lon=float('nan')),'bad'):
            with self.assertRaises(ValueError):receiver_position(value)
        self.assertEqual(receiver_position(dict(lat=0,lon=0)),dict(lat=0,lon=0))

    def test_site_persists_and_future_band_cannot_appear_as_installed(self):
        with tempfile.TemporaryDirectory() as root:
            manager=ADSBManager(root=root,scanner=lambda:[],port=-1)
            try:
                manager.control('location',position=dict(lat=44.4,lon=26.1))
                self.assertEqual(json.loads((Path(root)/'settings.json').read_text())['position'],dict(lat=44.4,lon=26.1))
                bands=manager.snapshot()['bands']
                self.assertEqual([b['id'] for b in bands],['1090','978'])
                self.assertFalse(bands[1]['installed'])
                self.assertEqual(bands[1]['status'],'NOT INSTALLED')
            finally:manager.close()

    def test_visible_log_endpoint_and_download_are_the_same_saved_data(self):
        with tempfile.TemporaryDirectory() as root:
            manager=ADSBManager(root=root,scanner=lambda:[],port=0)
            try:
                manager._event('test',detail='Receiver <ready>')
                manager.next_logs=0;manager._refresh_logs()
                base=f'http://127.0.0.1:{manager.port}'
                data=json.load(urlopen(base+'/api/logs?kind=receiver'))
                self.assertEqual(data['entries'][-1]['event'],'test')
                raw=urlopen(base+'/api/log?kind=receiver').read().decode()
                self.assertIn('Receiver <ready>',raw)
                for asset,mime in (('adsb_globe.js','text/javascript'),('adsb_controls.js','text/javascript'),('adsb_map.css','text/css')):
                    self.assertIn(mime,urlopen(base+'/'+asset).headers['Content-Type'])
                with self.assertRaises(HTTPError):urlopen(base+'/api/log?kind=../settings')
            finally:manager.close()

if __name__=='__main__':unittest.main()
