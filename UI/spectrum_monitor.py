"""Broker-owned, bounded spectrum surveys and comparable saved antenna traces."""
import json
import copy
from collections import deque
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from sdr_broker import soapy_args
from spectrum_history import SweepHistory, signature
from spectrum_analysis import SpectrumInsights

DEFAULT=dict(low=25000000,high=1700000000,bin=100000,gain=28.0,ppm=0,selection='auto',repeat=False,auto_gain=True,purpose='survey',focus=0)

def settings(values,previous=None):
    result={**DEFAULT,**(previous or {})}
    for key in ('low','high','bin','gain','ppm'):
        if key in values:
            number=float(values[key])
            if not math.isfinite(number):raise ValueError('Survey settings must be finite numbers')
            result[key]=number
    if not 25000000<=result['low']<result['high']<=1700000000:raise ValueError('Survey range must be within 25–1700 MHz')
    if not 2500<=result['bin']<=1000000:raise ValueError('Bin width must be 2.5–1000 kHz')
    count=math.ceil((result['high']-result['low'])/result['bin'])
    if count>20000:raise ValueError(f'This range needs {count:,} bins; maximum 20,000. Use 100 kHz for the full survey, or limit the span to 500 MHz at 25 kHz / 100 MHz at 5 kHz.')
    if not 0<=result['gain']<=49.6 or not -150<=result['ppm']<=150:raise ValueError('Gain must be 0–49.6 dB; PPM −150 to 150')
    if 'selection' in values:result['selection']=str(values['selection'])
    for key in ('repeat','auto_gain'):
        if key in values:
            if not isinstance(values[key],bool):raise ValueError(key+' must be true or false')
            result[key]=values[key]
    if 'purpose' in values:result['purpose']=values['purpose']
    if result['purpose'] not in ('survey','investigate','watch'):raise ValueError('Unknown survey mode')
    if 'focus' in values:result['focus']=float(values['focus'])
    if not math.isfinite(result['focus']):raise ValueError('Focus frequency must be finite')
    if result['purpose']=='investigate' and result['high']-result['low']>1536000:raise ValueError('Live investigation must fit within 1.536 MHz')
    return result

class SpectrumSurvey:
    def __init__(self,hub):
        self.hub=hub;self.root=hub.root/'spectrum';self.root.mkdir(exist_ok=True);self.lock=threading.RLock();self.control_lock=threading.RLock();self.requested_at=None;self.activity=deque(maxlen=15)
        self.enabled=False;self.status='STOPPED';self.detail='Choose a range and start a survey.';self.assigned=None;self.process=None;self.thread=None;self.stopped=threading.Event();self.data={};self.target='auto'
        try:self.settings=settings(json.loads((self.root/'settings.json').read_text()))
        except (OSError,ValueError,TypeError):self.settings=dict(DEFAULT)
        try:self.data=json.loads((self.root/'latest.json').read_text())
        except (OSError,ValueError):pass
        self.completed=json.loads(json.dumps(self.data)) if self.data.get('complete') else None
        self._report_stamp=None;self._report_rows=[]
        self.history=SweepHistory(self.root/'waterfall.sqlite3')
        if self.completed:self.history.append(self.completed)
        self.insights=SpectrumInsights(self.root);self.insights.seed(self.history,self.data)
        try:self.parents=json.loads((self.root/'survey-return.json').read_text())[-2:]
        except (ValueError,OSError,TypeError):self.parents=[]
        hub.broker.register('spectrum',lambda:self.stop('Receiver handed to another decoder'),lambda:self.control('start'),lambda:self.enabled)

    def event(self,action,detail):
        row=dict(time=time.time(),action=action,detail=str(detail)[:1000])
        with self.lock:
            self.activity.append(row)
            path=self.root/'activity.jsonl'
            try:
                if path.exists() and path.stat().st_size>1024*1024:path.replace(self.root/'activity.jsonl.1')
                with path.open('a') as stream:stream.write(json.dumps(row)+'\n')
            except OSError:pass

    def control(self,action,**values):
        # Threaded HTTP clients must not launch competing survey workers.
        with self.control_lock:return self._control(action,**values)

    def _control(self,action,**values):
        if action in ('start','survey_start','watch_start','investigate'):
            from dongle_notice import require_receiver
            require_receiver('spectrum',values.get('selection',self.settings['selection']),self.hub.devices,lambda key:self._control('configure',selection=key),lambda:self.control(action,**dict(values,selection=self.settings['selection'])))
        if action=='stop':self.stop();return
        if action=='save':return self.save(values.get('label','Antenna baseline'))
        if action=='survey_start':
            settings(dict(values,purpose='survey',focus=0),self.settings)
            self.stop();self._control('configure',**values);return self._control('start')
        if action=='watch_add':return self.insights.add_watch(values['frequency'],values.get('label',''),values.get('bandwidth',25000))
        if action=='watch_remove':
            self.insights.remove_watch(values['id'])
            if self.settings.get('purpose')=='watch' and not self.insights.watch:self.stop('Watchlist empty; receiver released')
            return
        if action=='report':
            from spectrum_report import create_report
            return create_report(self,values.get('label','RF survey'),values.get('notes',''),values.get('baseline_id',''))
        if action=='investigate':
            frequency=float(values['frequency']);span=float(values.get('span',1500000))
            if not math.isfinite(frequency) or not 25e6<=frequency<=1700e6:raise ValueError('Choose a frequency within 25–1700 MHz')
            if not math.isfinite(span) or not 100000<=span<=1536000:raise ValueError('Live span must be 0.1–1.536 MHz')
            low=max(25e6,min(1700e6-span,frequency-span/4))
            updated=dict(self.settings,low=low,high=low+span,bin=5000,repeat=True,purpose='investigate',focus=frequency,gain=self.data.get('settings',self.settings)['gain'])
            return self.switch(updated)
        if action=='watch_start':
            if not self.insights.watch:raise ValueError('Add a frequency to your watchlist first')
            frequencies=[w['frequency'] for w in self.insights.watch]
            updated=dict(self.settings,low=max(25e6,min(frequencies)-750000),high=min(1700e6,max(frequencies)+1250000),bin=100000,repeat=True,purpose='watch',focus=0,gain=self.data.get('settings',self.settings)['gain'])
            return self.switch(updated)
        if action=='return':
            if not self.parents:raise ValueError('There is no previous survey to return to')
            self.stop();parent=self.parents.pop();self.store_settings(settings(parent['settings']));self.store_parents()
            if parent['enabled']:self._control('start')
            return
        if action=='configure':
            updated=settings(dict(values,purpose='survey',focus=0),self.settings)
            if updated['selection']!='auto' and not any(d['id']==updated['selection'] and d.get('persistent') for d in self.hub.devices):raise ValueError('Choose a connected receiver with a unique USB serial')
            if self.enabled:raise ValueError('Stop the survey before changing its settings')
            self.parents=[];self.store_parents();self.store_settings(updated);return
        if action!='start':raise ValueError('Unknown survey action')
        if self.enabled:return
        devices=[d for d in self.hub.devices if d.get('persistent')]
        if not devices:raise ValueError('No uniquely identified RTL-SDR is connected')
        if self.settings['purpose']=='watch' and not self.insights.watch:raise ValueError('Add a watch frequency first')
        self.target=self.hub.broker.request('spectrum',devices,self.settings['selection'])
        self.stopped.clear();self.enabled=True;self.requested_at=time.time();self.status='STARTING';self.detail='Waiting for the assigned receiver to be released…'
        self.event('start','Start requested · receiver '+self.target)
        self.thread=threading.Thread(target=self.run,name='spectrum-survey',daemon=True);self.thread.start()

    def run(self):
        try:
            deadline=time.monotonic()+10;device=None
            while not self.stopped.is_set() and time.monotonic()<deadline:
                device=next((d for d in self.hub.devices if d['id']==self.target and d.get('persistent')),None)
                if device and self.hub.broker.acquire('spectrum',device['id']):break
                self.stopped.wait(.1)
            else:
                if self.stopped.is_set():return
                raise RuntimeError('Receiver is still busy or disconnected; try Start again')
            self.assigned=device
            config=dict(self.settings);n=math.ceil((config['high']-config['low'])/config['bin'])
            with self.lock:
                self.completed=None
                self.data=dict(settings=dict(config),requested_gain=config['gain'],device=device,started=time.time(),updated=None,finished=None,sweep=0,progress=0,current_frequency=None,power=[None]*n,peak=[None]*n,average=[None]*n,counts=[0]*n,masked=[False]*n,quality=[],adjustments=[],clipped=0,samples=0,complete=False)
                self.data['sample_time']=[None]*n
            command=[sys.executable,str(Path(__file__).with_name('soapy_survey.py')),'--device',soapy_args(device)]
            for key in ('low','high','bin','gain','ppm'):command+=['--'+key,str(config[key])]
            if config['repeat']:command+=['--repeat']
            if config['auto_gain']:command+=['--auto-gain']
            if config['purpose']=='investigate':command+=['--live']
            if config['purpose']=='watch':command+=['--watch',json.dumps(self.insights.watch,separators=(',',':'))]
            log=self.root/'receiver.log'
            if log.exists() and log.stat().st_size>1024*1024:log.replace(self.root/'receiver.log.1')
            with log.open('ab') as errors:
                self.process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,start_new_session=True)
                if self.stopped.is_set():os.killpg(self.process.pid,signal.SIGINT)
                self.status='STARTING';self.detail='Receiver opened · waiting for the first IQ measurements…'
                for raw in self.process.stdout:
                    if len(raw)>200000:raise RuntimeError('Survey output exceeded its size limit')
                    row=json.loads(raw)
                    if row.get('kind')=='error':raise RuntimeError(row.get('error','Receiver error'))
                    self.ingest(row)
                code=self.process.wait()
                if code and not self.stopped.is_set():raise RuntimeError('Survey receiver exited; inspect receiver log')
            if not self.stopped.is_set():
                if not self.data.get('complete'):raise RuntimeError('Receiver exited before completing a sweep. See receiver log.')
                self.status='COMPLETE';self.detail='Survey complete · USB receiver released.';self.event('complete',self.detail)
        except Exception as exc:self.status='ERROR';self.detail=str(exc);self.event('error',self.detail)
        finally:
            process=self.process
            if process and process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=2)
                except (ProcessLookupError,subprocess.TimeoutExpired):
                    try:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=2)
                    except ProcessLookupError:pass
            self.process=None;self.assigned=None;self.hub.broker.release('spectrum')
            try:
                if self.data.get('updated'):
                    with self.lock:
                        temporary=self.root/'latest.tmp';temporary.write_text(json.dumps(self.data,allow_nan=False));temporary.replace(self.root/'latest.json')
            except OSError as exc:self.status='ERROR';self.detail='Could not save survey: '+str(exc)
            finally:
                self.insights.flush();self.enabled=False

    def ingest(self,row):
        with self.lock:
            d=self.data;kind=row.get('kind')
            if kind=='begin':
                # Fixed-band frames retain the last display until the next real
                # measurement arrives; clearing at every begin makes a live view blank.
                power=d['power'] if d['settings'].get('purpose')=='investigate' else [None]*len(d['power'])
                d.update(sweep=row['sweep'],sweep_started=row.get('time',time.time()),progress=0,rate=row['rate'],fft=row['fft'],power=power,complete=False)
                d['masked']=[False]*len(d['power']);d['quality']=[]
                d['sample_time']=[None]*len(d['power'])
                if 'gain' in row:d['settings']['gain']=row['gain']
                if row.get('reset'):
                    self.completed=None
                    d.update(peak=[None]*len(d['power']),average=[None]*len(d['power']),counts=[0]*len(d['power']),clipped=0,samples=0)
                self.detail='Relative power density · '+str(d['settings']['gain'])+' dB fixed for this sweep · uncalibrated'
            elif kind=='gain_adjust':
                d.setdefault('adjustments',[]).append(row)
                self.detail='Automatic gain: reducing to '+str(row['gain'])+' dB and restarting the sweep.'
            elif kind=='chunk':
                if d['settings'].get('purpose')=='investigate':d['power']=[None]*len(d['power'])
                if self.status!='SCANNING':self.event('receiving','Fresh IQ measurements received')
                self.status='SCANNING'
                bad=row['clipped']/max(1,row['samples'])>.001
                masked=bad and d['settings'].get('auto_gain') is True and d['settings']['gain']<=0
                if bad:d.setdefault('quality',[]).append(dict(frequency=row['frequency'],clip_fraction=row['clipped']/max(1,row['samples']),excluded=masked))
                for index,value in zip(row['indices'],row['values']):
                    if not isinstance(index,int) or not 0<=index<len(d['power']) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Invalid spectrum data')
                    if masked:
                        d.setdefault('masked',[False]*len(d['power']))[index]=True
                        for field in ('power','peak','average'):d[field][index]=None
                        d['counts'][index]=0
                        continue
                    if d.setdefault('masked',[False]*len(d['power']))[index]:continue
                    d.setdefault('sample_time',[None]*len(d['power']))[index]=row['time']
                    d['power'][index]=value;d['peak'][index]=max(value,d['peak'][index] if d['peak'][index] is not None else value)
                    # Average linear power, not logarithmic dB values.
                    count=d['counts'][index];old=d['average'][index]
                    d['average'][index]=round(10*math.log10(((10**(old/10)*count if old is not None else 0)+10**(value/10))/(count+1)),2)
                    d['counts'][index]=count+1
                d.update(updated=row['time'],progress=round(row['hop']/row['hops'],5),current_frequency=row['frequency'])
                d['clipped']+=row['clipped'];d['samples']+=row['samples']
            elif kind=='complete':
                d.update(complete=True,finished=row['time'],progress=1)
                self.completed=json.loads(json.dumps(d))
                self.history.append(d)
                self.insights.observe(d)
            elif kind=='watch':
                watch=next((w for w in self.insights.watch if w['id']==row.get('id')),None)
                if watch:self.insights.watch_measure(watch,row,self.insights_key())

    def store_settings(self,updated):
        self.settings=updated;(self.root/'settings.json').write_text(json.dumps(updated))

    def store_parents(self):(self.root/'survey-return.json').write_text(json.dumps(self.parents))

    def context(self,scope='current'):
        with self.lock:
            if scope=='survey' and self.parents:return dict(self.parents[0]['context'])
            return {key:json.loads(json.dumps(self.data[key])) for key in ('settings','device','rate','fft') if key in self.data}

    def insights_key(self):
        from spectrum_history import signature
        return signature(self.context())

    def analysis(self,scope='current',**values):
        return self.insights.snapshot(self.context(scope),history=self.history,**values)

    def switch(self,updated):
        updated=settings(updated)
        if not any(d.get('persistent') for d in self.hub.devices):raise ValueError('No uniquely identified RTL-SDR is connected')
        if self.settings.get('purpose')!=updated['purpose']:
            self.parents.append(dict(settings=dict(self.settings),enabled=self.enabled,context=self.context()));self.parents=self.parents[-2:]
        self.stop();self.store_settings(updated);self.store_parents();self._control('start')

    def stop(self,reason='Stopped by request'):
        with self.control_lock:return self._stop(reason)

    def _stop(self,reason):
        active=self.enabled
        if active:self.status='STOPPING';self.detail='Stopping survey · releasing USB…'
        self.stopped.set();process=self.process
        if process and process.poll() is None:
            try:os.killpg(process.pid,signal.SIGINT)
            except ProcessLookupError:pass
        thread=self.thread
        if thread and thread is not threading.current_thread():thread.join(timeout=6)
        if thread and thread.is_alive():raise RuntimeError('Survey is still releasing its receiver')
        self.enabled=False
        if self.status!='ERROR':
            self.status='STOPPED';self.detail=reason+' · last measurements retained.'
        if active:self.event('stop',reason)

    def save(self,label):
        with self.lock:
            if not self.completed:raise ValueError('Complete at least one sweep before saving a baseline')
            label=str(label).strip()[:80] or 'Antenna baseline'
            stamp=str(time.time_ns());payload=dict(self.completed,label=label,id=stamp)
            (self.root/(stamp+'.json')).write_text(json.dumps(payload,allow_nan=False))
            for path in sorted(self.root.glob('[0-9]*.json'))[:-20]:path.unlink()
            return stamp

    def saved(self):
        rows=[]
        for path in sorted(self.root.glob('[0-9]*.json'),reverse=True):
            try:
                value=json.loads(path.read_text());rows.append({key:value.get(key) for key in ('id','label','settings','device','finished')})
            except (OSError,ValueError):pass
        return rows

    def trace(self,identity):
        if not str(identity).isdigit() or len(str(identity))>24:raise ValueError('Unknown saved trace')
        return json.loads((self.root/(str(identity)+'.json')).read_text())

    def run_state(self):
        process_running=bool(self.process and self.process.poll() is None)
        updated=self.data.get('updated') if self.data.get('started',0)>=(self.requested_at or float('inf')) else None
        age=max(0,time.time()-updated) if updated is not None else None
        if self.status=='ERROR':phase='FAILED'
        elif self.status=='STOPPING' and self.enabled:phase='STOPPING'
        elif self.enabled:
            phase='RUNNING' if process_running and age is not None and age<=5 else 'WAITING FOR DATA' if process_running and age is not None else 'STARTING'
        else:phase='COMPLETED' if self.status=='COMPLETE' else 'STOPPED'
        return dict(phase=phase,process_running=process_running,last_sample_age=age,requested_at=self.requested_at)

    def snapshot(self):
        with self.lock:
            # Serialize under the same lock that updates the trace arrays.
            return json.loads(json.dumps(dict(enabled=self.enabled,status=self.status,detail=self.detail,assigned=self.assigned,run=self.run_state(),activity=list(self.activity),settings=self.settings,data=self.data,history=self.history.metadata(self.data),last_complete_finished=self.completed.get('finished') if self.completed else None,can_return=bool(self.parents),return_to=self.parents[-1]['settings'].get('purpose','survey') if self.parents else None,watchlist=self.insights.watches(),reports=self.reports(),can_save=self.completed is not None,saved=self.saved()),allow_nan=False))

    def native_snapshot(self):
        """In-process data, without the HTTP/JSON serialization round trip.

        Copy mutable samples under the receiver lock; directory/database work
        stays outside it and is refreshed only when needed.
        """
        with self.lock:
            result=copy.deepcopy(dict(enabled=self.enabled,status=self.status,detail=self.detail,assigned=self.assigned,
                run=self.run_state(),activity=list(self.activity),settings=self.settings,data=self.data,
                last_complete_finished=self.completed.get('finished') if self.completed else None,
                can_return=bool(self.parents),return_to=self.parents[-1]['settings'].get('purpose','survey') if self.parents else None,
                can_save=self.completed is not None))
        now=time.monotonic();key=(signature(result['data']),result['last_complete_finished'])
        cached=getattr(self,'_native_catalog',None)
        if not cached or cached[0]!=key or now-cached[1]>2:
            cached=(key,now,dict(history=self.history.metadata(result['data']),saved=self.saved(),reports=self.reports()))
            self._native_catalog=cached
        result.update(copy.deepcopy(cached[2]));result['watchlist']=copy.deepcopy(self.insights.watches())
        return result

    def reports(self):
        # Reports contain large arrays; only read each immutable export once.
        paths=sorted((self.root/'reports').glob('*/report.json'),reverse=True)[:100]
        stamp=tuple(str(p) for p in paths)
        if self._report_stamp==stamp:return self._report_rows
        result=[]
        for path in paths:
            try:
                metadata=path.with_name('metadata.json')
                value=json.loads((metadata if metadata.exists() else path).read_text())
                result.append(dict(id=path.parent.name,label=value.get('label','RF survey'),time=value.get('created')))
            except (ValueError,OSError):pass
        self._report_rows=result;self._report_stamp=stamp
        return result

    def comparison_data(self):
        with self.lock:return json.loads(json.dumps(self.completed)) if self.completed else {}

    def close(self):self.stop()
