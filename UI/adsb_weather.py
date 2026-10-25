"""Bounded, local FIS-B products and an independent raw-stream consumer.

Weather failures never restart or claim either SDR. No Internet weather is
substituted for radio reception. The upstream decoder runs in a child process.
"""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ENGINE = Path(os.environ.get('ITUNER_FISB_ENGINE', '/opt/ituner-sdr/decoders/adsb/fisb-decode'))
RADAR_COLOURS = (None, '#28b774', '#8acb45', '#efdb45', '#ed982e', '#eb5049', '#d754d8', '#9129b9')


def epoch(value):
    try: return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError): return None


def atomic_json(path, value):
    path = Path(path); tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, separators=(',', ':')), encoding='utf-8')
    tmp.replace(path)


def radar_block(product):
    """Upstream alternate blocks: 4 north-to-south rows, 32 west-to-east bins.

    Upstream normalizes >60-degree blocks into the same 32-column grid.
    Regional zero is <5 dBZ; CONUS zero is unavailable. Seven is >=55 dBZ.
    """
    if product.get('unique_name') not in ('NEXRAD_REGIONAL', 'NEXRAD_CONUS'): return None
    scale = product.get('scale_factor'); block = product.get('alt_bn'); bins = product.get('bins')
    if scale not in (0, 1, 2) or not isinstance(block, int) or block < 0: return None
    if not isinstance(bins, str) or len(bins) != 128 or any(ord(c) > 7 for c in bins): return None
    factor = (1, 5, 9)[scale]; row, col = divmod(block, 1000)
    south = row*4*factor/60; west = col*48*factor/60
    if not 0 <= south < 90 or not 0 <= west < 360: return None
    if west >= 180: west -= 360
    return dict(product=product['unique_name'], block=block, scale=scale,
                bounds=[west, south, west+48*factor/60, south+4*factor/60],
                bins=[255 if c=='\0' and product['unique_name']=='NEXRAD_CONUS' else ord(c) for c in bins], time=epoch(product.get('observation_time')),
                expires_at=epoch(product.get('expiration_time')))


class WeatherStore:
    def __init__(self, root, live=None):
        self.root = Path(root); self.path = self.root/'weather-state.json'
        self.live = Path(live) if live else self.root/'weather-live.json'
        self.next_persist = 0
        try: saved = json.loads(self.path.read_text())
        except (OSError, ValueError): saved = {}
        if not isinstance(saved,dict): saved = {}
        self.reports = saved.get('reports', {}) if isinstance(saved.get('reports', {}),dict) else {}
        self.radar = saved.get('radar', {}) if isinstance(saved.get('radar', {}),dict) else {}
        self.stations = saved.get('stations', {}) if isinstance(saved.get('stations', {}),dict) else {}
        self.uplinks = saved.get('uplinks', 0)
        self.products = saved.get('products', 0)
        self.last_uplink_at = saved.get('last_uplink_at')
        self.errors = 0; self.last_error = ''; self.connected = False
        self.started_at = time.time(); self.session_uplinks = 0
        self.prune(time.time())

    def prune(self, now):
        # Expired products are removed; the latest reception metadata survives.
        self.reports = dict(sorted(((k,v) for k,v in self.reports.items() if v.get('expires_at', 0)>now),
                                   key=lambda kv: kv[1]['received_at'])[-500:])
        self.radar = dict(sorted(((k,v) for k,v in self.radar.items() if v.get('expires_at', 0)>now),
                                 key=lambda kv: kv[1]['received_at'])[-4096:])
        self.stations = dict(sorted(self.stations.items(), key=lambda kv: kv[1]['last_heard'])[-64:])

    def station(self, message, now, rssi=None):
        key = str(message.get('station', 'unknown'))[:80]
        row = self.stations.setdefault(key, dict(id=key, packets=0))
        row.update(last_heard=now, packets=row['packets']+1,
                   lat=message.get('latitude'), lon=message.get('longitude'),
                   position_valid=bool(message.get('position_valid')), rssi=rssi)
        self.uplinks += 1; self.session_uplinks += 1; self.last_uplink_at = now

    def ingest(self, product, now, station):
        expires = epoch(product.get('expiration_time'))
        if not expires or not now < expires <= now+8*86400: return
        kind = product.get('type', '')
        if kind.startswith('CANCEL_'):
            self.reports.pop(kind[7:]+':'+str(product.get('unique_name','')),None)
            return
        if kind == 'IMAGE':
            block = radar_block(product)
            if block is None: return
            block.update(received_at=now, station=station)
            key = f"{block['product']}:{block['scale']}:{block['block']}"
            previous = self.radar.get(key)
            if previous and (previous.get('time') or 0) > (block.get('time') or 0): return
            self.radar[key] = block
        else:
            text = product.get('contents')
            if not isinstance(text, str) or not text.strip() or len(text)>30000: return
            name = str(product.get('unique_name', ''))[:120]
            issued = next((epoch(product.get(k)) for k in ('observation_time','issued_time','report_time','valid_time') if epoch(product.get(k))), None)
            key = kind+':'+name
            if not name: key += ':'+hashlib.sha256(text.encode()).hexdigest()[:16]
            previous = self.reports.get(key)
            if previous and (previous.get('issued_at') or 0) > (issued or 0): return
            self.reports[key] = dict(type=kind, name=name, text=text, issued_at=issued,
                                     expires_at=expires, received_at=now, station=station)
        self.products += 1

    def save(self, force=False):
        self.prune(time.time())
        value=dict(now=time.time(), started_at=self.started_at, connected=self.connected,
                    reports=self.reports, radar=self.radar, stations=self.stations,
                    uplinks=self.uplinks, session_uplinks=self.session_uplinks, products=self.products,
                    last_uplink_at=self.last_uplink_at, errors=self.errors, last_error=self.last_error)
        atomic_json(self.live,value)
        if force or time.monotonic()>=self.next_persist:
            atomic_json(self.path,value);self.next_persist=time.monotonic()+30


class WeatherService:
    """Supervisor + cached snapshots; render threads never read a stream or wait."""
    def __init__(self, root, data=None):
        self.root = Path(root); self.process = None; self.port = None
        self.live = Path(data or root)/'weather-live.json'
        self.retry = 0; self.next_read = 0; self.saved = {}; self.lock = threading.Lock()
        self.enabled = False; self.receiver_running = False
        self.started_at = 0; self.failure = ''
        self.comparison_paused = False

    def stop(self):
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
        self.port = None

    def step(self, port, enabled):
        self.enabled = enabled; self.receiver_running = bool(port)
        if self.process and (self.port != port or self.process.poll() is not None):
            failed = self.process.poll() is not None
            if failed:
                try: self.failure = (self.root/'weather-worker.txt').read_text()[-800:]
                except OSError: self.failure = 'Weather worker exited'
            self.stop()
            if failed: self.retry = time.monotonic()+15
        if not port or not enabled:
            self.stop(); return
        if self.process is None and ENGINE.is_dir() and time.monotonic() >= self.retry:
            try:
                with (self.root/'weather-worker.txt').open('w') as output:
                    self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('adsb_weather_worker.py')),
                        '--port', str(port), '--root', str(self.root), '--engine', str(ENGINE), '--live', str(self.live)],
                        stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, close_fds=True)
                self.port = port
                self.started_at = time.time()
            except OSError: self.retry = time.monotonic()+15

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if time.monotonic() >= self.next_read:
                try:
                    path = self.live if self.live.exists() else self.root/'weather-state.json'
                    if path.stat().st_size <= 6*1024*1024: self.saved = json.loads(path.read_text())
                except (OSError, ValueError): pass
                self.next_read = time.monotonic()+2
            saved = self.saved
            engine = ENGINE.is_dir()
            healthy = bool(self.process and self.process.poll() is None and saved.get('started_at',0)>=self.started_at-1 and 0 <= now-saved.get('now', 0)<20 and saved.get('connected'))
            if healthy:self.failure=''
            last = saved.get('last_uplink_at')
            status = ('PAUSED FOR COMPARISON' if self.comparison_paused else 'NOT INSTALLED' if not engine else 'STOPPED' if not self.enabled else
                      'RECEIVER UNAVAILABLE' if not self.receiver_running else 'DECODER ERROR' if self.failure else 'CONNECTING' if not healthy else
                      'RECEIVING' if last and 0 <= now-last<30 else 'LISTENING')
            return dict(now=now, status=status, connected=healthy, last_uplink_at=last,
                uplinks=saved.get('uplinks', 0), session_uplinks=saved.get('session_uplinks', 0) if healthy else 0,
                errors=saved.get('errors', 0), last_error=self.failure or saved.get('last_error', ''),
                reports=sorted((v for v in saved.get('reports', {}).values() if v.get('expires_at', 0)>now), key=lambda v:v.get('issued_at') or v['received_at'], reverse=True),
                radar=[v for v in saved.get('radar', {}).values() if v.get('expires_at', 0)>now],
                stations=sorted((dict(v, live=healthy and 0<=now-v['last_heard']<30) for v in saved.get('stations', {}).values()), key=lambda v:v['last_heard'], reverse=True))
