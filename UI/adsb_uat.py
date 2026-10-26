"""Supervised, local-only 978 MHz reception using FlightAware dump978/skyaware.

Uses a separate broker lease and unique Soapy serial. Auto never displaces the
1090 receiver or another decoder. The ADS-B worker owns both child processes.
"""
import json
from rtl_registry import same_usb_attachment
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

from sdr_broker import soapy_args


def age_aircraft(payload, band, now):
    stamp = payload.get('now', 0)
    if not isinstance(stamp, (int, float)) or not 0 <= now-stamp <= 15:
        return []
    rows = []
    for plane in payload.get('aircraft', []):
        if not isinstance(plane, dict) or not isinstance(plane.get('seen'), (int, float)):
            continue
        row = dict(plane, band=band, last_seen_at=stamp-plane['seen'])
        row['seen'] = now-row['last_seen_at']
        if not 0 <= row['seen'] < 15:
            continue
        if isinstance(plane.get('seen_pos'), (int, float)):
            row['position_time'] = stamp-plane['seen_pos']
            row['seen_pos'] = max(0, now-row['position_time'])
        rows.append(row)
    return rows


def merge_aircraft(*sources):
    """One target per address, retaining a coherent position and its source.

    A newer speed-only packet must not hide a valid position from the other
    band. Never splice position timestamps or RSSI across sources.
    """
    result = {}
    for rows in sources:
        for row in rows:
            key = row.get('hex')
            if not key:
                continue
            previous = result.get(key)
            positioned = lambda p: (isinstance(p.get('lat'), (int, float)) and
                                    isinstance(p.get('lon'), (int, float)) and
                                    p.get('seen_pos', 100) < 15)
            rank = lambda p: (positioned(p), p.get('position_time', 0) if positioned(p)
                              else p.get('last_seen_at', 0))
            if previous is None or rank(row) > rank(previous):
                result[key] = dict(row)
    return list(result.values())


class UATReceiver:
    def __init__(self, root, data, broker=None, event=None, binary=None, tracker=None):
        self.root, self.data = Path(root), Path(data)/'uat'
        self.data.mkdir(exist_ok=True)
        self.broker, self.event = broker, event or (lambda *args, **kwargs: None)
        folder = '/opt/ituner-sdr/decoders/adsb/'
        self.binary = binary or os.environ.get('ITUNER_DUMP978_BIN', folder+'dump978-fa')
        self.tracker = tracker or os.environ.get('ITUNER_SKYAWARE978_BIN', folder+'skyaware978')
        try: saved = json.loads((self.root/'uat-settings.json').read_text())
        except (OSError, ValueError): saved = {}
        self.enabled = saved.get('enabled') is True
        self.selection = saved.get('selection', 'auto')
        if not isinstance(self.selection, str): self.selection = 'auto'
        self.status, self.detail = 'STOPPED', ''
        self.assigned = None
        self.processes = []
        self.raw_port = None
        self.payload = {}
        self.messages = 0
        try: reception=json.loads((self.root/'uat-reception.json').read_text())
        except (OSError,ValueError):reception={}
        if not isinstance(reception,dict):reception={}
        total=reception.get('messages',0);heard=reception.get('last_message_at')
        self.total_messages=total if isinstance(total,int) and 0<=total<2**63 else 0
        self.last_packet_at=heard if isinstance(heard,(int,float)) and math.isfinite(heard) and 0<heard<=time.time()+1 else None
        self.next_reception_save=0;self.reception_dirty=False
        self.last_message_at = self.started_at = None
        self.started = self.next_retry = self.last_payload = 0
        if broker:
            broker.register('uat', lambda: self.control('stop'),
                            lambda: self.control('start'), lambda: self.enabled)

    @property
    def installed(self):
        return all(Path(p).is_file() or shutil.which(p) for p in (self.binary, self.tracker))

    def control(self, action, selection=None, devices=(), excluded=()):
        if action == 'assign':
            device = next((d for d in devices if d['id'] == selection), None)
            if selection != 'auto':
                if not device: raise ValueError('UAT dongle is disconnected; reconnect it and scan again')
                if selection in excluded: raise ValueError('This dongle is assigned to 1090 ES; choose the second receiver')
                soapy_args(device)  # Refuse ambiguous serials, never open an arbitrary SDR.
            self.selection = selection
        elif action in ('start', 'stop'):
            self.enabled = action == 'start'
        elif action != 'scan':
            raise ValueError('Unknown UAT action')
        tmp = self.root/'uat-settings.tmp'
        tmp.write_text(json.dumps(dict(enabled=self.enabled, selection=self.selection)))
        tmp.replace(self.root/'uat-settings.json')
        self.next_retry = 0
        self.event('uat_'+action, selection=self.selection)

    def stop(self):
        self.raw_port = None
        self.save_reception(force=True)
        children, self.processes = self.processes, []
        for child in children:
            if child.poll() is None: child.terminate()
        for child in children:
            try: child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=2)
        if self.broker: self.broker.release('uat')
        if children: self.event('uat_released', device=self.assigned)
        self.assigned = None
        self.payload = {}
        self.messages = 0
        self.last_message_at = self.started_at = None
        self.last_payload = 0

    def save_reception(self,force=False):
        if not self.reception_dirty or (not force and time.monotonic()<self.next_reception_save):return
        tmp=self.root/'uat-reception.tmp'
        try:
            tmp.write_text(json.dumps(dict(messages=self.total_messages,last_message_at=self.last_packet_at)))
            tmp.replace(self.root/'uat-reception.json')
        except OSError as exc:
            self.next_reception_save=time.monotonic()+30
            self.event('uat_statistics_error',detail=str(exc));return
        self.reception_dirty=False;self.next_reception_save=time.monotonic()+30

    def launch(self, device, position):
        args = soapy_args(device)
        if self.broker and not self.broker.acquire('uat', device['id']): return
        # A private ephemeral loopback port connects the two upstream programs.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        for path in self.data.glob('*.json*'): path.unlink(missing_ok=True)
        decoder = [self.binary, '--sdr', args, '--format', 'CS8',
                   '--raw-port', '127.0.0.1:'+str(port)]
        tracker = [self.tracker, '--connect', '127.0.0.1:'+str(port), '--reconnect-interval', '2',
                   '--json-dir', str(self.data), '--history-count', '0']
        if position:
            tracker += ['--lat', str(position['lat']), '--lon', str(position['lon'])]
        try:
            with (self.root/'uat.txt').open('w') as output:
                for command in (decoder, tracker):
                    self.processes.append(subprocess.Popen(command, stdin=subprocess.DEVNULL,
                        stdout=output, stderr=subprocess.STDOUT, close_fds=True, env=dict(os.environ, TZ='UTC')))
        except Exception:
            self.stop(); raise
        self.assigned = dict(device)
        self.raw_port = port
        self.started, self.started_at = time.monotonic(), time.time()
        self.status, self.detail = 'STARTING', device['label']
        self.event('uat_assigned', device=device)

    def step(self, devices, excluded=(), position=None):
        now = time.monotonic()
        if self.processes and (not self.enabled or self.assigned['id'] in excluded or
                (self.selection != 'auto' and self.assigned['id'] != self.selection) or
                not any(same_usb_attachment(d,self.assigned) for d in devices)):
            self.stop()
        if self.processes and any(p.poll() is not None for p in self.processes):
            self.detail = (self.root/'uat.txt').read_text(errors='replace')[-1800:]
            self.event('uat_exited', device=self.assigned, detail=self.detail)
            self.stop(); self.next_retry = now+15
        if not self.installed:
            self.status, self.detail = 'NOT INSTALLED', 'Install scripts/install-uat.sh'
            return None
        if not self.enabled:
            self.status = 'STOPPED'
            return None
        if now < self.next_retry:
            self.status = 'RETRYING'
            return None
        if not self.processes:
            choices = [d for d in devices if d['id'] not in excluded and
                       (self.selection == 'auto' or d['id'] == self.selection)]
            if not choices:
                self.status, self.detail = 'WAITING FOR SECOND DONGLE', '978 UAT needs a separate connected RTL-SDR; 1090 keeps its receiver.'
                return None
            choices = [d for d in choices if not self.broker or self.broker.available('uat', d['id'])]
            if not choices:
                self.status, self.detail = 'DONGLE BUSY', 'The UAT receiver is in use by another decoder.'
                return None
            try: self.launch(choices[0], position)
            except ValueError as exc:
                self.status, self.detail = 'UNIQUE ID REQUIRED', str(exc)
                return None
            if not self.processes:
                self.status, self.detail = 'DONGLE BUSY', 'Waiting for the USB maintenance lease to be released.'
                return None
        try: payload = json.loads((self.data/'aircraft.json').read_text())
        except (OSError, ValueError): payload = {}
        stamp = payload.get('now', 0)
        if isinstance(stamp, (int, float)) and 0 <= time.time()-stamp <= 15:
            messages = payload.get('messages', 0)
            if messages > self.messages:
                self.total_messages+=messages-self.messages
                self.last_message_at=self.last_packet_at=stamp
                self.reception_dirty=True
                self.event('uat_packets',device=self.assigned,detail=f'{messages-self.messages} new UAT aircraft packets · {self.total_messages} total')
            self.messages, self.payload = messages, payload
            self.save_reception()
            heard = self.last_message_at is not None and time.time()-self.last_message_at < 15
            self.status = 'RECEIVING' if heard else 'LISTENING'
            self.detail = self.assigned['label']+('' if heard else ' · tuned to 978 MHz; no recent UAT packets')
            if stamp != self.last_payload:
                self.last_payload = stamp
                return payload
        elif now-self.started > 20:
            self.stop(); self.next_retry = now+10
            self.status, self.detail = 'RETRYING', 'UAT output stopped updating; restarting both decoder processes.'
        path = self.root/'uat.txt'
        if path.exists() and path.stat().st_size > 2*1024*1024: path.write_text('')
        return None

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        return dict(id='978', name='978 UAT', frequency_mhz=978, installed=bool(self.installed),
                    description='ADS-B / TIS-B · dump978-fa', status=self.status, detail=self.detail,
                    enabled=self.enabled, selection=self.selection, assigned=self.assigned,
                    messages=self.total_messages, session_messages=self.messages,
                    last_message_at=self.last_packet_at, started_at=self.started_at,
                    aircraft=age_aircraft(self.payload, '978', now))
