"""Streaming CW engines with spectral acquisition, bounded to four tracks.
The FFT power ratio is a local detection metric, not calibrated RF SNR.
"""
import ctypes
from collections import deque
from pathlib import Path
import sys
import uuid
import numpy as np
from cw_modes import bounds
from cw_fldigi import FldigiEngine,FldigiCapacityError

RATE=12000
NFFT=1024
HOP=256


class MorseEngine:
    def __init__(self,tone,wpm=0):
        path=Path(__file__).with_name('cw_vendor')/('libituner_cw.dylib' if sys.platform=='darwin' else 'libituner_cw.so')
        try:self.lib=ctypes.CDLL(str(path))
        except OSError as exc:raise ImportError('CW engine missing: run python3 scripts/build-cw.py during installation') from exc
        self.lib.cw_create.argtypes=[ctypes.c_float,ctypes.c_float];self.lib.cw_create.restype=ctypes.c_void_p
        self.lib.cw_destroy.argtypes=[ctypes.c_void_p];self.lib.cw_destroy.restype=None
        self.lib.cw_feed.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_float)]
        self.lib.cw_feed.restype=ctypes.c_int
        self.ptr=self.lib.cw_create(tone,wpm)
        if not self.ptr:raise ValueError('CW engine rejected pitch/speed settings')
        self.stats=(ctypes.c_float*4)();self.output=ctypes.create_string_buffer(4096)

    def feed(self,pcm):
        n=self.lib.cw_feed(self.ptr,pcm,len(pcm),self.output,len(self.output),self.stats)
        if n<0:raise RuntimeError('CW audio processing failed')
        return self.output.raw[:n].decode('ascii',errors='replace')

    def close(self):
        if getattr(self,'ptr',None):self.lib.cw_destroy(self.ptr);self.ptr=None

    def __del__(self):self.close()


class CWDecoder:
    def __init__(self,config):
        self.config=dict(config);self.samples=0;self.pending=np.empty(0,dtype=np.float32)
        self.spectra=deque(maxlen=48);self.waterfall=deque(maxlen=240)
        self.low,self.high=bounds(config)
        self.spacing=150 if config.get('engine')=='fldigi' else 85
        self.engine_type=FldigiEngine if config.get("engine")=="fldigi" else MorseEngine
        self.frequency=np.fft.rfftfreq(NFFT,1/RATE);self.mask=(self.frequency>=self.low)&(self.frequency<=self.high)
        self.capacity_limited=False
        self.window=np.hanning(NFFT);self.tracks=[];self.events=deque();self.next_scan=RATE;self.frame=0
        # Fail explicitly before consuming a Kiwi channel when native code is absent.
        if self.engine_type is FldigiEngine:FldigiEngine.binary()
        else:
            probe=MorseEngine(700);probe.close()

    def feed(self,pcm):
        if len(pcm)%2:raise ValueError('Odd PCM byte count')
        # Native engine accepts at most one second per call.
        if len(pcm)>RATE*2:
            for start in range(0,len(pcm),RATE*2):self.feed(pcm[start:start+RATE*2])
            return
        audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        self.samples+=len(audio);self.pending=np.concatenate((self.pending,audio))
        while len(self.pending)>=NFFT:
            power=np.abs(np.fft.rfft(self.pending[:NFFT]*self.window))**2
            self.spectra.append(power)
            self.frame+=1
            if self.frame%2==0:
                db=10*np.log10(power[self.mask]+1e-12)
                floor=max(float(np.median(db)),float(db.max())-40)
                pixels=np.clip((db-floor)/35,0,1)
                self.waterfall.append(np.interp(np.linspace(self.low,self.high,768),self.frequency[self.mask],pixels))
            self.pending=self.pending[HOP:]
        if self.samples>=self.next_scan and self.spectra:
            self.acquire();self.next_scan=self.samples+RATE//2
        now=self.samples/RATE
        for track in self.tracks:
            text=track['engine'].feed(pcm)
            # Keep timing continuous through key-up gaps; only publish output
            # when a real narrowband signal has recently crossed the gate.
            if text and now-track['seen']<4:
                track['text']=(track['text']+text)[-8192:]
                track['updated']=now
                self.events.append((dict(id=track['id'],rf_hz=track['rf_hz'],wpm=track['wpm']),text,now))
            stats=track['engine'].stats
            if track['level_db']>=self.config['squelch_db'] and np.isfinite(stats[1]):
                track['wpm']=round(float(stats[1]),1)
        expired=[t for t in self.tracks if now-t['seen']>15]
        # The owner snapshots final text before tracks expire at the next scan.
        for t in expired:t['engine'].close();self.tracks.remove(t)

    def acquire(self):
        self.capacity_limited=False
        avg=np.mean(self.spectra,axis=0)
        floor=max(float(np.median(avg[self.mask])),1e-12)
        db=10*np.log10(np.maximum(avg,1e-12)/floor)
        now=self.samples/RATE
        candidates=[]
        for i in np.where(self.mask)[0]:
            if avg[i]>avg[i-1] and avg[i]>=avg[i+1] and db[i]>=self.config['squelch_db']:
                # Parabolic interpolation reduces FFT-bin pitch error.
                a,b,c=np.log(np.maximum(avg[i-1:i+2],1e-12))
                shift=float(np.clip(.5*(a-c)/(a-2*b+c),-.5,.5)) if a-2*b+c else 0
                candidates.append((float(self.frequency[i]+shift*RATE/NFFT),float(db[i])))
        candidates.sort(key=lambda r:-r[1])
        if self.config['cw_mode']=='LOCK':
            tone=self.config['tone_hz'];idx=np.argmin(abs(self.frequency-tone))
            candidates=[(tone,float(db[idx]))] if db[idx]>=self.config['squelch_db'] else []
        for t in self.tracks:t['level_db']=0
        assigned=set()
        for tone,level in candidates:
            if not self.low<=tone<=self.high:continue
            nearest=next((t for t in self.tracks if abs(t['tone_hz']-tone)<self.spacing),None)
            if nearest:
                if nearest['id'] not in assigned:
                    nearest.update(seen=now,level_db=round(level,1));assigned.add(nearest['id'])
                continue
            limit=1 if self.config['cw_mode']=='LOCK' else self.config['max_tracks']
            if len(self.tracks)>=limit:continue
            try:engine=self.engine_type(tone,self.config['wpm'])
            except FldigiCapacityError:
                self.capacity_limited=True;continue
            self.tracks.append(dict(id=uuid.uuid4().hex,tone_hz=round(tone,1),
                rf_hz=round(self.config['freq_khz']*1000+tone,1),wpm=0,level_db=round(level,1),
                text='',started=now,updated=now,seen=now,engine=engine))

    def snapshot(self):
        now=self.samples/RATE
        return [dict((k,v) for k,v in t.items() if k not in ('engine','seen'))|
                {'active':now-t['seen']<4} for t in sorted(self.tracks,key=lambda t:t['tone_hz'])]

    def close(self):
        for t in self.tracks:t['engine'].close()
        self.tracks=[]
