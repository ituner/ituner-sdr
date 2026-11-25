"""Bounded USB signal search over the receiver's existing FFT frames.

No extra SDR handle, thread, FFT, or background work while idle. Thresholds
identify signal candidates, not confirmed stations or intelligible audio.
"""
import time
import numpy as np


def candidates(power, center, span, mode):
    power=np.asarray(power);n=len(power)
    if n<32:return []
    spacing=span/n;noise=float(np.percentile(power,35))
    if mode=='WFM':
        # Require energy across a channel; a tall single-bin spur is not FM.
        width=max(3,int(100/spacing))
        score=np.convolve((power>noise+6).astype(float),np.ones(width)/width,'same')
        eligible=score>.65
    else:
        score=power-noise;eligible=score>12
    edge=max(2,int((75 if mode=='WFM' else 5)/spacing))
    eligible[:edge]=False;eligible[-edge:]=False
    # Suppress the converter's DC bin, never neighbouring real RF signals.
    if mode!='WFM':eligible[n//2-1:n//2+2]=False
    indices=np.flatnonzero(eligible)
    if not len(indices):return []
    groups=np.split(indices,np.flatnonzero(np.diff(indices)>1)+1)
    result=[]
    for group in groups:
        index=int(round(float(np.mean(group)))) if mode=='WFM' else int(group[np.argmax(score[group])])
        frequency=center+(index-n//2)*spacing
        if mode=='WFM':frequency=round(frequency/100)*100.
        if not result or abs(result[-1]-frequency)>(100 if mode=='WFM' else 3):result.append(frequency)
    return result


def ranked_candidates(power, center, span, mode):
    """Rank channel energy above local noise, not the tallest single FFT bin."""
    power=np.asarray(power);noise=float(np.percentile(power,35))
    frequencies=center+(np.arange(len(power))-len(power)//2)*span/len(power)
    ranked=[]
    for frequency in candidates(power,center,span,mode):
        width=50 if mode=='WFM' else max(span/len(power)*2,1)
        channel=power[np.abs(frequencies-frequency)<=width]
        if not len(channel):continue
        score=float(np.median(channel) if mode=='WFM' else np.max(channel))-noise
        ranked.append((frequency,score))
    return ranked


class LocalSignalSearch:
    def __init__(self,receiver,state):
        self.receiver=receiver;self.state=state;self.active=False;self.notice=None
        self.next_poll=0.;self.origin=None;self.open=False;self.catalog=None;self.clear_catalog=None
        self.pending_band=None;self.full_band=False;self.best={}
        self.silent=False;self.audio_gate=None;self.audio_target=None;self.audio_context=None
    def cancel_for_handoff(self):
        """Release local scan state without retuning the newly selected receiver."""
        self.pending_band=None
        self.active=False
        self.open=False
        self.notice=None
        self.audio_target=None
        self.audio_context=None
        self.hold_audio(False)

    def hold_audio(self,value):
        value=bool(value)
        if self.silent!=value:
            self.silent=value
            if self.audio_gate:self.audio_gate(value)
    def await_landing(self,frequency,allow=True):
        self.audio_target=(frequency,time.monotonic()+.25 if allow else None)
        self.audio_context=self.context()
    def release_landed_audio(self,now):
        if not self.silent or self.active or self.pending_band:return
        if not getattr(self.state,'external_audio_snapshot',lambda:True)() or self.receiver.snapshot()['status']!='LIVE':
            self.hold_audio(False);return
        frequency=self.state.snapshot()[1]
        if self.audio_target is None or frequency!=self.audio_target[0] or self.context()!=self.audio_context:
            self.await_landing(frequency)
        target,settled=self.audio_target
        frame=self.receiver.signal_snapshot()
        if settled is not None and frame is not None and frame[0]>=settled and now-frame[0]<1 and abs(frame[1]-target)<.001:
            self.hold_audio(False)

    def request_mode_band(self,mode):
        if self.active:self.stop(restore=False)
        self.pending_band=None;self.full_band=False
        if mode not in ('AM','WFM'):return
        low,high=(531.,1602.) if mode=='AM' else (87500.,108000.)
        ranges=getattr(getattr(self.receiver,'capabilities',None),'frequency_ranges_khz',(self.receiver.tuning_bounds(),))
        if not any(a<=low and b>=high for a,b in ranges):
            self.notice=('AM BAND' if mode=='AM' else 'FM BAND',
                         'Medium-wave AM is outside this receiver’s supported range' if mode=='AM' else 'FM broadcast band is outside this receiver’s range')
            return
        self.pending_band=(self.context(),low,high)
        self.hold_audio(True)
    def begin_band(self,low,high,now):
        self.hold_audio(True)
        self.origin=self.state.snapshot()[1];self.scan_context=self.context();self.low,self.high=low,high
        step=min(self.receiver.source_span_khz()*.6,high-low)
        self.positions=list(np.arange(low+step/2,high,step)) or [(low+high)/2]
        if self.positions[-1]+step/2<high:self.positions.append(high-step/2)
        self.full_band=True;self.best={};self.open=False;self.active=True
        self.deadline=now+60;self.next_poll=0.;self.first_window=False
        self.notice=('BAND SCAN','Scanning silently · audio starts after landing')
        self.advance(now)
    def finish_band(self):
        target=max(self.best,key=self.best.get) if self.best else (self.origin if self.low<=self.origin<=self.high else (self.low+self.high)/2)
        self.active=False;self.state.set_view(freq_khz=target)
        self.await_landing(target,allow=bool(self.best))
        self.notice=('BAND SCAN',f'Strongest signal {target/1000:.4f} MHz' if self.best else 'No qualifying station found · audio stays silent')
    def capture_band(self,frame,power):
        for frequency,score in ranked_candidates(power,frame[1],frame[2],self.scan_context[2]):
            if self.low<=frequency<=self.high:
                if self.scan_context[2]=='AM':frequency=round(frequency/9)*9.
                self.best[frequency]=max(score,self.best.get(frequency,-float('inf')))
                if self.catalog:self.catalog(frequency)

    def context(self):
        return self.receiver.source_id,self.receiver.receiver_selection,self.receiver.current_home_mode()
    def available(self):
        return self.receiver.snapshot()['status']=='LIVE' and not self.state.stream_paused_snapshot()
    def pop_notice(self):
        result=self.notice;self.notice=None;return result
    def stop(self,message='Scan stopped',restore=True):
        if self.active and restore:self.state.set_view(freq_khz=self.origin)
        self.active=False;self.notice=('USB SCAN',message)
        if self.silent:self.await_landing(self.state.snapshot()[1])
    def tune(self,center,span,now=None):
        now=time.monotonic() if now is None else now
        if self.active:self.stop(restore=False)
        frame=self.receiver.signal_snapshot();frequency=self.state.snapshot()[1]
        if not self.available() or frame is None or now-frame[0]>1 or abs(frame[1]-frequency)>.001:
            self.notice=('USB TUNE','Waiting for a fresh signal frame');return False
        found=candidates(frame[3],frame[1],frame[2],self.receiver.current_home_mode())
        low,high=self.receiver.tuning_bounds()
        found=[f for f in found if max(low,center-span/2)<=f<=min(high,center+span/2)]
        if self.catalog:
            for f in found:self.catalog(f)
        if not found:
            self.notice=('USB TUNE','No qualifying signal in this view');return False
        target=min(found,key=lambda f:abs(f-frequency));self.state.set_view(freq_khz=target)
        self.notice=('USB TUNE',f'Signal candidate {target/1000:.4f} MHz');return True
    def toggle_scan(self,now=None):
        now=time.monotonic() if now is None else now
        if self.active:self.stop();return
        if not self.available():return
        origin=self.state.snapshot()[1];mode=self.receiver.current_home_mode()
        low,high=self.receiver.tuning_bounds();span=self.receiver.source_span_khz()
        ranges=getattr(getattr(self.receiver,'capabilities',None),'frequency_ranges_khz',((low,high),))
        if mode in ('AM','WFM'):
            low,high=(531.,1602.) if mode=='AM' else (87500.,108000.)
            if not any(a<=low and b>=high for a,b in ranges):
                self.notice=('AM SCAN UNAVAILABLE' if mode=='AM' else 'FM SCAN UNAVAILABLE',
                             f'531–1602 kHz needs HF support · RX starts at {self.receiver.tuning_bounds()[0]/1000:g} MHz' if mode=='AM' else 'FM band is outside this receiver’s range');return
        else:
            low,high=next(((a,b) for a,b in ranges if a<=origin<=b),(low,high))
            low,high=max(low,origin-2*span),min(high,origin+2*span)
        if high<=low:return
        if self.clear_catalog:self.clear_catalog()
        self.pending_band=None;self.begin_band(low,high,now);self.open=True
        self.notice=('USB SCAN',f'{low/1000:.3f}–{high/1000:.3f} MHz · collecting all signals')
    def advance(self,now):
        if not self.positions:
            if self.full_band:self.finish_band()
            else:self.stop('No further signal found')
            return
        self.target=float(self.positions.pop(0));self.state.set_view(freq_khz=self.target)
        self.generation=self.state.snapshot()[4];self.settled_at=now+.15
        self.frames=[];self.last_stamp=-1;self.window_deadline=now+2
    def poll(self,now=None,allowed=True):
        now=time.monotonic() if now is None else now
        self.release_landed_audio(now)
        if self.pending_band:
            context,low,high=self.pending_band
            if context!=self.context():self.pending_band=None
            elif allowed and self.available():
                self.pending_band=None;self.begin_band(low,high,now)
        if not self.active:return
        snapshot=self.state.snapshot()
        if self.context()!=self.scan_context or snapshot[4]!=self.generation:
            self.stop(restore=False);return
        if not allowed or not self.available():self.stop();return
        if now>self.deadline:self.stop('Scan timed out');return
        if now<self.next_poll:return
        self.next_poll=now+.07
        frame=self.receiver.signal_snapshot()
        if frame is None or frame[0]<self.settled_at or frame[0]<=self.last_stamp or abs(frame[1]-self.target)>.001:
            if now>self.window_deadline:self.stop('No fresh USB signal data')
            return
        self.last_stamp=frame[0];self.frames.append(frame[3])
        if len(self.frames)<3:return
        power=np.mean(self.frames,axis=0)
        self.capture_band(frame,power);self.advance(now)
