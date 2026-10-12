"""Persistent receive-only fldigi PCM worker; no access to system audio devices.
All tracks share one private virtual display. Per-track queues are bounded, and
failure is surfaced to the receiver instead of silently dropping timing data.
"""
import os
from pathlib import Path
import queue
import select
import shutil
import subprocess
import tempfile
import threading
import numpy as np


class FldigiCapacityError(RuntimeError):
    pass


class VirtualDisplay:
    lock=threading.Lock()
    process=None
    users=0
    name=None

    @classmethod
    def acquire(cls):
        with cls.lock:
            if cls.users>=4:raise FldigiCapacityError("All four fldigi signal slots are in use")
            if not cls.users:
                cls.process=subprocess.Popen(['Xvfb','-displayfd','1','-screen','0','640x480x24','-nolisten','tcp'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
                if not select.select([cls.process.stdout],[],[],8)[0]:
                    cls.process.kill();cls.process.wait();raise RuntimeError('fldigi virtual display did not start')
                value=cls.process.stdout.readline().decode().strip()
                if not value.isdigit():
                    cls.process.kill();cls.process.wait();raise RuntimeError('fldigi virtual display failed')
                cls.name=':'+value
            cls.users+=1
            return cls.name

    @classmethod
    def release(cls):
        with cls.lock:
            cls.users-=1
            if not cls.users:
                cls.process.terminate()
                try:cls.process.wait(timeout=2)
                except subprocess.TimeoutExpired:cls.process.kill();cls.process.wait()
                cls.process.stdout.close();cls.process=None


class FldigiEngine:
    @staticmethod
    def binary():
        path=Path(os.environ.get('ITUNER_FLDIGI_BIN',str(Path(__file__).with_name('cw_vendor')/'fldigi')))
        if not path.is_file() or not os.access(path,os.X_OK) or not shutil.which('Xvfb'):
            raise ImportError('fldigi engine missing: run scripts/install-fldigi.sh')
        try:from scipy.signal import lfilter
        except ImportError as exc:raise ImportError('fldigi needs python3-scipy') from exc
        return str(path)

    def __init__(self,tone,wpm=0):
        binary=self.binary()
        from scipy.signal import firwin
        self.taps=firwin(63,1/3)*2;self.zi=np.zeros(62);self.phase=0
        self.stats=[tone,0,0,0];self.error=None;self.closed=False
        self.incoming=queue.Queue(maxsize=64);self.outgoing=queue.Queue(maxsize=256)
        self.ready=threading.Event();self.threads=[];self.process=None;self.display=False
        self.work=tempfile.TemporaryDirectory(prefix='ituner-cw-fldigi-')
        try:
            display=VirtualDisplay.acquire();self.display=True
            options={'CWSPEED':wpm or 30,'CWTRACK':int(not wpm),'CWRANGE':25,
                     'CWLOWERLIMIT':5,'CWUPPERLIMIT':55,'CWBANDWIDTH':150,
                     'CWMFILT':0,'CWUSESOMDECODING':0}
            config=Path(self.work.name)
            (config/'fldigi_def.xml').write_text('<FLDIGI_DEFS>'+''.join(f'<{k}>{v}</{k}>' for k,v in options.items())+'</FLDIGI_DEFS>')
            self.process=subprocess.Popen([binary,'--config-dir',str(config),'--benchmark-modem','1',
                '--benchmark-frequency',str(tone),'--benchmark-afc','0','--benchmark-squelch','0',
                '--benchmark-input','-','--benchmark-output','/dev/null'],
                env=dict(os.environ,HOME=str(config),DISPLAY=display),stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=8192)
            for target in (self.read,self.write):
                thread=threading.Thread(target=target,daemon=True);self.threads.append(thread);thread.start()
        except Exception:self.close();raise

    def read(self):
        try:
            for line in self.process.stdout:
                if line.startswith(b'ITUNER_READY'):self.ready.set()
                elif line.startswith(b'ITUNER_RX:'):
                    value=bytes.fromhex(line[10:].decode().strip()).decode('utf-8',errors='replace')
                    if value:self.outgoing.put_nowait(value)
                elif line.startswith(b'ITUNER_WPM:'):self.stats[1]=float(line[11:])
            if not self.closed:self.error='fldigi stopped unexpectedly'
        except Exception as exc:
            if not self.closed:self.error='fldigi output: '+str(exc)

    def write(self):
        try:
            if not self.ready.wait(12):raise RuntimeError('fldigi streaming adapter did not become ready')
            while not self.closed:
                try:pcm=self.incoming.get(timeout=.2)
                except queue.Empty:continue
                if pcm is None:break
                view=memoryview(pcm)
                while view:
                    n=self.process.stdin.write(view)
                    if not n:raise RuntimeError('fldigi closed its audio pipe')
                    view=view[n:]
                self.process.stdin.flush()
        except Exception as exc:
            if not self.closed:self.error='fldigi audio: '+str(exc)

    def feed(self,pcm):
        if self.error:raise RuntimeError(self.error)
        from scipy.signal import lfilter
        # Continuous 12 -> 8 kHz FIR resampling, retaining delay and phase.
        audio=np.frombuffer(pcm,dtype='<i2').astype(float)
        up=np.zeros(len(audio)*2);up[::2]=audio
        filtered,self.zi=lfilter(self.taps,[1],up,zi=self.zi)
        down=filtered[self.phase::3];self.phase=(self.phase-len(up))%3
        data=np.clip(down,-32768,32767).astype('<i2').tobytes()
        try:self.incoming.put_nowait(data)
        except queue.Full:raise RuntimeError('fldigi cannot keep up with live audio; reduce active signals')
        text=[]
        while True:
            try:text.append(self.outgoing.get_nowait())
            except queue.Empty:break
        return ''.join(text)

    def close(self):
        if self.closed:return
        self.closed=True;self.ready.set()
        if self.process:
            self.process.terminate()
            try:self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            for t in self.threads:t.join(timeout=1)
            self.process.stdin.close();self.process.stdout.close()
        if self.display:VirtualDisplay.release()
        self.work.cleanup()
