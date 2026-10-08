import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from wspr_history import WSPRHistory, upload_fields, source_key


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'wspr.jsonl'
        self.posted=[]
        self.h=WSPRHistory(self.path,start=False,post=lambda fields:self.posted.append(fields) or '1 spot(s) added')
        self.h.ready.set()
        self.config=dict(server='http://kiwisdr.local:8073',name='Local',band='40')
        self.h.register(self.config)

    def tearDown(self):
        self.h.close();self.temp.cleanup()

    def spot(self,**extra):
        return dict(dict(event='wspr_decode',session_server=self.config['server'],session_receiver='Local',
            band_m='40',cycle_start=time.time(),frequency_mhz=7.0401,session_frequency_khz=7038.6,
            callsign='K1ABC',grid='FN42',power_dbm=30,snr_db=-20,dt_s=.1,drift_hz=0,wspr_tile_id='old-card'),**extra)

    def test_stable_receiver_band_dedup_and_restart(self):
        s=self.spot();self.h.record(s);self.h.record(dict(s,wspr_tile_id='new-card'))
        self.assertEqual(len(self.h.recent(dict(self.config,id='new-card'))),1)
        self.assertEqual(self.h.query(band='20')['total'],0)
        self.h.close();self.h=WSPRHistory(self.path,start=False)
        self.assertEqual(self.h.query()['total'],1)

    def test_import_active_and_archived_logs_never_uploads(self):
        self.h.configure(self.config['server'],'KN6KEZ','KN34al',True,True)
        self.path.write_text(json.dumps(self.spot())+'\nmalformed\n')
        self.path.with_name('wspr.old.jsonl').write_text(json.dumps(self.spot(cycle_start=time.time()-7200))+'\n')
        self.h.import_logs();self.h.import_logs()
        self.assertEqual(self.h.query()['total'],2)
        self.assertFalse(self.h.upload_once());self.assertEqual(self.posted,[])

    def test_session_filters_are_separate_from_all_history(self):
        r1=self.h.begin_run(self.config);self.h.record(self.spot(run_id=r1))
        r2=self.h.begin_run(self.config);self.h.record(self.spot(run_id=r2))
        self.assertEqual(self.h.query(scope='session',source=self.config['server'],band='40')['total'],1)
        self.assertEqual(self.h.query(scope='all')['total'],2)
        self.assertEqual(self.h.query(scope='session',run=r1)['spots'][0]['run_id'],r1)

    def test_pagination_and_csv_keep_more_than_96(self):
        for i in range(121):self.h.record(self.spot(cycle_start=1700000000+i*120))
        self.assertEqual(self.h.query()['total'],121)
        self.assertEqual(len(self.h.query(offset=100)['spots']),21)
        export=b''.join(self.h.csv()).decode()
        self.assertEqual(len(export.splitlines()),122)

    def test_upload_opt_in_ack_and_dedup(self):
        s=self.spot();self.h.record(s,live=True);self.assertFalse(self.h.upload_once())
        self.h.configure(self.config['server'],'KN6KEZ','KN34al',True,True)
        s=self.spot();self.h.record(s,live=True);self.h.record(s,live=True)
        self.assertTrue(self.h.upload_once());self.assertFalse(self.h.upload_once())
        self.assertEqual(len(self.posted),1);self.assertEqual(self.posted[0]['rcall'],'KN6KEZ');self.assertEqual(self.posted[0]['rgrid'],'KN34AL')
        self.assertEqual(self.h.sources()[0]['uploads'],{'sent':1})

    def test_remote_identity_is_never_inherited(self):
        self.h.configure(self.config['server'],'KN6KEZ','KN34al',True,True)
        self.h.record(self.spot(session_server='https://remote.example:8073'),live=True)
        self.assertFalse(self.h.upload_once())
        with self.assertRaisesRegex(ValueError,'Confirm'):
            self.h.configure('https://remote.example:8073','KN6KEZ','KN34al',True,False)

    def test_disable_cancels_queue_and_identity_changes_do_not_relabel(self):
        self.h.configure(self.config['server'],'KN6KEZ','KN34al',True,True)
        self.h.record(self.spot(),live=True)
        self.h.configure(self.config['server'],'KN6KEZ','KN34al',False,True)
        self.assertFalse(self.h.upload_once());self.assertEqual(self.h.sources()[0]['uploads'],{'cancelled':1})

    def test_unknown_reply_and_timeout_are_not_success(self):
        self.h.configure(self.config['server'],'KN6KEZ','KN34al',True,True)
        self.h.record(self.spot(),live=True);self.h.post=lambda p:'maintenance'
        self.h.upload_once();self.assertEqual(self.h.sources()[0]['uploads'],{'rejected':1})
        self.h.record(self.spot(),live=True)
        def timeout(p):raise TimeoutError('timeout')
        self.h.post=timeout;self.h.upload_once();self.assertFalse(self.h.upload_once())
        self.assertEqual(self.h.sources()[0]['uploads'],{'rejected':1,'uncertain':1})

    def test_wire_fields_use_capture_time_not_upload_time(self):
        fields=upload_fields(self.spot(cycle_start=1704067080),'KN6KEZ','KN34al')
        self.assertEqual((fields['date'],fields['time']),('231231','2358'))
        self.assertEqual(fields['tqrg'],'7.040100');self.assertEqual(fields['rqrg'],'7.038600')
        with self.assertRaises(ValueError):upload_fields(self.spot(frequency_mhz=float('nan')),'KN6KEZ','KN34al')

    def test_source_normalization_keeps_distinct_ports_and_paths(self):
        self.assertEqual(source_key('http://KIWISDR.local:8073/'),'http://kiwisdr.local:8073')
        self.assertNotEqual(source_key('http://host:8073'),source_key('http://host:8074'))

class IntegrationTests(unittest.TestCase):
    def test_monitor_archive_is_separate_from_waterfall_history(self):
        import kiwi_gl_display as ui
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as td:
            archive=WSPRHistory(Path(td)/'wspr.jsonl',start=False)
            session=ui.WSPRMonitorSession(dict(id='tile',server='http://kiwisdr.local:8073',band='40',freq_khz=7038.6), 'Test', history=archive)
            with patch.object(ui.threading.Thread,'start'), patch.object(ui.WSPRDecodeWorker,'start'):
                session.start(); run=session.run_id
                self.assertTrue(run);self.assertIs(session.archive,archive)
                session.history.append((1,-20));self.assertEqual(len(session.snapshot()['history']),1)
                session._publish_decodes([dict(callsign='K1ABC',grid='FN42')],time.time())
                session.stop();session.start()
                self.assertNotEqual(session.run_id,run)
                self.assertEqual(len(session.snapshot()['decoded_spots']),1)
            archive.close()

class HTTPTests(HistoryTests):
    # Exercise the actual handler with an isolated archive and no upload worker.
    def setUp(self):
        super().setUp()
        import threading
        from sstv_monitor import Gallery, GalleryServer
        from digital_web import DigitalWebBridge
        self.server=GalleryServer(Gallery(self.temp.name),lambda:[],('127.0.0.1',0))
        self.server.wspr_history=self.h;self.server.bridge=DigitalWebBridge()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.server.bridge.close()
        super().tearDown()

    def test_http_archive_and_csv(self):
        from urllib.request import urlopen
        self.h.record(self.spot());self.h.record(self.spot(band_m='20'))
        data=json.load(urlopen(self.base+'/api/wspr/history?band=40'))
        self.assertEqual(data['total'],1)
        response=urlopen(self.base+'/api/wspr/history.csv?band=40')
        self.assertIn('attachment',response.headers['Content-Disposition'])
        self.assertEqual(len(response.read().decode().splitlines()),2)
        self.assertIn(b'class WSPRHistoryUI',urlopen(self.base+'/wspr-history.js').read())

    def test_http_reporting_guards_and_persistence(self):
        from urllib.request import urlopen,Request
        from urllib.error import HTTPError
        payload=dict(source=self.config['server'],call='KN6KEZ',grid='KN34al',enabled=True,confirmed=True)
        headers={'Content-Type':'application/json'}
        def post():return json.load(urlopen(Request(self.base+'/api/wspr/reporting',data=json.dumps(payload).encode(),headers=headers)))
        with self.assertRaises(HTTPError) as c:post()
        self.assertEqual(c.exception.code,403)
        headers['X-SDR-Control']=self.server.control_token
        headers['Origin']='http://foreign.example'
        with self.assertRaises(HTTPError) as c:post()
        self.assertEqual(c.exception.code,403)
        del headers['Origin'];payload['confirmed']=False
        with self.assertRaises(HTTPError) as c:post()
        self.assertEqual(c.exception.code,400)
        payload['confirmed']=True;self.assertTrue(post()['ok'])
        profile=json.load(urlopen(self.base+'/api/wspr/reporting'))['sources'][0]
        self.assertEqual((profile['call'],profile['grid'],profile['enabled']),('KN6KEZ','KN34AL',1))
        self.assertEqual(self.posted,[])

class ViewTests(unittest.TestCase):
    def test_local_history_controls_filter_and_require_confirmation(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from wspr_history_view import WSPRHistoryView
        with tempfile.TemporaryDirectory() as td:
            h=WSPRHistory(Path(td)/'wspr.jsonl',start=False);h.ready.set()
            config=dict(server='http://kiwisdr.local:8073',name='Local',band='40');h.register(config)
            ui=SimpleNamespace(draw_logical_rect=Mock(),draw_text=Mock(),fit_station_text=lambda c,v,*a:str(v))
            v=WSPRHistoryView(ui,h);v.select(config,SimpleNamespace(run_id='run'));v.sources=h.sources()
            def press(action):
                v.draw(None)
                for box,a in v.actions:
                    self.assertTrue(0<=box[0]<box[2]<=1280 and 0<=box[1]<box[3]<=800)
                box=next(box for box,a in v.actions if a==action);v.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
            try:
                press(('scope','all'));self.assertEqual(v.scope,'all')
                press(('settings',));v.settings.update(call='KN6KEZ',grid='KN34AL',enabled=True)
                press(('save',));self.assertIn('Confirm',v.message)
                press(('confirm',));press(('save',));self.assertIsNone(v.settings)
                self.assertTrue(h.sources()[0]['enabled'])
            finally:v.close();h.close()

if __name__=='__main__':unittest.main()
