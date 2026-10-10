"""Local selected-slot listening without another receiver or decoder thread work."""
import copy
import queue
import threading
import time
import numpy as np


class SlotFilter:
    def __init__(self,tone):
        from scipy.signal import butter,sosfilt
        self.filter=sosfilt
        self.sos=butter(4,[max(60,tone-150),min(5000,tone+150)],btype='bandpass',fs=12000,output='sos')
        self.zi=np.zeros((len(self.sos),2));self.fade=0

    def feed(self,pcm):
        audio=np.frombuffer(pcm,dtype='<i2').astype(np.float64)
        audio,self.zi=self.filter(self.sos,audio,zi=self.zi)
        gain=np.minimum(1,(np.arange(len(audio))+self.fade)/240)
        self.fade+=len(audio)
        return np.clip(audio*gain,-32768,32767).astype('<i2').tobytes()


class CWListener:
    def __init__(self,ui,args,state,available=lambda:True):
        self.ui,self.args,self.state,self.available=ui,args,state,available
        self.key=None;self.track=None;self.error='';self.thread=None;self.stop_event=threading.Event()
        self.queue=queue.Queue(maxsize=12);self.lock=threading.Lock()

    def snapshot(self):
        with self.lock:return dict(receiver_id=self.key,track_id=self.track,error=self.error)

    def start(self,key,track):
        self.stop()
        if not self.available():raise ValueError('Stop dual listening before listening to a CW slot')
        with self.state.lock:
            if self.state.external_audio:raise ValueError('Another tool is using the speaker; stop it first')
            self.state.external_audio=True;self.state.external_audio_sink_released=False
            self.state.external_audio_generation=getattr(self.state,'external_audio_generation',0)+1
            token=self.state.external_audio_generation
        self.stop_event=threading.Event();self.queue=queue.Queue(maxsize=12)
        with self.lock:self.key=key;self.track=track['id'];self.error=''
        self.thread=threading.Thread(target=self.run,args=(track['tone_hz'],token),name='cw-listen',daemon=True)
        self.thread.start()

    def submit(self,key,pcm):
        if key!=self.key or self.stop_event.is_set():return
        try:self.queue.put_nowait(pcm)
        except queue.Full:
            try:self.queue.get_nowait()
            except queue.Empty:pass
            try:self.queue.put_nowait(pcm)
            except queue.Full:pass

    def stop(self,key=None):
        if key is not None and key!=self.key:return
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)
        if self.thread and self.thread.is_alive():raise ValueError('Audio is still stopping; retry shortly')
        self.thread=None

    def run(self,tone,token):
        player=None
        try:
            deadline=time.monotonic()+3
            while not self.stop_event.is_set() and not self.state.external_audio_sink_released_snapshot():
                if time.monotonic()>deadline:raise RuntimeError('Audio output did not become available')
                self.stop_event.wait(.05)
            if self.stop_event.is_set():return
            args=copy.copy(self.args);args.audio_rate=12000
            # Opening PipeWire must not restore an old launch-time volume.
            args.output_volume=None
            player=self.ui.BufferedAudioPlayer(args,1,state=self.state)
            filt=SlotFilter(tone);last=time.monotonic()
            while not self.stop_event.is_set():
                with self.state.lock:
                    if not self.state.external_audio or self.state.external_audio_generation!=token:break
                try:pcm=self.queue.get(timeout=.1)
                except queue.Empty:
                    if time.monotonic()-last>3:raise RuntimeError('CW audio stopped; normal listening restored')
                    continue
                last=time.monotonic();pcm=filt.feed(pcm)
                controls,_=self.state.audio_controls_snapshot()
                muted=bool(controls.get('mute'))
                player.submit(bytes(len(pcm)) if muted else pcm,silence=muted)
        except Exception as exc:
            with self.lock:self.error=str(exc)[:120]
        finally:
            try:
                if player:self.ui.stop_audio_player(player)
            finally:
                with self.state.lock:
                    if self.state.external_audio_generation==token:
                        self.state.external_audio=False;self.state.external_audio_sink_released=True
                with self.lock:self.key=None;self.track=None
