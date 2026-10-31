"""Experimental independent Kiwi survey and persistent station-activity history."""
from collections import defaultdict, deque
import json
import math
from pathlib import Path
import select
import socket
import sqlite3
import threading
import time
from urllib.parse import urlsplit

import kiwi_live_display_fb as kiwi
from smart_seek import SmartSeek
from scan_policy import ScanPolicy
from smart_seek_catalogue import SpectrumSurvey


HOURS = (1, 6, 12, 24)


def receiver_address(value):
    value = str(value).strip().rstrip('/')
    if '://' not in value:
        value = 'http://'+value
    parsed = urlsplit(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Enter a KiwiSDR http or https address.')
    try:
        parsed.port
    except ValueError:
        raise ValueError('The receiver port is invalid.') from None
    if parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Use the receiver address without a page or query.')
    return value


class ActivityHistory:
    """A failed/unvisited sweep can never become evidence of station absence."""
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS sweeps(
                id INTEGER PRIMARY KEY, receiver TEXT NOT NULL, stamp REAL NOT NULL,
                band TEXT NOT NULL, low REAL NOT NULL, high REAL NOT NULL, measured INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS sweep_time ON sweeps(receiver,stamp);
            CREATE TABLE IF NOT EXISTS signals(
                sweep INTEGER NOT NULL REFERENCES sweeps(id) ON DELETE CASCADE,
                frequency REAL NOT NULL, strength REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS signal_sweep ON signals(sweep);
        ''')
        self.revision = 0
        self.pruned_at = 0

    def record(self, receiver, band, low, high, candidates, measured, stamp=None):
        stamp = time.time() if stamp is None else stamp
        with self.lock,self.db:
            cursor = self.db.execute('INSERT INTO sweeps(receiver,stamp,band,low,high,measured) VALUES(?,?,?,?,?,?)',
                                     (receiver,stamp,band,low,high,int(measured)))
            if measured:
                self.db.executemany('INSERT INTO signals VALUES(?,?,?)',
                    [(cursor.lastrowid,c.tuning_khz,c.prominence) for c in candidates])
            if stamp-self.pruned_at >= 3600:
                self.db.execute('DELETE FROM sweeps WHERE stamp < ?',(stamp-48*3600,))
                self.pruned_at = stamp
            self.revision += 1

    def read(self, receiver, hours=12, period=360, now=None):
        now = time.time() if now is None else now
        start = now-hours*3600
        with self.lock:
            rows = self.db.execute('''SELECT s.id,s.stamp,s.band,s.low,s.high,s.measured,d.frequency,d.strength
                FROM sweeps s LEFT JOIN signals d ON d.sweep=s.id
                WHERE s.receiver=? AND s.stamp>=? AND s.stamp<=? ORDER BY s.stamp,s.id''',
                (receiver,start-period*2.5,now)).fetchall()
        sweeps = {}
        tracks = {}
        for identity,stamp,band,low,high,measured,frequency,strength in rows:
            sweep = sweeps.setdefault(identity,dict(stamp=stamp,band=band,low=low,high=high,
                                                    measured=bool(measured),hits={}))
            if frequency is not None:
                key = band,round(frequency)
                sweep['hits'][key] = max(sweep['hits'].get(key,0),strength)
                tracks[key] = frequency
        segments,points,tails,gaps = [],[],[],[]
        by_band = defaultdict(list)
        for key in tracks:
            by_band[key[0]].append(key)
        states = {}
        for sweep in sweeps.values():
            stamp = sweep['stamp']
            keys = by_band.get(sweep['band'],()) if sweep['band'] != '*' else tracks
            if not sweep['measured']:
                if stamp >= start:
                    gaps.append((stamp,sweep['band']))
                for key in keys:
                    states.pop(key,None)
                continue
            for key in keys:
                frequency = tracks[key]
                if not sweep['low'] <= frequency <= sweep['high']:
                    continue
                strength = sweep['hits'].get(key)
                previous = states.get(key)
                if strength is not None:
                    if stamp >= start and previous and previous['misses'] < 2 and stamp-previous['stamp'] <= period*2.5:
                        segments.append((max(start,previous['stamp']),stamp,key[0],frequency,
                                         (previous['strength']+strength)/2))
                    if stamp >= start:
                        points.append((stamp,key[0],frequency,strength))
                    states[key] = dict(stamp=stamp,strength=strength,misses=0)
                elif previous:
                    previous['misses'] += 1
        for (band,channel),state in states.items():
            if state['misses'] < 2 and now-state['stamp'] <= period*1.5:
                tails.append((max(start,state['stamp']),now,band,tracks[(band,channel)],state['strength']))
        return dict(start=start,end=now,segments=segments,points=points,tails=tails,gaps=gaps,
                    tracks=tuple((band,frequency) for (band,_),frequency in tracks.items()),
                    sweeps=sum(s['measured'] and s['stamp'] >= start for s in sweeps.values()))

    def close(self):
        with self.lock:
            self.db.close()


class KiwiScanSession:
    """One extra, uniquely paired SND/W/F session; received audio is discarded."""
    def __init__(self, server, stamp, stopped, connect=None):
        self.server,self.stamp,self.stopped = server,stamp,stopped
        self.connect = connect or kiwi.KiwiWebSocket.connect
        self.sockets = []
        self.frames = deque()
        self.bandwidth,self.zoom_max,self.zoom_cap = 30000000,14,14
        self.audio_ready = False
        self.audio_configured = False
        self.wf_authenticated = False
        self.target = None
        self.waterfall_paused = False
        self.last_keepalive = 0
        self.last_frame = time.monotonic()

    def _socket(self, name):
        ws = self.connect(self.server,name,timeout=3,session_timestamp=self.stamp)
        self.sockets.append(ws)
        ws.sock.settimeout(1)
        # Never briefly advertise the listening session's identity first.
        ws.send_text('SET auth t=kiwi p=#')
        ws.send_text('SET ident_user='+kiwi.CLIENT_NAME+'-LongScan')
        ws.send_text('SET geo=Ituner receiver')
        if self.stopped.is_set():
            raise InterruptedError('Stopped')
        return ws

    def open(self):
        self.snd = self._socket('SND')
        deadline = time.monotonic()+12
        while not self.stopped.is_set() and not self.audio_ready:
            if time.monotonic() > deadline:
                raise TimeoutError('Receiver did not start its session')
            self._read_ready([self.snd],.2)
        if self.stopped.is_set():
            raise InterruptedError('Stopped')
        self.wf = self._socket('W/F')
        self.last_frame = time.monotonic()
        return self

    def set_view(self, center, zoom):
        target = center,zoom
        if target != self.target or self.waterfall_paused:
            self.target = target
            if self.wf_authenticated:
                kiwi.send_wf_setup(self.wf,center,zoom,4)
                if self.waterfall_paused:
                    self.frames.clear()
                    self.last_frame = time.monotonic()
                self.waterfall_paused = False

    def pause_waterfall(self):
        """Stop unused FFT rows between cycles without reopening the session."""
        if self.wf_authenticated and not self.waterfall_paused:
            kiwi.send_wf_speed(self.wf,0)
            self.waterfall_paused = True
            self.frames.clear()

    def _message(self, ws, message):
        if message[:3] == b'MSG':
            params = kiwi.parse_msg_params(message)
            kiwi.raise_for_kiwi_server_message(params)
            if 'badp' in params and str(params['badp']) != '0':
                raise RuntimeError('badp='+str(params['badp']))
            if ws is self.snd:
                if 'audio_rate' in params:
                    ws.send_text('SET AR OK in='+str(int(float(params['audio_rate'])))+' out=12000')
                if 'sample_rate' in params and not self.audio_configured:
                    kiwi.send_snd_setup(ws,10000,'am',-2500,2500)
                    self.audio_configured = True
            else:
                for name,limits in (('bandwidth',(1000000,100000000)),('zoom_max',(8,14)),('zoom_cap',(0,14))):
                    try:
                        value = int(params.get(name,getattr(self,name)))
                    except (ValueError,TypeError):
                        continue
                    if limits[0] <= value <= limits[1]:
                        setattr(self,name,value)
                if params.get('badp') == '0':
                    self.wf_authenticated = True
                    if self.target:
                        kiwi.send_wf_setup(ws,*self.target,4)
        elif ws is self.snd and message[:3] == b'SND' and len(message) >= 10:
            self.audio_ready = True
        elif message[:3] == b'W/F' and len(message) == 1040:
            self.last_frame = time.monotonic()
            if not self.waterfall_paused:
                self.frames.append(message)

    def _read_ready(self, sockets, timeout):
        now = time.monotonic()
        if now-self.last_keepalive >= 1:
            for ws in sockets:
                ws.send_text('SET keepalive')
            self.last_keepalive = now
        ready,_,_ = select.select([ws.sock for ws in sockets],[],[],timeout)
        for ws in sockets:
            pending = getattr(ws.sock,'pending',lambda:0)()
            if ws.sock in ready or pending:
                try:
                    self._message(ws,ws.recv())
                except socket.timeout:
                    continue

    def read(self, timeout=.2):
        self._read_ready(self.sockets,timeout)
        if not self.waterfall_paused and time.monotonic()-self.last_frame > 15:
            raise TimeoutError('Waterfall stopped responding')
        return self.frames.popleft() if self.frames else None

    def close(self):
        for ws in self.sockets:
            try:
                ws.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                ws.sock.close()
            except OSError:
                pass
        self.sockets = []


class LongScan:
    def __init__(self, bands, root=None, session_stamp=None, session_factory=None):
        self.bands = tuple(bands)
        self.root = Path(root or Path.home()/'.local/state/ituner-long-scan')
        self.config_path = self.root/'settings.json'
        self.lock = threading.RLock()
        self.config = dict(receiver='',enabled=False,hours=12,period=360)
        try:
            saved = json.loads(self.config_path.read_text())
            self.config.update(receiver=receiver_address(saved['receiver']),enabled=bool(saved.get('enabled')),
                               hours=saved.get('hours',12) if saved.get('hours') in HOURS else 12)
        except (OSError,ValueError,KeyError,TypeError):
            pass
        self.history = None
        self.status,self.detail = 'Stopped',''
        try:
            self.history = ActivityHistory(self.root/'activity.sqlite3')
        except (sqlite3.Error,OSError):
            self.status,self.detail = 'Unavailable','Cannot open the saved activity history.'
        self.thread = None
        self.stopped = threading.Event()
        self.session = None
        self.session_stamp = session_stamp or (lambda:time.time_ns()//1000000)
        self.session_factory = session_factory or KiwiScanSession
        self.band = ''
        self.next_cycle = 0

    def _save(self):
        pending = self.config_path.with_suffix('.json.next')
        pending.write_text(json.dumps(self.config,indent=2)+'\n')
        pending.replace(self.config_path)

    def configure(self, receiver=None, hours=None):
        with self.lock:
            if receiver is not None:
                if self.thread and self.thread.is_alive():
                    raise ValueError('Stop Long Scan before changing its receiver.')
                self.config['receiver'] = receiver_address(receiver)
            if hours is not None:
                if hours not in HOURS:
                    raise ValueError('Choose 1, 6, 12 or 24 hours.')
                self.config['hours'] = hours
            self._save()

    def snapshot(self):
        with self.lock:
            return dict(self.config,status=self.status,detail=self.detail,band=self.band,
                        running=bool(self.thread and self.thread.is_alive()),next_cycle=self.next_cycle,
                        revision=self.history.revision if self.history else 0)

    def start(self, startup_delay=0):
        with self.lock:
            if not self.history:
                return False
            if self.thread and self.thread.is_alive():
                return not self.stopped.is_set()
            self.config['receiver'] = receiver_address(self.config['receiver'])
            self.config['enabled'] = True
            self._save()
            self.stopped = threading.Event()
            self.status,self.detail = 'Connecting','Opening a dedicated receiver session…'
            def run():
                if not self.stopped.wait(startup_delay):
                    self._run()
            self.thread = threading.Thread(target=run,name='long-scan',daemon=True)
            self.thread.start()
            return True

    def resume(self):
        if self.config['enabled'] and self.config['receiver']:
            self.start(startup_delay=5)

    def stop(self, persist=True):
        with self.lock:
            self.stopped.set()
            session = self.session
            if persist:
                self.config['enabled'] = False
                self._save()
            self.status,self.detail,self.band = 'Stopped','',''
        if session:
            session.close()

    def close(self):
        self.stop(persist=False)
        if self.thread:
            self.thread.join(timeout=5)
        if self.history and (not self.thread or not self.thread.is_alive()):
            self.history.close()

    def _state(self, status, detail='', band=''):
        with self.lock:
            if not self.stopped.is_set():
                self.status,self.detail,self.band = status,detail,band

    @staticmethod
    def retry_delay(failures, error):
        return 60 if 'badp=' in str(error) else min(60,2**min(failures,6))

    def _run(self):
        receiver = self.config['receiver']
        policy = ScanPolicy()
        failures = 0
        while not self.stopped.is_set():
            session = None
            try:
                self._state('Connecting','Opening a dedicated receiver session…')
                session = self.session_factory(receiver,self.session_stamp(),self.stopped)
                with self.lock:
                    self.session = session
                session.open()
                # Four seconds of broad RF is a priority hint only. It never
                # records presence or absence in the activity history.
                survey = SpectrumSurvey()
                survey.start(0,session.bandwidth/1000,'Spectrum',(receiver,),time.monotonic(),refresh=True)
                survey.bands = tuple(b for b in self.bands if b[0]<session.bandwidth/1000)
                while survey.active and not self.stopped.is_set():
                    request = survey.request((receiver,),time.monotonic(),session.bandwidth,session.zoom_cap)
                    if request is None:
                        break
                    self._state('Surveying','Checking spectrum activity…')
                    session.set_view(*request)
                    frame = session.read()
                    if frame:
                        survey.feed(frame,session.bandwidth,session.zoom_max,session.zoom_cap,time.monotonic())
                while not self.stopped.is_set():
                    cycle = time.monotonic()
                    for low,high,label in policy.rank_bands((receiver,),self.bands,
                            session.bandwidth,session.zoom_cap,survey.scores):
                        if low >= session.bandwidth/1000 or self.stopped.is_set():
                            continue
                        engine = SmartSeek(policy)
                        engine.OBSERVE_SECONDS = 2
                        engine.start(low,min(high,session.bandwidth/1000),label,(receiver,),time.monotonic(),refresh=True)
                        while engine.active and not self.stopped.is_set():
                            request = engine.request((receiver,),time.monotonic(),session.bandwidth,session.zoom_cap)
                            if request is None:
                                break
                            self._state('Scanning',f'{label} · view {engine.index+1} of {len(engine.windows)}',label)
                            session.set_view(*request)
                            frame = session.read()
                            if frame:
                                engine.feed(frame,session.bandwidth,session.zoom_max,session.zoom_cap,time.monotonic())
                        if self.stopped.is_set():
                            break
                        measured = engine.index >= len(engine.windows) and engine.skipped == 0 and engine.measured_at is not None
                        self.history.record(receiver,label,low,high,engine.snapshot()['candidates'],measured)
                        if measured:
                            failures = 0
                    with self.lock:
                        self.next_cycle = cycle+self.config['period']
                    if self.next_cycle-time.monotonic() >= 3:
                        session.pause_waterfall()
                    while not self.stopped.is_set() and time.monotonic() < self.next_cycle:
                        seconds = math.ceil(self.next_cycle-time.monotonic())
                        self._state('Waiting',f'Next full sweep in {seconds//60}:{seconds%60:02d}')
                        session.read()
            except Exception as error:
                if not self.stopped.is_set():
                    failures += 1
                    delay = self.retry_delay(failures,error)
                    try:
                        self.history.record(receiver,'*',0,100000,(),False)
                    except (sqlite3.Error,OSError):
                        self._state('History unavailable','Cannot save activity; Long Scan stopped.')
                        self.stopped.set()
                        break
                    message = 'Receiver busy or authentication required.' if 'badp=' in str(error) else 'Receiver connection interrupted.'
                    self._state('Reconnecting',message+f' Retrying in {delay} seconds.')
                    if session:
                        session.close()
                    self.stopped.wait(delay)
            finally:
                if session:
                    session.close()
                with self.lock:
                    self.session = None
