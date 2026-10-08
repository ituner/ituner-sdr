"""Independent SSTV receiver sessions, durable gallery and LAN web access."""
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import secrets
from digital_web import ControlError
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit, parse_qs
import uuid
import wave

# Analog SSTV dial frequencies, not the audio tone frequencies. See docs/sstv.md.
PRESETS = (
    ('160 m', 1890.0, 'lsb'), ('80 m', 3730.0, 'lsb'),
    ('40 m EU', 7165.0, 'lsb'), ('40 m US', 7171.0, 'lsb'),
    ('20 m', 14230.0, 'usb'), ('20 m alt', 14240.0, 'usb'),
    ('17 m', 18117.0, 'usb'), ('15 m', 21340.0, 'usb'),
    ('12 m', 24940.0, 'usb'), ('10 m', 28680.0, 'usb'),
)
MAX_SESSIONS = 6
GALLERY_LIMIT = 300
RATE = 12000


def image_snapshot(gallery, sessions, session_id=None):
    """Merge transient captures with saved previews without duplicate tiles."""
    saved = {item['id']: dict(item, has_image=True) for item in gallery.snapshot(session_id)}
    live = []
    for session in sessions:
        if session_id and session['id'] != session_id:
            continue
        for capture in session.get('in_progress', []):
            previous = saved.pop(capture['id'], {})
            live.append(dict(previous, **capture, has_image=bool(previous)))
    live.sort(key=lambda item: item['capture_utc'], reverse=True)
    return live + list(saved.values())


def atomic_json(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


class Gallery:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.items = []
        for path in self.root.glob('*.json'):
            try:
                item = json.loads(path.read_text())
                if not isinstance(item.get('capture_utc'), str) or not isinstance(item.get('session_id'), str):
                    continue
                if self.image_path(item.get('id', '')).is_file():
                    self.items.append(item)
            except (ValueError, OSError, TypeError, AttributeError):
                continue
        self.items.sort(key=lambda item: item.get('capture_utc', ''), reverse=True)
        self._prune()

    def image_path(self, key):
        if len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid image id')
        return self.root / (key + '.png')

    def _prune(self):
        for item in self.items[GALLERY_LIMIT:]:
            self.image_path(item['id']).unlink(missing_ok=True)
            (self.root / (item['id'] + '.json')).unlink(missing_ok=True)
        self.items = self.items[:GALLERY_LIMIT]

    def publish(self, png, item):
        with self.lock:
            # Same capture id is updated from partial to full, never duplicated.
            png.replace(self.image_path(item['id']))
            atomic_json(self.root / (item['id'] + '.json'), item)
            self.items = [old for old in self.items if old['id'] != item['id']]
            self.items.insert(0, dict(item))
            self.items.sort(key=lambda row: row['capture_utc'], reverse=True)
            self._prune()

    def snapshot(self, session_id=None):
        with self.lock:
            return [dict(item) for item in self.items if not session_id or item['session_id'] == session_id]


class DecodeQueue:
    """One expensive decoder at a time; newest partial replaces older partials."""
    def __init__(self, gallery):
        self.gallery = gallery
        self.condition = threading.Condition()
        self.pending = OrderedDict()
        self.stopping = False
        self.process = None
        self.thread = threading.Thread(target=self.run, name='sstv-images', daemon=True)
        self.thread.start()

    def submit(self, session, pcm, meta):
        with self.condition:
            key = meta['id']
            if key not in self.pending and len(self.pending) >= 12:
                partial = next((k for k, job in self.pending.items() if job[2]['kind'] == 'partial'), None)
                if meta['kind'] == 'full' and partial is not None:
                    del self.pending[partial]
                else:
                    session.note('Image queue full; this decode was skipped')
                    if meta['kind'] == 'full':
                        session.finish_capture(meta['id'])
                    return
            self.pending[key] = (session, pcm, dict(meta))
            self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopping or self.pending)
                if self.stopping:
                    return
                key = next((k for k, job in self.pending.items() if job[2]['kind'] == 'full'), next(iter(self.pending)))
                session, pcm, meta = self.pending.pop(key)
            if session.stop_event.is_set():
                continue
            try:
                with tempfile.TemporaryDirectory(prefix='sstv-', dir=self.gallery.root) as tmp:
                    wav, png = Path(tmp)/'audio.wav', Path(tmp)/'image.png'
                    with wave.open(str(wav), 'wb') as out:
                        out.setnchannels(1)
                        out.setsampwidth(2)
                        out.setframerate(RATE)
                        out.writeframes(pcm)
                    self.process = subprocess.Popen([
                        sys.executable, str(Path(__file__).with_name('sstv_decoder.py')),
                        str(wav), str(png), str(meta['progress_pct']),
                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    deadline = time.monotonic() + 90
                    while self.process.poll() is None:
                        if self.stopping or session.stop_event.is_set() or time.monotonic() > deadline:
                            self.process.kill()
                            self.process.communicate()
                            raise RuntimeError('Decode stopped or timed out')
                        time.sleep(.1)
                    output, error = self.process.communicate()
                    result = json.loads(output)
                    if self.process.returncode:
                        raise RuntimeError(result.get('error') or error[-120:])
                    if session.stop_event.is_set():
                        continue
                    item = {**meta, **result, 'session_id': session.config['id'],
                            'band': session.config['band'], 'freq_khz': session.config['freq_khz'],
                            'receiver': session.config['name'], 'server': session.config['server'],
                            'sideband': session.config['mode'], 'updated_ns': time.time_ns()}
                    self.gallery.publish(png, item)
                    session.note(f"Saved {meta['mode']} · {meta['progress_pct']}%")
                    if meta['kind'] == 'full':
                        session.finish_capture(meta['id'])
            except Exception as exc:
                if not session.stop_event.is_set():
                    session.note(str(exc)[:120])
                if meta['kind'] == 'full':
                    session.finish_capture(meta['id'])
            finally:
                self.process = None

    def stop(self):
        with self.condition:
            self.stopping = True
            self.pending.clear()
            self.condition.notify()
        self.thread.join(timeout=3)


class Session:
    def __init__(self, config, kiwi, queue, user):
        self.config, self.kiwi, self.queue, self.user = dict(config), kiwi, queue, user
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.status, self.detail, self.last_decode = 'QUEUED', '', ''
        self.thread = None
        self.ws = None
        self.capture_times = {}
        self.captures = {}

    def report(self, status, detail=''):
        with self.lock:
            self.status, self.detail = status, detail

    def note(self, text):
        with self.lock:
            self.last_decode = text

    def snapshot(self):
        with self.lock:
            return dict(self.config, status=self.status, detail=self.detail, last_decode=self.last_decode,
                        in_progress=[dict(item) for item in self.captures.values()])

    def progress(self, meta):
        with self.lock:
            if meta is None:
                self.captures = {key: item for key, item in self.captures.items() if item['kind'] == 'processing'}
                return
            if self.stop_event.is_set():
                return
            key = meta['id']
            if key not in self.capture_times:
                self.capture_times[key] = time.strftime('%Y-%m-%dT%H:%M:%SZ',
                    time.gmtime(time.time()-meta['elapsed_seconds']))
            self.captures[key] = dict(meta, capture_utc=self.capture_times[key],
                session_id=self.config['id'], receiver=self.config['name'], server=self.config['server'],
                band=self.config['band'], freq_khz=self.config['freq_khz'], sideband=self.config['mode'])

    def finish_capture(self, key):
        with self.lock:
            self.captures.pop(key, None)

    def start(self):
        self.thread = threading.Thread(target=self.run, name='sstv-'+self.config['id'], daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            self.captures.clear()
        # Closing the socket also interrupts startup/read timeouts.
        if self.ws:
            try:
                self.ws.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.report('STOPPED')

    def emit(self, pcm, meta):
        key = meta['id']
        if key not in self.capture_times:
            self.capture_times[key] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time()-len(pcm)/(RATE*2)))
        meta['capture_utc'] = self.capture_times[key]
        self.queue.submit(self, pcm, meta)
        if meta['kind'] == 'full':
            self.capture_times.pop(key, None)

    receiver_label = 'SSTV'
    listening_message = 'Waiting for an SSTV header'

    def make_assembler(self):
        from sstv_decoder import FrameAssembler
        return FrameAssembler(self.emit, self.report, self.progress)

    def bandpass(self):
        return (-2700, -500) if self.config['mode'] == 'lsb' else (500, 2700)

    def run(self):
        try:
            assembler = self.make_assembler()
        except ImportError as exc:
            self.report('DEPENDENCY MISSING', str(exc))
            return
        failures = 0
        while not self.stop_event.is_set():
            ws = None
            try:
                assembler.reset()
                self.capture_times.clear()
                self.report('CONNECTING', self.config['server'])
                ws = self.kiwi.KiwiWebSocket.connect(self.config['server'], 'SND', timeout=7.0,
                                                     session_timestamp=time.time_ns()//1000)
                self.ws = ws
                if self.stop_event.is_set():
                    break
                self.kiwi.send_kiwi_setup(ws, 'kiwi', self.user+'-'+self.receiver_label)
                authenticated = False
                rate_seen = False
                configured = False
                actual_rate = RATE
                last_audio = time.monotonic()
                last_keepalive = last_audio
                previous_seq = None
                while not self.stop_event.is_set():
                    now = time.monotonic()
                    if now-last_audio > 20:
                        raise RuntimeError('Audio timeout')
                    if configured and now-last_keepalive >= 5:
                        ws.send_text('SET keepalive')
                        last_keepalive = now
                    if not select.select([ws.sock], [], [], .25)[0]:
                        continue
                    message = ws.recv()
                    if message[:3] == b'MSG':
                        params = self.kiwi.parse_msg_params(message)
                        if 'badp' in params:
                            if str(params['badp']) != '0':
                                raise PermissionError('Receiver busy or password required; press Start to retry')
                            authenticated = True
                        if 'audio_rate' in params:
                            ws.send_text(f"SET AR OK in={int(float(params['audio_rate']))} out={RATE}")
                        if 'sample_rate' in params:
                            actual_rate = float(params['sample_rate'])
                            rate_seen = True
                        if authenticated and rate_seen and not configured:
                            if abs(actual_rate-RATE) > 1:
                                raise PermissionError(f'Unsupported receiver sample rate: {actual_rate:g} Hz')
                            mode = self.config['mode']
                            low, high = self.bandpass()
                            self.kiwi.send_snd_setup(ws, self.config['freq_khz'], mode, low, high,
                                {'agc': True, 'mute': False, 'nr_algo': 0, 'denoise_level': 0})
                            configured = True
                            self.report('LISTENING', self.listening_message)
                        continue
                    if not configured or message[:3] != b'SND' or len(message) < 10:
                        continue
                    flags, seq = struct.unpack('<BI', message[3:8])
                    if flags & (self.kiwi.SND_FLAG_COMPRESSED | self.kiwi.SND_FLAG_STEREO):
                        raise RuntimeError('Receiver sent incompatible PCM format')
                    pcm = message[10:]
                    if len(pcm) % 2:
                        raise RuntimeError('Malformed audio packet')
                    if previous_seq is not None and seq != (previous_seq+1) % 2**32:
                        assembler.reset()
                        self.report('LISTENING', 'Audio gap; decoder restarted')
                    previous_seq = seq
                    if not flags & self.kiwi.SND_FLAG_LITTLE_ENDIAN:
                        pcm = self.kiwi.swap_s16_bytes(pcm)
                    assembler.feed(pcm)
                    last_audio = time.monotonic()
                    failures = 0
            except PermissionError as exc:
                self.report('NO AUDIO', str(exc))
                break
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                failures += 1
                delay = min(120, 5 * 2**min(failures, 5))
                self.report('RETRY', f'{str(exc)[:65]} · retry in {delay}s')
                if self.stop_event.wait(delay):
                    break
            finally:
                try:
                    if hasattr(assembler, "flush"):
                        assembler.flush()
                except Exception as exc:
                    self.report("SAVE ERROR", str(exc)[:120])
                self.progress(None)
                self.ws = None
                if ws:
                    try:
                        ws.send_close()
                    except OSError:
                        pass
        if self.stop_event.is_set():
            self.report('STOPPED')


class SSTVManager:
    def __init__(self, kiwi, user, root=None, web_port=None):
        self.root = Path(root or os.environ.get('ITUNER_SSTV_DIR', '~/.local/share/ituner-sdr/sstv')).expanduser()
        self.gallery = Gallery(self.root / 'images')
        self.config_path = self.root/'sessions.json'
        self.kiwi, self.user = kiwi, user
        self.queue = DecodeQueue(self.gallery)
        self.configs, self.sessions = [], {}
        self.web = None
        self.web_error = ''
        self.web_port = int(web_port if web_port is not None else os.environ.get('ITUNER_SSTV_PORT', '8073'))
        try:
            saved = json.loads(self.config_path.read_text())
            for config in saved[:MAX_SESSIONS]:
                self.validate(config)
                if any(row['id'] == config['id'] for row in self.configs):
                    continue
                self.configs.append(config)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        self.next_start = time.monotonic()+35
        if self.configs or self.gallery.snapshot():
            self.ensure_web()

    @staticmethod
    def validate(config):
        if not isinstance(config, dict):
            raise ValueError('Invalid decoder')
        for field in ('id', 'name', 'server', 'band'):
            if not isinstance(config.get(field), str) or not config[field]:
                raise ValueError('Missing '+field)
        if config.get('mode') not in ('usb', 'lsb') or not 0 < float(config.get('freq_khz', 0)) <= 30000:
            raise ValueError('Choose a Kiwi frequency between 0 and 30 MHz')

    def save(self):
        atomic_json(self.config_path, self.configs)

    def add(self, name, server, preset, key=None, running=True):
        if len(self.configs) >= MAX_SESSIONS:
            raise ValueError('Six decoders maximum; delete a stopped decoder first')
        band, freq, mode = preset
        config = dict(id=key or uuid.uuid4().hex, name=name, server=server, band=band,
                      freq_khz=freq, mode=mode, paused=not running)
        self.validate(config)
        self.configs.append(config)
        self.save()
        self.ensure_web()
        if running:
            self.start(config)
        return config['id']

    def start(self, config):
        previous = self.sessions.get(config['id'])
        if previous:
            previous.stop()
        session = Session(config, self.kiwi, self.queue, self.user)
        self.sessions[config['id']] = session
        session.start()

    def update(self, key, name, server, preset):
        config = next(row for row in self.configs if row['id'] == key)
        band, freq, mode = preset
        updated = dict(config, name=name, server=server, band=band, freq_khz=freq, mode=mode)
        self.validate(updated)
        changed = any(config.get(k) != updated[k] for k in ('server', 'freq_khz', 'mode'))
        if changed:
            session = self.sessions.pop(key, None)
            if session:
                session.stop()
        config.update(updated)
        self.save()
        if changed and not config.get('paused'):
            self.start(config)

    def set_running(self, key, running):
        config = next(row for row in self.configs if row['id'] == key)
        session = self.sessions.get(key)
        live = bool(session and session.thread and session.thread.is_alive() and not session.stop_event.is_set())
        config['paused'] = not running
        if running and not live:
            self.start(config)
        elif not running and session:
            session.stop()
        self.save()

    def toggle(self, key):
        row = next(row for row in self.snapshot() if row['id'] == key)
        self.set_running(key, not row['running'])

    def delete(self, key):
        session = self.sessions.pop(key, None)
        if session:
            session.stop()
        self.configs = [row for row in self.configs if row['id'] != key]
        self.save()

    def tick(self):
        if time.monotonic() >= self.next_start:
            config = next((row for row in self.configs if not row.get('paused') and row['id'] not in self.sessions), None)
            if config:
                self.start(config)
                self.next_start = time.monotonic()+12

    def snapshot(self):
        rows = []
        for config in tuple(self.configs):
            session = self.sessions.get(config['id'])
            row = session.snapshot() if session else dict(config,
                status='STOPPED' if config.get('paused') else 'QUEUED', detail='', last_decode='')
            row.update(config)
            row['paused'] = bool(config.get('paused'))
            row['running'] = bool(not row['paused'] and (session is None or
                (session.thread and session.thread.is_alive() and not session.stop_event.is_set())))
            rows.append(row)
        return rows

    def image_snapshot(self, session_id=None):
        return image_snapshot(self.gallery, self.snapshot(), session_id)

    def ensure_web(self):
        if self.web or self.web_port < 0:
            return
        try:
            self.web = GalleryServer(self.gallery, self.snapshot,
                                     (os.environ.get('ITUNER_SSTV_BIND', '0.0.0.0'), self.web_port))
            self.web_port = self.web.server_port
            threading.Thread(target=self.web.serve_forever, name='sstv-web', daemon=True).start()
        except OSError as exc:
            self.web_error = str(exc)

    def stop(self):
        for session in self.sessions.values():
            session.stop()
        self.queue.stop()
        if self.web:
            self.web.shutdown()
            self.web.server_close()


class GalleryServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, gallery, sessions, address):
        self.gallery, self.sessions = gallery, sessions
        self.bridge = None
        self.wspr_history = None
        self.hell = None
        self.qrss = None
        self.control_token = secrets.token_urlsafe(32)
        super().__init__(address, GalleryHandler)


class GalleryHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path)
        try:
            if path.path in ('/', '/sstv', '/sstv/'):
                data = Path(__file__).with_name('sstv_gallery.html').read_bytes()
                content_type = 'text/html; charset=utf-8'
            elif path.path in ('/qrss','/qrss/'):
                data = Path(__file__).with_name('qrss_gallery.html').read_bytes()
                content_type = 'text/html; charset=utf-8'
            elif path.path.startswith('/qrss-images/') and path.path.endswith('.png'):
                if self.server.qrss is None:
                    self.send_error(503)
                    return
                data = self.server.qrss.gallery.image_path(path.path[13:-4]).read_bytes()
                content_type = 'image/png'
            elif path.path == '/api/qrss':
                if self.server.qrss is None or self.server.bridge is None:
                    self.send_error(503)
                    return
                state = dict(images=self.server.qrss.image_snapshot(),decoders=self.server.bridge.snapshot('qrss')['decoders'],control_token=self.server.control_token)
                data = json.dumps(state).encode()
                content_type = 'application/json'
            elif path.path in ('/hell', '/hell/'):
                data = Path(__file__).with_name('hell_gallery.html').read_bytes()
                content_type = 'text/html; charset=utf-8'
            elif path.path.startswith('/hell-images/') and path.path.endswith('.png'):
                if self.server.hell is None:
                    self.send_error(503)
                    return
                data = self.server.hell.gallery.image_path(path.path[13:-4]).read_bytes()
                content_type = 'image/png'
            elif path.path in ('/api/hell', '/api/hell/reporting'):
                if self.server.hell is None:
                    self.send_error(503)
                    return
                if path.path.endswith('/reporting'):
                    state = self.server.hell.reporter.snapshot()
                else:
                    if self.server.bridge is None:
                        self.send_error(503)
                        return
                    state = dict(images=self.server.hell.image_snapshot(), decoders=self.server.bridge.snapshot('hell')['decoders'])
                state['control_token'] = self.server.control_token
                data = json.dumps(state).encode()
                content_type = 'application/json'
            elif path.path in ('/wspr', '/wspr/'):
                data = Path(__file__).with_name('wspr_gallery.html').read_bytes()
                content_type = 'text/html; charset=utf-8'
            elif path.path in ('/digital-controls.js', '/wspr-history.js'):
                data = Path(__file__).with_name('digital_controls.js' if path.path == '/digital-controls.js' else 'wspr_history.js').read_bytes()
                content_type = 'text/javascript; charset=utf-8'
            elif path.path == '/api/digital/options':
                if self.server.bridge is None:
                    self.send_error(503)
                    return
                data = json.dumps(self.server.bridge.options_snapshot()).encode()
                content_type = 'application/json'
            elif path.path in ('/api/wspr/history', '/api/wspr/history.csv', '/api/wspr/reporting'):
                history = self.server.wspr_history
                if history is None:
                    self.send_error(503)
                    return
                if path.path == '/api/wspr/reporting':
                    data = json.dumps({'sources': history.sources(), 'control_token': self.server.control_token}).encode()
                else:
                    filters = {k:v[0] for k,v in parse_qs(path.query).items() if k in ('source','band','scope','run','since','until','offset','limit')}
                    if path.path.endswith('.csv'):
                        filters.pop('offset',None); filters.pop('limit',None)
                        # Freeze the displayed time window; the CSV iterator also
                        # excludes rows inserted after its snapshot began.
                        filters.setdefault('until', time.time()+1)
                        history.query(**filters, limit=1)
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/csv; charset=utf-8')
                        self.send_header('Content-Disposition', 'attachment; filename="wspr-history.csv"')
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        for chunk in history.csv(**filters):
                            self.wfile.write(chunk)
                        return
                    data = json.dumps(history.query(**filters)).encode()
                content_type = 'application/json'
            elif path.path == '/api/wspr':
                if self.server.bridge is None:
                    self.send_error(503)
                    return
                state = self.server.bridge.snapshot('wspr')
                state['control_token'] = self.server.control_token
                data = json.dumps(state).encode()
                content_type = 'application/json'
            elif path.path == '/api/sstv':
                session = parse_qs(path.query).get('session', [None])[0]
                decoders = (self.server.bridge.snapshot('sstv')['decoders']
                            if self.server.bridge else self.server.sessions())
                data = json.dumps({'images': image_snapshot(self.server.gallery, decoders, session),
                                   'decoders': decoders,
                                   'control_token': self.server.control_token if self.server.bridge else None}).encode()
                content_type = 'application/json'
            elif path.path.startswith('/images/') and path.path.endswith('.png'):
                data = self.server.gallery.image_path(path.path[8:-4]).read_bytes()
                content_type = 'image/png'
            else:
                self.send_error(404)
                return
        except (OSError, ValueError):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            path = urlsplit(self.path).path
            if path not in ('/api/sstv/control', '/api/wspr/control', '/api/wspr/reporting', '/api/hell/control', '/api/hell/reporting', '/api/qrss/control'):
                raise ControlError(404, 'Unknown control endpoint')
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                raise ControlError(403, 'Use the controls on this SDR page')
            token = self.headers.get('X-SDR-Control', '')
            if not secrets.compare_digest(token, self.server.control_token):
                raise ControlError(403, 'Refresh the page before using controls')
            if self.headers.get_content_type() != 'application/json':
                raise ControlError(415, 'Expected JSON')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise ControlError(400, 'Invalid request length')
            if not 0 < length <= 2048:
                raise ControlError(413, 'Invalid request size')
            self.connection.settimeout(5)
            try:
                payload = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError, OSError):
                raise ControlError(400, 'Invalid JSON')
            if not isinstance(payload, dict):
                raise ControlError(400, 'Invalid control request')
            if self.server.bridge is None:
                raise ControlError(503, 'Receiver controls unavailable')
            if path == '/api/hell/reporting':
                if self.server.hell is None:
                    raise ControlError(503, 'Hell reporting unavailable')
                try:
                    reporter = self.server.hell.reporter
                    result = reporter.cancel(payload.get('id')) if payload.get('action')=='cancel' else reporter.submit(payload)
                except (ValueError, TypeError) as exc:
                    raise ControlError(400, str(exc))
            elif path == '/api/wspr/reporting':
                if self.server.wspr_history is None:
                    raise ControlError(503, 'History unavailable')
                try:
                    result = self.server.wspr_history.configure(payload.get('source'), payload.get('call',''),
                        payload.get('grid',''), payload.get('enabled',False), payload.get('confirmed',False))
                except (ValueError, TypeError) as exc:
                    raise ControlError(400, str(exc))
            else:
                result = self.server.bridge.request(path.split('/')[2], payload.get('id'), payload.get('action'), config=payload.get('config'))
            status = 200
        except ControlError as exc:
            status, result = exc.status, {'error': str(exc)}
        data = json.dumps(result).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)
