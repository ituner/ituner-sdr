"""CW receiver lifecycle, persistent transcripts and a live waterfall."""
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from collections import deque
import numpy as np
from PIL import Image
from sstv_monitor import Session, SSTVManager, atomic_json
from cw_modes import bounds,settings,display_bounds
from cw_decoder import CWDecoder, RATE


def utc(stamp=None):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(time.time() if stamp is None else stamp))


class CWHistory:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.db=sqlite3.connect(self.root/'history.sqlite3',check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS text_log (id TEXT PRIMARY KEY, session_id TEXT, receiver TEXT, server TEXT, band TEXT, rf_hz REAL, wpm REAL, start_utc TEXT, end_utc TEXT, text TEXT)')
        self.db.execute('CREATE INDEX IF NOT EXISTS text_time ON text_log(end_utc DESC)');self.db.commit()
        if 'engine' not in {r[1] for r in self.db.execute('PRAGMA table_info(text_log)')}:
            self.db.execute("ALTER TABLE text_log ADD COLUMN engine TEXT DEFAULT 'ggmorse'");self.db.commit()
        self.streams={}

    def append(self,config,track,text,stamp):
        if not text.strip() and track['id'] not in self.streams:return
        with self.lock:
            key,length=self.streams.get(track['id'],(uuid.uuid4().hex,0))
            if length+len(text)>8192:key,length=uuid.uuid4().hex,0
            if not length:
                self.db.execute('INSERT INTO text_log (id,session_id,receiver,server,band,rf_hz,wpm,start_utc,end_utc,text,engine) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (key,config['id'],config['name'],config['server'],config['band'],track['rf_hz'],track['wpm'],stamp,stamp,text,config.get('engine','ggmorse')))
            else:
                self.db.execute('UPDATE text_log SET text=text||?,end_utc=?,wpm=? WHERE id=?',(text,stamp,track['wpm'],key))
            self.streams[track['id']]=(key,length+len(text));self.db.commit()
            # Only live stream bookkeeping is bounded; history stays on disk.
            if len(self.streams)>128:self.streams.pop(next(iter(self.streams)))

    def rows(self,session_id=None,limit=200):
        with self.lock:
            cur=self.db.execute('SELECT * FROM text_log '+('WHERE session_id=? ' if session_id else '')+'ORDER BY end_utc DESC,rowid DESC LIMIT ?',
                                (session_id,limit) if session_id else (limit,))
            names=[d[0] for d in cur.description]
            return [dict(zip(names,row)) for row in cur]

    def export(self):
        rows=self.rows(limit=10000);out=io.StringIO()
        keys=('start_utc','end_utc','receiver','server','band','rf_hz','wpm','engine','text')
        writer=csv.DictWriter(out,fieldnames=keys,extrasaction='ignore');writer.writeheader()
        for row in reversed(rows):
            # Spreadsheet-safe export; keep raw unmodified text in the database.
            row={k:(' '+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()}
            writer.writerow(row)
        return out.getvalue().encode()

    def close(self):
        with self.lock:
            if self.db is not None:
                self.db.close();self.db=None

    def __del__(self):
        if getattr(self,'db',None) is not None:self.db.close()

    def image_path(self,key):
        if not key or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in key):raise ValueError('Invalid receiver id')
        return self.root/(key+'.png')


class CWAssembler:
    def __init__(self,session,store):
        self.session,self.store=session,store;self.decoder=None;self.reset()

    def reset(self):
        if self.decoder:
            self.publish();self.decoder.close()
        self.decoder=CWDecoder(self.session.config);self.next_publish=0;self.started=time.time()
        with self.session.lock:
            self.session.tracks=[];self.session.image_version=0;self.session.audio_seconds=0
            self.session.capacity_limited=False

    def feed(self,pcm):
        self.decoder.feed(pcm)
        if self.decoder.samples>=self.next_publish:
            self.publish();self.next_publish=self.decoder.samples+RATE

    def publish(self):
        tracks=self.decoder.snapshot()
        for track,text,sample_time in self.decoder.events:
            self.store.append(self.session.config,track,text,utc(self.started+sample_time))
        self.decoder.events.clear()
        # Pixel-only image: labels are drawn at native size in both interfaces.
        if self.decoder.waterfall:
            rows=np.asarray(self.decoder.waterfall)
            values=np.zeros((240,rows.shape[1]),dtype=np.float32);values[-len(rows):]=rows
            rgb=np.stack((values**2*.7,values*.95,values*.8+.035),axis=-1)
            image=Image.fromarray(np.uint8(np.clip(rgb,0,1)*255))
            path=self.store.image_path(self.session.config['id']);tmp=path.with_suffix('.tmp')
            image.save(tmp,format='PNG');tmp.replace(path)
        with self.session.lock:
            self.session.capacity_limited=self.decoder.capacity_limited
            self.session.tracks=tracks
            if self.decoder.waterfall:self.session.image_version+=1
            self.session.audio_seconds=round(self.decoder.samples/RATE,1)
            self.session.last_decode=next((r['text'][-100:].strip() for r in tracks if r['text'].strip()),'')

    def flush(self):
        self.publish();self.decoder.close()


class CWSession(Session):
    receiver_label='CW'
    listening_message='Scanning 1 kHz for Morse signals · automatic speed'
    def __init__(self,*args):
        super().__init__(*args);self.listening_message=f"{self.config.get('engine','ggmorse')} · scanning {(bounds(self.config)[1]-200)/1000:g} kHz · up to 4 signals";self.tracks=[];self.image_version=0;self.audio_seconds=0;self.capacity_limited=False
    def make_assembler(self):return CWAssembler(self,self.queue)
    def bandpass(self):return 150,display_bounds(self.config)[1]+50
    def snapshot(self):
        with self.lock:
            return dict(self.config,display_low_hz=display_bounds(self.config)[0],display_high_hz=display_bounds(self.config)[1],decode_low_hz=bounds(self.config)[0],decode_high_hz=bounds(self.config)[1],status=self.status,detail=self.detail+(" · all 4 fldigi signal slots in use" if self.capacity_limited else ""),last_decode=self.last_decode,
                        tracks=[dict(t,active=t['active'] and not self.stop_event.is_set()) for t in self.tracks],image_version=self.image_version,audio_seconds=self.audio_seconds)


class CWManager(SSTVManager):
    def __init__(self,kiwi,user,root=None):
        self.root=Path(root or os.environ.get('ITUNER_CW_DIR','~/.local/share/ituner-sdr/cw')).expanduser()
        self.gallery=CWHistory(self.root);self.config_path=self.root/'sessions.json'
        self.kiwi,self.user=kiwi,user;self.configs=[];self.sessions={};self.web=None;self.web_port=8073;self.web_error=''
        self.next_start=time.monotonic()+40
        try:
            for config in json.loads(self.config_path.read_text())[:6]:
                self.validate(config);config.update(settings(config,config))
                if not any(r['id']==config['id'] for r in self.configs):self.configs.append(config)
        except (OSError,ValueError,TypeError,KeyError):pass

    @staticmethod
    def validate(config):
        SSTVManager.validate(config)
        if config['mode']!='usb':raise ValueError('CW monitoring uses a USB audio window')
        if not config.get('id') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in config['id']):raise ValueError('Invalid receiver id')
        settings(config,config)

    def ensure_web(self):pass

    def add(self,name,server,preset,key=None,running=True):
        if len(self.configs)>=6:raise ValueError('Six CW receivers maximum')
        config=dict(preset,id=key or uuid.uuid4().hex,name=name,server=server,paused=not running)
        config.update(settings(config,config));self.validate(config)
        if any(r['id']==config['id'] for r in self.configs):raise ValueError('Receiver already exists')
        self.configs.append(config);self.save()
        if running:self.start(config)
        return config['id']

    def start(self,config):
        old=self.sessions.get(config['id'])
        if old:
            old.stop()
            if old.thread:old.thread.join(timeout=3)
            if old.thread and old.thread.is_alive():raise ValueError('Receiver is still stopping; retry shortly')
        session=CWSession(config,self.kiwi,self.gallery,self.user)
        self.sessions[config['id']]=session;session.start()

    def update(self,key,name,server,preset):
        config=next(r for r in self.configs if r['id']==key)
        updated=dict(config,**{k:v for k,v in preset.items() if k not in ('id','paused','name','server')})
        updated.update(name=name,server=server);updated.update(settings(preset,updated));self.validate(updated)
        changed=any(updated[k]!=config.get(k) for k in ('server','freq_khz','tone_hz','cw_mode','wpm','squelch_db','max_tracks','engine'))
        if changed:
            old=self.sessions.get(key)
            if old:
                old.stop()
                if old.thread:old.thread.join(timeout=3)
                if old.thread and old.thread.is_alive():raise ValueError('Receiver is still stopping; retry shortly')
                self.sessions.pop(key,None)
        config.update(updated);self.save()
        if changed and not config.get('paused'):self.start(config)

    def history(self,session_id=None):return self.gallery.rows(session_id)

    def stop(self):
        for session in self.sessions.values():session.stop()
        for session in self.sessions.values():
            if session.thread:session.thread.join(timeout=3)
        if not any(s.thread and s.thread.is_alive() for s in self.sessions.values()):self.gallery.close()
