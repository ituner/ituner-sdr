import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'UI'))
from digital_web import ControlError, DigitalWebBridge, wspr_snapshot, set_wspr_running, receiver_options, ReceiverController
from sstv_monitor import Gallery, GalleryServer, SSTVManager


class WebControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = DigitalWebBridge()
        self.rows = [dict(id='rx', name='<script>RX</script>', paused=False, running=True)]
        self.bridge.publish(self.rows, self.rows)
        self.server = GalleryServer(Gallery(self.temp.name), lambda: [], ('127.0.0.1', 0))
        self.server.bridge = self.bridge
        self.base = 'http://127.0.0.1:'+str(self.server.server_port)
        self.stop = threading.Event()
        self.applied = []
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        def owner():
            while not self.stop.wait(.01):
                self.bridge.drain(self.apply)
        self.owner = threading.Thread(target=owner, daemon=True)
        self.owner.start()

    def apply(self, mode, key, action, config):
        running = action == "start"
        if key != 'rx':
            raise KeyError(key)
        self.applied.append((mode, key, running))
        self.rows[0].update(paused=not running, running=running)
        self.bridge.publish(self.rows, self.rows)

    def tearDown(self):
        self.stop.set(); self.owner.join()
        self.bridge.close(); self.server.shutdown(); self.server.server_close(); self.worker.join()
        self.temp.cleanup()

    def post(self, mode='wspr', data=None, token=True, origin=None):
        headers={'Content-Type':'application/json'}
        if token: headers['X-SDR-Control']=self.server.control_token
        if origin: headers['Origin']=origin
        request=Request(self.base+'/api/'+mode+'/control',
            data=json.dumps(data if data is not None else {'id':'rx','action':'stop'}).encode(),headers=headers)
        return json.load(urlopen(request))

    def test_both_pages_controls_and_shared_snapshots(self):
        for mode in ['wspr','sstv']:
            self.assertEqual(urlopen(self.base+'/'+mode).status,200)
            data=json.load(urlopen(self.base+'/api/'+mode))
            self.assertEqual(data['control_token'], self.server.control_token)
            self.assertTrue(self.post(mode)['ok'])
            self.assertFalse(json.load(urlopen(self.base+'/api/'+mode))['decoders'][0]['running'])
            self.assertTrue(self.post(mode,{'id':'rx','action':'start'})['ok'])
        self.assertEqual(len(self.applied),4)

    def test_reject_cross_site_missing_token_invalid_action_and_unknown_receiver(self):
        for kwargs,code in [({'token':False},403),({'origin':'http://foreign.example'},403),
                ({'data':{'id':'rx','action':'reset'}},400),({'data':{'id':'missing','action':'stop'}},404),
                ({'data':[]},400)]:
            with self.assertRaises(HTTPError) as ctx: self.post(**kwargs)
            self.assertEqual(ctx.exception.code,code)
        self.assertEqual(self.applied,[])

    def test_expired_command_cannot_execute_later(self):
        self.stop.set();self.owner.join()
        with self.assertRaises(ControlError) as ctx:
            self.bridge.request('wspr','rx','stop',timeout=.02)
        self.assertEqual(ctx.exception.status,504)
        self.bridge.drain(self.apply)
        self.assertEqual(self.applied,[])


class ReceiverControlTests(unittest.TestCase):
    def test_sstv_stop_start_is_idempotent_and_saved(self):
        with tempfile.TemporaryDirectory() as root:
            manager=SSTVManager(None,'test',root=root,web_port=-1)
            config=dict(id='rx',name='RX',server='test',band='20 m',mode='usb',freq_khz=14230,paused=True)
            manager.configs=[config]
            class FakeSession:
                def __init__(self,*args):
                    self.stop_event=threading.Event();self.thread=None
                def start(self): self.thread=SimpleNamespace(is_alive=lambda:True)
                def stop(self): self.stop_event.set()
                def snapshot(self): return dict(config,status='LISTENING')
            try:
                with patch('sstv_monitor.Session',FakeSession):
                    manager.set_running('rx',True);first=manager.sessions['rx']
                    manager.set_running('rx',True);self.assertIs(first,manager.sessions['rx'])
                    manager.set_running('rx',False);self.assertTrue(first.stop_event.is_set())
                    self.assertFalse(manager.snapshot()[0]['running'])
                    self.assertTrue(json.loads(manager.config_path.read_text())[0]['paused'])
                    manager.set_running('rx',False)
                    manager.set_running('rx',True);self.assertIsNot(first,manager.sessions['rx'])
                    self.assertFalse(json.loads(manager.config_path.read_text())[0]['paused'])
            finally: manager.stop()

    def test_wspr_restart_retry_and_bounded_history(self):
        tile=dict(id='rx',name='RX',band='20',freq_khz=14095.6,paused=True)
        session=Mock();session.snapshot.return_value=dict(status='LIVE',decode_status='CAPTURE',
            decode_audio_seconds=60,decoded_spots=[dict(callsign='YO1ABC')]*100,history=['not for web'])
        manager=SimpleNamespace(sessions={'rx':session},sync=Mock())
        set_wspr_running([tile],manager,'rx',True)
        session.retry_now.assert_called_once()
        set_wspr_running([tile],manager,'rx',True)
        session.retry_now.assert_called_once()
        row=wspr_snapshot([tile],manager)[0]
        self.assertEqual(row['progress_pct'],50);self.assertEqual(len(row['spots']),96)
        self.assertNotIn('history',row)
        set_wspr_running([tile],manager,'rx',False)
        row=wspr_snapshot([tile],manager)[0]
        self.assertEqual(row['decode_status'],'STOPPED');self.assertEqual(len(row['spots']),96)
        self.assertFalse(row['running'])


class ReceiverEditingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.sstv = SSTVManager(None, 'test', root=self.temp.name, web_port=-1)
        self.tiles = []
        self.wspr = SimpleNamespace(sessions={}, start_at={}, sync=Mock())
        self.options = receiver_options([('Local', 'LAN', 'http://kiwi.local'), ('Remote', 'Romania', 'http://remote')],
            [('20', 14095.6), ('40', 7038.6)], [('20 m', 14230, 'usb'), ('40 m EU', 7165, 'lsb')])
        self.controller = ReceiverController(self.sstv, self.tiles, self.wspr, lambda:self.options)
        self.config = dict(server='http://kiwi.local', preset='14230:usb', start=False)

    def tearDown(self):
        self.sstv.stop(); self.temp.cleanup()

    def test_sstv_create_edit_delete_persist_and_preserve_stopped_state(self):
        self.controller.apply('sstv','new','add',self.config)
        self.controller.apply('sstv','new','add',self.config)
        self.assertEqual(len(self.sstv.configs),1)
        self.controller.apply('sstv','new','edit',dict(server='http://remote',preset='7165:lsb'))
        row=json.loads(self.sstv.config_path.read_text())[0]
        self.assertEqual((row['server'],row['mode'],row['freq_khz']),('http://remote','lsb',7165))
        self.assertTrue(row['paused']);self.assertFalse(self.sstv.sessions)
        self.controller.apply('sstv','new','delete',{})
        self.assertEqual(json.loads(self.sstv.config_path.read_text()),[])

    def test_wspr_create_edit_discards_previous_band_session_and_preserves_pause(self):
        self.controller.apply('wspr','w','add',dict(server='http://kiwi.local',preset='20',start=False))
        old=Mock();self.wspr.sessions['w']=old
        self.controller.apply('wspr','w','edit',dict(server='http://remote',preset='40'))
        old.stop.assert_called_once();self.assertNotIn('w',self.wspr.sessions)
        self.assertEqual(self.tiles[0]['freq_khz'],7038.6);self.assertTrue(self.tiles[0]['paused'])
        self.controller.apply('wspr','w','delete',{})
        self.assertEqual(self.tiles,[])

    def test_invalid_source_preset_limit_and_id_collision_do_not_change_settings(self):
        for payload in [dict(server='file:///tmp/x',preset='20'),dict(server='http://kiwi.local',preset='invalid')]:
            with self.assertRaises(ControlError):self.controller.apply('wspr','w','add',payload)
        self.assertEqual(self.tiles,[])
        for i in range(6):self.controller.apply('sstv',str(i),'add',self.config)
        with self.assertRaises(ControlError) as ctx:self.controller.apply('sstv','seventh','add',self.config)
        self.assertEqual(ctx.exception.status,409)
        with self.assertRaises(ControlError):self.controller.apply('sstv','0','add',dict(server='http://remote',preset='7165:lsb'))
        self.assertEqual(len(self.sstv.configs),6)

    def test_local_sstv_editor_uses_same_saved_configuration(self):
        from sstv_workspace import SSTVWorkspace
        self.controller.apply('sstv','new','add',self.config)
        ui=SimpleNamespace(draw_logical_rect=Mock(),draw_text=Mock(),
            fit_station_text=lambda cache,value,*args:str(value),
            station_fields=lambda row:(row[0],row[1],row[2],None,None),
            contains=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3],LOCAL_KIWI_SERVER='http://kiwi.local')
        w=SSTVWorkspace(ui,self.sstv);w.decoders_open=True
        receivers=[('Local','LAN','http://kiwi.local'),('Remote','Romania','http://remote')]
        w.draw(None,receivers)
        box=next(box for box,action in w.actions if action==('edit','new'))
        w.tap((box[0]+box[2])/2,(box[1]+box[3])/2,receivers)
        self.assertTrue(w.add_open);self.assertEqual(w.edit_id,'new')
        w.draw(None,receivers)
        for box,action in w.actions:
            self.assertTrue(0<=box[0]<box[2]<=1280 and 0<=box[1]<box[3]<=800)
        w.selected_server='http://remote';w.preset=('40 m EU',7165,'lsb')
        box=next(box for box,action in w.actions if action[0]=='create')
        w.tap((box[0]+box[2])/2,(box[1]+box[3])/2,receivers)
        self.assertEqual(self.sstv.configs[0]['server'],'http://remote')
        self.assertTrue(self.sstv.configs[0]['paused']);self.assertTrue(w.decoders_open)

    def test_live_sstv_edit_restarts_only_changed_stream(self):
        class Session:
            def __init__(self,config,*args):self.config=dict(config);self.stop=Mock();self.start=Mock()
        with patch('sstv_monitor.Session',Session):
            self.sstv.add('Local','http://kiwi.local',('20 m',14230,'usb'),key='live')
            first=self.sstv.sessions['live']
            self.sstv.update('live','Local','http://kiwi.local',('20 m',14230,'usb'))
            self.assertIs(self.sstv.sessions['live'],first)
            self.sstv.update('live','Remote','http://remote',('40 m EU',7165,'lsb'))
            first.stop.assert_called_once();self.assertIsNot(self.sstv.sessions['live'],first)
            self.sstv.sessions['live'].start.assert_called_once()

if __name__=='__main__': unittest.main()
