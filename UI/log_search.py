"""Read-only cross-decoder history search, with a background image text cache."""
import datetime
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import os
import threading
import time

MODES = ('wspr', 'sstv', 'hell', 'qrss', 'cw')


def utc(stamp):
    return datetime.datetime.fromtimestamp(float(stamp), datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class LogSearch:
    def __init__(self, server):
        self.server = server
        self.lock = threading.RLock()
        self.db = sqlite3.connect(server.gallery.root.parent / 'image-search.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS images (mode TEXT, id TEXT, stamp TEXT, text TEXT, data TEXT, fingerprint TEXT, PRIMARY KEY(mode,id))')
        self.db.commit()
        self.stop_event = threading.Event()
        self.status = 'Reading saved image logs…'
        self.worker = threading.Thread(target=self._run, daemon=True, name='log-search')
        self.worker.start()

    def galleries(self):
        return {**{m: obj.gallery for m in ('hell','qrss') if (obj := getattr(self.server,m,None)) is not None}, 'sstv': self.server.gallery}

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.sync_images()
                self.status = '' if shutil.which('tesseract') else 'SSTV image text needs Tesseract; other decoded text is searchable.'
            except Exception:
                self.status = 'Some image logs could not be read; search will retry.'
            self.stop_event.wait(10)

    def sync_images(self):
        for mode, gallery in self.galleries().items():
            for item in gallery.snapshot():
                if self.stop_event.is_set(): return
                key = item['id']
                path = gallery.image_path(key)
                try: fingerprint = str(path.stat().st_mtime_ns) + json.dumps(item, sort_keys=True)
                except OSError: continue
                with self.lock:
                    old = self.db.execute('SELECT fingerprint FROM images WHERE mode=? AND id=?',(mode,key)).fetchone()
                if old and old[0] == fingerprint: continue
                text = item.get('tentative_text') or item.get('ocr_text') or item.get('callsign') or ''
                source = 'Tentative decoded text' if mode == 'qrss' else 'OCR · unverified'
                if mode == 'sstv':
                    source = 'OCR · unverified'
                    # Include abandoned partials once settled; do not OCR every live frame.
                    if item.get('kind') not in ('full', 'saved') and time.time()-path.stat().st_mtime<30: continue
                    executable = shutil.which('tesseract')
                    if executable:
                        try:
                            result = subprocess.run([executable,str(path),'stdout','-l','eng','--psm','11'],
                                capture_output=True,text=True,timeout=10,env=dict(os.environ,OMP_THREAD_LIMIT='1'))
                            if result.returncode: continue
                            text = result.stdout[:16000]
                        except (OSError,subprocess.TimeoutExpired): continue
                row = dict(mode=mode,id=key,utc=item.get('capture_utc',''),receiver=item.get('receiver',''),
                    band=item.get('band',''),frequency_hz=float(item.get('rf_hz') or float(item.get('freq_khz',0))*1000),
                    text=text,source=source,image_id=key,detail=item.get('mode',''))
                with self.lock, self.db:
                    self.db.execute('INSERT OR REPLACE INTO images VALUES (?,?,?,?,?,?)',
                        (mode,key,row['utc'],text,json.dumps(row),fingerprint))

    def query(self, q='', mode='all', offset=0, limit=30):
        q = str(q).strip().upper()
        if len(q)>80: raise ValueError('Search is limited to 80 characters')
        if mode not in ('all',*MODES): raise ValueError('Unknown decoder type')
        offset=max(0,int(offset));limit=min(100,max(1,int(limit)))
        if offset>1000000: raise ValueError('Page is too far into history')
        take=offset+limit;rows=[];total=0;warnings=[]
        modes=MODES if mode=='all' else (mode,)
        history=getattr(self.server,'wspr_history',None)
        if 'wspr' in modes and history:
            with history.lock:
                clause=" WHERE instr(upper(coalesce(json_extract(data,'$.callsign'),'')),?)>0"
                total+=history.db.execute('SELECT count(*) FROM spots'+clause,(q,)).fetchone()[0]
                for r in history.db.execute('SELECT * FROM spots'+clause+' ORDER BY cycle DESC,id DESC LIMIT ?',(q,take)):
                    d=json.loads(r['data']);rows.append(dict(mode='wspr',id=r['id'],utc=utc(r['cycle']),
                        receiver=d.get('session_receiver') or r['source'],band=r['band'],frequency_hz=float(d.get('frequency_mhz',0))*1e6,
                        text='{}  {}  SNR {} dB  {} dBm'.format(d.get('callsign',''),d.get('grid',''),d.get('snr_db',''),d.get('power_dbm','')),
                        source='Decoded spot'))
            if not history.ready.is_set(): warnings.append('WSPR history import is still running.')
        cw=getattr(self.server,'cw',None)
        if 'cw' in modes and cw:
            with cw.gallery.lock:
                clause=' WHERE instr(upper(text),?)>0'
                total+=cw.gallery.db.execute('SELECT count(*) FROM text_log'+clause,(q,)).fetchone()[0]
                cur=cw.gallery.db.execute('SELECT * FROM text_log'+clause+' ORDER BY end_utc DESC,id DESC LIMIT ?',(q,take))
                names=[d[0] for d in cur.description]
                for values in cur:
                    r=dict(zip(names,values));rows.append(dict(mode='cw',id=r['id'],utc=r['end_utc'],start_utc=r['start_utc'],
                        receiver=r['receiver'],band=r['band'],frequency_hz=r['rf_hz'],text=r['text'],source='Tentative decoded text'))
        hell=getattr(self.server,'hell',None)
        if 'hell' in modes and hell and getattr(hell,'reporter',None):
            with hell.reporter.lock:
                reports=[dict(r) for r in hell.reporter.rows if q in r.get('call','').upper()]
            total+=len(reports)
            for r in reports:
                rows.append(dict(mode='hell',id='report-'+r['id'],utc=utc(r['received_at']),
                    receiver=r['server'],band='',frequency_hz=r['rf_hz'],text=r['call'],
                    source='Human-confirmed reception report',image_id=r['image'],detail=r['mode']))
        image_modes=[m for m in modes if m in ('sstv','hell','qrss')]
        if image_modes:
            clause=' WHERE mode IN ('+','.join('?' for _ in image_modes)+') AND instr(upper(text),?)>0'
            args=[*image_modes,q]
            with self.lock:
                total+=self.db.execute('SELECT count(*) FROM images'+clause,args).fetchone()[0]
                rows.extend(json.loads(r[0]) for r in self.db.execute('SELECT data FROM images'+clause+' ORDER BY stamp DESC,mode DESC,id DESC LIMIT ?',[*args,take]))
        rows.sort(key=lambda r:(r['utc'],r['mode'],r['id']),reverse=True)
        rows=rows[offset:offset+limit]
        galleries=self.galleries()
        for r in rows:
            if r.get('image_id'):
                gallery=galleries.get(r['mode'])
                if gallery and gallery.image_path(r['image_id']).is_file():
                    r['image_url']=('/images/' if r['mode']=='sstv' else '/'+r['mode']+'-images/')+r['image_id']+'.png'
                else: r['image_missing']=True
        if self.status: warnings.append(self.status)
        return dict(results=rows,total=total,offset=offset,limit=limit,notice=' '.join(warnings))

    def close(self):
        self.stop_event.set()
        self.worker.join(12)
        if not self.worker.is_alive():
            with self.lock: self.db.close()
