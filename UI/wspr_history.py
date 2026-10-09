"""Durable receiver/band history and explicitly enabled WSPRnet reporting.

SQLite is an index of the retained JSONL log and a durable upload outbox.
No remote uploads are created by migration or by merely opening a history view.
"""
import csv
import hashlib
import io
import ipaddress
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit, urlunsplit, urlencode
from urllib.request import Request, urlopen
import uuid

ENDPOINT = 'https://wsprnet.org/post/'
MAX_UPLOAD_AGE = 24 * 3600


def source_key(server):
    u = urlsplit(str(server).strip())
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
        raise ValueError('Invalid receiver address')
    host = u.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    port = u.port
    if port and port != (443 if u.scheme == 'https' else 80):
        host += ':' + str(port)
    return urlunsplit((u.scheme.lower(), host, u.path.rstrip('/'), '', ''))


def local_source(server):
    host = urlsplit(server).hostname or ''
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return host == 'localhost' or host.endswith('.local')


def record_time(record):
    value = record.get('cycle_start') or record.get('cycle_start_utc') or record.get('timestamp')
    if isinstance(value, (float, int)):
        result = float(value)
    else:
        from datetime import datetime
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    if not math.isfinite(result) or result <= 0:
        raise ValueError('Invalid spot time')
    return result


def validate_identity(call, grid):
    call, grid = str(call).strip().upper(), str(grid).strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9/-]{2,15}', call) or call in ('SWL', 'NOCALL'):
        raise ValueError('Enter your reporter callsign or unique SWL identifier')
    if not re.fullmatch(r'[A-R]{2}[0-9]{2}(?:[A-X]{2})?', grid):
        raise ValueError('Enter the receiving antenna’s 4- or 6-character grid')
    return call, grid


def upload_fields(record, call, grid):
    call, grid = validate_identity(call, grid)
    stamp = record_time(record)
    tx = str(record['callsign']).strip('<>').upper()
    tx_grid = str(record.get('grid', '')).upper()
    if not re.fullmatch(r'[A-Z0-9/]{3,20}', tx) or not re.fullmatch(r'[A-R]{2}\d{2}(?:[A-X]{2})?', tx_grid):
        raise ValueError('Spot has no resolved callsign/grid')
    freq, dial = float(record['frequency_mhz']), float(record['session_frequency_khz']) / 1000
    snr, dt, drift, power = (float(record[k]) for k in ('snr_db', 'dt_s', 'drift_hz', 'power_dbm'))
    if not all(math.isfinite(n) for n in (freq, dial, snr, dt, drift, power)):
        raise ValueError('Invalid numeric spot')
    if not (0 < freq <= 30.01 and abs(freq-dial) < .01 and -60 <= snr <= 50 and abs(dt) <= 30 and abs(drift) <= 100 and 0 <= power <= 60):
        raise ValueError('Spot outside reporting limits')
    return dict(function='wspr', date=time.strftime('%y%m%d', time.gmtime(stamp)),
                time=time.strftime('%H%M', time.gmtime(stamp)), sig=str(int(snr)), dt=f'{dt:.1f}',
                drift=str(int(drift)), tqrg=f'{freq:.6f}', tcall=tx, tgrid=tx_grid,
                dbm=str(int(power)), rcall=call, rgrid=grid, rqrg=f'{dial:.6f}',
                mode='2', version='iTuner-SDR-1')


class WSPRHistory:
    def __init__(self, log_file, *, start=True, post=None):
        self.log_file = Path(log_file).expanduser()
        self.path = self.log_file.with_name(self.log_file.stem + '-history.sqlite3')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sources (source TEXT PRIMARY KEY, name TEXT NOT NULL,
                is_local INTEGER NOT NULL, call TEXT DEFAULT '', grid TEXT DEFAULT '',
                enabled INTEGER DEFAULT 0, enabled_at REAL DEFAULT 0, confirmed INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS spots (id TEXT PRIMARY KEY, source TEXT NOT NULL,
                band TEXT NOT NULL, cycle REAL NOT NULL, run TEXT NOT NULL, data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS spots_lookup ON spots(source, band, cycle DESC);
            CREATE INDEX IF NOT EXISTS spots_run ON spots(run, cycle DESC);
            CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, source TEXT, band TEXT, started REAL);
            CREATE TABLE IF NOT EXISTS imports (path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER);
            CREATE TABLE IF NOT EXISTS outbox (spot TEXT PRIMARY KEY, source TEXT NOT NULL,
                payload TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER DEFAULT 0,
                next_at REAL DEFAULT 0, error TEXT DEFAULT '', sent_at REAL);
        ''')
        self.db.commit()
        self.path.chmod(0o600)
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.error = ''
        self.post = post or self._post
        self.worker = self.importer = None
        # A crash after sending but before receiving an acknowledgement is
        # ambiguous. Keep it visible for review instead of blindly resending.
        with self.db:
            self.db.execute("UPDATE outbox SET state='uncertain', error='Interrupted before acknowledgement; not resent' WHERE state='sending'")
        if start:
            self.importer = threading.Thread(target=self._import, daemon=True, name='wspr-history-import')
            self.importer.start()
            self.worker = threading.Thread(target=self._upload_loop, daemon=True, name='wspr-upload')
            self.worker.start()

    def register(self, config):
        source = source_key(config['server'])
        with self.lock, self.db:
            self.db.execute('INSERT INTO sources(source,name,is_local) VALUES(?,?,?) ON CONFLICT(source) DO UPDATE SET name=excluded.name',
                            (source, str(config.get('name') or source), int(local_source(source))))
        return source

    def begin_run(self, config):
        source = self.register(config)
        run = uuid.uuid4().hex
        with self.lock, self.db:
            self.db.execute('INSERT INTO runs VALUES(?,?,?,?)', (run, source, str(config['band']), time.time()))
        return run

    def record(self, record, live=False):
        if record.get('event') != 'wspr_decode':
            return
        source = source_key(record['session_server'])
        band, stamp = str(record['band_m']), record_time(record)
        record = dict(record, cycle_start=stamp)
        freq = float(record['frequency_mhz'])
        identity = [source, band, stamp, record['callsign'], record.get('grid'), round(freq, 6), record.get('power_dbm')]
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        run = str(record.get('run_id') or 'legacy-' + str(record.get('wspr_tile_id', 'unknown')))
        self.register(dict(server=source, name=record.get('session_receiver', source)))
        with self.lock, self.db:
            inserted = self.db.execute('INSERT OR IGNORE INTO spots VALUES(?,?,?,?,?,?)',
                (key, source, band, stamp, run, json.dumps(record))).rowcount
            profile = self.db.execute('SELECT * FROM sources WHERE source=?', (source,)).fetchone()
            if live and inserted and profile['enabled'] and stamp >= profile['enabled_at']:
                try:
                    payload = upload_fields(record, profile['call'], profile['grid'])
                except (ValueError, KeyError, TypeError) as exc:
                    self.db.execute('INSERT OR IGNORE INTO outbox(spot,source,payload,state,error) VALUES(?,?,?,?,?)',
                                    (key, source, '{}', 'skipped', str(exc)))
                else:
                    self.db.execute('INSERT OR IGNORE INTO outbox(spot,source,payload,state) VALUES(?,?,?,?)',
                                    (key, source, json.dumps(payload), 'queued'))
        return key

    def _import(self):
        try:
            self.import_logs()
        except Exception as exc:
            self.error = 'History import: ' + str(exc)
        finally:
            self.ready.set()

    def import_logs(self):
        paths = sorted(self.log_file.parent.glob(self.log_file.stem + '.*' + self.log_file.suffix)) + [self.log_file]
        for path in paths:
            if self.stop_event.is_set() or not path.is_file():
                continue
            stat = path.stat()
            with self.lock:
                old = self.db.execute('SELECT size,mtime FROM imports WHERE path=?', (str(path),)).fetchone()
            if old and (old['size'], old['mtime']) == (stat.st_size, stat.st_mtime_ns):
                continue
            with path.open(encoding='utf8') as f:
                for line in f:
                    if self.stop_event.is_set():
                        return
                    try:
                        self.record(json.loads(line))
                    except (ValueError, KeyError, TypeError):
                        continue
            with self.lock, self.db:
                self.db.execute('INSERT OR REPLACE INTO imports VALUES(?,?,?)', (str(path), stat.st_size, stat.st_mtime_ns))

    def sources(self):
        with self.lock:
            rows = [dict(r) for r in self.db.execute('SELECT * FROM sources ORDER BY is_local DESC,name')]
            for row in rows:
                row['bands'] = [r[0] for r in self.db.execute('SELECT DISTINCT band FROM spots WHERE source=? ORDER BY band', (row['source'],))]
                row['uploads'] = {r[0]:r[1] for r in self.db.execute('SELECT state,count(*) FROM outbox WHERE source=? GROUP BY state', (row['source'],))}
                last = self.db.execute("SELECT error FROM outbox WHERE source=? AND error!='' ORDER BY rowid DESC LIMIT 1", (row['source'],)).fetchone()
                row['last_error'] = last[0] if last else ''
            return rows

    def configure(self, source, call='', grid='', enabled=False, confirmed=False):
        source = source_key(source)
        if type(enabled) is not bool or type(confirmed) is not bool:
            raise ValueError('Invalid upload setting')
        if call or grid or enabled:
            call, grid = validate_identity(call, grid)
        if enabled and not confirmed:
            raise ValueError('Confirm ownership/permission and the receiving antenna location')
        with self.lock, self.db:
            old = self.db.execute('SELECT * FROM sources WHERE source=?', (source,)).fetchone()
            if old is None:
                raise ValueError('Unknown receiver')
            changed = (old['call'], old['grid']) != (call, grid)
            since = time.time() if enabled and (not old['enabled'] or changed) else old['enabled_at']
            self.db.execute('UPDATE sources SET call=?,grid=?,enabled=?,enabled_at=?,confirmed=? WHERE source=?',
                            (call, grid, int(enabled), since, int(confirmed), source))
            if not enabled or changed:
                self.db.execute("UPDATE outbox SET state='cancelled',error='Uploading disabled or identity changed' WHERE source=? AND state IN ('queued','retry')", (source,))
        return {'ok': True, 'enabled': enabled}

    def query(self, source='', band='', scope='all', run='', since=None, until=None, offset=0, limit=50, _max_rowid=None, q=''):
        limit = min(200, max(1, int(limit)))
        offset = max(0, min(10000000, int(offset)))
        if scope not in ('all', 'today', '24h', 'session', 'range'):
            raise ValueError('Unknown history filter')
        where, args = [], []
        if source:
            where.append('source=?'); args.append(source_key(source))
        if band:
            where.append('band=?'); args.append(str(band))
        now = time.time()
        if scope == 'today':
            since = int(now // 86400) * 86400
        elif scope == '24h':
            since = now - 86400
        elif scope == 'session':
            if not run:
                with self.lock:
                    sql = 'SELECT id FROM runs' + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY started DESC LIMIT 1'
                    row = self.db.execute(sql, args).fetchone()
                    run = row[0] if row else 'no-session'
            where.append('run=?'); args.append(run)
        for op, val in (('>=', since), ('<', until)):
            if val is not None:
                val = float(val)
                if not math.isfinite(val):
                    raise ValueError('Invalid date')
                where.append('cycle'+op+'?'); args.append(val)
        if q:
            where.append("instr(upper(coalesce(json_extract(data,'$.callsign'),'')),?)>0"); args.append(str(q).strip().upper()[:80])
        if _max_rowid is not None:
            where.append('rowid<=?'); args.append(int(_max_rowid))
        clause = ' WHERE ' + ' AND '.join(where) if where else ''
        with self.lock:
            total = self.db.execute('SELECT count(*) FROM spots'+clause, args).fetchone()[0]
            rows = self.db.execute('SELECT * FROM spots'+clause+' ORDER BY cycle DESC,id LIMIT ? OFFSET ?', [*args,limit,offset]).fetchall()
            spots = [dict(json.loads(r['data']), history_id=r['id'], source=r['source'], band=r['band'], run_id=r['run']) for r in rows]
        return dict(spots=spots, total=total, offset=offset, limit=limit, importing=not self.ready.is_set(), error=self.error)

    def recent(self, config, limit=96):
        return self.query(source=config['server'], band=config['band'], limit=limit)['spots']

    def csv(self, **filters):
        # Stream pages to the HTTP client; never load a whole archive in RAM.
        fields = ('cycle_start_utc','callsign','grid','snr_db','dt_s','frequency_mhz','power_dbm','drift_hz','session_receiver','source','band','run_id')
        buf = io.StringIO(); writer = csv.DictWriter(buf, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); yield buf.getvalue().encode(); buf.seek(0); buf.truncate()
        with self.lock:
            ceiling = self.db.execute('SELECT coalesce(max(rowid),0) FROM spots').fetchone()[0]
        offset = 0
        while True:
            page = self.query(**filters, offset=offset, limit=200, _max_rowid=ceiling)
            for row in page['spots']:
                row = dict(row, cycle_start_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(row['cycle_start'])))
                # Keep untrusted receiver names from becoming spreadsheet formulas.
                row = {k: ("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()}
                writer.writerow(row)
            yield buf.getvalue().encode(); buf.seek(0); buf.truncate()
            offset += len(page['spots'])
            if offset >= page['total'] or not page['spots']:
                return

    @staticmethod
    def _post(fields):
        req = Request(ENDPOINT, data=urlencode(fields).encode(), headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'iTuner-SDR/1'})
        with urlopen(req, timeout=10) as response:
            return response.read(4096).decode('utf8', 'replace')

    def upload_once(self):
        with self.lock, self.db:
            self.db.execute("UPDATE outbox SET state='expired',error='Older than 24 hours; retained locally' WHERE state IN ('queued','retry') AND spot IN (SELECT id FROM spots WHERE cycle<?)", (time.time()-MAX_UPLOAD_AGE,))
            row = self.db.execute("SELECT o.* FROM outbox o JOIN sources s ON o.source=s.source WHERE s.enabled=1 AND o.state IN ('queued','retry') AND o.next_at<=? ORDER BY o.rowid LIMIT 1", (time.time(),)).fetchone()
            if row is None:
                return False
            self.db.execute("UPDATE outbox SET state='sending',attempts=attempts+1 WHERE spot=?", (row['spot'],))
        state, error = 'sent', ''
        try:
            response = self.post(json.loads(row['payload']))
            if not re.search(r'\b[1-9]\d*\s+spot\(s\)\s+added', response):
                state, error = 'rejected', ('WSPRnet did not acknowledge a spot: ' + re.sub('<[^>]+>','',response))[:200]
        except Exception as exc:
            # A timeout may occur after acceptance; do not create duplicate
            # public reports by automatically re-posting an ambiguous request.
            state, error = 'uncertain', ('No acknowledgement; not resent: ' + str(exc))[:200]
        with self.lock, self.db:
            self.db.execute('UPDATE outbox SET state=?,error=?,sent_at=? WHERE spot=?', (state, error, time.time() if state=='sent' else None, row['spot']))
        return True

    def _upload_loop(self):
        while not self.stop_event.wait(2):
            try:
                self.upload_once()
            except Exception as exc:
                self.error = 'Upload queue: '+str(exc)

    def close(self):
        self.stop_event.set()
        for thread in (self.importer,self.worker):
            if thread:
                thread.join(timeout=12)
        with self.lock:
            self.db.close()
