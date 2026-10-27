"""Local 1090 MHz readsb receiver, RTL allocation, bounded logs and tar1090 HTTP."""
import ctypes
import ctypes.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from rtl_registry import same_usb_attachment
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import threading
import tempfile
import time
from urllib.parse import unquote, urlsplit, parse_qs
from station_web import station_get, station_post
from dongle_web import dongle_get, dongle_post
from dongle_notice import inject_notice, notice_post
from station_profile import distance_m
from adsb_ground import GroundMap
from adsb_aircraft import AircraftDetails
from adsb_coverage import ReceptionCoverage
from adsb_logs import LOG_FILES, read_log_tail
from adsb_globe import GlobeAssets
from adsb_traffic import BANDS, TrafficHistory, receiver_position
from adsb_uat import UATReceiver, age_aircraft, merge_aircraft
from adsb_weather import WeatherService
from adsb_compare import ReceiverComparison, readsb_command


def _read_rtl_devices():
    """Query descriptors without claiming an SDR or interrupting another decoder."""
    lib = ctypes.CDLL(ctypes.util.find_library('rtlsdr') or 'librtlsdr.so.0')
    lib.rtlsdr_get_device_count.restype = ctypes.c_uint32
    lib.rtlsdr_get_device_name.restype = ctypes.c_char_p
    rows = []
    for index in range(min(lib.rtlsdr_get_device_count(), 64)):
        buffers = [ctypes.create_string_buffer(256) for _ in range(3)]
        result = lib.rtlsdr_get_device_usb_strings(index, *buffers)
        manufacturer, product, serial = [b.value.decode('utf-8', 'replace') for b in buffers]
        rows.append(dict(index=index, name=(lib.rtlsdr_get_device_name(index) or b'RTL-SDR').decode('utf-8', 'replace'),
                         manufacturer=manufacturer, product=product, serial=serial if result == 0 else ''))
    from rtl_registry import REGISTRY, identify, usb_inventory, usb_order
    try: physical, order = usb_inventory(), usb_order()
    except OSError: physical, order = [], []
    return REGISTRY.remember(identify(rows, physical, order, REGISTRY.shared_serials()))


def rtl_devices():
    from rtl_registry import REGISTRY
    with REGISTRY.lock:
        if REGISTRY.operation and REGISTRY.operation.get('running'):
            return [dict(row) for row in REGISTRY.current_rows]
    return _read_rtl_devices()


rtl_devices.fresh = _read_rtl_devices



def aircraft_rows(payload, now=None):
    """Discard stale cached positions; never present old JSON as live reception."""
    now = time.time() if now is None else now
    stamp = float(payload.get('now', 0))
    if not 0 <= now-stamp <= 15:
        return []
    return [dict(row) for row in payload.get('aircraft', [])
            if isinstance(row, dict) and isinstance(row.get('seen'), (int, float)) and 0 <= row['seen'] < 15]


class ADSBManager:
    def __init__(self, root=None, port=None, scanner=rtl_devices, binary=None, map_root=None, broker=None, station=None):
        self.root = Path(root or Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'ituner-sdr/adsb')
        self.root.mkdir(parents=True, exist_ok=True)
        self.data = self.root/'live' if root else Path(os.environ.get('XDG_RUNTIME_DIR', tempfile.gettempdir()))/f'ituner-adsb-{os.getuid()}'
        self.data.mkdir(exist_ok=True)
        self.map_root = Path(map_root or os.environ.get('ITUNER_ADSB_MAP', '/opt/ituner-sdr/decoders/adsb/tar1090/html'))
        self.binary = binary or os.environ.get('ITUNER_READSB_BIN', '/opt/ituner-sdr/decoders/adsb/readsb')
        self.port = int(port if port is not None else os.environ.get('ITUNER_ADSB_PORT', '8090'))
        self.broker = broker
        if broker: broker.register("adsb", lambda: self.control("stop"),lambda:self.control("start"),lambda:self.enabled)
        self.scanner = scanner
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.process = None
        self.assigned = None
        self.devices = []
        self.planes = []
        self.aircraft_stamp = None
        self.status = 'STOPPED'
        self.detail = ''
        self.messages = 0
        self.next_scan = 0
        self.retry = {}
        self.started = 0
        self.started_at = None
        self.last_message_at = None
        self.last_log = -float('inf')
        self.last_payload = 0
        self.server = None
        self.token = secrets.token_urlsafe(32)
        self.aircraft_details = AircraftDetails(self.root, self.map_root)
        self.globe = GlobeAssets()
        self.ground_map = GroundMap(self.globe)
        self.weather = WeatherService(self.root,self.data)
        self.log_cache = {kind: read_log_tail(self.root, kind) for kind in LOG_FILES}
        self.next_logs = 0
        try:
            saved = json.loads((self.root/'settings.json').read_text())
        except (OSError, ValueError):
            saved = {}
        self.enabled = saved.get('enabled') is True
        self.selection = saved.get('selection', 'auto')
        try: self.position = receiver_position(saved.get('position'))
        except ValueError: self.position = None
        self.active_position = None
        self.history = TrafficHistory()
        self.history_path = self.root/'trails.json.gz'
        self.history.load(self.history_path,time.time())
        self.next_history_save = 0
        for item in self.log_cache['flights']['entries']:
            if isinstance(item.get('time'), (int,float)) and 0<=time.time()-item['time'] <= self.history.retention:
                self.history.ingest([item.get('aircraft') or {}], item['time'])
        if not isinstance(self.selection, str): self.selection = 'auto'
        self.coverage = ReceptionCoverage(self.root)
        self.coverage_error = ''
        self.station = station
        if station:station.subscribe(self._station_changed)
        self.flight_log = self._logger('flights', 10*1024*1024, 6)
        self.events = self._logger('receiver', 2*1024*1024, 3)
        self.uat = UATReceiver(self.root, self.data, broker, self._event)
        self.comparison = ReceiverComparison(self.root,self.data,self.binary,broker)
        self.last_uat_log = -float('inf')
        self.thread = threading.Thread(target=self._worker, name='adsb-receiver', daemon=True)
        self.thread.start()
        if self.port >= 0:
            try:
                self.server = ThreadingHTTPServer((os.environ.get('ITUNER_ADSB_BIND', '0.0.0.0'), self.port), ADSBHandler)
                self.server.manager = self
                self.port = self.server.server_port
                threading.Thread(target=self.server.serve_forever, name='adsb-web', daemon=True).start()
            except OSError as exc:
                self._event('map_error', detail=str(exc))
                self.detail = f'Map server unavailable: {exc}'

    def _station_changed(self, data):
        p=data['position']
        with self.lock:
            self.position=dict(lat=p['lat'],lon=p['lon']) if p else None
            height=p.get('ellipsoid_height_m') if p else None
            with self.coverage.lock:
                if self.coverage.height!=height:
                    self.coverage.height=height;self.coverage.key=None;self.coverage.requested=True
        self.wake.set()

    def _location_restart_needed(self):
        if self.position==self.active_position:return False
        # GPS motion updates maps immediately without repeatedly interrupting RF.
        # readsb's local CPR reference needs resetting only after substantial travel.
        if self.station and (self.station.snapshot()['position'] or {}).get('source')=='gps':
            return distance_m(self.active_position,self.position)>=25000
        return True

    def _logger(self, name, size, backups):
        logger = logging.Logger(f'adsb-{name}-{id(self)}')
        handler = RotatingFileHandler(self.root/(name+'.jsonl'), maxBytes=size, backupCount=backups)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        return logger

    def _event(self, event, **values):
        stamp=time.time()
        self.events.info(json.dumps(dict(time=stamp, event=event, **values)))
        if event in ('start','stop','released','assigned','readsb_exited','location'):
            self.coverage.mark_break(stamp)

    def control(self, action, selection=None, position=None, height_m=None, band=None):
        if action in ('comparison_start','comparison_stop','comparison_reset'):
            with self.lock:
                if action=='comparison_reset':
                    self.comparison.reset_graphs()
                elif action=='comparison_start':
                    primary_id=self.assigned['id'] if self.assigned else self.selection
                    if primary_id=='auto':
                        candidate=next((d for d in self.devices if d.get('persistent') and d['id']!=selection
                                        and (not self.broker or self.broker.available('adsb',d['id']))),None)
                        if candidate:self.selection=primary_id=candidate['id']
                    spare=[d for d in self.devices if d['id']!=primary_id and d.get('persistent') and (selection in (None,'auto','all') or d['id']==selection)]
                    requested=[d['id'] for d in spare]
                    # Keep receiver letters/colors stable when USB indices reorder at boot.
                    requested=[k for k in self.comparison.selections if k in requested]+[k for k in requested if k not in self.comparison.selections]
                    if not requested:
                        if selection not in (None,'auto','all'):
                            if selection not in self.comparison.selections:raise ValueError('Reconnect the selected comparison receiver or choose a saved receiver')
                            requested=[selection]
                        else:requested=[key for key in self.comparison.selections if key!=primary_id]
                    if not self.comparison.enabled:self.comparison.restore_uat=self.uat.enabled
                    self.uat.control('stop')
                    self.comparison.reset_graphs()
                    self.comparison.control('start',requested or 'all')
                    # Start is one action even when USB enumeration is still pending.
                    if not self.enabled or not self.assigned:self.control('start')
                    self.next_scan=0
                else:
                    self.comparison.control('stop')
                    if self.comparison.restore_uat:
                        self.uat.control('start');self.comparison.restore_uat=False;self.comparison.save()
                self._event(action,selection=self.comparison.selection)
            self.wake.set();return
        if band == '978':
            with self.lock:
                if self.comparison.enabled and action in ('start','assign'):
                    raise ValueError('Stop the 1090 receiver comparison first; it is using the UAT dongle')
                excluded = [self.assigned['id']] if self.assigned else []
                if self.enabled and self.selection != 'auto': excluded.append(self.selection)
                self.uat.control(action, selection, self.devices, excluded)
                self.next_scan = 0
            self.wake.set()
            return
        if band not in (None, '1090'): raise ValueError('Unknown receiver band')
        if action == "start" and self.broker:
            self.broker.request("adsb", self.devices, self.selection)
        with self.lock:
            if action == 'assign':
                if self.comparison.enabled and self.comparison.contains(selection):
                    raise ValueError('This dongle is being compared; stop comparison before reassigning it')
                if selection != 'auto' and not any(d['id'] == selection for d in self.devices):
                    raise ValueError('Dongle no longer available; scan again')
                if self.uat.assigned and selection == self.uat.assigned['id']:
                    raise ValueError('This dongle is assigned to 978 UAT; choose the other receiver')
                self.selection = selection
            elif action == 'location':
                if self.station:
                    p=receiver_position(position)
                    self.station.update(dict(latitude=p['lat'] if p else None,longitude=p['lon'] if p else None,gps_auto=False))
                else:self.position = receiver_position(position)
            elif action == 'coverage_height':
                if self.station:self.station.update(dict(ellipsoid_height_m=height_m))
                else:self.coverage.set_height(height_m)
            elif action in ('start', 'stop'):
                self.enabled = action == 'start'
            elif action != 'scan':
                raise ValueError('Unknown ADS-B action')
            temporary = self.root/'settings.tmp'
            temporary.write_text(json.dumps(dict(enabled=self.enabled, selection=self.selection, position=self.position)))
            temporary.replace(self.root/'settings.json')
            self.next_scan = 0
            self.retry.clear()
            self._event(action, selection=self.selection)
        self.wake.set()

    def snapshot(self):
        with self.lock:
            assigned = self.assigned
            now=time.time();stamp=self.aircraft_stamp if self.aircraft_stamp is not None else now
            # Absolute observation times let clients age a cached snapshot honestly.
            planes=[]
            for p in self.planes:
                row=dict(p, band='1090', last_seen_at=stamp-p.get('seen',100))
                row['seen']=max(0,now-row['last_seen_at'])
                if isinstance(p.get('seen_pos'),(int,float)):
                    row['position_time']=stamp-p['seen_pos'];row['seen_pos']=max(0,now-row['position_time'])
                if row['seen']<15:planes.append(row)
            uat = self.uat.snapshot(now)
            if self.comparison.enabled:
                uat.update(status='PAUSED FOR COMPARISON',detail='Receivers are testing 1090 MHz. Stop comparison to restore UAT.')
            uat['aircraft_count']=len(uat['aircraft'])
            es_count=len(planes)
            planes = merge_aircraft(planes, uat.pop('aircraft'))
            latest = lambda values: max((v for v in values if v is not None), default=None)
            band1090 = dict(BANDS[0], status=self.status, enabled=self.enabled, selection=self.selection,
                            assigned=dict(assigned) if assigned else None, messages=self.messages,
                            detail=self.detail, last_message_at=self.last_message_at)
            band1090['aircraft_count']=es_count
            return dict(now=now, enabled=self.enabled or self.uat.enabled, enabled_1090=self.enabled,
                        selection=self.selection, devices=[dict(d) for d in self.devices],leases=self.broker.snapshot() if self.broker else {},
                        assigned=dict(assigned) if assigned else None, status=self.status if self.enabled else uat['status'] if self.uat.enabled else self.status, detail=self.detail,
                        aircraft=planes, messages=self.messages+self.uat.total_messages, port=self.port,
                        started_at=latest([self.started_at,self.uat.started_at]),last_message_at=latest([self.last_message_at,self.uat.last_packet_at]),
                        last_position_at=self.history.latest_position_time(time.time()),
                        receiver_position=dict(self.position) if self.position else None,
                        bands=[band1090, uat],
                        map_installed=(self.map_root/'index.html').is_file(), log=str(self.root/'flights.jsonl'))

    def track_snapshot(self):
        with self.lock:
            self.history.prune(time.time())
            return self.history.snapshot()

    def _save_history(self, force=False):
        now=time.monotonic()
        if not force and now<self.next_history_save:return
        self.next_history_save=now+60
        try:
            with self.lock:self.history.save(self.history_path,time.time())
        except (OSError,ValueError) as exc:self._event('history_save_error',detail=str(exc))

    def log_snapshot(self, kind):
        if kind not in LOG_FILES: raise ValueError('Unknown log type')
        with self.lock:
            data = self.log_cache[kind]
            return dict(data, entries=list(data['entries']), lines=list(data['lines']))

    def _refresh_logs(self):
        now = time.monotonic()
        if now < self.next_logs: return
        logs = {kind: read_log_tail(self.root, kind) for kind in LOG_FILES}
        with self.lock: self.log_cache = logs
        self.next_logs = now + 2

    def _stop(self):
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process:
            self._event('released', device=self.assigned)
        self.assigned = None
        if self.broker: self.broker.release("adsb")
        self.planes = []
        self.messages = 0
        self.started_at = None
        self.last_message_at = None
        # tar1090 must also stop showing old aircraft after Stop or loss of USB.
        (self.data/'aircraft.json').write_text(json.dumps(dict(now=time.time(), messages=0, aircraft=[])))

    def _launch(self, device):
        if self.broker and not self.broker.acquire("adsb", device["id"]):
            return
        for path in self.data.glob('*.json*'):
            path.unlink(missing_ok=True)
        self.active_position = dict(self.position) if self.position else None
        command = readsb_command(self.binary,device,self.data,self.active_position)
        # No external feed or listening receiver ports; map reads local JSON.
        stderr = self.root/'readsb.txt'
        stderr.write_text('')
        self.readsb_output = stderr.open('a')
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self.readsb_output,
                                            stderr=subprocess.STDOUT, close_fds=True, env=dict(os.environ, TZ='UTC'))
        finally:
            self.readsb_output.close()
        self.assigned = dict(device)
        self.started = time.monotonic()
        self.started_at = time.time()
        self.status, self.detail = 'STARTING', device['label']
        self._event('assigned', device=device)

    def _step(self):
        # Only this worker owns the child process. USB and child waits never hold
        # the snapshot lock needed by the render thread.
        now = time.monotonic()
        stderr = self.root/'readsb.txt'
        if stderr.exists() and stderr.stat().st_size > 2*1024*1024:
            stderr.write_text('')
        if now >= self.next_scan:
            self.devices = self.scanner()
            from rtl_registry import REGISTRY
            selection=REGISTRY.resolve(self.selection,self.devices)
            if selection!=self.selection:self.control('assign',selection)
            self.next_scan = now+5
        if self.process and (not self.enabled or self._location_restart_needed() or
                (self.selection != 'auto' and self.assigned['id'] != self.selection) or
                not any(same_usb_attachment(d,self.assigned) for d in self.devices)):
            self._stop()
        if self.process and self.process.poll() is not None:
            failed = self.assigned['id']
            self.detail = (self.root/'readsb.txt').read_text(errors='replace')[-1800:]
            self._event('readsb_exited', device=self.assigned, code=self.process.returncode, detail=self.detail)
            self._stop()
            self.retry[failed] = now+30
            self.status = 'RETRYING'
        if not self.enabled:
            self.status = 'STOPPED'
            self.planes = []
            return
        if not Path(self.binary).is_file() and not shutil.which(self.binary):
            self.status, self.detail = 'NOT INSTALLED', 'Install the ADS-B package with scripts/install-adsb.sh'
            return
        if not self.process:
            candidates = [d for d in self.devices if (self.selection == 'auto' or d['id'] == self.selection)
                          and (not self.uat.assigned or d['id'] != self.uat.assigned['id'])
                          and self.retry.get(d['id'], 0) <= now
                          and (not self.broker or self.broker.available("adsb", d["id"]))]
            if candidates:
                self._launch(candidates[0])
            else:
                self.status = 'WAITING FOR USB' if not self.devices else 'WAITING FOR DONGLE'
                if not self.devices: self.detail = 'No RTL-SDR detected. Check USB power and connection.'
                elif self.selection != 'auto' and not any(d['id'] == self.selection for d in self.devices):
                    self.detail = 'Assigned dongle is missing or USB order changed. Select a dongle again.'
                return
        # Nicknames can change while the same USB receiver stays open.
        current_device=next((d for d in self.devices if d['id']==self.assigned['id']),None)
        if current_device:self.assigned.update({k:current_device[k] for k in ('label','nickname') if k in current_device})
        try:
            payload = json.loads((self.data/'aircraft.json').read_text())
        except (OSError, ValueError):
            payload = {}
        fresh = 0 <= time.time()-float(payload.get('now', 0)) <= 15
        self.planes = aircraft_rows(payload)
        self.aircraft_stamp = payload.get('now') if fresh else None
        if fresh:
            self.status, self.detail = 'RECEIVING', self.assigned['label']
            if payload.get('messages',0)>self.messages:self.last_message_at=payload['now']
            self.messages = payload.get('messages', 0)
            with self.lock: self.history.ingest(self.planes, payload['now'])
            if now-self.last_log >= 5 and payload.get('now') != self.last_payload:
                self.last_log, self.last_payload = now, payload.get('now')
                coverage_rows = []
                for plane in self.planes:
                    if plane.get('seen', 100) < 5:
                        observation=dict(time=payload['now'],device=self.assigned,aircraft=plane,receiver_position=dict(self.position) if self.position else None)
                        self.flight_log.info(json.dumps(observation))
                        coverage_rows.append(observation)
                self.coverage.add(coverage_rows)
        elif now-self.started > 20:
            self.detail = 'Decoder stopped updating; reconnecting the assigned dongle.'
            failed = self.assigned['id']
            self._stop()
            self.retry[failed] = now+10
            self.status = 'RETRYING'

    def _step_uat(self):
        excluded = [self.assigned['id']] if self.assigned else []
        if self.enabled and self.selection != 'auto': excluded.append(self.selection)
        payload = self.uat.step(self.devices, excluded, self.position)
        # Weather consumes a second loopback connection, never a second RF stream.
        self.weather.step(self.uat.raw_port, self.uat.enabled)
        self.weather.comparison_paused = self.comparison.enabled
        if not payload: return
        planes = age_aircraft(payload, '978', payload['now'])
        with self.lock: self.history.ingest(planes, payload['now'])
        now = time.monotonic()
        if now-self.last_uat_log < 5: return
        self.last_uat_log = now
        observations = []
        for plane in planes:
            if plane.get('seen', 100) >= 5: continue
            observation = dict(time=payload['now'], device=self.uat.assigned, aircraft=plane,
                               receiver_position=dict(self.position) if self.position else None)
            self.flight_log.info(json.dumps(observation))
            observations.append(observation)
        self.coverage.add(observations)

    def _worker(self):
        while not self.closed.is_set():
            try: self._step()
            except Exception as exc:
                if self.broker and not self.process: self.broker.release("adsb")
                with self.lock:
                    self.status, self.detail = 'ERROR', str(exc)
                self._event('error', detail=str(exc))
            try: self._step_uat()
            except Exception as exc:
                self.uat.stop()
                self.uat.status, self.uat.detail = 'ERROR', str(exc)
                self.uat.next_retry = time.monotonic()+15
                self._event('uat_error', detail=str(exc))
            try:
                self.comparison.primary_detail=self.detail
                self.comparison.step(self.devices,self.assigned if self.process else None,self.data,self.position)
            except Exception as exc:
                self.comparison.stop();self.comparison.status='ERROR';self.comparison.detail=str(exc)
                self._event('comparison_error',detail=str(exc))
            try: self._refresh_logs()
            except OSError: pass
            self._save_history()
            try:
                with self.lock: site = dict(self.position) if self.position else None
                self.coverage.tick(site)
                self.coverage_error = ''
            except Exception as exc:
                if str(exc) != self.coverage_error: self._event('coverage_error', detail=str(exc))
                self.coverage_error = str(exc)
            self.wake.wait(1)
            self.wake.clear()
        self._save_history(force=True)
        self.coverage.close()
        self._stop()
        self.uat.stop()
        self.weather.stop()
        self.comparison.stop()

    def close(self):
        self.ground_map.close()
        self.aircraft_details.close()
        self.closed.set()
        self.wake.set()
        self.thread.join(timeout=16)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        for logger in (self.flight_log, self.events):
            for handler in logger.handlers: handler.close()


class ADSBHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send(self, data, mime='application/json', status=200, encoding=None):
        if mime.startswith('text/html') and not encoding:data=inject_notice(data)
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if encoding: self.send_header('Content-Encoding', encoding)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        manager = self.server.manager
        request = urlsplit(self.path)
        path = unquote(request.path)
        query = parse_qs(request.query)
        if station_get(self,path) or dongle_get(self,path):return
        try:
            if path == '/api/state':
                self.send(json.dumps(dict(manager.snapshot(), control_token=manager.token)).encode())
            elif path == '/api/aircraft':
                self.send(json.dumps(manager.aircraft_details.snapshot(query.get('hex', [''])[0])).encode())
            elif path == '/api/aircraft/photo':
                target=manager.aircraft_details.photo_path(query.get('hex', [''])[0])
                if target is None or not target.is_file(): self.send(b'No photo', 'text/plain', 404)
                else: self.send(target.read_bytes(), 'image/jpeg')
            elif path == '/api/coverage/ground':
                site=dict(lat=float(query.get('lat',['nan'])[0]),lon=float(query.get('lon',['nan'])[0]))
                self.send(json.dumps(manager.ground_map.snapshot(site,float(query.get('radius',['5000'])[0]))).encode())
            elif path == '/api/coverage/ground.png':
                image=manager.ground_map.image(query.get('key',[''])[0])
                self.send(image or b'', 'image/png', status=200 if image else 404)
            elif path == '/api/coverage':
                state=manager.snapshot()
                self.send(json.dumps(dict(manager.coverage.snapshot(float(query['since'][0]) if 'since' in query else None), error=manager.coverage_error, receiver_enabled=state['enabled'], receiver_status=state['status'])).encode())
            elif path == '/api/footprint':
                data=manager.coverage.maximum_snapshot() if query.get('scope')==['maximum'] else manager.coverage.snapshot(float(query['since'][0]) if 'since' in query else None);meta=data.get('meta',{})
                self.send(json.dumps(dict(status=data.get('status'),scope=data.get('scope','selected window'),error=manager.coverage_error,footprint=data.get('footprint'),retained_positions=meta.get('retained_positions',0),first_position=meta.get('first_position'),last_position=meta.get('last_position'))).encode())
            elif path == '/api/tracks':
                self.send(json.dumps(manager.track_snapshot()).encode())
            elif path == '/api/weather':
                self.send(json.dumps(dict(manager.weather.snapshot(), receiver_position=manager.snapshot()['receiver_position'])).encode())
            elif path == '/api/comparison':
                self.send(json.dumps(manager.comparison.snapshot()).encode())
            elif path == '/api/comparison.csv':
                self.send(manager.comparison.csv(),'text/csv; charset=utf-8')
            elif path == '/api/logs':
                self.send(json.dumps(manager.log_snapshot(query.get('kind', ['flights'])[0])).encode())
            elif path == '/api/log':
                kind = query.get('kind', ['flights'])[0]
                if kind not in LOG_FILES: raise ValueError('Unknown log type')
                data = (manager.root/LOG_FILES[kind]).read_bytes()
                self.send(data, 'text/plain; charset=utf-8' if kind == 'diagnostics' else 'application/x-ndjson')
            elif path == '/api/globe/view':
                self.send(json.dumps(manager.globe.view(query)).encode())
            elif path == '/globe/countries.json':
                self.send(manager.globe.country_data())
            elif path == '/globe/oxanium.ttf':
                self.send((Path(__file__).resolve().parent.parent/'assets/fonts/oxanium/Oxanium.ttf').read_bytes(), 'font/ttf')
            elif path == '/globe/earth.jpg':
                self.send((manager.globe.assets/'nasa-blue-marble-4096.jpg').read_bytes(), 'image/jpeg')
            elif path.startswith('/globe/tiles/'):
                tile = manager.globe.tile(path)
                self.send(tile or b'', 'image/jpeg', status=200 if tile else 404)
            elif path in ('/adsb_globe.js', '/adsb_controls.js', '/adsb_view.js', '/adsb_bands.js', '/adsb_coverage.js', '/adsb_map.css', '/adsb_coverage.css', '/adsb_weather.js', '/adsb_weather.css', '/adsb_compare.js', '/adsb_compare.css'):
                self.send(Path(__file__).with_name(path[1:]).read_bytes(), 'text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8')
            elif path == '/':
                self.send(Path(__file__).with_name('adsb_map.html').read_bytes(), 'text/html; charset=utf-8')
            elif path == '/weather':
                self.send(Path(__file__).with_name('adsb_weather.html').read_bytes(), 'text/html; charset=utf-8')
            elif path == '/compare':
                self.send(Path(__file__).with_name('adsb_compare.html').read_bytes(), 'text/html; charset=utf-8')
            elif path == '/map/data/receiver.json':
                payload = json.loads((manager.data/'receiver.json').read_text())
                # Local traffic is small; JSON avoids a WebAssembly requirement.
                payload.update(binCraft=False, zstd=False, history=0)
                self.send(json.dumps(payload).encode())
            elif path.startswith('/map/'):
                relative = path[5:] or 'index.html'
                root = manager.data if relative.startswith('data/') else manager.map_root
                if relative.startswith('data/'): relative = relative[5:]
                if relative == 'chunks/chunks.json':
                    self.send(b'{"chunks":[],"chunksAll":[],"chunksSelected":[]}')
                    return
                target = (root/relative).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    self.send(b'Not found', 'text/plain', 404)
                    return
                mime = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
                content = target.read_bytes()
                # tar1090-db deliberately stores gzip data under .js names.
                self.send(content, mime, encoding='gzip' if content.startswith(b'\x1f\x8b') else None)
            else: self.send(b'Not found', 'text/plain', 404)
        except (OSError, ValueError): self.send(b'Unavailable', 'text/plain', 503)

    def do_POST(self):
        if notice_post(self):return
        if self.path=='/api/dongles':dongle_post(self);return
        if self.path=='/api/station':station_post(self);return
        manager = self.server.manager
        # Same-origin page token is required; no permissive CORS or query tokens.
        origin = self.headers.get('Origin')
        if (self.path != '/api/control' or self.headers.get('X-ADSB-Token') != manager.token or
                (origin and urlsplit(origin).netloc != self.headers.get('Host'))):
            self.send(b'{"error":"Control token required"}', status=403)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096: raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(size))
            manager.control(data.get('action'), data.get('selection'), data.get('position'), data.get('height_m'), data.get('band'))
            self.send(b'{"ok":true}')
        except (ValueError, TypeError, AttributeError) as exc:
            self.send(json.dumps(dict(error=str(exc))).encode(), status=400)
