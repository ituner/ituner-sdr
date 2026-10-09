import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from log_search import LogSearch
from sstv_monitor import Gallery,GalleryServer
from wspr_history import WSPRHistory


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.h=WSPRHistory(self.root/'wspr.jsonl',start=False);self.h.ready.set()
        self.cw=SimpleNamespace(lock=threading.RLock(),db=sqlite3.connect(':memory:',check_same_thread=False))
        self.cw.db.execute('CREATE TABLE text_log (id TEXT,session_id TEXT,receiver TEXT,server TEXT,band TEXT,rf_hz REAL,wpm REAL,start_utc TEXT,end_utc TEXT,text TEXT)')
        self.server=SimpleNamespace(gallery=Gallery(self.root/'sstv'),wspr_history=self.h,
            cw=SimpleNamespace(gallery=self.cw),hell=SimpleNamespace(gallery=Gallery(self.root/'hell')),qrss=SimpleNamespace(gallery=Gallery(self.root/'qrss')))
        with patch.object(LogSearch,'_run'):
            self.search=LogSearch(self.server)
    def tearDown(self):
        self.search.close();self.cw.db.close();self.h.close();self.tmp.cleanup()
    def spot(self,i,call='S52AB/P'):
        self.h.record(dict(event='wspr_decode',session_server='http://kiwisdr.local:8073',session_receiver='KN6KEZ receiver',band_m='40',cycle_start=1700000000+i*120,frequency_mhz=7.0401,session_frequency_khz=7038.6,callsign=call,grid='JN76',power_dbm=30,snr_db=-20,dt_s=.1,drift_hz=0))
    def capture(self,mode,text):
        g=getattr(self.server,mode).gallery if mode!='sstv' else self.server.gallery
        key=('a' if mode=='hell' else 'b' if mode=='qrss' else 'c')*32
        g.image_path(key).write_bytes(b'image')
        g.items=[dict(id=key,session_id='rx',capture_utc='2026-10-09T12:00:00Z',receiver='KN6KEZ receiver',kind='full',band='30',freq_khz=10140,mode=mode,ocr_text=text,tentative_text=text)]
        return key
    def test_all_history_case_portable_literal_and_csv(self):
        for i in range(240):self.spot(i)
        self.assertEqual(self.search.query(q='s52ab')['total'],240)
        page=self.search.query(q='ab/p',offset=230,limit=30)
        self.assertEqual(len(page['results']),10)
        self.assertEqual(self.search.query(q='KN6KEZ')['total'],0)
        self.assertEqual(self.search.query(q='%')['total'],0)
        self.assertEqual(self.h.query(q='s52ab',offset=230)['total'],240)
        self.assertEqual(len(b''.join(self.h.csv(q='S52AB')).splitlines()),241)
    def test_old_cw_and_cross_mode_pagination(self):
        self.spot(1)
        for i in range(240):self.cw.db.execute('INSERT INTO text_log VALUES (?,?,?,?,?,?,?,?,?,?)',(str(i),'rx','receiver','server','40',7030000,20,'2026-10-09T11:00:00Z','2026-10-09T12:00:00Z','CQ S52AB TEST'))
        self.cw.db.commit()
        self.assertEqual(self.search.query(q='s52ab',mode='cw',offset=220)['total'],240)
        ids=[]
        for offset in range(0,241,30):ids += [r['mode']+r['id'] for r in self.search.query(q='s52ab',offset=offset)['results']]
        self.assertEqual(len(ids),241);self.assertEqual(len(set(ids)),241)
    def test_image_reference_retained_text_and_ocr(self):
        key=self.capture('hell','CQ S52AB');self.capture('qrss','DE S52AB');self.capture('sstv','')
        with patch('log_search.shutil.which',return_value='/bin/tesseract'),patch('log_search.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='CQ S52AB')) as run:
            self.search.sync_images();self.search.sync_images();self.assertEqual(run.call_count,1)
        r=self.search.query(q='S52AB');self.assertEqual(r['total'],3)
        self.assertTrue(all(row.get('image_url') for row in r['results']))
        self.server.hell.gallery.image_path(key).unlink()
        row=self.search.query(q='S52AB',mode='hell')['results'][0]
        self.assertTrue(row['image_missing']);self.assertNotIn('image_url',row)
    def test_touch_search_does_not_swallow_taps(self):
        from log_search_workspace import install_search
        from unittest.mock import Mock
        ui=SimpleNamespace(contains=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3],draw_logical_rect=Mock(),draw_text=Mock())
        workspace=SimpleNamespace(ui=ui,draw=Mock(),tap=Mock(),close=Mock(),swipe=Mock(return_value=False))
        install_search(workspace,'qrss',self.search)
        workspace.draw(None,[]);workspace.tap(50,35,[])
        self.assertTrue(workspace.log_search_view.open)
        self.assertFalse(workspace.swipe(50,35,50,35))
        self.assertTrue(workspace.swipe(50,35,50,135))
        workspace.log_search_view.future.result();workspace.close()

    def test_validation(self):
        for values in (dict(mode='invalid'),dict(q='x'*81),dict(offset=1000001)):
            with self.assertRaises(ValueError):self.search.query(**values)
    def test_http_search_and_assets(self):
        from urllib.request import urlopen
        server=GalleryServer(self.server.gallery,lambda:[],('127.0.0.1',0));server.log_search=self.search
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            for path in ('/search','/log-search.js','/wspr','/hell','/sstv','/qrss','/cw'):
                with urlopen(base+path) as r:self.assertEqual(r.status,200)
            with urlopen(base+'/api/logs/search?q=absent') as r:self.assertEqual(json.load(r)['total'],0)
        finally:server.log_search=None;server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
