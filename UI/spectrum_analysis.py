"""Survey discoveries, sampled activity, watch events and time-based retention."""
import base64
from collections import OrderedDict
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
import zlib

import numpy as np
from spectrum_history import signature, encode

THRESHOLD = 6.0
DAY = 86400


def measured(data):
    power=np.asarray([float(v) if isinstance(v,(int,float)) and math.isfinite(v) else np.nan for v in data.get('power',[])])
    masked=np.asarray(data.get('masked',[False]*len(power)),dtype=bool)
    if len(masked)!=len(power):masked=np.zeros(len(power),dtype=bool)
    if data.get('settings'):
        config=data['settings']
        for row in data.get('quality',[]):
            if row.get('clip_fraction',0)<=.001:continue
            low=max(0,int((row['frequency']-768000-config['low'])/config['bin']))
            high=min(len(power),math.ceil((row['frequency']+768000-config['low'])/config['bin']))
            masked[low:high]=True
    power[masked]=np.nan
    return power,masked


def detect(data, threshold=THRESHOLD):
    """Local 20th-percentile floor; widths are threshold estimates, not channel IDs."""
    power,masked=measured(data);n=len(power)
    if not n:return dict(power=power,floor=power,active=np.zeros(0,bool),valid=np.zeros(0,bool),signals=[])
    valid=np.isfinite(power);window=min(65,n if n%2 else n-1)
    if window<3:floor=np.full(n,np.nanpercentile(power,20) if valid.any() else np.nan)
    else:
        windows=np.lib.stride_tricks.sliding_window_view(np.pad(power,window//2,constant_values=np.nan),window)
        # Empty tuning gaps stay unavailable; a finite sentinel avoids all-NaN warnings.
        filled=np.where(np.isfinite(windows),windows,np.inf);ordered=np.sort(filled,axis=1)
        count=np.isfinite(windows).sum(axis=1);index=np.maximum(0,np.floor(np.maximum(0,count-1)*.2).astype(int))
        floor=ordered[np.arange(n),index];floor[count==0]=np.nan
    excess=power-floor;active=valid&(excess>=threshold)
    # Join a single quiet bin only when it really was measured, never across clipping/DC holes.
    joined=active.copy()
    if n>2:joined[1:-1]|=active[:-2]&active[2:]&valid[1:-1]
    edges=np.diff(np.r_[False,joined,False].astype(int));starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
    config=data['settings'];signals=[]
    times=data.get('sample_time',[])
    for first,last in zip(starts,ends):
        peak=first+int(np.nanargmax(power[first:last]));low=config['low']+int(first)*config['bin'];high=min(config['high'],config['low']+int(last)*config['bin'])
        signals.append(dict(frequency=config['low']+(int(peak)+.5)*config['bin'],low=low,high=high,width=high-low,
                            level=round(float(power[peak]),2),floor=round(float(floor[peak]),2),excess=round(float(excess[peak]),2),
                            time=times[peak] if len(times)>peak and times[peak] else data.get('finished',data.get('updated',time.time()))))
    return dict(power=power,floor=floor,active=active,valid=valid,signals=signals)


def packed(array):return zlib.compress(np.asarray(array,dtype='<f8').tobytes())
def unpacked(blob):return np.frombuffer(zlib.decompress(blob),dtype='<f8').copy()

def reduce_values(values,config,low,high,columns,method='max'):
    values=np.asarray(values,dtype=float);n=len(values)
    if not n:return [None]*columns
    x=np.arange(columns,dtype=float)
    first=np.clip(((low+(high-low)*x/columns-config['low'])/config['bin']).astype(int),0,n-1)
    end=np.minimum(n,np.maximum(first+1,np.ceil((low+(high-low)*(x+1)/columns-config['low'])/config['bin']).astype(int)))
    indices=first[:,None]+np.arange(int(np.max(end-first)))
    cells=values[np.minimum(indices,n-1)];valid=(indices<end[:,None])&np.isfinite(cells)
    count=valid.sum(axis=1)
    if method=='mean':result=np.divide(np.where(valid,cells,0).sum(axis=1),count,out=np.full(columns,np.nan),where=count>0)
    else:result=np.max(np.where(valid,cells,-np.inf),axis=1)
    return [float(v) if count[i] else None for i,v in enumerate(result)]


class SpectrumInsights:
    def __init__(self,root):
        self.root=Path(root);self.path=self.root/'insights.sqlite3';self.lock=threading.RLock();self.pending={};self.last_flush=0;self.revision=0;self.cache={}
        self.watch_path=self.root/'watchlist.json'
        try:self.watch=json.loads(self.watch_path.read_text())
        except (ValueError,OSError):self.watch=[]
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS minutes (signature TEXT, minute INTEGER, config TEXT, first REAL, last REAL, visits INTEGER, peak BLOB, total BLOB, seen BLOB, hits BLOB, PRIMARY KEY(signature,minute))')
            db.execute('CREATE TABLE IF NOT EXISTS discoveries (id INTEGER PRIMARY KEY, signature TEXT, frequency REAL, low REAL, high REAL, level REAL, floor REAL, excess REAL, first REAL, last REAL, detections INTEGER)')
            db.execute('CREATE INDEX IF NOT EXISTS discoveries_scope ON discoveries(signature,last)')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time REAL, watch_id TEXT, label TEXT, frequency REAL, kind TEXT, detail TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS imported (identity TEXT PRIMARY KEY, time REAL)')
        self.watch_state={};self.prune()

    @contextmanager
    def db(self):
        db=sqlite3.connect(str(self.path),timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def prune(self):
        with self.lock,self.db() as db:
            since=time.time()-DAY
            deleted=0
            for table,field in (('minutes','last'),('discoveries','last'),('events','time'),('imported','time')):deleted+=db.execute(f'DELETE FROM {table} WHERE {field}<?',(since,)).rowcount
            db.execute('DELETE FROM minutes WHERE rowid NOT IN (SELECT rowid FROM minutes ORDER BY last DESC LIMIT 2880)')
            db.execute('DELETE FROM discoveries WHERE id NOT IN (SELECT id FROM discoveries ORDER BY last DESC LIMIT 2048)')
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')
            if deleted:self.revision+=1;self.cache.clear()

    def observe(self,data,imported=False):
        if not data.get('complete') or not data.get('power'):return
        key=signature(data);identity=str(data.get('started'))+':'+str(data.get('sweep'));finished=data['finished']
        if finished<time.time()-DAY:return
        result=detect(data);power=result['power'];valid=result['valid'];n=len(power)
        minute=int(finished//60);slot=(key,minute)
        with self.lock:
            with self.db() as db:
                if db.execute('SELECT 1 FROM imported WHERE identity=?',(identity,)).fetchone():return
                db.execute('INSERT INTO imported VALUES (?,?)',(identity,finished))
                if slot not in self.pending:
                    saved=db.execute('SELECT first,last,visits,peak,total,seen,hits FROM minutes WHERE signature=? AND minute=?',slot).fetchone()
                    self.pending[slot]=dict(config=dict(data['settings']),first=saved[0] if saved else data.get('sweep_started',data['started']),last=finished,
                        visits=saved[2] if saved else 0,peak=unpacked(saved[3]) if saved else np.full(n,np.nan),total=unpacked(saved[4]) if saved else np.zeros(n),
                        seen=unpacked(saved[5]) if saved else np.zeros(n),hits=unpacked(saved[6]) if saved else np.zeros(n))
                bucket=self.pending[slot];bucket['last']=finished;bucket['visits']+=1
                bucket['peak']=np.fmax(bucket['peak'],power);bucket['total']+=np.where(valid,10**(np.nan_to_num(power,nan=-200)/10),0)
                bucket['seen']+=valid;bucket['hits']+=result['active']
                for signal in result['signals'][:128]:
                    old=db.execute('SELECT id,low,high,level,excess FROM discoveries WHERE signature=? AND high>=? AND low<=? ORDER BY ABS(frequency-?) LIMIT 1',
                                   (key,signal['low'],signal['high'],signal['frequency'])).fetchone()
                    if old:
                        db.execute('UPDATE discoveries SET frequency=?,low=?,high=?,level=MAX(level,?),floor=?,excess=MAX(excess,?),last=?,detections=detections+1 WHERE id=?',
                                   (signal['frequency'],min(old[1],signal['low']),max(old[2],signal['high']),signal['level'],signal['floor'],signal['excess'],signal['time'],old[0]))
                    else:db.execute('INSERT INTO discoveries(signature,frequency,low,high,level,floor,excess,first,last,detections) VALUES (?,?,?,?,?,?,?,?,?,1)',
                                    (key,signal['frequency'],signal['low'],signal['high'],signal['level'],signal['floor'],signal['excess'],signal['time'],signal['time']))
            if not imported and data['settings'].get('purpose')!='watch':self.observe_watches(data,result)
            self.revision+=1
            if time.monotonic()-self.last_flush>=5 or any(k!=slot for k in self.pending):self.flush()

    def flush(self):
        with self.lock,self.db() as db:
            for (key,minute),b in self.pending.items():
                db.execute('INSERT OR REPLACE INTO minutes VALUES (?,?,?,?,?,?,?,?,?,?)',(key,minute,json.dumps(b['config']),b['first'],b['last'],b['visits'],packed(b['peak']),packed(b['total']),packed(b['seen']),packed(b['hits'])))
            self.pending.clear();self.last_flush=time.monotonic()
        self.prune()

    def seed(self,history,data):
        """Import genuine retained rows once; never synthesize old sweeps from averages."""
        if not data.get('settings'):return
        key=signature(data)
        with history.lock,history.connect() as db:
            rows=db.execute('SELECT identity,started,finished,pass,power FROM sweeps WHERE signature=? ORDER BY id',(key,)).fetchall()
        for identity,started,finished,sweep,blob in rows:
            codes=zlib.decompress(blob);power=[c-202 if c>1 else None for c in codes]
            item=dict(data,started=float(identity.rsplit(':',1)[0]),sweep_started=started,finished=finished,sweep=sweep,complete=True,power=power,masked=[c==1 for c in codes],quality=[],sample_time=[])
            self.observe(item,imported=True)
        self.flush()

    def add_watch(self,frequency,label='',bandwidth=25000):
        frequency=float(frequency);bandwidth=float(bandwidth)
        if not math.isfinite(frequency) or not 25e6<=frequency<=1700e6:raise ValueError('Watch frequency must be 25–1700 MHz')
        if not math.isfinite(bandwidth) or not 2500<=bandwidth<=1e6:raise ValueError('Watch width must be 2.5–1000 kHz')
        with self.lock:
            if len(self.watch)>=64:raise ValueError('Watchlist limit: 64 frequencies')
            if any(abs(w['frequency']-frequency)<1 for w in self.watch):raise ValueError('This frequency is already on your watchlist')
            self.watch.append(dict(id=str(time.time_ns()),frequency=frequency,bandwidth=bandwidth,label=str(label).strip()[:60] or f'{frequency/1e6:.6f} MHz'))
            self.watch_path.write_text(json.dumps(self.watch));return self.watch[-1]['id']

    def remove_watch(self,identity):
        with self.lock:
            self.watch=[w for w in self.watch if w['id']!=str(identity)];self.watch_state.pop(str(identity),None)
            self.watch_path.write_text(json.dumps(self.watch))

    def observe_watches(self,data,result):
        config=data['settings']
        for watch in self.watch:
            half=max(config['bin']/2,watch['bandwidth']/2);low=watch['frequency']-half;high=watch['frequency']+half
            if low<config['low'] or high>config['high']:continue
            first=max(0,int((low-config['low'])/config['bin']));last=min(len(result['power']),max(first+1,math.ceil((high-config['low'])/config['bin'])))
            valid=result['valid'][first:last]
            if not valid.any():continue
            indices=np.flatnonzero(valid)+first;peak=int(indices[np.argmax(result['power'][indices])])
            self.watch_measure(watch,dict(level=float(result['power'][peak]),excess=float(result['power'][peak]-result['floor'][peak]),time=(data.get('sample_time',[])[peak] if peak<len(data.get('sample_time',[])) else None) or data['finished'],resolution=config['bin'],method='survey bin peak'),signature(data))

    def watch_measure(self,watch,measurement,key):
        if measurement.get('clipped') or not all(math.isfinite(measurement.get(k,float('nan'))) for k in ('level','excess','time')):return
        with self.lock:
            old=self.watch_state.get(watch['id']);present=measurement['excess']>=THRESHOLD
            state=dict(measurement,present=present,signature=key,visits=(old or {}).get('visits',0)+1,quiet=0 if present else (old or {}).get('quiet',0)+1)
            kind=None
            if old and old['signature']==key:
                if present and not old['present']:kind='appeared'
                elif not present and old['present']:
                    if state['quiet']<2:state['present']=True
                    else:kind='disappeared'
                elif present and abs(measurement['level']-old.get('reference',old['level']))>=6:kind='level changed'
            elif present:kind='detected'
            state['reference']=measurement['level'] if kind or not old else old.get('reference',old['level'])
            self.watch_state[watch['id']]=state
            if kind:
                with self.db() as db:db.execute('INSERT INTO events(time,watch_id,label,frequency,kind,detail) VALUES (?,?,?,?,?,?)',
                    (measurement['time'],watch['id'],watch['label'],watch['frequency'],kind,f"{measurement['level']:.1f} dBFS/Hz · {measurement['excess']:.1f} dB above estimated floor"))

    def watches(self):
        with self.lock:
            return [dict(w,measurement=self.watch_state.get(w['id']),stale=not self.watch_state.get(w['id']) or time.time()-self.watch_state[w['id']]['time']>300) for w in self.watch]

    def events(self):
        with self.lock,self.db() as db:
            return [dict(id=r[0],time=r[1],label=r[2],frequency=r[3],kind=r[4],detail=r[5]) for r in db.execute('SELECT id,time,label,frequency,kind,detail FROM events ORDER BY id DESC LIMIT 100')]

    def snapshot(self,data,low=None,high=None,columns=512,history=None,detail='full'):
        if detail not in ('full','signals','timeline','persistence'):raise ValueError('Unknown analysis detail')
        config=data.get('settings')
        if not config:return dict(signals=[],watchlist=self.watches(),events=self.events(),visits=0,timeline=[],activity=[],persistence=[],threshold=THRESHOLD)
        low=float(low) if low is not None else config['low'];high=float(high) if high is not None else config['high'];columns=max(1,min(1024,int(columns)))
        if not all(math.isfinite(v) for v in (low,high)):raise ValueError('Invalid analysis viewport')
        low=max(config['low'],low);high=min(config['high'],high)
        if high<=low:raise ValueError('Invalid analysis viewport')
        key=signature(data);cache_key=(key,low,high,columns,detail)
        with self.lock:
            cache=self.cache.get(cache_key)
            if cache and time.monotonic()-cache[1]<(60 if cache[0]==self.revision else 1):return dict(cache[2],watchlist=self.watches(),events=self.events())
            # Flushing makes the export and both interfaces observe the same snapshot.
            self.flush()
            with self.db() as db:
                rows=db.execute('SELECT first,last,visits,peak,total,seen,hits FROM minutes WHERE signature=? AND last>=? ORDER BY minute',(key,time.time()-DAY)).fetchall()
                discovered=db.execute('SELECT id,frequency,low,high,level,floor,excess,first,last,detections FROM discoveries WHERE signature=? AND last>=? ORDER BY excess DESC LIMIT 256',(key,time.time()-DAY)).fetchall()
            n=math.ceil((config['high']-config['low'])/config['bin']);seen=np.zeros(n);hits=np.zeros(n);total=np.zeros(n);peak=np.full(n,np.nan);timeline=[];visits=0
            for first,last,count,p,t,s,h in rows:
                pp=unpacked(p);ss=unpacked(s);hh=unpacked(h);tt=unpacked(t)
                if len(pp)!=n:continue
                seen+=ss;hits+=hh;total+=tt;peak=np.fmax(peak,pp);visits+=count
                if detail in ('full','timeline'):
                    activity=np.divide(hh,ss,out=np.full(n,np.nan),where=ss>0)*100
                    reduced=reduce_values(pp,config,low,high,columns)
                    codes=encode(reduced,[])
                    timeline.append(dict(started=first,finished=last,visits=count,values=base64.b64encode(codes).decode(),
                                     mean=base64.b64encode(encode(reduce_values(np.where(ss>0,10*np.log10(np.maximum(tt/np.maximum(ss,1),1e-20)),np.nan),config,low,high,columns),[])).decode(),
                                     activity=reduce_values(activity,config,low,high,columns),aggregate=True))
            occupancy=np.divide(hits,seen,out=np.full(n,np.nan),where=seen>0)*100
            average=np.full(n,np.nan);valid=seen>0;average[valid]=10*np.log10(np.maximum(total[valid]/seen[valid],1e-20))
            signals=[]
            for r in discovered:
                index=min(n-1,max(0,int((r[1]-config['low'])/config['bin'])));denominator=int(seen[index]);detected=int(hits[index])
                signals.append(dict(zip(('id','frequency','low','high','level','floor','excess','first','last','detections'),r),
                                    width=r[3]-r[2],visits=denominator,active_visits=detected,activity=round(100*detected/denominator,1) if denominator else None))
            persistence=[];persistence_visits=0
            if history and detail in ('full','persistence'):
                # Persistence is explicitly the recent detailed sweeps, not minute peak buckets.
                raw=history.read(data,columns=min(columns,512),low=low,high=high,raw=True)['rows'][-240:]
                if raw:
                    levels=np.vstack([np.asarray(r['values'],dtype=np.uint8) for r in raw]);persistence_visits=len(raw)
                    for db_level in range(-150,-29,3):persistence.append(((levels>1)&(levels.astype(int)-202>=db_level)&(levels.astype(int)-202<db_level+3)).sum(axis=0).tolist())
            result=dict(key=key,low=low,high=high,columns=columns,threshold=THRESHOLD,visits=visits,signals=signals,
                        activity=reduce_values(occupancy,config,low,high,columns),measured=reduce_values(seen,config,low,high,columns),
                        average=reduce_values(average,config,low,high,columns),peak=reduce_values(peak,config,low,high,columns),timeline=timeline[-1440:],
                        persistence=persistence,persistence_visits=persistence_visits,persistence_low=-150,persistence_step=3,
                        started=min((r[0] for r in rows),default=None),finished=max((r[1] for r in rows),default=None),
                        method='Detected visits / valid sampled visits · local 20th-percentile noise floor · +6 dB threshold · widths limited by bin resolution')
            self.cache[cache_key]=(self.revision,time.monotonic(),result)
            if len(self.cache)>8:self.cache.pop(next(iter(self.cache)))
            return dict(result,watchlist=self.watches(),events=self.events())
