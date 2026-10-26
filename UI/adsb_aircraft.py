"""On-demand aircraft identity and thumbnails; never runs on the radio/UI thread."""
from collections import OrderedDict
import gzip
from io import BytesIO
import json
from pathlib import Path
import queue
import re
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

USER_AGENT = 'iTuner-SDR/1.0 (+https://github.com/ituner/ituner-sdr)'
PHOTO_HOSTS = {'airport-data.com', 'www.airport-data.com', 'image.airport-data.com'}
API_HOSTS = {'api.adsbdb.com', 'hexdb.io'}


def valid_url(url, hosts):
    if not isinstance(url, str): return False
    try:
        p = urlsplit(url)
        return p.scheme == 'https' and p.hostname in hosts and p.port in (None, 443) and not p.username and not p.password
    except ValueError: return False


class RestrictedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not valid_url(newurl, API_HOSTS | PHOTO_HOSTS): raise ValueError('Unsupported redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit=65536):
    if not valid_url(url, API_HOSTS | PHOTO_HOSTS): raise ValueError('Unsupported aircraft source')
    with build_opener(RestrictedRedirect()).open(Request(url, headers={'User-Agent': USER_AGENT}), timeout=4) as response:
        body = response.read(limit + 1)
        if len(body) > limit: raise ValueError('Aircraft response too large')
        return body


def text(value):
    return ' '.join(value.split())[:160] if isinstance(value, str) else ''


class AircraftDetails:
    """Bounded single worker, persistent seven-day cache; look up only opened cards."""
    def __init__(self, root, map_root, fetcher=fetch):
        self.root = Path(root)/'aircraft-details'; self.map_root = Path(map_root)/'db2'
        self.fetch = fetcher; self.rows = OrderedDict(); self.pending = set()
        self.lock = threading.Lock(); self.jobs = queue.Queue(maxsize=32)
        self.closed = threading.Event(); self.thread = None

    def snapshot(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-fA-F]{6}', key):
            return dict(status='unavailable', hex=str(key), message='No ICAO aircraft identity')
        key = key.lower()
        with self.lock:
            row = self.rows.get(key)
            if row: self.rows.move_to_end(key)
            if (not row or row.get('expires', 0) < time.time()) and key not in self.pending and not self.closed.is_set():
                try:
                    self.jobs.put_nowait(key); self.pending.add(key)
                    if self.thread is None:
                        self.thread = threading.Thread(target=self._worker, name='aircraft-details', daemon=True); self.thread.start()
                except queue.Full: pass
            return dict(row or {}, hex=key, status='loading' if key in self.pending else (row or {}).get('status', 'unavailable'))

    def _publish(self, key, row):
        with self.lock:
            self.rows[key] = row; self.rows.move_to_end(key)
            while len(self.rows) > 128: self.rows.popitem(last=False)

    def _local(self, key):
        def load(name):
            b = (self.map_root/name).read_bytes()
            return json.loads(gzip.decompress(b) if b.startswith(b'\x1f\x8b') else b)
        hexkey = key.upper(); record = None
        for level in range(1, 7):
            data = load(hexkey[:level]+'.js')
            record = data.get(hexkey[level:])
            if record is not None: break
            if hexkey[:level+1] not in data.get('children', []): break
        if not isinstance(record, list): return {}
        registration = text(record[0] if record else '')
        code = text(record[1] if len(record)>1 else '')
        model = text(record[3] if len(record)>3 else '')
        if not model and code:
            try: model = text(load('icao_aircraft_types2.js').get(code, [''])[0])
            except (OSError, ValueError, IndexError, TypeError): pass
        return dict(registration=registration, icao_type=code, model=model, source='Local tar1090 database')

    def _resolve(self, key):
        row = {}
        try:
            saved = json.loads((self.root/(key+'.json')).read_text())
            if saved.get('hex') == key and saved.get('expires', 0) > time.time(): return saved
        except (OSError, ValueError, AttributeError): pass
        try: row.update(self._local(key))
        except (OSError, ValueError, TypeError, IndexError): pass
        self._publish(key, dict(row, status='loading'))
        online = False
        try:
            payload = json.loads(self.fetch('https://api.adsbdb.com/v0/aircraft/'+key))
            data = payload.get('response', {}).get('aircraft', {})
            if text(data.get('mode_s')).lower() == key:
                for field, source in [('manufacturer','manufacturer'),('model','type'),('registration','registration'),('icao_type','icao_type')]:
                    if text(data.get(source)): row[field] = text(data[source])
                row['source'] = 'adsbdb / PlaneBase'; online = True
                url, link = data.get('url_photo_thumbnail'), data.get('url_photo')
                if valid_url(url, PHOTO_HOSTS) and valid_url(link, PHOTO_HOSTS):
                    row['photo'] = dict(url=url, link=link, credit='Photo: Airport-Data.com')
        except (OSError, ValueError, TypeError, AttributeError): pass
        if not row.get('manufacturer'):
            try:
                data = json.loads(self.fetch('https://hexdb.io/api/v1/aircraft/'+key))
                if text(data.get('ModeS')).lower() == key:
                    for field, source in [('manufacturer','Manufacturer'),('model','Type'),('registration','Registration'),('icao_type','ICAOTypeCode')]:
                        if text(data.get(source)): row[field] = text(data[source])
                    row['source'] = 'hexdb / PlaneBase'; online = True
            except (OSError, ValueError, TypeError, AttributeError): pass
        if row.get('photo'):
            try:
                from PIL import Image
                raw = self.fetch(row['photo']['url'], 512*1024)
                with Image.open(BytesIO(raw)) as image:
                    if image.width*image.height > 4_000_000: raise ValueError('Photo too large')
                    image.thumbnail((240,160)); image = image.convert('RGB')
                    self.root.mkdir(parents=True, exist_ok=True)
                    path = self.root/(key+'.jpg'); tmp = path.with_suffix('.tmp')
                    image.save(tmp, format='JPEG', quality=85); tmp.replace(path)
                    row['photo_cached'] = True
            except (OSError, ValueError, ImportError): pass
        known = bool(row.get('model') or row.get('manufacturer') or row.get('registration'))
        row.update(hex=key, status='ready' if known else 'unavailable', expires=time.time()+(7*86400 if online else 300))
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root/(key+'.json'); tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(row)); tmp.replace(path)
            # Bound persistent metadata and photos together, retaining recently opened cards.
            entries = sorted(self.root.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
            for old in entries[512:]:
                old.unlink(missing_ok=True); old.with_suffix('.jpg').unlink(missing_ok=True)
        except OSError: pass
        return row

    def _worker(self):
        while not self.closed.is_set():
            try: key = self.jobs.get(timeout=.25)
            except queue.Empty: continue
            try: self._publish(key, self._resolve(key))
            except Exception: self._publish(key, dict(hex=key,status='unavailable',expires=time.time()+300))
            finally:
                with self.lock: self.pending.discard(key)
                self.jobs.task_done()

    def photo_path(self, key):
        return self.root/(key.lower()+'.jpg') if isinstance(key,str) and re.fullmatch(r'[0-9a-fA-F]{6}',key) else None

    def close(self):
        self.closed.set()
