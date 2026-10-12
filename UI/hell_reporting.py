"""Opt-in, human-confirmed Hell reception reports to PSK Reporter.

Protocol: https://pskreporter.info/pskdev.html (IPFIX/UDP). No image upload,
OCR guesses, fabricated SNR, or inferred remote receiving locations.
"""
import json
import random
import re
import secrets
import socket
import struct
import threading
import time
from sstv_monitor import atomic_json

RX_TEMPLATE = bytes.fromhex('000300249992000300018002FFFF0000768F8004FFFF0000768F8008FFFF0000768F0000')
TX_TEMPLATE = bytes.fromhex('0002002C999300058001FFFF0000768F800500040000768F800AFFFF0000768F800B00010000768F00960004')


def string(value):
    data = value.encode('ascii')
    if len(data)>254:
        raise ValueError('Report field too long')
    return bytes([len(data)])+data


def record(kind, data):
    padding = b'\0'*((-len(data))%4)
    return struct.pack('!HH',kind,4+len(data)+len(padding))+data+padding


def packet(rows, sequence, domain, now=None):
    first = rows[0]
    rx = record(0x9992, string(first['reporter'])+string(first['grid'])+string('iTuner Hell RX 1.0'))
    tx = record(0x9993, b''.join(string(r['call'])+struct.pack('!I',r['rf_hz'])+string(r['mode'])+
                b'\x03'+struct.pack('!I',int(r['received_at'])) for r in rows))
    body = RX_TEMPLATE+TX_TEMPLATE+rx+tx
    return struct.pack('!HHIII',10,16+len(body),int(now or time.time()),sequence,domain)+body


def callsign(value):
    if not isinstance(value,str):
        raise ValueError('Enter a valid callsign')
    value = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{1,8}(?:/[A-Z0-9]{1,8}){0,2}',value) or not any(c.isdigit() for c in value) or not any(c.isalpha() for c in value):
        raise ValueError('Enter a valid callsign, for example KN6KEZ')
    return value


class HellReporter:
    def __init__(self, path, gallery, start=True):
        self.path, self.gallery = path, gallery
        self.lock = threading.RLock()
        self.rows = []
        self.profiles = {}
        self.domain = secrets.randbits(32)
        self.sequence = 0
        self.sock = None
        self.stop = threading.Event()
        self.thread = None
        self.next_send = time.monotonic()+300+random.uniform(0,30)
        try:
            saved = json.loads(path.read_text())
            self.rows = saved['reports'][-500:]
            self.profiles = saved.get('profiles',{})
            for row in self.rows:
                if row['status']=='sending':
                    row['status']='uncertain'
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if start:
            self.thread = threading.Thread(target=self.run, name='hell-reporting', daemon=True)
            self.thread.start()

    def save(self):
        atomic_json(self.path,dict(reports=self.rows[-500:],profiles=self.profiles))

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(dict(reports=self.rows[-100:][::-1],profiles=self.profiles)))

    def submit(self, payload):
        if payload.get('confirmed') is not True:
            raise ValueError('Confirm the callsign, receiver location and permission to report')
        call, reporter = callsign(payload.get('call')), callsign(payload.get('reporter'))
        grid = str(payload.get('grid','')).strip().upper()
        if not re.fullmatch('[A-R]{2}[0-9]{2}(?:[A-X]{2})?',grid):
            raise ValueError('Enter the receiving antenna’s 4- or 6-character grid')
        image = next((r for r in self.gallery.snapshot() if r['id']==payload.get('image')),None)
        if not image:
            raise ValueError('This image is no longer available')
        if not 0 <= time.time()-image['received_at'] <= 86400:
            raise ValueError('Only receptions from the last 24 hours may be reported')
        with self.lock:
            if any(r['call']==call and r['server']==image['server'] and abs(r['received_at']-image['received_at'])<300
                   for r in self.rows):
                raise ValueError('This station was already reported for this receiver within five minutes')
            if sum(r['status']=='queued' for r in self.rows)>=100:
                raise ValueError('Reporting queue full; wait for pending reports')
            row = {k:image[k] for k in ('server','rf_hz','mode','received_at')}
            row.update(id=secrets.token_hex(16),image=image['id'],call=call,reporter=reporter,grid=grid,status='queued')
            self.rows.append(row)
            self.rows = self.rows[-500:]
            self.profiles[image['server']] = dict(reporter=reporter,grid=grid)
            self.save()
            return dict(ok=True,status='queued',message='Queued for PSK Reporter; sends about every five minutes. Delivery cannot be confirmed over UDP.')

    def cancel(self, key):
        with self.lock:
            row = next((r for r in self.rows if r['id']==key),None)
            if not row or row['status']!='queued':
                raise ValueError('Only queued reports can be cancelled')
            row['status']='cancelled'
            self.save()
        return dict(ok=True)

    def send_pending(self):
        with self.lock:
            for row in self.rows:
                if row['status']=='queued' and time.time()-row['received_at']>86400:
                    row['status']='expired'
            queued = [r for r in self.rows if r['status']=='queued']
            if not queued:
                self.save()
                return
            first = queued[0]
            selected = [r for r in queued if (r['reporter'],r['grid'])==(first['reporter'],first['grid'])][:20]
            for row in selected:
                row['status']='sending'
            self.save()
            data = packet(selected, self.sequence, self.domain)
        try:
            if self.sock is None:
                self.sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                self.sock.settimeout(5)
            self.sock.sendto(data, ('report.pskreporter.info',4739))
            status, error = 'sent (unconfirmed)', ''
        except OSError as exc:
            status, error = 'uncertain', str(exc)[:160]
        with self.lock:
            self.sequence = (self.sequence+len(selected)) % 2**32
            for row in selected:
                row.update(status=status,error=error)
            self.save()

    def run(self):
        while not self.stop.wait(1):
            if time.monotonic()>=self.next_send:
                try:
                    self.send_pending()
                except Exception:
                    # Persisted 'sending' rows are intentionally never retried.
                    pass
                self.next_send = time.monotonic()+300+random.uniform(0,30)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=6)
        if self.sock:
            self.sock.close()
