#!/usr/bin/env python3
"""Receive-only stepped power-density survey using the assigned SoapySDR serial."""
import argparse
import json
import math
import signal
import threading
import time

RATE=2048000
FFT=1024
USABLE=1536000
CLIP_LIMIT=.001

def lower_gain(gain):return max(0,gain-10)

def plan(low,high):
    count=max(1,math.ceil((high-low)/USABLE))
    width=(high-low)/count
    return [low+(i+.5)*width for i in range(count)]

def fft_density(samples):
    """Two-sided PSD, normalized so its integral equals mean complex IQ power."""
    import numpy as np
    window=np.hanning(FFT)
    frames=samples[:len(samples)//FFT*FFT].reshape(-1,FFT)
    return np.abs(np.fft.fftshift(np.fft.fft(frames*window,axis=1),axes=1))**2/(RATE*float(np.sum(window**2)))

def retune(radio,stream,frequency,direction):
    # SoapyRTLSDR activateStream on its active stream drains its async FIFO.
    # Keep USB streaming; repeated cancel/start cycles can stall control writes.
    for attempt in range(3):
        try:radio.setFrequency(direction,0,frequency);break
        except RuntimeError:
            if attempt==2:raise
            time.sleep(.05)
    radio.activateStream(stream)

def main():
    p=argparse.ArgumentParser();p.add_argument('--device',required=True)
    for key in ('low','high','bin','gain','ppm'):p.add_argument('--'+key,type=float,required=True)
    p.add_argument('--repeat',action='store_true');p.add_argument('--auto-gain',action='store_true');a=p.parse_args()
    import numpy as np
    import SoapySDR as S
    stopped=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stopped.set())
    radio=S.Device(a.device);stream=None
    try:
        ranges=radio.getFrequencyRange(S.SOAPY_SDR_RX,0)
        if not any(r.minimum()<=a.low and r.maximum()>=a.high for r in ranges):raise ValueError('Requested range exceeds this receiver’s SoapySDR tuning range.')
        radio.setSampleRate(S.SOAPY_SDR_RX,0,RATE);radio.setGainMode(S.SOAPY_SDR_RX,0,False);radio.setGain(S.SOAPY_SDR_RX,0,a.gain)
        if any(setting.key=='digital_agc' for setting in radio.getSettingInfo()):radio.writeSetting('digital_agc','false')
        if a.ppm:radio.setFrequencyCorrection(S.SOAPY_SDR_RX,0,a.ppm)
        centers=plan(a.low,a.high);size=math.ceil((a.high-a.low)/a.bin)
        radio.setFrequency(S.SOAPY_SDR_RX,0,centers[0]);stream=radio.setupStream(S.SOAPY_SDR_RX,S.SOAPY_SDR_CF32,[0],dict(bufflen='32768',buffers='4',asyncBuffs='4'));radio.activateStream(stream)
        buffer=np.empty(16384,np.complex64);sweep=0;gain=a.gain;reset=False
        def emit(value):print(json.dumps(value,separators=(',',':'),allow_nan=False),flush=True)
        def read():
            deadline=time.monotonic()+3
            while not stopped.is_set() and time.monotonic()<deadline:
                r=radio.readStream(stream,[buffer],len(buffer),timeoutUs=300000)
                if r.ret>0:return buffer[:r.ret].copy()
                if r.ret not in (S.SOAPY_SDR_TIMEOUT,S.SOAPY_SDR_OVERFLOW):raise RuntimeError('SoapySDR read error '+str(r.ret))
            if not stopped.is_set():raise RuntimeError('Receiver returned no samples for three seconds')
            return None
        while not stopped.is_set():
            sweep+=1;retry=False
            emit(dict(kind='begin',sweep=sweep,hops=len(centers),rate=RATE,fft=FFT,gain=radio.getGain(S.SOAPY_SDR_RX,0),reset=reset))
            reset=False
            for hop,center in enumerate(centers):
                if stopped.is_set():break
                retune(radio,stream,center,S.SOAPY_SDR_RX)
                # Eight 16k reads exceed both bounded four-buffer queues (USB
                # plus Soapy), so no old-frequency samples enter the estimate.
                for _ in range(8):
                    if read() is None:break
                powers=[];clipped=total=0
                for _ in range(4):
                    samples=read()
                    if samples is None:break
                    clipped+=int(np.count_nonzero((np.abs(samples.real)>=.98)|(np.abs(samples.imag)>=.98)));total+=len(samples)
                    if len(samples)>=FFT:powers.append(fft_density(samples))
                if stopped.is_set():break
                if not powers:raise RuntimeError('No FFT samples captured')
                if a.auto_gain and clipped/max(1,total)>CLIP_LIMIT and gain>0:
                    previous=gain;gain=lower_gain(gain);radio.setGain(S.SOAPY_SDR_RX,0,gain)
                    emit(dict(kind='gain_adjust',previous=previous,gain=gain,frequency=center,time=time.time()))
                    reset=True;retry=True;break
                density=np.mean(np.concatenate(powers),axis=0)
                offset=np.fft.fftshift(np.fft.fftfreq(FFT,1/RATE));freq=center+offset
                mask=(np.abs(offset)<USABLE/2)&(np.abs(offset)>6000)&(freq>=a.low)&(freq<a.high)
                indices=((freq[mask]-a.low)/a.bin).astype(int)
                sums=np.bincount(indices,weights=density[mask],minlength=size);counts=np.bincount(indices,minlength=size)
                cells=np.flatnonzero(counts)
                values=(10*np.log10(np.maximum(sums[cells]/counts[cells],1e-18))).round(2)
                emit(dict(kind='chunk',sweep=sweep,hop=hop+1,hops=len(centers),frequency=center,time=time.time(),clipped=clipped,samples=total,indices=cells.tolist(),values=values.tolist()))
            if stopped.is_set():break
            if retry:sweep-=1;continue
            emit(dict(kind='complete',sweep=sweep,time=time.time()))
            if not a.repeat:break
    finally:
        if stream is not None:radio.deactivateStream(stream);radio.closeStream(stream)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps(dict(kind='error',error=str(exc))),flush=True);raise SystemExit(1)
