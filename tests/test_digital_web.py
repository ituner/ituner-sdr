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
from digital_web import ControlError, DigitalWebBridge, wspr_snapshot, set_wspr_running
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

    def apply(self, mode, key, running):
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
                ({'data':{'id':'rx','action':'delete'}},400),({'data':{'id':'missing','action':'stop'}},404),
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

if __name__=='__main__': unittest.main()
