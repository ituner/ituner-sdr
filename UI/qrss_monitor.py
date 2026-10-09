"""One QRSS Kiwi connection supplies visual captures and tentative Morse text."""
import json
import os
from pathlib import Path
import time
import uuid
import numpy as np
from PIL import Image, ImageDraw
from qrss_modes import settings
from qrss_decoder import QRSSDecoder
from sstv_monitor import Session, SSTVManager, Gallery, atomic_json


class QRSSAssembler:
    def __init__(self, session, gallery):
        self.session,self.gallery=session,gallery
        self.decoder=QRSSDecoder(session.config)
        self.columns=[];self.times=[];self.key=None;self.next_publish=0
        self.stream_id=uuid.uuid4().hex
        # Bound memory even at wide spans / very slow integration.
        self.rows=min(320,len(self.decoder.frequencies))
        self.groups=np.array_split(np.arange(len(self.decoder.frequencies)),self.rows)

    def reset(self):
        self.flush()
        self.decoder.reset()
        self.stream_id=uuid.uuid4().hex

    def feed(self, pcm):
        for when,spectrum in self.decoder.feed(pcm):
            if self.key is None:
                self.key=uuid.uuid4().hex
                self.started=time.time();self.start_sample=when
            self.columns.append(np.array([np.max(spectrum[g]) for g in self.groups],dtype=np.float32))
            self.times.append(when)
            if when-self.start_sample>=self.session.config['minutes']*60:
                self.flush()
        if self.columns and time.monotonic()>=self.next_publish:
            self.publish('receiving');self.next_publish=time.monotonic()+5
        self.session.report('RECEIVING',self.decoder.auto.status['detail'] if self.decoder.auto else 'Waterfall + tentative text · one Kiwi channel')

    def publish(self, kind):
        if not self.columns:return
        c=self.session.config
        data=np.stack(self.columns,axis=1)[::-1]
        # Stable relative scale per capture; robust floor excludes narrow traces.
        floor=float(np.percentile(data,40))
        level=np.clip((data-floor)/35,0,1)
        rgb=np.stack((np.clip(3*level-1,0,1),np.clip(2*level,0,1),np.clip(3*level,0,1)),axis=2)
        im=Image.fromarray((rgb*255).astype('uint8'))
        # Keep seconds per pixel constant from the first update to rollover.
        # Stretching a few early columns across the whole plot hides keying.
        duration=max(0,self.times[-1]-self.start_sample)
        window_seconds=c['minutes']*60
        width=1600
        received_width=max(1,min(width,round(width*duration/window_seconds)))
        im=im.resize((received_width,320),Image.Resampling.BOX)
        canvas=Image.new('RGB',(width+100,390),(7,18,25));canvas.paste(im,(90,35))
        draw=ImageDraw.Draw(canvas)
        center=c['freq_khz']*1000+c['tone_hz'];half=c['span_hz']/2
        for y,hz in ((35,center+half),(195,center),(350,center-half)):
            draw.text((4,y),f'{hz/1e6:.6f}',fill='white')
        draw.text((4,15),'MHz RF',fill='white')
        draw.text((90,13),time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(self.started)),fill='white')
        draw.text((90,365),'Time ->   0 s',fill='white')
        draw.text((90+width/2-20,365),f'{window_seconds/2:g} s',fill='white')
        draw.text((width+30,365),f'{window_seconds:g} s',fill='white')
        draw.text((width-140,13),f'Received {duration:.0f} / {window_seconds:g} s',fill='white')
        if received_width<width:
            draw.line((90+received_width,35,90+received_width,354),fill=(62,106,115))
        acquisition=dict(self.decoder.auto.status) if self.decoder.auto else {}
        tracks=self.track_snapshot(self.start_sample,self.times[-1])
        if acquisition.get('state')=='locked':
            acquisition['rf_hz']=c['freq_khz']*1000+acquisition['tone_hz']
            for track in tracks:
                if not track['active']:continue
                y=35+320*(center+half-track['rf_hz'])/c['span_hz']
                draw.line((86,y,98,y),fill=(255,150,40),width=2)
                draw.text((101,y-10),track['id'],fill=(255,190,90))
            draw.text((400,13),f"AUTO · {acquisition['track_count']} signals",fill=(255,190,90))
        else:draw.line((86,195,94,195),fill=(255,150,40),width=2)
        text=self.track_text(tracks) if tracks else ''.join(char for t,char in self.decoder.morse.events if self.start_sample<=t<=self.times[-1]).strip()
        path=self.gallery.root/(self.key+'.working.png');canvas.save(path)
        item=dict(id=self.key,session_id=c['id'],receiver=c['name'],server=c['server'],
            band=c['band'],freq_khz=c['freq_khz'],tone_hz=c['tone_hz'],rf_hz=center,
            mode=c['qrss_mode'],dot_seconds=c['dot_seconds'],shift_hz=c['shift_hz'],span_hz=c['span_hz'],
            kind=kind,progress_pct=min(100,round(duration/(c['minutes']*60)*100)),
            capture_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(self.started)),
            received_at=self.started,updated_ns=time.time_ns(),has_image=True,
            duration_seconds=round(duration,1),window_seconds=window_seconds,
            width=canvas.width,height=canvas.height,
            stream_id=self.stream_id,sample_start=self.start_sample,sample_end=self.times[-1],
            acquisition=acquisition,tracks=tracks,tentative_text=text[-4000:],text_status='visual_only' if c['qrss_mode']=='VISUAL' else 'tentative')
        self.gallery.publish(path,item)
        # A slow signal can be acquired after a capture rolled over. Fill text
        # into those recent captures too, without changing their images.
        if self.decoder.auto and self.decoder.auto.tracks:
            with self.gallery.lock:
                for row in self.gallery.items:
                    if row.get('stream_id')!=self.stream_id or row['id']==self.key:continue
                    updates=self.track_snapshot(row['sample_start'],row['sample_end'])
                    # Tracks no longer in bounded acquisition history still
                    # belong to saved captures. Refresh only known IDs.
                    merged={r['id']:r for r in row.get('tracks',[]) if r['id'] not in self.decoder.auto.superseded}
                    merged.update({r['id']:r for r in updates if r['tentative_text'] or r['id'] in merged})
                    old_tracks=sorted(merged.values(),key=lambda r:r['tone_hz'],reverse=True)
                    old_text=self.track_text(old_tracks)
                    if old_tracks!=row.get('tracks',[]):
                        row.update(tracks=old_tracks,tentative_text=old_text[-4000:],updated_ns=time.time_ns())
                        atomic_json(self.gallery.root/(row['id']+'.json'),row)

    def track_snapshot(self,start,end):
        if not self.decoder.auto:return []
        rows=self.decoder.auto.snapshot(start,end)
        for row in rows:row['rf_hz']=self.session.config['freq_khz']*1000+row['tone_hz']
        return rows

    @staticmethod
    def track_text(tracks):
        # Compatibility summary also carries identity; never concatenate
        # unrelated stations into what looks like one Morse message.
        return '\n'.join(f"{r['id']} {r['rf_hz']/1e6:.6f} MHz ({r['dot_seconds']:g} s/dot): {r['tentative_text']}"
            for r in tracks if r['tentative_text'])

    def flush(self):
        if self.columns:self.publish('saved')
        self.columns=[];self.times=[];self.key=None
        # Keep Morse timing across image boundaries; reset only on audio gaps.


class QRSSSession(Session):
    receiver_label='QRSS'
    listening_message='Receiving QRSS waterfall and tentative Morse text'
    def make_assembler(self):return QRSSAssembler(self,self.queue)
    def bandpass(self):
        c=self.config
        return round(c['tone_hz']-c['span_hz']/2-50),round(c['tone_hz']+c['span_hz']/2+50)


class QRSSManager(SSTVManager):
    def __init__(self, kiwi, user, root=None):
        self.root = Path(root or os.environ.get('ITUNER_QRSS_DIR', '~/.local/share/ituner-sdr/qrss')).expanduser()
        self.gallery = Gallery(self.root/'images')
        # Recover interrupted live strips as saved; no phantom reception on boot.
        with self.gallery.lock:
            for row in self.gallery.items:
                if row['kind'] == 'receiving':
                    row['kind'] = 'saved'
                    atomic_json(self.gallery.root/(row['id']+'.json'),row)
        self.config_path = self.root/'sessions.json'
        self.kiwi, self.user = kiwi, user
        self.configs, self.sessions = [], {}
        self.web = None
        self.web_port = 8073
        self.web_error = ''
        self.next_start = time.monotonic()+40
        try:
            for config in json.loads(self.config_path.read_text())[:6]:
                self.validate(config)
                config.update(settings(config, config))
                if not any(r['id']==config['id'] for r in self.configs):
                    self.configs.append(config)
        except (OSError, ValueError, TypeError, KeyError):
            pass

    @staticmethod
    def validate(config):
        SSTVManager.validate(config)
        if config['mode'] != 'usb':
            raise ValueError('QRSS presets use USB')
        settings(config, config)

    def ensure_web(self):
        pass  # Hosted by SSTV's existing shared HTTP server.

    def add(self, name, server, preset, key=None, running=True):
        if len(self.configs) >= 6:
            raise ValueError('Six QRSS receivers maximum; each shares audio between waterfall and text')
        config = dict(preset, id=key or uuid.uuid4().hex, name=name, server=server, paused=not running)
        config.update(settings(config, config))
        self.validate(config)
        self.configs.append(config)
        self.save()
        if running:
            self.start(config)
        return config['id']

    def start(self, config):
        previous = self.sessions.get(config['id'])
        if previous:
            previous.stop()
            if previous.thread:
                previous.thread.join(timeout=2)
        session = QRSSSession(config, self.kiwi, self.gallery, self.user)
        self.sessions[config['id']] = session
        session.start()

    def update(self, key, name, server, preset):
        config = next(row for row in self.configs if row['id']==key)
        updated = dict(config, **{k:v for k,v in preset.items() if k not in ('id','paused','name','server')})
        updated.update(name=name, server=server)
        updated.update(settings(preset, updated))
        self.validate(updated)
        changed = any(config.get(k)!=updated[k] for k in ('server','freq_khz','tone_hz','qrss_mode','span_hz','dot_seconds','shift_hz','minutes','reverse'))
        if changed:
            old = self.sessions.pop(key, None)
            if old:
                old.stop()
                if old.thread:
                    old.thread.join(timeout=2)
        config.update(updated)
        self.save()
        if changed and not config.get('paused'):
            self.start(config)

    def image_snapshot(self, session_id=None):
        return [dict(row, has_image=True) for row in self.gallery.snapshot(session_id)]

    def stop(self):
        for session in self.sessions.values():
            session.stop()
        for session in self.sessions.values():
            if session.thread:
                session.thread.join(timeout=3)

