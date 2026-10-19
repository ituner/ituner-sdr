"""Persistent, directly received ADS-B positions and WGS84 reception geometry.

No missing position is classified as an obstruction. Storage is independent of
24-hour map trails; retain up to 90 days / 250,000 positions (whichever is less).
Only the receiver worker writes; HTTP and touch read immutable cached snapshots.
"""
import json
import math
import sqlite3
import threading
import time
from station_profile import distance_m
from pathlib import Path

RETENTION = 90 * 86400
MAX_POINTS = 250000
DISPLAY_POINTS = 20000


def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def ecef(lat, lon, height):
    p, l = math.radians(lat), math.radians(lon)
    n = 6378137 / math.sqrt(1 - 6.6943799901413165e-3 * math.sin(p)**2)
    return ((n+height)*math.cos(p)*math.cos(l), (n+height)*math.cos(p)*math.sin(l),
            (n*(1-6.6943799901413165e-3)+height)*math.sin(p))


def enu(lat, lon, height, site, origin=None):
    x, y, z = (a-b for a, b in zip(ecef(lat, lon, height), origin or ecef(site['lat'], site['lon'], 0)))
    p, l = math.radians(site['lat']), math.radians(site['lon'])
    return (-math.sin(l)*x+math.cos(l)*y,
            -math.sin(p)*math.cos(l)*x-math.sin(p)*math.sin(l)*y+math.cos(p)*z,
            math.cos(p)*math.cos(l)*x+math.cos(p)*math.sin(l)*y+math.sin(p)*z)


def observation(row):
    a = row.get('aircraft') or {}
    if not isinstance(a, dict): return None
    stamp, age = row.get('time'), a.get('seen_pos')
    if not finite(stamp) or not finite(age) or not 0 <= age <= 10: return None
    if not isinstance(a.get('hex'), str) or not a['hex']: return None
    if not all(finite(a.get(k)) for k in ('lat', 'lon')): return None
    if not -90 <= a['lat'] <= 90 or not -180 <= a['lon'] <= 180: return None
    if a.get('type') not in ('adsb_icao', 'adsb_other'): return None
    if any(k in (a.get(source) or []) for source in ('mlat', 'tisb') for k in ('lat', 'lon')): return None
    gnss = finite(a.get('alt_geom'))
    altitude = a.get('alt_geom') if gnss else a.get('alt_baro')
    if not finite(altitude) or not -2000 <= altitude <= 100000: return None
    rssi = a.get('rssi') if finite(a.get('rssi')) else None
    site=row.get('receiver_position') or {}
    if not isinstance(site,dict):site={}
    valid_site=all(finite(site.get(k)) for k in ('lat','lon')) and -90<=site['lat']<=90 and -180<=site['lon']<=180
    return (round(stamp-age, 3), a['hex'].lower(), a['lat'], a['lon'], altitude,
            int(gnss), rssi, str(a.get('flight') or '').strip()[:32],
            site['lat'] if valid_site else None,site['lon'] if valid_site else None)


class ReceptionCoverage:
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.data = dict(status='LOADING', meta={}, aircraft=[], points=[], cells=[], breaks=[], base=0)
        self.pending_breaks = []
        self.revision = 0
        self.key = None
        self.error = ''
        self.imported = False
        self.db = None
        self.next_build = 0
        self.requested = True
        self.next_prune = 0
        self.height = None
        try:
            value = json.loads((self.root/'coverage-settings.json').read_text()).get('height_m')
            if finite(value) and -500 <= value <= 9000: self.height = value
        except (ValueError, OSError, AttributeError): pass

    def set_height(self, value):
        if value is not None and (not finite(value) or not -500 <= value <= 9000):
            raise ValueError('Antenna ellipsoid height must be -500 to 9000 metres, or empty if unknown')
        with self.lock:
            temporary = self.root/'coverage-settings.tmp'
            temporary.write_text(json.dumps(dict(height_m=value)))
            temporary.replace(self.root/'coverage-settings.json')
            self.height = value
            self.requested = True
            self.key = None

    def snapshot(self):
        with self.lock:
            self.requested = True
            return self.data

    def _open(self):
        if self.db is not None: return
        self.db = sqlite3.connect(str(self.root/'coverage.sqlite3'))
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS positions (
            time REAL, hex TEXT, lat REAL, lon REAL, altitude REAL, gnss INTEGER,
            rssi REAL, label TEXT, PRIMARY KEY(time,hex,lat,lon))''')
        columns={r[1] for r in self.db.execute('PRAGMA table_info(positions)')}
        for column in ('site_lat','site_lon'):
            if column not in columns:self.db.execute('ALTER TABLE positions ADD COLUMN '+column+' REAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS coverage_meta (key TEXT PRIMARY KEY,value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS breaks (time REAL PRIMARY KEY)')
        if not self.db.execute("SELECT value FROM coverage_meta WHERE key='legacy_site'").fetchone():
            try:
                site=json.loads((self.root/'settings.json').read_text()).get('position')
                if site:self.db.execute('INSERT OR IGNORE INTO coverage_meta VALUES (?,?)',('legacy_site',json.dumps(site)))
            except (OSError,ValueError,AttributeError):pass
        self.db.commit()

    def add(self, rows):
        self._open()
        values = [p for p in (observation(row) for row in rows) if p]
        before = self.db.total_changes
        self.db.executemany('INSERT OR IGNORE INTO positions (time,hex,lat,lon,altitude,gnss,rssi,label,site_lat,site_lon) VALUES (?,?,?,?,?,?,?,?,?,?)', values)
        self.db.commit()
        self.revision += self.db.total_changes-before

    def import_logs(self):
        if self.imported: return
        self._open()
        # Replay rotated logs once at startup; primary keys make restarts idempotent.
        for path in sorted(self.root.glob('flights.jsonl*'), reverse=True):
            batch = []
            with path.open(errors='replace') as source:
                for line in source:
                    try:
                        row = json.loads(line)
                        if isinstance(row, dict) and finite(row.get('time')) and row['time'] >= time.time()-RETENTION:
                            batch.append(row)
                    except (ValueError, TypeError): pass
                    if len(batch) >= 1000: self.add(batch); batch = []
            self.add(batch)
        for path in self.root.glob('receiver.jsonl*'):
            with path.open(errors='replace') as source:
                for line in source:
                    try:
                        row = json.loads(line)
                        if row.get('event') in ('start','stop','released','assigned','readsb_exited','location') and finite(row.get('time')):
                            self.db.execute('INSERT OR IGNORE INTO breaks VALUES (?)', (row['time'],))
                    except (ValueError, AttributeError): pass
        self.db.commit()
        self.imported = True

    def tick(self, site, now=None):
        now = time.time() if now is None else now
        self.import_logs()
        with self.lock:
            pending, self.pending_breaks = self.pending_breaks, []
        if pending:
            self.db.executemany('INSERT OR IGNORE INTO breaks VALUES (?)', [(t,) for t in pending]); self.db.commit(); self.revision += 1
        if now >= self.next_prune:
            self.db.execute('DELETE FROM positions WHERE time < ?', (now-RETENTION,))
            self.db.execute('DELETE FROM positions WHERE rowid IN (SELECT rowid FROM positions ORDER BY time DESC LIMIT -1 OFFSET ?)', (MAX_POINTS,))
            self.db.execute('DELETE FROM breaks WHERE time < ?', (now-RETENTION,))
            self.db.commit(); self.next_prune = now+3600; self.revision += 1
        with self.lock:
            height = self.height
            key = (self.revision, json.dumps(site, sort_keys=True), height)
            if not self.requested or (key == self.key and not self.error) or now < self.next_build: return
            self.requested = False
        data = self.build(site, height)
        with self.lock:
            self.data = data; self.key = key; self.error = ''; self.next_build = now+5

    def build(self, site, height):
        meta = dict(reference=site, reference_height_m=height or 0, reference_height_known=height is not None,
                    retention_days=90, storage_limit=MAX_POINTS, retained_positions=0, positioned_aircraft=0,
                    altitude_sources={}, horizontal_range_max_km=0, slant_range_max_km=0, max_altitude_ft=None,
                    rssi_min=-40, rssi_max=0)
        empty = dict(status='NO SITE' if not site else 'EMPTY', meta=meta, base=0, points=[], cells=[], aircraft=[], breaks=[])
        if not site: return empty
        rows = self.db.execute('SELECT time,hex,lat,lon,altitude,gnss,rssi,label,site_lat,site_lon FROM positions ORDER BY time,hex').fetchall()
        legacy=self.db.execute("SELECT value FROM coverage_meta WHERE key='legacy_site'").fetchone()
        if not legacy:
            self.db.execute('INSERT OR IGNORE INTO coverage_meta VALUES (?,?)',('legacy_site',json.dumps(site)));self.db.commit()
        anchor=json.loads(legacy[0]) if legacy else site
        count=len(rows)
        rows=[r for r in rows if distance_m(dict(lat=r[8],lon=r[9]) if r[8] is not None and r[9] is not None else anchor,site)<=100]
        meta.update(excluded_other_sites=count-len(rows),coverage_site_radius_m=100)
        if not rows: return empty
        origin = ecef(site['lat'], site['lon'], 0)
        names = {}; points = []; cells = {}; addresses = sorted({r[1] for r in rows}); indexes = {a:i for i,a in enumerate(addresses)}
        base = math.floor(rows[0][0]); max_range = 0; max_slant = 0; max_alt = None; max_alt_index = 0; max_range_index = 0; sources = {'GNSS':0,'barometric approximation':0}
        for t, address, lat, lon, alt, gnss, rssi, label, _site_lat, _site_lon in rows:
            if label: names[address] = label
            e, n, u = enu(lat, lon, alt*.3048, site, origin)
            distance = math.hypot(e, n); up = u-(height or 0)
            az = math.degrees(math.atan2(e,n)) % 360; el = math.degrees(math.atan2(up,distance))
            sources['GNSS' if gnss else 'barometric approximation'] += 1
            if max_alt is None or alt > max_alt:
                max_alt = alt; max_alt_index = len(points)
                meta.update(max_altitude_ft=alt, max_altitude_source='GNSS' if gnss else 'BARO ≈', max_altitude_aircraft=label or address)
            if distance > max_range: max_range = distance; max_range_index = len(points)
            max_slant = max(max_slant, math.hypot(distance, up))
            points.append([round(t-base,3), indexes[address], round(e,2), round(n,2), round(u,2), alt, rssi, gnss, label or address])
            if el >= 0:
                cell = cells.setdefault((int(az//4)*4, min(88,int(el//2)*2)), [0,0,0,set(),0,0])
                cell[0] += 1
                if rssi is not None: cell[1] += rssi; cell[2] += 1
                cell[3].add(address); cell[4] = max(cell[4], distance)
        levels = [r[6] for r in rows if r[6] is not None]
        meta.update(retained_positions=len(points), positioned_aircraft=len(addresses), first_position=rows[0][0], last_position=rows[-1][0],
                    horizontal_range_max_km=max_range/1000, slant_range_max_km=max_slant/1000, altitude_sources=sources,
                    cells_observed=len(cells), rssi_min=min(levels) if levels else -40, rssi_max=max(levels) if levels else 0)
        # All cells and extrema use the complete history. Bound only rendered dots.
        if len(points)>DISPLAY_POINTS:
            keep=set(range(0,len(points),math.ceil(len(points)/DISPLAY_POINTS))) | {max_alt_index,max_range_index,len(points)-1}
            points=[p for i,p in enumerate(points) if i in keep]
        meta['displayed_positions']=len(points)
        breaks = [r[0] for r in self.db.execute('SELECT time FROM breaks WHERE time >= ? ORDER BY time', (base,))]
        return dict(status='READY', meta=meta, base=base, aircraft=[dict(hex=a,label=names.get(a,a)) for a in addresses], points=points,
                    cells=[[a,e,v[0],v[1]/v[2] if v[2] else None,len(v[3]),v[4]] for (a,e),v in cells.items()], breaks=breaks)

    def mark_break(self, stamp):
        with self.lock:self.pending_breaks.append(stamp)

    def close(self):
        if self.db is not None: self.db.close(); self.db = None
