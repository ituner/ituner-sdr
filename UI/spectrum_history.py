"""Bounded, persistent individual sweeps; never reconstruct history from averages."""
import base64
from contextlib import contextmanager
import hashlib
import json
import math
import sqlite3
import threading
import time
import zlib
import numpy as np

MAX_ROWS = 720
MAX_AGE = 24 * 3600


def signature(data):
    config = data.get('settings', {})
    values = [config.get(k) for k in ('low', 'high', 'bin', 'gain', 'ppm')]
    # Normalize JSON numeric representation across saved files and driver values.
    values = [float(v) if v is not None else None for v in values]
    values += [data.get('device', {}).get('id'), data.get('rate'), data.get('fft')]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()[:24]


def encode(power, masked):
    # 0 = unmeasured; 1 = clipped; 2..255 = -200..53 dBFS/Hz (1 dB steps).
    return bytes(1 if i < len(masked) and masked[i] else
                 max(2, min(255, round(value) + 202))
                 if isinstance(value, (int, float)) and math.isfinite(value) else 0
                 for i, value in enumerate(power))


class SweepHistory:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sweeps (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                       'identity TEXT UNIQUE, signature TEXT, started REAL, finished REAL, '
                       'low REAL, high REAL, bin REAL, gain REAL, pass INTEGER, power BLOB)')
            db.execute('CREATE INDEX IF NOT EXISTS sweeps_signature ON sweeps(signature, id)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def prune(self, db):
        db.execute('DELETE FROM sweeps WHERE finished < ?', (time.time() - MAX_AGE,))
        db.execute('DELETE FROM sweeps WHERE id NOT IN (SELECT id FROM sweeps ORDER BY id DESC LIMIT ?)', (MAX_ROWS,))

    def append(self, data):
        if not data.get('complete') or not data.get('power'):
            return
        config = data['settings']
        identity = str(data.get('started')) + ':' + str(data.get('sweep'))
        with self.lock, self.connect() as db:
            db.execute('INSERT OR IGNORE INTO sweeps '
                       '(identity,signature,started,finished,low,high,bin,gain,pass,power) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (identity, signature(data), data.get('sweep_started', data['started']),
                        data['finished'], config['low'], config['high'], config['bin'], config['gain'],
                        data.get('sweep', 1), zlib.compress(encode(data['power'], data.get('masked', [])))))
            self.prune(db)

    def metadata(self, data):
        key = signature(data)
        with self.lock, self.connect() as db:
            self.prune(db)
            count, latest = db.execute('SELECT COUNT(*), MAX(id) FROM sweeps WHERE signature=?', (key,)).fetchone()
        return dict(key=key, count=count, latest_id=latest or 0, max_rows=MAX_ROWS, max_age=MAX_AGE)

    def read(self, data, after=0, low=None, high=None, columns=1024, raw=False):
        config = data.get('settings')
        if not config:
            return dict(key=signature(data), rows=[], latest_id=0)
        low = float(low) if low is not None else config['low']
        high = float(high) if high is not None else config['high']
        if not math.isfinite(low) or not math.isfinite(high):
            raise ValueError('Invalid waterfall frequency range')
        low = max(config['low'], low)
        high = min(config['high'], high)
        columns = max(1, min(2048, int(columns)))
        after = max(0, int(after))
        if not math.isfinite(low) or not math.isfinite(high) or high <= low:
            raise ValueError('Invalid waterfall frequency range')
        key = signature(data)
        result = []
        with self.lock, self.connect() as db:
            self.prune(db)
            for identity, started, finished, gain, sweep, blob in db.execute(
                    'SELECT id,started,finished,gain,pass,power FROM sweeps '
                    'WHERE signature=? AND id>? ORDER BY id', (key, after)):
                power = zlib.decompress(blob)
                values=np.frombuffer(power,dtype=np.uint8);n=len(values)
                if not n:continue
                x=np.arange(columns,dtype=float)
                start=np.clip(((low+(high-low)*x/columns-config['low'])/config['bin']).astype(int),0,n-1)
                end=np.minimum(n,np.maximum(start+1,np.ceil((low+(high-low)*(x+1)/columns-config['low'])/config['bin']).astype(int)))
                indices=start[:,None]+np.arange(int(np.max(end-start)))
                valid=indices<end[:,None];samples=values[np.minimum(indices,n-1)]
                cells=np.max(np.where(valid,samples,0),axis=1).astype(np.uint8)
                cells[np.any(valid&(samples==1),axis=1)]=1
                result.append(dict(id=identity, started=started, finished=finished, gain=gain,
                                   sweep=sweep, values=cells if raw else base64.b64encode(cells.tobytes()).decode()))
        return dict(key=key, rows=result, low=low, high=high, columns=columns,
                    latest_id=result[-1]['id'] if result else after)
