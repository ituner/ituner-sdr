"""USB RDS from the existing IQ stream; bounded queues, native decoder process."""
import json
import os
from pathlib import Path
import queue
import re
import select
import shutil
import subprocess
import threading
import time
import numpy as np


class MPXConverter:
    """Streaming channel filter and FM discriminator, retaining the 57 kHz data."""
    def __init__(self,rate):
        from scipy.signal import butter
        self.ratio=int(rate//256000)
        if self.ratio<1 or rate!=self.ratio*256000:raise ValueError('Unsupported RDS input rate')
        self.channel=butter(6,100000,fs=rate,output='sos');self.channel_zi=np.zeros((3,2),complex)
        self.lowpass=butter(8,60000,fs=256000,output='sos');self.audio_zi=np.zeros((4,2))
        self.previous=None;self.phase=0;self.audio_phase=0
    def convert(self,samples):
        from scipy.signal import sosfilt
        filtered,self.channel_zi=sosfilt(self.channel,samples,zi=self.channel_zi)
        iq=filtered[self.phase::self.ratio];self.phase=(self.phase-len(filtered))%self.ratio
        if not len(iq):return b''
        previous=iq[0] if self.previous is None else self.previous
        phase=np.angle(iq*np.conj(np.concatenate(([previous],iq[:-1]))));self.previous=iq[-1]
        phase,self.audio_zi=sosfilt(self.lowpass,phase,zi=self.audio_zi)
        output=phase[self.audio_phase::2];self.audio_phase=(self.audio_phase-len(phase))%2
        return np.clip(output*16000,-32768,32767).astype('<i2').tobytes()


def clean(value,limit):
    return ''.join(c for c in str(value) if c.isprintable()).strip()[:limit]


class StationStore:
    def __init__(self,path=None):
        self.path=Path(path) if path else None;self.lock=threading.RLock();self.rows={};self.dirty=False;self.saved_at=0;self.epochs={}
        if self.path:
            try:
                for row in json.loads(self.path.read_text())[-256:]:
                    key=(str(row['source']),str(row['selection']),int(row['hz']))
                    self.rows[key]={k:row.get(k,'') for k in ('source','selection','hz','ps','radiotext','pi','updated')}
            except (OSError,ValueError,KeyError,TypeError):self.rows={}
    def epoch(self,key):
        with self.lock:return self.epochs.get(key[:2],0)
    def clear(self,source,selection):
        with self.lock:
            receiver=(source,selection)
            self.rows={key:row for key,row in self.rows.items() if key[:2]!=receiver}
            self.epochs[receiver]=self.epochs.get(receiver,0)+1
            self.dirty=True
    def observe(self,key):
        with self.lock:
            if key not in self.rows:
                self.rows[key]=dict(source=key[0],selection=key[1],hz=key[2],ps='',radiotext='',pi='',updated=0)
                while len(self.rows)>256:del self.rows[next(iter(self.rows))]
                self.dirty=True
    def ingest(self,key,message,epoch=None):
        pi=message.get('pi')
        if not isinstance(pi,str) or not re.fullmatch(r'0x[0-9a-fA-F]{4}',pi):return
        with self.lock:
            if epoch is not None and epoch!=self.epoch(key):return
            self.observe(key);row=self.rows[key]
            if row['pi'] and row['pi']!=pi:row.update(ps='',radiotext='')
            row['pi']=pi
            for field,limit in [('ps',8),('radiotext',64)]:
                if field in message:row[field]=clean(message[field],limit)
            row['updated']=time.time();self.dirty=True
    def snapshot(self,source,selection):
        with self.lock:return sorted((dict(row) for key,row in self.rows.items() if key[:2]==(source,selection)),key=lambda r:r['hz'])
    def save(self):
        if not self.path:return
        with self.lock:
            if not self.dirty:return
            payload=json.dumps(list(self.rows.values()));self.dirty=False
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix('.tmp');tmp.write_text(payload);tmp.replace(self.path)
        except OSError:
            with self.lock:self.dirty=True


class USBRDS:
    def __init__(self,path=None,binary=None):
        self.store=StationStore(path);self.binary=binary or shutil.which('redsea')
        self.queue=queue.Queue(maxsize=6);self.closed=threading.Event();self.key=None;self.since=0.;self.generation=0
        self.process=None;self.status='Waiting for WFM' if self.binary else 'RDS decoder not installed'
        self.thread=None
        if self.binary:
            self.thread=threading.Thread(target=self.run,name='usb-rds-mpx',daemon=True);self.thread.start()
    def feed(self,samples,frequency,rate,mode,source,selection):
        if not self.binary or self.closed.is_set():return
        key=(source,selection,int(round(frequency*1000))) if mode=='wbfm' else None
        if key!=self.key:
            self.key=key;self.since=time.monotonic();self.generation+=1
            if key is None:self.status='RDS is available in WFM mode'
        if key is None or time.monotonic()-self.since<1:return
        try:self.queue.put_nowait((self.generation,key,rate,samples))
        except queue.Full:
            self.generation+=1  # A dropped block must not corrupt decoder timing.
    def disable(self):
        self.key=None;self.generation+=1
    def read_json(self,process,key,epoch):
        try:
            for line in process.stdout:
                if len(line)>16384:continue
                try:message=json.loads(line)
                except (ValueError,UnicodeError):continue
                if isinstance(message,dict):self.store.ingest(key,message,epoch)
        except (OSError,ValueError):pass
    def stop_process(self):
        process=self.process;self.process=None
        if process:
            try:process.terminate()
            except ProcessLookupError:pass
            try:process.wait(timeout=.4)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
            process.stdin.close();process.stdout.close()
    def run(self):
        generation=-1;converter=None;reader=None;save_at=time.monotonic()+5
        try:
            while not self.closed.is_set():
                if self.process and generation!=self.generation:
                    self.stop_process()
                    if reader:reader.join(timeout=.5)
                if time.monotonic()>=save_at:self.store.save();save_at=time.monotonic()+5
                try:item=self.queue.get(timeout=.2)
                except queue.Empty:continue
                current,key,rate,samples=item
                if current!=self.generation or key!=self.key:continue
                try:
                    if not self.process:
                        converter=MPXConverter(rate)
                        self.process=subprocess.Popen([self.binary,'--input','mpx','-r','128000'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
                        os.set_blocking(self.process.stdin.fileno(),False);generation=current
                        reader=threading.Thread(target=self.read_json,args=(self.process,key,self.store.epoch(key)),name='usb-rds-json',daemon=True);reader.start()
                        self.store.observe(key);self.status='Listening for RDS'
                    data=converter.convert(samples);deadline=time.monotonic()+.15
                    while data and time.monotonic()<deadline:
                        if select.select([], [self.process.stdin], [], .03)[1]:
                            try:written=os.write(self.process.stdin.fileno(),data);data=data[written:]
                            except BlockingIOError:pass
                    if data:self.generation+=1
                except (OSError,ValueError,ImportError) as exc:
                    self.status='RDS decoder unavailable';self.stop_process();self.since=time.monotonic()
                    self.closed.wait(.5)
        finally:
            self.stop_process();self.store.save()
    def close(self):
        self.closed.set()
        if self.thread:self.thread.join(timeout=2)
        else:self.store.save()
