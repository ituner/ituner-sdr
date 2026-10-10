"""Bounded live CW rows, paired Kiwi W/F transport and continuous audio fallback.

Kiwi wire layout follows jks-prv/Beagle_SDR_GPS web/openwebrx/openwebrx.js:
the header carries the actual starting bin and zoom, not the requested center.
"""
import base64
from collections import deque
import select
import socket
import struct
import threading
import time
import uuid
import numpy as np

WIDTH, HEIGHT, FPS = 1024, 240, 20
RATE, FFT, HOP = 12000, 4096, 600


def rgba(row):
    v=np.asarray(row,dtype=np.float32)/255
    return np.uint8(np.stack((v*v*.7,v*.95,v*.8+.035,np.ones_like(v)),axis=-1)*255).tobytes()


def kiwi_row(message,dial_hz,bandwidth=30000000,offset_hz=0):
    if len(message)!=1040 or message[:3]!=b'W/F':return None
    start,flags,_=struct.unpack_from('<III',message,4)
    zoom=flags&0xffff
    if zoom!=13 or flags&65536:return None  # discard startup/old zoom rows
    left=start*bandwidth/(1024*2**14)+offset_hz
    step=bandwidth/(2**zoom*1024)
    frequencies=left+np.arange(1024)*step
    target=np.linspace(dial_hz+200,dial_hz+3200,WIDTH)
    if target[0]<left or target[-1]>frequencies[-1]:return None
    values=np.frombuffer(message,dtype=np.uint8,offset=16).astype(np.float32)
    # Kiwi uncompressed values increase with power. Relative contrast is used
    # for display only; this is not a calibrated signal strength measurement.
    floor=max(float(np.percentile(values,30)),float(values.max())-60)
    return np.uint8(np.clip(np.interp(target,frequencies,values)-floor,0,45)*255/45)


class LiveWaterfall:
    def __init__(self,clock=time.monotonic):
        self.lock=threading.RLock();self.clock=clock
        self.pending=np.empty(0,dtype=np.float32);self.window=np.hanning(FFT)
        self.frequencies=np.fft.rfftfreq(FFT,1/RATE)
        self.target=np.linspace(200,3200,WIDTH)
        self.rows=deque(maxlen=HEIGHT);self.seq=0;self.epoch=uuid.uuid4().hex
        self.source='audio';self.kiwi=None;self.kiwi_at=-1e9;self.reason='Waiting for Kiwi waterfall'

    def reset(self):
        with self.lock:
            self.pending=np.empty(0,dtype=np.float32);self.rows.clear()
            self.seq=0;self.epoch=uuid.uuid4().hex;self.kiwi=None;self.kiwi_at=-1e9;self.source='audio'

    def unavailable(self,reason):
        with self.lock:self.kiwi=None;self.kiwi_at=-1e9;self.reason=reason

    def receive(self,row):
        with self.lock:self.kiwi=np.asarray(row,dtype=np.uint8).copy();self.kiwi_at=self.clock()

    def feed(self,pcm):
        # Runs on the audio decoder thread. Always calculate the fallback, so
        # loss of hardware W/F never leaves the screen waiting for another FFT.
        self.pending=np.concatenate((self.pending,np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768))
        while len(self.pending)>=FFT:
            power=np.abs(np.fft.rfft(self.pending[:FFT]*self.window))**2
            db=10*np.log10(np.interp(self.target,self.frequencies,power)+1e-12)
            floor=max(float(np.median(db)),float(db.max())-45)
            audio=np.uint8(np.clip((db-floor)/40,0,1)*255)
            with self.lock:
                source='kiwi' if self.kiwi is not None and self.clock()-self.kiwi_at<3 else 'audio'
                if source=='audio' and self.source=='kiwi':self.reason='Kiwi stream stalled; retrying'
                if source!=self.source:
                    self.rows.clear();self.epoch=uuid.uuid4().hex;self.seq=0;self.source=source
                self.seq+=1
                self.rows.append(bytes(self.kiwi if source=='kiwi' else audio))
            self.pending=self.pending[HOP:]

    def read(self,epoch='',after=0,encoded=False):
        with self.lock:
            reset=epoch!=self.epoch or after<self.seq-len(self.rows) or after>self.seq
            count=len(self.rows) if reset else max(0,min(len(self.rows),self.seq-after))
            rows=list(self.rows)[-count:] if count else []
            result=dict(epoch=self.epoch,seq=self.seq,reset=reset,width=WIDTH,height=HEIGHT,fps=FPS,
                        source=self.source,detail=('Kiwi waterfall' if self.source=='kiwi' else 'Audio waterfall · '+self.reason),
                        rows=base64.b64encode(b''.join(rows)).decode() if encoded else rows)
            return result


class KiwiWaterfall:
    """Optional paired W/F. Its failure must never restart the audio decoder."""
    def __init__(self,session,timestamp):
        self.session=session;self.timestamp=timestamp;self.stop_event=threading.Event();self.ws=None
        self.thread=threading.Thread(target=self.run,name='cw-waterfall',daemon=True);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.ws:
            try:self.ws.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        self.thread.join(timeout=1)

    def run(self):
        s=self.session;k=s.kiwi
        while not self.stop_event.is_set():
            ws=None
            try:
                ws=k.KiwiWebSocket.connect(s.config['server'],'W/F',timeout=5,session_timestamp=self.timestamp)
                self.ws=ws
                k.send_kiwi_setup(ws,'kiwi',s.user+'-CW')
                auth=False;configured=False;bandwidth=30000000;offset_hz=0;configured_freq=None
                channel=wf_channels=None;hardware=None
                last=time.monotonic();keepalive=last;retry_at=last+30
                while not self.stop_event.is_set():
                    now=time.monotonic()
                    if configured and configured_freq!=s.config['freq_khz']:
                        k.send_wf_setup(ws,s.config['freq_khz']+1.7-offset_hz/1000,13,4)
                        configured_freq=s.config['freq_khz'];last=now
                    if not configured and now-last>8:raise RuntimeError('Kiwi waterfall handshake timed out')
                    # Closing an idle paired W/F may also close SND on Kiwi.
                    # Keep it alive while audio fallback runs; retry setup in place.
                    if configured and hardware is not False and now-last>3:
                        s.waterfall.unavailable('Kiwi waterfall unavailable; using audio')
                        if now>=retry_at:
                            k.send_wf_setup(ws,s.config['freq_khz']+1.7-offset_hz/1000,13,4)
                            retry_at=now+30
                    if now-keepalive>5:ws.send_text('SET keepalive');keepalive=now
                    if not select.select([ws.sock],[],[],.2)[0]:continue
                    message=ws.recv()
                    if message[:3]==b'MSG':
                        p=k.parse_msg_params(message)
                        if 'too_busy' in p or ('badp' in p and p['badp']!='0'):raise RuntimeError('No Kiwi waterfall slot available')
                        if 'badp' in p:auth=True
                        if 'rx_chan' in p:channel=int(p['rx_chan'])
                        if 'wf_chans' in p:wf_channels=int(p['wf_chans'])
                        if channel is not None and wf_channels is not None:
                            hardware=channel<wf_channels
                            if not hardware:s.waterfall.unavailable('No hardware waterfall on this Kiwi channel')
                        if 'bandwidth' in p:bandwidth=float(p['bandwidth'])
                        if 'freq_offset' in p:offset_hz=float(p['freq_offset'])*1000
                        if auth and not configured:
                            k.send_wf_setup(ws,s.config['freq_khz']+1.7-offset_hz/1000,13,4);configured=True;configured_freq=s.config['freq_khz']
                    elif configured and hardware is not False and message[:3]==b'W/F':
                        row=kiwi_row(message,s.config['freq_khz']*1000,bandwidth,offset_hz)
                        if row is not None:s.waterfall.receive(row);last=now
            except Exception as exc:
                s.waterfall.unavailable(str(exc)[:100])
            finally:
                self.ws=None
                if ws:
                    try:ws.send_close()
                    except OSError:pass
            if self.stop_event.wait(30):break


class WaterfallTexture:
    """GPU ring updated a row at a time, newest at the top."""
    def __init__(self,ui):
        self.ui=ui;self.epoch='';self.seq=0;self.row=0
        g=ui.GL;self.tex=g.glGenTextures(1);g.glBindTexture(g.GL_TEXTURE_2D,self.tex)
        for flag in (g.GL_TEXTURE_MIN_FILTER,g.GL_TEXTURE_MAG_FILTER):g.glTexParameteri(g.GL_TEXTURE_2D,flag,g.GL_LINEAR)
        for flag in (g.GL_TEXTURE_WRAP_S,g.GL_TEXTURE_WRAP_T):g.glTexParameteri(g.GL_TEXTURE_2D,flag,g.GL_CLAMP_TO_EDGE)
        g.glTexImage2D(g.GL_TEXTURE_2D,0,g.GL_RGBA,WIDTH,HEIGHT,0,g.GL_RGBA,g.GL_UNSIGNED_BYTE,bytes(WIDTH*HEIGHT*4))

    def draw(self,stream,box,offset=0):
        data=stream.read(self.epoch,self.seq);g=self.ui.GL;g.glBindTexture(g.GL_TEXTURE_2D,self.tex)
        if data['reset']:
            self.row=0
            g.glTexSubImage2D(g.GL_TEXTURE_2D,0,0,0,WIDTH,HEIGHT,g.GL_RGBA,g.GL_UNSIGNED_BYTE,bytes(WIDTH*HEIGHT*4))
        for row in data['rows']:
            g.glTexSubImage2D(g.GL_TEXTURE_2D,0,0,self.row,WIDTH,1,g.GL_RGBA,g.GL_UNSIGNED_BYTE,rgba(np.frombuffer(row,dtype=np.uint8)))
            self.row=(self.row+1)%HEIGHT
        self.epoch,self.seq=data['epoch'],data['seq']
        x0,y0,x1,y1=box;split=y0+(y1-y0)*self.row/HEIGHT
        width=x1-x0;left=max(x0,x0+offset);right=min(x1,x1+offset)
        if left>=right:return
        u0=(left-x0-offset)/width;u1=(right-x0-offset)/width
        x0,x1=left,right
        # Source rows arrive oldest-first; reverse only the vertical mapping.
        if self.row:self.ui.draw_textured_quad(self.tex,x0,y0,x1,split,u0,self.row/HEIGHT,u1,0)
        if self.row<HEIGHT:self.ui.draw_textured_quad(self.tex,x0,split,x1,y1,u0,1,u1,self.row/HEIGHT)

    def close(self):self.ui.GL.glDeleteTextures([self.tex])
