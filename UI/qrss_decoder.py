"""QRSS spectrogram and experimental timed Morse receiver. GPL-3.0-or-later.

The overlapping periodic-Hann FFT pipeline is adapted from QrssPiG's
QGProcessor.cpp by Martin Herren / HB9FXX (commit 19bb36425053e0d179ddd9a309ed9b169f5858d8).
https://gitlab.com/hb9fxx/qrsspig ; licenses/qrsspig-GPL-3.txt.
Acquisition, rendering and the tentative Morse tracker are iTuner adaptations.
This is an integrated NumPy implementation, not the QrssPiG executable.
"""
from collections import deque
import numpy as np

RATE=12000
CODES=dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/',
    '.- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. ----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----. -..-.'.split()))
MORSE={code:letter for letter,code in CODES.items()}


class MorseTiming:
    """Fixed slow dot timing, tolerant edges; no guessed callsign correction."""
    def __init__(self,dot):
        self.dot=dot
        self.events=deque(maxlen=2000)
        self.reset()

    def reset(self):
        self.mark=False;self.since=None;self.pattern='';self.emitted=False;self.spaced=False
        self.blocked=False

    def emit(self,when):
        if self.pattern:
            self.events.append((when,MORSE.get(self.pattern,'?')))
        self.pattern='';self.emitted=True

    def feed(self,mark,when):
        if mark is None:
            self.reset()  # Lost FSK carrier: do not invent a space/letter.
            return
        if self.since is None:
            self.since=when;self.mark=mark;self.blocked=bool(mark)
            return  # Starting mid-mark must not invent its missing beginning.
        duration=when-self.since
        if mark!=self.mark:
            if self.mark:
                if not self.blocked and .4*self.dot <= duration <= 4.6*self.dot:
                    self.pattern+='.' if duration<2*self.dot else '-'
                    if len(self.pattern)>6:self.pattern='';self.blocked=True
                else:self.pattern=''
                self.emitted=False;self.spaced=False
            self.since=when;self.mark=mark;self.blocked=False
        elif not mark:
            if duration>=2*self.dot and not self.emitted:self.emit(when)
            if duration>=5*self.dot and not self.spaced:
                if self.events and self.events[-1][1]!=' ':self.events.append((when,' '))
                self.spaced=True
        elif duration>4.6*self.dot:
            self.pattern='';self.blocked=True


class QRSSDecoder:
    def __init__(self,config):
        self.config=config
        dot=3 if config['qrss_mode']=='AUTO' else config['dot_seconds']
        # <= half a dot of integration: slow traces remain spectrally narrow
        # without smearing adjacent Morse elements into one continuous line.
        self.n=2**int(np.floor(np.log2(RATE*dot/2)))
        self.hop=self.n//4
        self.window=.5*(1-np.cos(2*np.pi*np.arange(self.n)/self.n))
        frequencies=np.fft.rfftfreq(self.n,1/RATE)
        center,half=config['tone_hz'],config['span_hz']/2
        self.mask=(frequencies>=center-half)&(frequencies<=center+half)
        self.frequencies=frequencies[self.mask]
        self.df=RATE/self.n
        self.mark_mask=abs(self.frequencies-center)<=self.df
        self.space_mask=abs(self.frequencies-(center-config['shift_hz']))<=self.df
        if config['reverse'] and config['qrss_mode']=='FSKCW':self.mark_mask,self.space_mask=self.space_mask,self.mark_mask
        self.morse=MorseTiming(dot)
        self.auto=None
        if config['qrss_mode']=='AUTO':
            from qrss_acquisition import AutoAcquisition
            self.auto=AutoAcquisition(self.frequencies,MorseTiming,self.hop/RATE)
        self.reset()

    def reset(self):
        self.buffer=np.empty(0)
        self.samples=0;self.on=False
        self.morse.reset()
        self.morse.events.clear()
        if self.auto:self.auto.reset()

    def feed(self,pcm):
        self.buffer=np.concatenate((self.buffer,np.frombuffer(pcm,'<i2').astype(float)/32768))
        frames=[]
        while len(self.buffer)>=self.n:
            spectrum=np.abs(np.fft.rfft(self.buffer[:self.n]*self.window))**2
            spectrum=spectrum[self.mask]/max(1,self.window.sum()**2)
            # Median of the displayed band is a robust local noise estimate;
            # this is not a calibrated receiver SNR or a reported spot SNR.
            floor=max(1e-18,float(np.median(spectrum)))
            mark=max(1e-18,float(np.max(spectrum[self.mark_mask])))
            space=max(1e-18,float(np.max(spectrum[self.space_mask])))
            snr=10*np.log10(mark/floor)
            when=(self.samples+self.n/2)/RATE
            kind=self.config['qrss_mode']
            if kind=='CW':
                self.on=snr>=(9 if self.on else 12)
                self.morse.feed(self.on,when)
            elif kind=='FSKCW':
                if max(mark,space)/floor<4:
                    self.morse.feed(None,when)
                else:
                    ratio=10*np.log10(mark/space)
                    if ratio>2:self.on=True
                    elif ratio<-2:self.on=False
                    self.morse.feed(self.on,when)
            db=10*np.log10(np.maximum(spectrum,1e-18))
            if self.auto:
                self.auto.feed(when,db)
                self.morse.events=self.auto.events
            frames.append((when,db))
            self.buffer=self.buffer[self.hop:]
            self.samples+=self.hop
        return frames
