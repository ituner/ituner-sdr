"""Hell receiver sessions, saved raster strips, and shared digital web gallery."""
import json
import os
from pathlib import Path
import threading
import time
import uuid
from hell_modes import MODES, settings
from sstv_monitor import Gallery, Session, SSTVManager


class StripAssembler:
    def __init__(self, session, gallery):
        from hell_decoder import HellDecoder
        self.session, self.gallery = session, gallery
        config = session.config
        self.decoder = HellDecoder(config['hell_mode'], config['tone_hz'], config['reverse'])
        self.parts = []
        self.columns = 0
        self.key = None
        self.next_publish = 0

    def reset(self):
        self.flush()
        self.decoder.reset()

    def feed(self, pcm):
        columns = self.decoder.feed(pcm)
        if not columns.shape[1]:
            return
        if self.key is None:
            self.key = uuid.uuid4().hex
            self.started = time.time()
        self.parts.append(columns)
        self.columns += columns.shape[1]
        self.session.report('RECEIVING', f"{MODES[self.session.config['hell_mode']]['label']} · {self.session.config['tone_hz']:g} Hz audio · {self.decoder.level:.0f} dBFS")
        now = time.monotonic()
        if self.columns >= min(768, 30*self.decoder.spec['columns']):
            self.flush()
        elif now >= self.next_publish:
            self.publish('receiving')
            self.next_publish = now+2

    def publish(self, kind):
        if not self.columns:
            return
        import numpy as np
        from PIL import Image
        config = self.session.config
        array = np.concatenate(self.parts, axis=1)
        image = Image.fromarray(array)
        # Compensate 2x vertical raster oversampling for readable aspect ratio.
        image = image.resize((array.shape[1]*4, array.shape[0]*2), Image.Resampling.NEAREST)
        path = self.gallery.root/(self.key+'.working.png')
        image.save(path)
        item = dict(id=self.key, session_id=config['id'], receiver=config['name'], server=config['server'],
                    band=config['band'], freq_khz=config['freq_khz'], tone_hz=config['tone_hz'],
                    rf_hz=round(config['freq_khz']*1000+config['tone_hz']), mode=config['hell_mode'],
                    sideband='usb', reverse=config['reverse'], kind=kind, progress_pct=0,
                    capture_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.started)),
                    received_at=self.started, updated_ns=time.time_ns(), has_image=True,
                    duration_seconds=round(self.columns/self.decoder.spec['columns'],1),
                    width=image.width, height=image.height)
        self.gallery.publish(path, item)
        self.session.note('Live raster · read callsigns visually; noise is also displayed')

    def flush(self):
        if self.columns:
            self.publish('saved')
        self.parts, self.columns, self.key = [], 0, None


class HellSession(Session):
    receiver_label = 'Hell'
    listening_message = 'Receiving a live Hell raster (no automatic text recognition)'

    def make_assembler(self):
        return StripAssembler(self, self.queue)

    def bandpass(self):
        half = MODES[self.config['hell_mode']]['bandwidth']/2
        center = self.config['tone_hz']
        return round(center-half-70), round(center+half+70)


class HellManager(SSTVManager):
    def __init__(self, kiwi, user, root=None):
        self.root = Path(root or os.environ.get('ITUNER_HELL_DIR', '~/.local/share/ituner-sdr/hell')).expanduser()
        self.gallery = Gallery(self.root/'images')
        # Recover interrupted live strips as saved; no phantom reception on boot.
        with self.gallery.lock:
            for row in self.gallery.items:
                row['kind'] = 'saved'
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
                if not any(r['id']==config['id'] for r in self.configs):
                    self.configs.append(config)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        from hell_reporting import HellReporter
        self.reporter = HellReporter(self.root/'reports.json', self.gallery)

    @staticmethod
    def validate(config):
        SSTVManager.validate(config)
        if config['mode'] != 'usb':
            raise ValueError('Hell presets use USB')
        settings(config, config)

    def ensure_web(self):
        pass  # Hosted by SSTV's existing shared HTTP server.

    def add(self, name, server, preset, key=None, running=True):
        if len(self.configs) >= 6:
            raise ValueError('Six Hell decoders maximum; remove an unused decoder')
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
        session = HellSession(config, self.kiwi, self.gallery, self.user)
        self.sessions[config['id']] = session
        session.start()

    def update(self, key, name, server, preset):
        config = next(row for row in self.configs if row['id']==key)
        updated = dict(config, **{k:v for k,v in preset.items() if k not in ('id','paused','name','server')})
        updated.update(name=name, server=server)
        updated.update(settings(updated, updated))
        self.validate(updated)
        changed = any(config.get(k)!=updated[k] for k in ('server','freq_khz','tone_hz','hell_mode','reverse'))
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
        self.reporter.close()
