"""Simultaneous 1090 MHz receiver comparison with continuous five-minute bins."""
from collections import deque
import threading
import csv
import io
import math
import json
from rtl_registry import same_usb_attachment
import os
from pathlib import Path
import subprocess
import time
from adsb_weather import atomic_json
from station_profile import distance_m

GRAPH_SPANS=(300,1800,3600,43200,86400)
GRAPH_RETENTION=86400


def readsb_command(binary, device, data, position):
    command=[binary,'--device-type=rtlsdr',f"--device={device['index']}",'--gain=auto','--quiet',
             '--write-json='+str(data),'--write-json-every=1','--json-trace-interval=5']
    if position:command.extend([f"--lat={position['lat']}",f"--lon={position['lon']}"])
    return command


def comparison_history(data):
    """Never attribute a previous dongle's result to newly selected hardware."""
    data=dict(data,history=[w for w in data.get('history',[]) if not data.get('graph_reset_at') or w.get('start',0)>=data['graph_reset_at']])
    roster=[r['id'] for r in (data.get('current') or {}).get('receivers',[])]
    selected=data.get('selections') or []
    if not roster and data.get('receivers'):roster=[r['id'] for r in data['receivers']]
    if roster:return [w for w in data.get('history',[]) if [r['id'] for r in w['receivers']]==roster]
    if selected:return [w for w in data.get('history',[]) if [r['id'] for r in w['receivers'][1:]]==selected]
    selected=data.get('selection','auto')
    return [w for w in data.get('history',[]) if selected=='auto' or
            len(w['receivers'])==2 and w['receivers'][1]['id']==selected]


def comparison_rates(series,count,interval=5,average_seconds=30):
    """Time-weighted rolling rates, growing from startup to a 30-second window."""
    rates=[];recent=deque()
    for point in series:
        packets=point.get('packets',[]);stamp=point.get('elapsed')
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or len(packets)!=count or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in packets):
            recent.clear();continue
        if recent and stamp<=recent[-1]['elapsed']:continue
        if recent and any(a<b for a,b in zip(packets,recent[-1]['packets'])):recent.clear()
        recent.append(point);cutoff=stamp-max(interval,average_seconds)
        while len(recent)>1 and recent[1]['elapsed']<=cutoff:recent.popleft()
        first=recent[0];start=first['elapsed'];baseline=first['packets']
        if len(recent)>1 and start<cutoff:
            second=recent[1];fraction=(cutoff-start)/(second['elapsed']-start)
            baseline=[a+(b-a)*fraction for a,b in zip(baseline,second['packets'])];start=cutoff
        duration=stamp-start
        if duration>=interval:
            rates.append(dict(elapsed=stamp,rates=[(a-b)/duration for a,b in zip(packets,baseline)]))
    return rates


def rate_graph_max(series):
    """Fit the visible peak, with headroom and rounded steps at every magnitude."""
    peak=max([0]+[v for point in series for v in point['rates']])
    if peak<=0:return 1
    target=max(.1,peak*1.2);unit=10**math.floor(math.log10(target))
    return next(step*unit for step in (1,1.5,2,2.5,3,4,5,6,8,10) if step*unit>=target)


def rate_tick_digits(maximum):
    return max(0,1-math.floor(math.log10(maximum/4)))


def comparison_plot(data,seconds=300):
    """Select a rolling graph horizon; gaps stay separate and never become zero."""
    seconds=seconds if seconds in GRAPH_SPANS else 300
    now=data['now'];points=[p for p in data.get('rate_history',[]) if p['time']>data.get('graph_reset_at',0)]
    roster=[r['id'] for r in (data.get('current') or {}).get('receivers',[]) or data.get('receivers',[])]
    if not roster or roster!=data.get('rate_history_ids'):points=[]
    segments=[];segment=[];previous=None
    for point in points:
        if point['time']<now-seconds:continue
        if point['time']>now:break
        if point['rates'] is None or previous is not None and point['time']-previous['time']>max(8,1.5*point.get('period',2),1.5*previous.get('period',2)):
            if segment:segments.append(segment)
            segment=[]
        if point['rates'] is not None:segment.append(dict(elapsed=point['time']-(now-seconds),rates=point['rates']))
        previous=point
    if segment:segments.append(segment)
    series=[point for segment in segments for point in segment]
    latest=points[-1] if points else None
    return dict(seconds=seconds,segments=segments,max=rate_graph_max(series),
                rates=latest['rates'] if latest and 0<=now-latest['time']<=8 and latest['rates'] is not None else [],
                available_seconds=min(seconds,max(0,now-points[0]['time'])) if points else 0)


class ComparisonGraph:
    """24 hours of rates: detailed for one hour, minute averages before that."""
    def __init__(self,root):
        self.path=Path(root)/'comparison-rates.json';self.ids=[];self.points=deque(maxlen=6000)
        self.raw=[];self.runs=None;self.last_emit=0;self.last_save=0;self.reset_at=0
        try:
            saved=json.loads(self.path.read_text());ids=saved['receiver_ids'];now=time.time()
            if saved.get('version')!=1 or not isinstance(ids,list) or not all(isinstance(k,str) for k in ids):raise ValueError('Invalid graph roster')
            points=[]
            for point in saved['points']:
                t=point['time'];rates=point['rates']
                if not isinstance(t,(int,float)) or not math.isfinite(t):continue
                if rates is not None and (not isinstance(rates,list) or len(rates)!=len(ids) or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in rates)):continue
                if now-GRAPH_RETENTION<=t<=now and (not points or t>points[-1]['time']):
                    record=dict(time=t,rates=rates)
                    if point.get('period')==60 and isinstance(point.get('samples'),int) and 0<point['samples']<=3600:
                        record.update(period=60,samples=point['samples'])
                    points.append(record)
            self.ids=ids;self.points.extend(points[-6000:]);self.reset_at=saved.get('reset_at',0)
        except (OSError,ValueError,KeyError,TypeError):pass

    def checkpoint(self,now,force=False):
        while self.points and self.points[0]['time']<now-GRAPH_RETENTION:self.points.popleft()
        if force or now-self.last_save>=30:
            self.compact(now)
            atomic_json(self.path,dict(version=1,receiver_ids=self.ids,points=list(self.points),reset_at=self.reset_at))
            self.last_save=now

    def compact(self,now):
        # Compact only complete older minutes. Explicit outage markers and reset
        # boundaries split buckets, so averaging never joins separate sessions.
        cutoff=math.floor((now-3600)/60)*60;records=[];group=[];key=None
        def flush():
            if not group:return
            count=sum(p.get('samples',1) for p in group)
            records.append(dict(time=group[-1]['time'],period=60,samples=count,
                rates=[sum(p['rates'][i]*p.get('samples',1) for p in group)/count for i in range(len(group[0]['rates']))]))
            group.clear()
        for point in self.points:
            if point['time']>=cutoff or point['rates'] is None:
                flush();key=None;records.append(point);continue
            bucket=(int(point['time']//60),point['time']>=self.reset_at)
            gap=group and point['time']-group[-1]['time']>max(8,1.5*group[-1].get('period',2),1.5*point.get('period',2))
            if bucket!=key or gap:
                flush();key=bucket
                if gap:records.append(dict(time=point['time']-.000001,rates=None))
            group.append(point)
        flush();self.points.clear();self.points.extend(records)

    def interrupt(self,now):
        self.raw=[];self.runs=None
        if self.points and self.points[-1]['rates'] is not None:
            self.points.append(dict(time=now,rates=None));self.last_emit=now

    def reset(self,now):
        # Hide prior graph samples without deleting retained measurements.
        self.reset_at=now;self.interrupt(now);self.last_emit=0
        self.checkpoint(now,force=True)

    def observe(self,samples,devices,now):
        if samples is None:
            self.interrupt(now);self.checkpoint(now);return
        ids=[d['id'] for d in devices];runs=[s['run'] for s in samples];packets=[s['packets'] for s in samples]
        if ids!=self.ids:
            self.ids=ids;self.points.clear();self.interrupt(now);self.last_emit=0
        if runs!=self.runs or self.raw and (now-self.raw[-1]['elapsed']>8 or any(a<b for a,b in zip(packets,self.raw[-1]['packets']))):
            self.interrupt(now);self.runs=runs
        if not self.raw and self.points and self.points[-1]['rates'] is not None:self.interrupt(now);self.runs=runs
        self.raw.append(dict(elapsed=now,packets=packets))
        while len(self.raw)>2 and self.raw[1]['elapsed']<now-40:self.raw.pop(0)
        rates=comparison_rates(self.raw,len(ids))
        if rates and now-self.last_emit>=2:
            self.points.append(dict(time=now,rates=rates[-1]['rates']));self.last_emit=now
        self.checkpoint(now)


def sample(folder, now):
    try:
        payload=json.loads((Path(folder)/'aircraft.json').read_text())
        stats=json.loads((Path(folder)/'stats.json').read_text())
        # readsb rounds JSON timestamps; a write can also finish after this poll began.
        if not -.5<=now-payload['now']<4 or not -.5<=now-stats['now']<25:return None
        local=stats['last1min']['local']
        return dict(stamp=payload['now'],packets=payload['messages'],aircraft=payload.get('aircraft',[]),
                    run=stats['total']['start'],gain=stats.get('gain_db'),
                    signal=local.get('signal'),noise=local.get('noise'),
                    dropped=stats['total']['local'].get('samples_dropped',0),
                    strong=local.get('strong_signals',0))
    except (OSError,ValueError,KeyError,TypeError):return None


class ComparisonMeter:
    def __init__(self):self.current=None;self.previous=None
    def begin(self, samples, devices, now):
        self.previous=samples
        self.current=dict(start=now,end=now,duration=0,complete=False,valid=True,reason='',
            receivers=[dict(id=d['id'],label=d['label'],packets=0,positions=0,aircraft=[],positioned_aircraft=[],max_range_km=None,gain=s['gain'],signal=s['signal'],noise=s['noise'],strong=s['strong'],samples_dropped=0) for s,d in zip(samples,devices)])
    def update(self, samples, devices, now, site):
        finished=[]
        if self.current and (samples is None or len(samples)!=len(self.previous) or any(a['run']!=b['run'] or a['packets']<b['packets'] for a,b in zip(samples,self.previous)) or [d['id'] for d in devices]!=[r['id'] for r in self.current['receivers']]):
            self.current.update(valid=False,reason='Receiver interrupted or restarted',end=now,duration=now-self.current['start'])
            finished.append(self.current);self.current=None;self.previous=None
        if samples is None:return finished
        if self.current is None:self.begin(samples,devices,now);return finished
        for row,s,old in zip(self.current['receivers'],samples,self.previous):
            row['packets']+=s['packets']-old['packets'];row['gain']=s['gain'];row['signal']=s['signal'];row['noise']=s['noise'];row['strong']=s['strong']
            row['samples_dropped']+=max(0,s['dropped']-old['dropped'])
            aircraft=set(row['aircraft']);positioned=set(row['positioned_aircraft'])
            for p in s['aircraft']:
                if not isinstance(p.get('seen'),(int,float)) or p['seen']>=4 or s['stamp']-p['seen']<self.current['start']:continue
                aircraft.add(p['hex'])
                if isinstance(p.get('lat'),(int,float)) and isinstance(p.get('lon'),(int,float)) and p.get('seen_pos',100)<4:
                    position_time=s['stamp']-p['seen_pos']
                    if position_time<self.current['start']:continue
                    positioned.add(p['hex'])
                    old_plane=next((q for q in old['aircraft'] if q['hex']==p['hex']),None)
                    if old_plane is None or position_time>old['stamp']-old_plane.get('seen_pos',100)+.01:row['positions']+=1
                    if site:
                        distance=distance_m(site,p)/1000
                        if distance<=600:row['max_range_km']=max(row['max_range_km'] or 0,distance)
            row['aircraft']=sorted(aircraft);row['positioned_aircraft']=sorted(positioned)
        self.previous=samples;self.current.update(end=now,duration=now-self.current['start'])
        if self.current['duration']>=300:
            self.current['complete']=True;finished.append(self.current);self.begin(samples,devices,now)
        return finished


class ReceiverComparison:
    def __init__(self,root,data,binary,broker=None):
        self.root=Path(root);self.data=Path(data)/'comparison';self.data.mkdir(exist_ok=True)
        self.binary=binary;self.broker=broker;self.sessions={};self.lock=threading.RLock()
        self.graph=ComparisonGraph(self.root)
        self.meter=ComparisonMeter();self.status='STOPPED';self.detail='';self.primary_detail='';self.receivers=[]
        self.series=deque(maxlen=310);self.series_start=None;self.last_series=0;self.last_ready=0
        try:saved=json.loads((self.root/'comparison.json').read_text())
        except (OSError,ValueError):saved={}
        self.enabled=saved.get('enabled') is True;self.selection=saved.get('selection','auto')
        self.selections=saved.get('selections',[])
        self.restore_uat=saved.get('restore_uat') is True;self.history=saved.get('history',[])[-576:]
        if broker:broker.register('adsb-compare',lambda:self.control('stop'),lambda:self.control('start'),lambda:self.enabled)

    @property
    def process(self):return next((s['process'] for s in self.sessions.values() if s['process']),None)
    @property
    def assigned(self):return next((s['device'] for s in self.sessions.values() if s['process']),None)

    def contains(self,key):
        return key in self.selections or key in self.sessions or key==self.selection

    def save(self):
        atomic_json(self.root/'comparison.json',dict(enabled=self.enabled,selection=self.selection,selections=self.selections,restore_uat=self.restore_uat,history=self.history[-576:]))

    def control(self,action,selection=None):
        with self.lock:
            if action=='start':self.enabled=True
            elif action=='stop':self.enabled=False
            else:raise ValueError('Unknown comparison action')
            if isinstance(selection,list):
                self.selections=list(dict.fromkeys(selection));self.selection='all'
            elif selection is not None:
                self.selection=selection;self.selections=[]
            self.save()

    def reset_graphs(self):
        with self.lock:
            now=time.time();self.graph.reset(now)
            if self.meter.current:
                self.meter.current.update(valid=False,reason='Graphs reset',end=now,duration=now-self.meter.current['start'])
                self.history.append(self.meter.current);self.history=self.history[-576:]
            self.meter=ComparisonMeter();self.series.clear();self.series_start=None;self.last_series=0
            self.save()

    def _stop_session(self,key):
        session=self.sessions[key];process=session['process'];session['process']=None
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        if self.broker:self.broker.release(session['owner'])

    def stop(self):
        with self.lock:
            for key in list(self.sessions):self._stop_session(key)
            self.sessions={}
            self.graph.interrupt(time.time());self.graph.checkpoint(time.time(),force=True)

    def step(self,devices,primary,primary_data,site):
        with self.lock:self._step(devices,primary,primary_data,site)

    def _step(self,devices,primary,primary_data,site):
        now=time.time();online={d['id']:d for d in devices}
        targets=list(self.selections)
        if not targets and primary:
            choices=[d['id'] for d in devices if d['id']!=primary['id'] and d.get('persistent') and (self.selection in ('auto','all') or d['id']==self.selection)]
            targets=choices if self.selection=='all' else choices[:1]
        if not self.enabled:targets=[]
        for key in list(self.sessions):
            session=self.sessions[key];process=session['process']
            failed=process and process.poll() is not None
            if process and (key not in targets or key not in online or not primary or key==primary['id'] or failed or session['position']!=site or key in online and not same_usb_attachment(session['device'],online[key])):
                self._stop_session(key)
                if failed:session['retry']=time.monotonic()+15
            if key not in targets:del self.sessions[key]
        if self.enabled and primary:
            for key in targets:
                device=online.get(key)
                session=self.sessions.setdefault(key,dict(process=None,device=device or dict(id=key,label=key),owner='adsb-compare:'+key,retry=0,position=None))
                if device:session['device']=dict(device)
                if not device or key==primary['id'] or session['process'] or time.monotonic()<session['retry']:continue
                owner=session['owner']
                if self.broker:
                    self.broker.register(owner,lambda:self.control('stop'))
                    if not self.broker.acquire(owner,key):continue
                folder=self.data/('receiver-'+str(device['serial']))
                folder.mkdir(exist_ok=True);session['folder']=folder
                for path in folder.glob('*.json*'):path.unlink(missing_ok=True)
                log=self.root/('comparison-'+str(device['serial'])+'-readsb.txt');session['log']=log
                try:
                    with log.open('w') as output:
                        session['process']=subprocess.Popen(readsb_command(self.binary,device,folder,site),stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,close_fds=True,env=dict(os.environ,TZ='UTC'))
                    session['position']=dict(site) if site else None
                except OSError as exc:
                    session['error']=str(exc);session['retry']=time.monotonic()+15
                    if self.broker:self.broker.release(owner)
        roster=[online.get(primary['id'],primary)]+[self.sessions[k]['device'] for k in targets] if primary and targets else []
        samples=[sample(primary_data,now)] if roster else []
        for key in targets if roster else []:
            session=self.sessions[key];samples.append(sample(session['folder'],now) if session['process'] else None)
        ready=bool(roster) and all(s is not None for s in samples)
        # A transient file read must not discard an otherwise continuous window.
        # Cumulative packet counters bridge it on the next successful poll.
        same_roster=self.meter.current and [d['id'] for d in roster]==[r['id'] for r in self.meter.current['receivers']]
        healthy=primary and all(k in online and self.sessions[k]['process'] is not None for k in targets)
        transient=not ready and same_roster and healthy and now-self.last_ready<4
        if not transient:self.graph.observe(samples if ready else None,roster,now)
        if ready:self.last_ready=now
        finished=[] if transient else self.meter.update(samples if ready else None,roster if ready else [],now,site)
        if finished:self.history.extend(finished);self.history=self.history[-576:];self.save()
        self.receivers=[dict(id=d['id'],label=d['label'],status='RECEIVING' if s else 'WAITING FOR USB' if d['id'] not in online else 'WARMING UP') for d,s in zip(roster,samples)]
        current=self.meter.current
        if current:
            for row,device in zip(current['receivers'],roster):row['label']=device['label']
        if self.series_start!=(current or {}).get('start'):
            self.series.clear();self.series_start=(current or {}).get('start');self.last_series=0
        if current and now-self.last_series>=1:
            self.series.append(dict(elapsed=current['duration'],packets=[r['packets'] for r in current['receivers']]))
            self.last_series=now
        if not self.enabled:self.status='STOPPED';self.detail='Start a comparison with all connected, uniquely identified receivers.'
        elif not primary:self.status='WAITING FOR PRIMARY';self.detail=self.primary_detail or 'Waiting for the primary 1090 receiver to start. USB receivers are checked automatically.'
        elif not roster:self.status='WAITING FOR RECEIVERS';self.detail='Connect another receiver with a unique serial.'
        elif ready:self.status='RUNNING';self.detail=f'{len(roster)} receivers on 1090 MHz · identical readsb settings · gain auto'
        else:
            self.status='WARMING UP' if all(s['process'] for s in self.sessions.values()) else 'WAITING FOR RECEIVERS'
            missing=[r['label'] for r in self.receivers if r['status']!='RECEIVING']
            self.detail='Waiting for fresh data from: '+', '.join(missing)+'. Results require all receivers.'
        for session in self.sessions.values():
            log=session.get('log')
            if log and log.exists() and log.stat().st_size>2*1024*1024:log.write_text('')

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(dict(now=time.time(),enabled=self.enabled,status=self.status,detail=self.detail,
                  interval_seconds=300,uat_paused=self.enabled,selection=self.selection,selections=self.selections,
                  assigned=self.assigned,receivers=self.receivers,series=list(self.series),current=self.meter.current,
                  rate_history_ids=self.graph.ids,rate_history=list(self.graph.points),rate_retention_seconds=GRAPH_RETENTION,graph_reset_at=self.graph.reset_at,
                  history=self.history[-144:],settings='1090 MHz · readsb · gain auto · same sample rate / CRC policy')))

    def csv(self):
        stream=io.StringIO();writer=csv.writer(stream)
        writer.writerow(('start_utc','duration_s','complete','valid','reason','receiver_serial','receiver_label','packets','positions','unique_aircraft','positioned_aircraft','max_range_km','gain_db','samples_dropped'))
        with self.lock:windows=json.loads(json.dumps(self.history))
        for window in windows:
            for r in window['receivers']:writer.writerow((time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(window['start'])),round(window['duration'],1),window['complete'],window['valid'],window['reason'],r['id'],r['label'],r['packets'],r['positions'],len(r['aircraft']),len(r['positioned_aircraft']),r['max_range_km'],r['gain'],r['samples_dropped']))
        return stream.getvalue().encode()
