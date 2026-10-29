"""Supervised, receive-only VHF/UHF engines and their local web observatory."""
from collections import OrderedDict, deque
from datetime import datetime
import copy
from http.server import ThreadingHTTPServer
import json
from rtl_registry import same_usb_attachment
import logging
from logging.handlers import RotatingFileHandler
import math
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import urlopen
from station_web import station_get, station_post
from adsb_monitor import ADSBHandler, rtl_devices
from dongle_web import dongle_get, dongle_post
from dongle_notice import notice_post
from adsb_globe import GlobeAssets
from adsb_traffic import receiver_position
from web_app_preview import WebAppPreviews, WEB_APPS, preview_html
from sdr_broker import ReceiverBroker, soapy_args
from vhf_catalog import rtl433_sample_rate, MODES, profiles, write_satellite_profile
from vhf_satellite import prediction, refresh_tle

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
BIN = Path(os.environ.get('ITUNER_VHF_BIN', '/opt/ituner-sdr/decoders/vhf/bin'))


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); return sock.getsockname()[1]


def clean_position(row):
    lat, lon = row.get('lat'), row.get('lon')
    return (isinstance(lat,(int,float)) and isinstance(lon,(int,float))
        and math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180)


def parse_packet(mode, line):
    """Only demodulator output creates observations; diagnostics stay separate."""
    line = ANSI.sub('', line).strip()
    if mode in ('ais','ism','sonde','cubesat'):
        try: item = json.loads(line,parse_constant=lambda value:None)
        except ValueError: return None
        if not isinstance(item,dict): return None
        if mode=='cubesat':
            return item if item.get('kind')=='satellite' and item.get('id') and isinstance(item.get('fields'),dict) else None
        if mode=='ais':
            if not item.get('mmsi'): return None
            return dict(id=str(item['mmsi']), label=item.get('shipname') or str(item['mmsi']),
                lat=item.get('lat'),lon=item.get('lon'),heading=item.get('course',item.get('cog')),speed=item.get('speed'),
                kind='ship',speed_unit='kn',fields=item)
        if mode=='ism':
            if not item.get('model'): return None
            identity=':'.join(str(item.get(k,'')) for k in ('model','id','channel'))
            return dict(id=identity,label=item['model'],kind='sensor',fields=item)
        if not item.get('id'): return None
        return dict(id=str(item['id']),label=str(item['id']),lat=item.get('lat'),lon=item.get('lon'),
            altitude=item.get('alt'),kind='balloon',fields=item)
    if mode=='aprs':
        match=re.match(r'^\[\d+[^\]]*\]\s+([^\s]+>[^:]+:.*)$',line)
        if not match: return None
        packet=match.group(1)
        try:
            import aprslib
            item=aprslib.parse(packet)
        except Exception:
            item=dict(raw=packet, **{'from':packet.split('>',1)[0]})
        return dict(id=item['from'],label=item['from'],lat=item.get('latitude'),lon=item.get('longitude'),
            heading=item.get('course'),speed=item.get('speed'),speed_unit='km/h',kind='station',fields=item)
    return None


class DecoderSession:
    def __init__(self, hub, mode, owner=None):
        self.hub,self.mode,self.owner=hub,mode,owner or mode
        self.root=hub.root/self.owner; self.root.mkdir(exist_ok=True)
        self.runtime=hub.runtime/self.owner; self.runtime.mkdir(exist_ok=True)
        self.lock=threading.RLock(); self.wake=threading.Event(); self.closed=threading.Event()
        self.processes=[]; self.assigned=None; self.generation=0; self.active_generation=-1; self.active_frequency=None
        self.status='STOPPED'; self.detail='Choose a band and press Start.' if self.mode=='ism' else 'Choose a profile and press Start.'; self.messages=0
        self.records=OrderedDict(); self.tracks={}; self.events=deque(maxlen=160); self.output=deque(maxlen=120)
        self.rf={}; self.decoder_stats={}; self.orbit=None; self.started=0; self.retry=0; self.device_retry={}; self.run=None; self.kiss_offset=0; self.kiss_pending=b''
        self.reception={};self.last_reception_sample=0;self.next_reception_log=0
        self.log=logging.Logger('vhf-'+mode+'-'+str(id(self)))
        handler=RotatingFileHandler(self.root/'observations.jsonl',maxBytes=4*1024*1024,backupCount=4)
        handler.setFormatter(logging.Formatter('%(message)s')); self.log.addHandler(handler)
        self.diagnostics=logging.Logger('vhf-diag-'+mode+'-'+str(id(self)))
        handler=RotatingFileHandler(self.root/'receiver.log',maxBytes=2*1024*1024,backupCount=2)
        handler.setFormatter(logging.Formatter('%(message)s')); self.diagnostics.addHandler(handler)
        try: self.settings=json.loads((self.root/'settings.json').read_text())
        except (OSError,ValueError): self.settings={}
        presets=hub.catalog[mode]['presets']
        default=next((p for p in presets if p.get('satellite')=='AO-73'),presets[0])
        self.settings.setdefault('profile',default['id']); self.settings.setdefault('selection','auto')
        self.settings.setdefault('frequency',default['frequency']); self.settings.setdefault('gain',38.6)
        self.settings.setdefault('ppm',0); self.settings.setdefault('doppler',True)
        self.settings.setdefault('continuous',False)
        # The installed sensor dashboard and continuous Meteor can run unattended.
        resume=(self.mode=='ism' and getattr(hub,'rtl433_ui_installed',False)) or (self.mode=='meteor' and self.settings.get('continuous') is True)
        self.enabled=bool(resume and self.settings.get('enabled') is True)
        self.target=self.settings['selection']; self.tle_busy=False
        hub.broker.register(self.owner,lambda:self.control('stop'),lambda:self.control('start'),lambda:self.enabled)
        try:
            with (self.root/'receiver.log').open('rb') as stream:
                stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-65536));lines=stream.read(65536).decode('utf-8','replace').splitlines()
            for line in (lines[1:] if size>65536 else lines)[-120:]:
                try:
                    stamp,text=line.split(' ',1);self.output.append(dict(time=datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp(),text=text))
                except ValueError:pass
        except OSError:pass
        self.thread=threading.Thread(target=self._worker,name='vhf-'+mode,daemon=True); self.thread.start()

    def event(self, text):
        stamp=time.time()
        with self.lock: self.output.append(dict(time=stamp,text=text[:2000]))
        self.diagnostics.info(time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(stamp))+' '+text)

    def profile(self):
        return next((p for p in self.hub.catalog[self.mode]['presets'] if p['id']==self.settings['profile']),self.hub.catalog[self.mode]['presets'][0])

    def control(self, action, **values):
        if action=='start':
            from dongle_notice import require_receiver
            require_receiver(self.owner,self.settings['selection'],self.hub.devices,lambda key:self.control('configure',selection=key),lambda:self.control('start'))
            self.target=self.hub.broker.request(self.owner,[d for d in self.hub.devices if d.get('persistent')],self.settings['selection'],handoff=self.owner==self.mode)
            if self.target is None:raise ValueError('Receiver belongs to another decoder; automatic expansion only uses free dongles.')
        if action=='tle':
            norads=self.profile().get('norads') or [self.profile().get('norad')]
            if not norads[0]: raise ValueError('This profile does not use orbital elements')
            if self.tle_busy: return
            self.tle_busy=True
            def update():
                try:
                    for norad in norads:refresh_tle(self.hub.tle_root,norad)
                    self.event('Orbital data updated from CelesTrak.')
                except Exception as exc: self.event('Orbital update: '+str(exc))
                finally: self.tle_busy=False
            threading.Thread(target=update,daemon=True).start(); return
        with self.lock:
            if action=='configure':
                updated=dict(self.settings)
                if 'profile' in values:
                    item=next((p for p in self.hub.catalog[self.mode]['presets'] if p['id']==values['profile']),None)
                    if not item: raise ValueError('Unknown receiver profile')
                    updated.update(profile=item['id'],frequency=item['frequency'])
                if 'frequency' in values:
                    frequency=float(values['frequency'])
                    if not math.isfinite(frequency) or not 30000000<=frequency<=1700000000: raise ValueError('Frequency must be 30–1700 MHz')
                    if self.mode=='ais' and frequency!=162000000: raise ValueError('AIS receives the fixed A and B channels together')
                    updated['frequency']=int(frequency)
                if 'selection' in values:
                    if values['selection']!='auto' and not any(d['id']==values['selection'] for d in self.hub.devices): raise ValueError('Receiver missing; scan USB again')
                    if values['selection']!='auto' and not next(d for d in self.hub.devices if d['id']==values['selection']).get('persistent'):
                        raise ValueError('SoapySDR needs a unique USB serial for this receiver.')
                    updated['selection']=values['selection']
                for field,lo,hi in (('gain',0,49.6),('ppm',-150,150)):
                    if field in values:
                        number=float(values[field])
                        if not math.isfinite(number) or not lo<=number<=hi: raise ValueError(f'{field} must be {lo} to {hi}')
                        updated[field]=number
                if 'doppler' in values: updated['doppler']=values['doppler'] is True
                if 'continuous' in values:
                    if self.mode!='meteor' and values['continuous']:raise ValueError('Continuous reception is available for Meteor')
                    updated['continuous']=values['continuous'] is True
                self.settings=updated; self.generation+=1; self.target=updated['selection']
            elif action in ('start','stop'):
                self.enabled=action=='start'; self.generation+=1
                if self.enabled and self.profile().get('norad') and any(not (self.hub.tle_root/f'{norad}.json').exists() for norad in (self.profile().get('norads') or [self.profile()['norad']])): self.control('tle')
            elif action!='scan': raise ValueError('Unknown receiver action')
            self.settings['enabled']=self.enabled
            temporary=self.root/'settings.tmp'; temporary.write_text(json.dumps(self.settings)); temporary.replace(self.root/'settings.json')
            self.retry=0;self.device_retry.clear()
        self.wake.set()

    def ingest(self, item):
        now=time.time(); item=dict(item,time=now)
        if self.mode=='ism':item.update(frequency=self.active_frequency,receiver=self.owner,serial=(self.assigned or {}).get('serial'))
        with self.lock:
            self.messages+=1; identity=item['id']; old=self.records.get(identity,{})
            if not clean_position(item):
                item.pop('lat',None);item.pop('lon',None)
                if clean_position(old): item.update(lat=old['lat'],lon=old['lon'],position_time=old.get('position_time',old['time']))
            else: item['position_time']=now
            # Static AIS reports supplement the last dynamic report.
            if self.mode=='ais' and old:
                if item['label']==identity: item['label']=old['label']
                item['fields']=dict(old.get('fields',{}),**item['fields'])
            item['count']=old.get('count',0)+1
            self.records[identity]=item; self.records.move_to_end(identity)
            while len(self.records)>256:
                removed,_=self.records.popitem(last=False); self.tracks.pop(removed,None)
            if clean_position(item) and item.get('position_time')==now:
                trace=self.tracks.setdefault(identity,deque(maxlen=512))
                trace.append(dict(lat=item['lat'],lon=item['lon'],time=now))
            self.events.append(item)
        self.log.info(json.dumps(item,default=str))
        if self.mode=='cubesat' and self.run:
            with (self.run/'telemetry.jsonl').open('a') as stream:stream.write(json.dumps(item,default=str)+'\n')

    def consume(self, stream, generation):
        try:
            while True:
                raw=stream.readline(65537)
                if not raw: break
                line=raw.decode('utf-8','replace').strip(); line=ANSI.sub('',line)
                if not line: continue
                if generation!=self.active_generation: continue
                item=parse_packet(self.mode,line)
                if item: self.ingest(item)
                else: self.event(line[:2000])
        finally: stream.close()

    def child(self, command, stdin=None, output=True):
        process=subprocess.Popen(command,stdin=stdin if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT if output else subprocess.PIPE,
            cwd=str(self.run or self.root),env=dict(os.environ,TZ='UTC',PYTHONUNBUFFERED='1'),start_new_session=True)
        self.processes.append(process)
        stream=process.stdout if output else process.stderr
        threading.Thread(target=self.consume,args=(stream,self.active_generation),daemon=True).start()
        return process

    def launch(self, device):
        if not self.hub.broker.acquire(self.owner,device['id']): return
        self.assigned=dict(device); self.active_generation=self.generation; self.started=time.monotonic()
        self.rf={};self.decoder_stats={};self.messages=0;self.records.clear();self.events.clear();self.tracks.clear()
        self.reception={};self.last_reception_sample=0;self.next_reception_log=0
        self.run=self.root/'sessions'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
        self.run.mkdir(parents=True,exist_ok=True); self.kiss_offset=0;self.kiss_pending=b'';self.telemetry_pipe=None;self.satdump_port=None;self.first_frame=None;self.last_frame=None;self.active_norad=None
        profile=self.profile(); args=soapy_args(device); freq=self.settings['frequency'];self.active_frequency=freq
        gain=str(self.settings['gain']); ppm=str(self.settings['ppm'])
        self.event(f"Starting {MODES[self.mode]['engine']} · {freq/1e6:.6f} MHz · {device['label']}")
        self.status='STARTING';self.detail='Opening the assigned SoapySDR receiver…'
        if self.mode=='ais':
            self.child([str(BIN/'AIS-catcher'),'-d','SOAPYSDR','-gu','DEVICE',args,'AGC','off','GAIN','TUNER='+gain,
                '-s','1536K','-o','5','-M','DT','-N','8101','STATION','iTuner Maritime','-v','10'])
        elif self.mode=='ism':
            rate=str(rtl433_sample_rate(freq))
            self.child([str(BIN/'rtl_433'),'-c','0','-d',args,'-f',str(freq),'-s',rate,'-g',gain,'-p',ppm,'-F','json','-M','time:unix','-M','level'])
        else:
            format={'aprs':'pcm','cubesat':'iq','sonde':'iq16','meteor':'tcp'}[self.mode]
            port=free_port()
            command=[sys.executable,str(Path(__file__).with_name('soapy_rx.py')),'--device',args,'--frequency',str(freq),
                '--tuning',str(self.runtime/'tuning.json'),'--format',format,'--status',str(self.runtime/'rf.json'),'--port',str(port),'--gain',gain,'--ppm',ppm]
            (self.runtime/'rf.json').unlink(missing_ok=True)
            if self.mode=='cubesat':
                telemetry=self.child([sys.executable,str(Path(__file__).with_name('vhf_satellite_frame.py')),'--satellite',profile['satellite']],stdin=subprocess.PIPE)
                self.telemetry_pipe=telemetry.stdin
                frontend=self.child(command,output=False)
                self.child([str(BIN/'gr_satellites'),write_satellite_profile(profile,self.run),'--rawfile','/dev/stdin',
                    '--iq','--samp_rate','48000','--kiss_out',str(self.run/'frames.kiss'),
                    '--telemetry_output',str(self.run/'telemetry.txt'),'--f_offset','0'],stdin=frontend.stdout)
                frontend.stdout.close()
            elif self.mode=='meteor':
                self.write_meteor_product_settings()
                self.child(command)
                # The RTL-TCP bridge owns SoapySDR. SatDump only reads its loopback stream.
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    try:
                        with socket.socket() as probe:
                            probe.bind(('127.0.0.1',port))
                    except OSError: break
                    time.sleep(.1)
                self.satdump_port=free_port()
                self.child([str(BIN/'satdump'),'live',profile['pipeline'],str(self.run/'products'),
                    '--source','rtltcp','--ip_address','127.0.0.1','--port',str(port),
                    '--samplerate','1024000','--frequency',str(freq),'--gain',gain,
                    '--satellite_number',profile['satellite'],'--http_server','127.0.0.1:'+str(self.satdump_port),'--timeout','86400' if self.settings.get('continuous') else '900','--finish_processing'])
            else:
                frontend=self.child(command,output=False)
                if self.mode=='aprs':
                    config=self.run/'direwolf.conf'
                    config.write_text('ADEVICE stdin null\nARATE 48000\nACHANNELS 1\nCHANNEL 0\nMYCALL N0CALL\nMODEM 1200\nAGWPORT 0\nKISSPORT 0\n')
                    consumer=[str(BIN/'direwolf'),'-c',str(config),'-t','0','-q','h','-']
                else:
                    decoder=profile['decoder']; consumer=[str(BIN/decoder),'--json','--iq2','--lpIQ','--ecc' if decoder=='dfm09mod' else '--ecc2','-','48000','16']
                self.child(consumer,stdin=frontend.stdout);frontend.stdout.close()
        self.detail=device['label']

    def write_meteor_product_settings(self):
        # Per-capture overrides use SatDump's documented user-config merge.
        # Save a map for each available channel, even when RGB channels are missing.
        projection=dict(draw_map_overlay=True,individual_equalize=True,config=dict(
            type='equirec',offset_x=-180,offset_y=90,scalar_x=360/2048,scalar_y=-180/1024,width=2048,height=1024))
        composites={f'Meteor channel {channel} map':dict(equation=f'ch{channel}',
            individual_equalize=True,project=projection) for channel in range(1,7)}
        settings=dict(viewer=dict(instruments=dict(msu_mr=dict(rgb_composites=composites))))
        try:
            saved=json.loads((Path.home()/'.config/satdump/settings.json').read_text())
            stamp=saved.get('user',{}).get('tles_last_updated')
            if isinstance(stamp,(int,float)):settings['user']=dict(tles_last_updated=stamp)
        except (OSError,ValueError):pass
        (self.run/'settings.json').write_text(json.dumps(settings,indent=2))

    def stop(self):
        processes,self.processes=self.processes,[]
        if processes:
            self.status='FINISHING' if self.mode=='meteor' else 'STOPPING'
            # Stop the data consumer before its source; Meteor needs a chance to save imagery.
            for process in reversed(processes):
                if process.poll() is None:
                    try: os.killpg(process.pid,signal.SIGINT)
                    except ProcessLookupError: pass
            deadline=time.monotonic()+((180 if self.messages else 25) if self.mode=='meteor' else 4)
            for process in processes:
                try: process.wait(timeout=max(.1,deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    try: os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(timeout=2)
            if self.mode=='meteor':self.poll_meteor()
            if self.run:
                summary=dict(mode=self.mode,profile=self.profile()['name'],frequency=self.settings['frequency'],messages=self.messages,finished=time.time(),reception=dict(self.reception))
                (self.run/'capture-summary.json').write_text(json.dumps(summary,indent=2))
            self.event('Receiver released. Capture files retained.')
        if getattr(self,'telemetry_pipe',None):
            self.telemetry_pipe.close();self.telemetry_pipe=None
        self.assigned=None;self.rf={};self.hub.broker.release(self.owner)
        if self.settings['selection']=='auto':self.target='auto'

    def poll_kiss(self):
        path=self.run/'frames.kiss'
        if not path.exists(): return
        with path.open('rb') as handle:
            handle.seek(self.kiss_offset); chunk=handle.read(262144); self.kiss_offset+=len(chunk)
        self.kiss_pending+=chunk
        while b'\xc0' in self.kiss_pending:
            frame,self.kiss_pending=self.kiss_pending.split(b'\xc0',1)
            if not frame: continue
            frame=frame.replace(b'\xdb\xdc',b'\xc0').replace(b'\xdb\xdd',b'\xdb')
            if frame[0]&15==0 and len(frame)>1:
                if getattr(self,'telemetry_pipe',None):
                    self.telemetry_pipe.write((json.dumps(dict(hex=frame[1:].hex()))+'\n').encode());self.telemetry_pipe.flush()
                else:
                    self.ingest(dict(id=self.profile()['satellite'],label=self.profile()['satellite'],kind='satellite',
                        fields=dict(bytes=len(frame)-1,hex=frame[1:].hex(),profile=self.profile()['name'])))
        if len(self.kiss_pending)>65536: self.kiss_pending=b''

    def poll_meteor(self):
        if not self.run: return
        frames=sum(path.stat().st_size//1024 for path in self.run.rglob('*.cadu'))
        if frames!=self.messages:
            if frames>self.messages:
                self.last_frame=time.monotonic()
                if self.first_frame is None:self.first_frame=self.last_frame
            self.messages=frames
            self.log.info(json.dumps(dict(time=time.time(),id=self.profile()['id'],frames=frames,frequency=self.settings['frequency'])))
        if getattr(self,'satdump_port',None):
            try:
                with urlopen(f'http://127.0.0.1:{self.satdump_port}/api',timeout=.4) as response:
                    stats=json.loads(response.read(65536),parse_constant=lambda value:None)
                self.decoder_stats={key:values for key,values in stats.items() if isinstance(values,dict)}
            except (OSError,ValueError):pass

    def record_reception(self):
        """Keep weak-signal evidence even if no valid frames or images result."""
        if self.mode not in ('meteor','cubesat'):return
        now=time.time();stamp=self.rf.get('time',0)
        if not 0<=now-stamp<4 or stamp<=self.last_reception_sample:return
        self.last_reception_sample=stamp
        summary=self.reception
        summary.setdefault('first_sample',stamp)
        summary.update(last_sample=stamp,samples=self.rf.get('samples'),measurements=summary.get('measurements',0)+1)
        modules={key:value for module in self.decoder_stats.values() for key,value in module.items()}
        for field,value in (('power_dbfs',self.rf.get('power_dbfs')),('snr_db',modules.get('snr')),
                            ('peak_snr_db',modules.get('peak_snr')),('viterbi_ber',modules.get('viterbi_ber'))):
            if isinstance(value,(int,float)) and math.isfinite(value):
                summary['min_'+field]=min(summary.get('min_'+field,value),value)
                summary['max_'+field]=max(summary.get('max_'+field,value),value)
        for field in ('viterbi_lock','deframer_lock'):
            summary[field+'_seen']=summary.get(field+'_seen',False) or bool(modules.get(field))
        if now>=self.next_reception_log:
            orbit={key:(self.orbit or {}).get(key) for key in ('norad','elevation','azimuth','doppler_hz')}
            self.event('RF/decoder measurement '+json.dumps(dict(frequency=self.settings['frequency'],
                rf=self.rf,decoder_stats=self.decoder_stats,orbit=orbit,frames=self.messages),allow_nan=False))
            self.next_reception_log=now+60

    def step(self):
        now=time.monotonic()
        if self.processes and (not self.enabled or self.active_generation!=self.generation or
            not any(same_usb_attachment(d,self.assigned) for d in self.hub.devices)):
            self.stop()
        if not self.enabled:
            self.status='STOPPED';self.detail='Ready. Choose a band and press Start.' if self.mode=='ism' else 'Ready. Choose a profile and press Start.'; return
        if self.processes:
            failed=next((p for p in self.processes if p.poll() is not None),None)
            if failed:
                code=failed.returncode;failed_device=self.assigned['id'];self.stop()
                self.device_retry[failed_device]=now+30
                if self.mode=='meteor' and code==0:
                    if self.settings.get('continuous'):
                        self.device_retry.pop(failed_device,None);self.retry=now+2
                        self.status='STARTING';self.detail='Capture saved · continuous Meteor reception resumes automatically.'
                        self.event(self.detail);return
                    self.enabled=False;self.status='COMPLETE';self.detail='Pass capture complete. Open Products.';return
                self.status='ERROR';self.detail=f'Decoder exited ({code}). See receiver log.';self.retry=now if self.settings['selection']=='auto' else now+30
        if not self.processes and now>=self.retry:
            devices=[d for d in self.hub.devices if d.get('persistent') and (self.target=='auto' or d['id']==self.target)]
            device=next((d for d in devices if self.hub.broker.available(self.owner,d['id']) and self.device_retry.get(d['id'],0)<=now),None)
            if not device:
                self.status='WAITING FOR USB' if not devices else 'WAITING FOR RECEIVER'
                self.detail='Connect or assign an RTL-SDR.' if not devices else 'Receiver is busy or reconnecting; see receiver log.'
                return
            self.launch(device)
        if not self.processes: return
        try:
            rf=json.loads((self.runtime/'rf.json').read_text())
            if time.time()-rf['time']<4: self.rf=rf;self.status='RECEIVING';self.detail='RF stream active · waiting for decoded data' if not self.messages else 'RF stream active · decoding'
        except (OSError,ValueError,KeyError): pass
        if self.mode in ('ais','ism') and now-self.started>3:
            # These engines own the native Soapy stream; process liveness is distinct from decoded data.
            self.status='LISTENING';self.detail='Decoder running · '+('data received' if self.messages else 'no decoded messages yet')
        if self.mode=='cubesat': self.poll_kiss()
        if self.mode=='meteor':
            self.poll_meteor()
            if self.rotate_meteor_if_finished(now):return
        if self.rf and time.time()-self.rf.get('time',0)>12:
            raise RuntimeError('RF stream stopped updating; reconnecting the receiver.')
        if self.mode in ('meteor','cubesat'):
            self.orbit=self.satellite_prediction()
            correction=(self.orbit or {}).get('doppler_hz',0) if self.settings['doppler'] else 0
            tuning=self.runtime/'tuning.json'; temporary=tuning.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(time=time.time(),frequency=self.settings['frequency']+correction)));temporary.replace(tuning)
            self.record_reception()
            if self.mode=='cubesat' and now-self.started>1800:
                self.enabled=False;self.event('30 minute capture limit reached; frames saved.')

    def satellite_prediction(self):
        profile=self.profile()
        norads=profile.get('norads') or [profile.get('norad')]
        options=[prediction(self.hub.tle_root,norad,self.hub.position,self.settings['frequency']) for norad in norads]
        options=[item for item in options if item]
        if not options:return None
        current=next((item for item in options if item['norad']==getattr(self,'active_norad',None) and item.get('elevation',-90)>=0),None)
        chosen=current or max(options,key=lambda item:item.get('elevation',-90))
        self.active_norad=chosen['norad']
        chosen=dict(chosen)
        if len(options)>1:
            chosen['passes']=sorted([dict(p,satellite='M2-3' if item['norad']==57166 else 'M2-4') for item in options for p in item.get('passes',[])],key=lambda p:p['rise'])[:6]
            if chosen.get('elevation',-90)<0:chosen['doppler_hz']=0
        return chosen

    def rotate_meteor_if_finished(self, now):
        if self.mode!='meteor' or not self.settings.get('continuous') or not self.processes:return False
        first,last=getattr(self,'first_frame',None),getattr(self,'last_frame',None)
        if first is not None and last is not None and (now-last>90 or now-first>1200):
            self.event('Meteor pass ended · finalizing imagery, then resuming continuous reception.')
            self.stop();self.retry=time.monotonic()+2
            self.status='FINISHING';self.detail='Saving pass imagery · continuous reception will resume.'
            return True
        return False

    def _worker(self):
        while not self.closed.is_set():
            try: self.step()
            except Exception as exc:
                self.event(str(exc));self.stop();self.status='ERROR';self.detail=str(exc);self.retry=time.monotonic()+30
            self.wake.wait(1);self.wake.clear()
        self.stop()

    def snapshot(self):
        with self.lock:
            return dict(mode=self.mode,receiver=self.owner,target=self.target,status=self.status,detail=self.detail,enabled=self.enabled,
                receiving_frequency=self.active_frequency if self.assigned and self.active_generation==self.generation else None,
                settings=dict(self.settings),assigned=dict(self.assigned) if self.assigned else None,
                messages=self.messages,records=copy.deepcopy(list(self.records.values())),events=copy.deepcopy(list(self.events)),
                output=list(self.output),rf=dict(self.rf),decoder_stats=copy.deepcopy(self.decoder_stats),reception=dict(self.reception),orbit=copy.deepcopy(self.orbit),tle_busy=self.tle_busy)

    def close(self):
        self.closed.set();self.wake.set();self.thread.join(timeout=30)
        for logger in (self.log,self.diagnostics):
            for handler in logger.handlers: handler.close()


class VHFHub:
    def __init__(self,broker=None,root=None,port=8092,scanner=rtl_devices,station=None):
        self.broker=broker or ReceiverBroker();self.scanner=scanner;self.devices=[]
        self.root=Path(root or Path.home()/'.local/share/ituner-sdr/vhf');self.root.mkdir(parents=True,exist_ok=True)
        self.runtime=Path(tempfile.gettempdir())/f'ituner-vhf-{os.getuid()}' if not root else self.root/'runtime'
        self.runtime.mkdir(exist_ok=True);self.tle_root=self.root/'orbits';self.tle_root.mkdir(exist_ok=True)
        self.rtl433_ui_installed=Path('/opt/ituner-sdr/decoders/rtl433-ui/server/index.js').is_file()
        self.catalog=profiles();self.globe=GlobeAssets();self.port=port;self.token=secrets.token_urlsafe(32)
        self.web_apps=WebAppPreviews(port)
        self.closed=threading.Event();self.asset_lock=threading.Lock();self.assets=[];self.next_assets=0
        try:self.position=receiver_position(json.loads((self.root/'station.json').read_text()))
        except (OSError,ValueError):
            try:self.position=receiver_position(json.loads((self.root.parent/'adsb/settings.json').read_text()).get('position'))
            except (OSError,ValueError):self.position=None
        self.station=station
        if station:station.subscribe(self._station_changed)
        self.sessions={mode:DecoderSession(self,mode) for mode in MODES}
        self.sensor_receivers={'ism':self.sessions['ism'],**{f'ism-{i}':DecoderSession(self,'ism',f'ism-{i}') for i in range(2,7)}}
        from spectrum_monitor import SpectrumSurvey
        self.spectrum=SpectrumSurvey(self)
        self.thread=threading.Thread(target=self._worker,name='vhf-discovery',daemon=True);self.thread.start()
        self.server=None
        if port>=0:
            try:
                self.server=ThreadingHTTPServer(('0.0.0.0',port),VHFHandler);self.server.manager=self;self.port=self.server.server_port
                self.web_apps.port=self.port
                threading.Thread(target=self.server.serve_forever,name='vhf-web',daemon=True).start()
            except OSError as exc:
                self.web_error=str(exc)

    def _station_changed(self,data):
        p=data['position']
        self.position=dict(lat=p['lat'],lon=p['lon'],alt=p.get('altitude_msl_m') or 0) if p else None

    def _worker(self):
        while not self.closed.is_set():
            try:
                self.devices=self.scanner()
                from rtl_registry import REGISTRY
                for session in {**self.sessions,**self.sensor_receivers}.values():
                    selection=REGISTRY.resolve(session.settings['selection'],self.devices)
                    if selection!=session.settings['selection']:session.control('configure',selection=selection)
            except (OSError,RuntimeError):self.devices=[]
            try:self.refresh_assets()
            except OSError:pass
            self.closed.wait(5)

    def refresh_assets(self):
        assets=[]
        for mode,session in {**self.sessions,**self.sensor_receivers}.items():
            base=session.root/'sessions'
            sessions=sorted(base.glob('*'),reverse=True) if base.exists() else []
            for directory in (sessions[:20] if mode in MODES else []):
                for path in directory.rglob('*'):
                    if path.is_file() and path.name!='settings.json' and path.suffix.lower() in ('.png','.jpg','.jpeg','.json','.jsonl','.kiss','.txt','.cadu','.cbor'):
                        stat=path.stat()
                        if stat.st_size==0:continue
                        assets.append(dict(path=path.relative_to(self.root).as_posix(),name=path.name,mode=mode,size=stat.st_size,time=stat.st_mtime,
                            image=path.suffix.lower() in ('.png','.jpg','.jpeg')))
            # Keep storage bounded; never remove an active capture directory.
            active=session.run
            total=sum(p.stat().st_size for d in sessions for p in d.rglob('*') if p.is_file())
            for directory in reversed(sessions):
                if directory==active:continue
                if len(sessions)<=20 and total<=512*1024*1024:break
                size=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
                shutil.rmtree(directory);total-=size;sessions.remove(directory)
        with self.asset_lock:self.assets=sorted((a for a in assets if (self.root/a['path']).exists()),key=lambda a:a['time'],reverse=True)[:300]

    def snapshot(self):
        with self.asset_lock:assets=list(self.assets)
        return dict(sessions={k:v.snapshot() for k,v in self.sessions.items()},devices=list(self.devices),
            sensor_receivers={k:v.snapshot() for k,v in self.sensor_receivers.items()},
            leases=self.broker.snapshot(),receiver_position=self.position,assets=assets,port=self.port,
            dashboards=dict(rtl433=self.rtl433_ui_installed))

    def control(self,mode,action,**values):
        if mode=='spectrum':return self.spectrum.control(action,**values)
        if action=='location':
            p=receiver_position(values.get('position'))
            if self.station:self.station.update(dict(latitude=p['lat'] if p else None,longitude=p['lon'] if p else None,gps_auto=False))
            else:
                self.position=p
                (self.root/'station.json').write_text(json.dumps(self.position))
            return
        if action=='scan':
            self.devices=self.scanner();return
        if mode in self.sensor_receivers:
            if mode!='ism' and action not in ('start','stop','configure'):raise ValueError('Unknown sensor receiver action')
            # Native Stop sensors releases the whole pool. A broker handoff calls
            # the individual session directly, leaving other dongles receiving.
            if mode=='ism' and action=='stop':
                for key,session in self.sensor_receivers.items():
                    if key!='ism':session.control('stop')
            self.sensor_receivers[mode].control(action,**values);return
        if mode not in self.sessions:raise ValueError('Unknown decoder')
        self.sessions[mode].control(action,**values)

    def close(self):
        self.closed.set();self.thread.join(timeout=6)
        self.web_apps.close()
        self.spectrum.close()
        for session in self.sessions.values():session.close()
        for key,session in self.sensor_receivers.items():
            if key!='ism':session.close()
        if self.server:self.server.shutdown();self.server.server_close()


class VHFHandler(ADSBHandler):
    def do_GET(self):
        manager=self.server.manager;request=urlsplit(self.path);path=unquote(request.path);query=parse_qs(request.query)
        if dongle_get(self,path):return
        try:
            if path.startswith('/apps/'):
                key=path.removeprefix('/apps/')
                if key not in WEB_APPS:raise ValueError('Unknown satellite application')
                hostname=urlsplit('http://'+self.headers.get('Host','localhost')).hostname or 'localhost'
                rotation=int(query.get('rotation',['0'])[0])
                if rotation not in (0,90,270):raise ValueError('Invalid preview rotation')
                self.send(preview_html(key,manager.web_apps.hostname or hostname,manager.token,touch=query.get('touch')==['1'],rotation=rotation).encode(),'text/html; charset=utf-8')
            elif path=='/api/state':self.send(json.dumps(dict(manager.snapshot(),control_token=manager.token)).encode())
            elif path=='/api/spectrum':self.send(json.dumps(dict(manager.spectrum.snapshot(),devices=manager.devices,leases=manager.broker.snapshot(),control_token=manager.token)).encode())
            elif path=='/api/spectrum/trace':self.send(json.dumps(manager.spectrum.trace(query.get('id',[''])[0])).encode())
            elif path=='/api/spectrum/insights':
                values={key:query[key][0] for key in ('low','high','columns') if key in query}
                values['detail']=query.get('detail',['full'])[0]
                self.send(json.dumps(manager.spectrum.analysis(query.get('scope',['current'])[0],**values),allow_nan=False).encode())
            elif path=='/api/spectrum/compare':
                from spectrum_report import comparison
                self.send(json.dumps(comparison(manager.spectrum.comparison_data(),manager.spectrum.trace(query.get('id',[''])[0])),allow_nan=False).encode())
            elif path=='/api/spectrum/history':
                with manager.spectrum.lock:
                    data=dict(manager.spectrum.data)
                    if 'settings' in data:data['settings']=dict(data['settings'])
                values={key:query[key][0] for key in ('after','low','high','columns') if key in query}
                self.send(json.dumps(manager.spectrum.history.read(data,**values)).encode())
            elif path=='/api/catalog':self.send(json.dumps(manager.catalog).encode())
            elif path.startswith('/spectrum/reports/'):
                parts=path.split('/')
                if len(parts)!=5 or not parts[3].isdigit() or len(parts[3])>24 or parts[4] not in ('index.html','report.json','signals.csv','comparison.csv','waterfall.png','spectrum.svg'):raise ValueError('Unknown report file')
                file=manager.spectrum.root/'reports'/parts[3]/parts[4]
                self.send(file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            elif path=='/api/tracks':
                mode=query.get('mode',['ais'])[0]
                if mode not in manager.sessions:raise ValueError('Unknown decoder')
                session=manager.sessions[mode]
                with session.lock:data={k:list(v) for k,v in session.tracks.items()}
                self.send(json.dumps(data).encode())
            elif path=='/api/log':
                mode=query.get('mode',['ais'])[0];kind=query.get('kind',['observations'])[0]
                if mode not in set(MODES)|set(manager.sensor_receivers)|{'spectrum'} or kind not in ('observations','receiver'):raise ValueError('Unknown log')
                file=manager.root/mode/('observations.jsonl' if kind=='observations' else 'receiver.log')
                self.send(file.read_bytes() if file.exists() else b'', 'text/plain; charset=utf-8')
            elif path.startswith('/products/'):
                file=(manager.root/path[len('/products/'):]).resolve()
                if not file.is_relative_to(manager.root.resolve()) or not any(file.is_relative_to((manager.root/m/'sessions').resolve()) for m in MODES):raise ValueError('Invalid capture path')
                if file.suffix.lower() not in ('.png','.jpg','.jpeg','.json','.jsonl','.kiss','.txt','.cadu','.cbor'):raise ValueError('Unknown capture type')
                if file.stat().st_size>64*1024*1024:raise ValueError('Capture is too large to download in the browser')
                self.send(file.read_bytes(),mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            elif path in ('/','/vhf_dashboard.js','/vhf_dashboard.css','/spectrum','/spectrum.js','/spectrum_tools.js','/spectrum.css'):
                filename='vhf_dashboard.html' if path=='/' else 'spectrum.html' if path=='/spectrum' else path[1:]
                self.send(Path(__file__).with_name(filename).read_bytes(),mimetypes.guess_type(filename)[0] or 'text/plain')
            else:super().do_GET()
        except (ValueError,OSError,KeyError) as exc:self.send(json.dumps(dict(error=str(exc))).encode(),status=400)

    def do_POST(self):
        if notice_post(self):return
        if self.path=='/api/dongles':dongle_post(self);return
        if self.path=='/api/station':station_post(self);return
        manager=self.server.manager
        origin=self.headers.get('Origin')
        if self.headers.get('X-VHF-Token')!=manager.token or (origin and urlsplit(origin).netloc!=self.headers.get('Host')):
            self.send(b'{"error":"Reload the receiver page before controlling it"}',status=403);return
        try:
            if self.path not in ('/api/control','/api/web-app'):raise ValueError('Unknown action path')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=8192:raise ValueError('Invalid request size')
            values=json.loads(self.rfile.read(length))
            if self.path=='/api/web-app':
                if self.client_address[0] not in ('127.0.0.1','::1'):
                    self.send(b'{"error":"Touchscreen launch controls are local only"}',status=403);return
                action=values.get('action')
                if action=='close':manager.web_apps.close()
                elif action=='open':manager.web_apps.open(values.get('app'))
                else:raise ValueError('Unknown web preview action')
                self.send(b'{"ok":true}');return
            mode=values.pop('mode','');action=values.pop('action','')
            result=manager.control(mode,action,**values);self.send(json.dumps(dict(ok=True,result=result)).encode())
        except (ValueError,TypeError,KeyError,OSError) as exc:self.send(json.dumps(dict(error=str(exc))).encode(),status=400)
