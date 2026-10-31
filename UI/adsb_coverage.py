"""Persistent, directly received ADS-B positions and WGS84 reception geometry.

No missing position is classified as an obstruction. Storage is independent of
24-hour map trails; target seven days, subject to the aggregate storage budget.
Only the receiver worker writes; HTTP and touch read immutable cached snapshots.
"""
import json
import math
import sqlite3
import threading
import time
from bisect import bisect_right
from collections import OrderedDict
from station_profile import distance_m
from adsb_footprint import build_footprint, footprint_from_peaks, SECTOR_DEGREES
from pathlib import Path
from adsb_persistence import PERSIST_SECONDS
from adsb_geometry import camera_hull, enu_positions
from adsb_coverage_cache import CoverageAccumulator, project_rows
from adsb_storage import StorageBudget

RETENTION = 90 * 86400
FULL_RETENTION = 7 * 86400
MAX_POINTS = 250000
DISPLAY_POINTS = MAX_POINTS


def coverage_payload(data,after=None,cache_key=None):
    """Transmit a small overlapping tail after the initial immutable RAM snapshot."""
    meta=data.get('meta',{});site=meta.get('reference') or {}
    key=json.dumps([site.get('lat'),site.get('lon'),meta.get('reference_height_m')],separators=(',',':'))
    result=dict(data,cache_key=key)
    if (data.get('status')=='READY' and cache_key==key and finite(after)
            and after<=meta.get('last_position',0) and not meta.get('sampled')):
        result.update(delta=True,after=after,points=[p for p in data['points'] if data.get('base',0)+p[0]>=after])
        result.pop('segments',None) # Client rebuilds confirmed links from every retained point and break.
    return result


def retained_trail_links(points, keep, breaks, base):
    """Join thinned samples only when every original reception link was valid."""
    last={};retained={};links=[];component=0;output=0
    for index,p in enumerate(points):
        previous=last.get(p[1]);connected=False
        if previous:
            a,group=previous;dt=p[0]-a[0]
            connected=(0<dt<=15 and math.dist(a[2:5],p[2:5])<=500+400*dt
                       and bisect_right(breaks,base+p[0])==bisect_right(breaks,base+a[0]))
        if not connected:component+=1;group=component
        last[p[1]]=(p,group)
        if index not in keep:continue
        old=retained.get(p[1])
        if old and old[1]==group:links.append([old[0],output])
        retained[p[1]]=(output,group);output+=1
    return links


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
        self.maximum=dict(status='LOADING',meta={},footprint={});self.maximum_key=None;self.peak_revision=0
        self.scoped = {}
        self.projections = OrderedDict()
        self.storage = StorageBudget(self.root)
        self.storage_before = None
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
        self.next_flush=time.monotonic()+PERSIST_SECONDS;self.pending_prune_at=None
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

    def snapshot(self, since=None):
        if since==0:since=None
        if since is not None:
            if not finite(since) or since<0:raise ValueError('Invalid reception window')
            since=float(since)
            with self.lock:
                if since not in self.scoped:
                    if len(self.scoped)>=4:self.scoped.pop(next(iter(self.scoped)))
                    self.scoped[since]=dict(key=None,next_build=0,data=dict(status='LOADING',meta=dict(window_since=since,retained_positions=0,positioned_aircraft=0,**{k:self.data.get('meta',{}).get(k) for k in ('reference','reference_height_m','reference_height_known')}),aircraft=[],points=[],cells=[],breaks=[],base=0,footprint={}))
                self.scoped[since]['used_at']=time.monotonic()
                return self.scoped[since]['data']
        with self.lock:
            self.requested = True
            return self.data

    def maximum_snapshot(self):
        """Persistent maximum extent, independent of display windows or pruning."""
        with self.lock:return self.maximum

    def _open(self):
        if self.db is not None: return
        self.db = sqlite3.connect(':memory:')
        path=self.root/'coverage.sqlite3'
        if path.exists():
            disk=sqlite3.connect(str(path))
            try:disk.backup(self.db)
            finally:disk.close()
        self.db.execute('''CREATE TABLE IF NOT EXISTS positions (
            time REAL, hex TEXT, lat REAL, lon REAL, altitude REAL, gnss INTEGER,
            rssi REAL, label TEXT, PRIMARY KEY(time,hex,lat,lon))''')
        columns={r[1] for r in self.db.execute('PRAGMA table_info(positions)')}
        for column in ('site_lat','site_lon'):
            if column not in columns:self.db.execute('ALTER TABLE positions ADD COLUMN '+column+' REAL')
        if 'footprint_saved' not in columns:self.db.execute('ALTER TABLE positions ADD COLUMN footprint_saved INTEGER NOT NULL DEFAULT 0')
        self.db.execute('CREATE INDEX IF NOT EXISTS positions_footprint_pending ON positions(footprint_saved)')
        self.db.execute('CREATE TABLE IF NOT EXISTS footprint_sites (id INTEGER PRIMARY KEY,lat REAL,lon REAL,first_position REAL,last_position REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS footprint_peaks (site_id INTEGER,sector INTEGER,radius REAL,positions INTEGER,PRIMARY KEY(site_id,sector))')
        self.db.execute('CREATE TABLE IF NOT EXISTS coverage_meta (key TEXT PRIMARY KEY,value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS breaks (time REAL PRIMARY KEY)')
        if not self.db.execute("SELECT value FROM coverage_meta WHERE key='legacy_site'").fetchone():
            try:
                site=json.loads((self.root/'settings.json').read_text()).get('position')
                if site:self.db.execute('INSERT OR IGNORE INTO coverage_meta VALUES (?,?)',('legacy_site',json.dumps(site)))
            except (OSError,ValueError,AttributeError):pass
        self.db.commit()
        self.db.execute('CREATE TEMP TABLE dirty_positions(time,hex,lat,lon,PRIMARY KEY(time,hex,lat,lon))')
        saved = self.db.execute("SELECT value FROM coverage_meta WHERE key='storage_before'").fetchone()
        if saved:self.storage_before=float(saved[0])

    def add(self, rows):
        self._open()
        values = [p for p in (observation(row) for row in rows) if p and (self.storage_before is None or p[0]>self.storage_before)]
        before = self.db.total_changes
        self.db.executemany('INSERT OR IGNORE INTO positions (time,hex,lat,lon,altitude,gnss,rssi,label,site_lat,site_lon) VALUES (?,?,?,?,?,?,?,?,?,?)', values)
        added=self.db.total_changes-before
        if added:self.db.executemany('INSERT OR IGNORE INTO dirty_positions VALUES (?,?,?,?)',(p[:4] for p in values))
        self.db.commit()
        self.revision += added

    def _storage_prune(self, budget):
        """Budget takes precedence over seven-day retention; trim oldest evidence.

        Keep a durable timestamp watermark so rotated logs cannot resurrect data
        removed for space. Lifetime bearing maxima are small and remain intact.
        """
        page = self.db.execute('PRAGMA page_size').fetchone()[0]
        def occupied():
            pages=self.db.execute('PRAGMA page_count').fetchone()[0]
            free=self.db.execute('PRAGMA freelist_count').fetchone()[0]
            return (pages-free)*page
        if budget<64*1024:raise OSError('ADS-B storage budget has no room for the coverage database')
        while occupied()>budget:
            count=self.db.execute('SELECT count(*) FROM positions').fetchone()[0]
            if not count:raise OSError('ADS-B storage budget cannot fit required settings and database metadata')
            remove=max(1, min(count, math.ceil(count*(1-budget/max(1,occupied())*.85))))
            cutoff=self.db.execute('SELECT time FROM positions ORDER BY time LIMIT 1 OFFSET ?', (remove-1,)).fetchone()[0]
            self.db.execute('DELETE FROM positions WHERE time<=?',(cutoff,))
            self.db.execute('DELETE FROM breaks WHERE time<=?',(cutoff,))
            self.storage_before=max(self.storage_before or cutoff,cutoff)
            self.db.execute("INSERT OR REPLACE INTO coverage_meta VALUES ('storage_before',?)",(str(self.storage_before),))
            self.db.commit()
            # Compact the RAM database only under pressure. VACUUM can renumber
            # implicit rowids, so all incremental cursors must be discarded.
            self.projections.clear();self.revision+=1;self.key=None;self.requested=True
            self.db.execute('VACUUM')
        with self.storage.lock:self.storage.state['coverage_pruned_before']=self.storage_before

    def flush(self,force=False,_retry=False):
        """Persist every five minutes, with one 250 MiB directory-wide budget."""
        now=time.monotonic()
        if self.db is None or not force and now<self.next_flush:return False
        page=self.db.execute('PRAGMA page_size').fetchone()[0]
        occupied=(self.db.execute('PRAGMA page_count').fetchone()[0]-self.db.execute('PRAGMA freelist_count').fetchone()[0])*page
        budget=self.storage.database_budget(required=occupied)
        self._storage_prune(budget)
        disk=sqlite3.connect(str(self.root/'coverage.sqlite3'))
        try:
            disk.execute('PRAGMA temp_store=MEMORY')
            if self.storage_before is not None:
                with disk:
                    if disk.execute("SELECT 1 FROM sqlite_master WHERE name='positions'").fetchone():
                        disk.execute('DELETE FROM positions WHERE time<=?',(self.storage_before,))
                        disk.execute('DELETE FROM breaks WHERE time<=?',(self.storage_before,))
                        disk.execute("INSERT OR REPLACE INTO coverage_meta VALUES ('storage_before',?)",(str(self.storage_before),))
            size=disk.execute('PRAGMA page_count').fetchone()[0]*disk.execute('PRAGMA page_size').fetchone()[0]
            if size>budget:disk.execute('VACUUM')
            # Prevent a batch from growing the database past the remaining room.
            disk.execute('PRAGMA max_page_count='+str(max(1,budget//page)))
            schema=list(self.db.execute("SELECT type,sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table','index') AND name NOT LIKE 'sqlite_%' ORDER BY type DESC"))
            with disk:
                for kind,sql in schema:
                    if kind=='table':disk.execute(sql.replace('CREATE TABLE ','CREATE TABLE IF NOT EXISTS ',1))
                known={r[1] for r in disk.execute('PRAGMA table_info(positions)')}
                columns=list(self.db.execute('PRAGMA table_info(positions)'))
                for _,name,kind,_required,default,_pk in columns:
                    if name not in known:disk.execute(f'ALTER TABLE positions ADD COLUMN {name} {kind}'+(f' DEFAULT {default}' if default is not None else ''))
                for kind,sql in schema:
                    if kind=='index':disk.execute(sql.replace('CREATE INDEX ','CREATE INDEX IF NOT EXISTS ',1))
                names=','.join(r[1] for r in columns);marks=','.join('?' for _ in columns)
                rows=self.db.execute('SELECT p.* FROM positions p JOIN dirty_positions d USING(time,hex,lat,lon)').fetchall()
                disk.executemany(f'INSERT INTO positions ({names}) VALUES ({marks}) ON CONFLICT(time,hex,lat,lon) DO UPDATE SET footprint_saved=excluded.footprint_saved',rows)
                for table in ('footprint_peaks','footprint_sites','coverage_meta'):
                    disk.execute('DELETE FROM '+table)
                    values=self.db.execute('SELECT * FROM '+table).fetchall()
                    if values:disk.executemany('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in values[0])+')',values)
                disk.executemany('INSERT OR IGNORE INTO breaks VALUES (?)',self.db.execute('SELECT time FROM breaks'))
                if self.pending_prune_at is not None:self.prune(disk,self.pending_prune_at)
            self.db.execute('DELETE FROM dirty_positions');self.db.commit()
            self.pending_prune_at=None;self.next_flush=now+PERSIST_SECONDS
            self.storage.usage()
            return True
        except sqlite3.OperationalError as exc:
            if 'full' in str(exc).lower() and not _retry:
                disk.close()
                self._storage_prune(int(budget*.75))
                return self.flush(force=True,_retry=True)
            raise
        finally:disk.close()

    @staticmethod
    def prune(db,now):
        db.execute('DELETE FROM positions WHERE time < ?', (now-RETENTION,))
        recent=db.execute('SELECT count(*) FROM positions WHERE time >= ?',(now-FULL_RETENTION,)).fetchone()[0]
        db.execute('DELETE FROM positions WHERE rowid IN (SELECT rowid FROM positions WHERE time < ? ORDER BY time DESC LIMIT -1 OFFSET ?)',(now-FULL_RETENTION,max(0,MAX_POINTS-recent)))
        db.execute('DELETE FROM breaks WHERE time < ?', (now-RETENTION,))

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
        self.accumulate_maximum(site)
        maximum_key=(self.peak_revision,json.dumps(site,sort_keys=True))
        if maximum_key!=self.maximum_key:
            maximum=self.build_maximum(site)
            with self.lock:self.maximum=maximum;self.maximum_key=maximum_key
        with self.lock:
            pending, self.pending_breaks = self.pending_breaks, []
        if pending:
            self.db.executemany('INSERT OR IGNORE INTO breaks VALUES (?)', [(t,) for t in pending]); self.db.commit(); self.revision += 1
        if now >= self.next_prune:
            before_prune = self.db.total_changes
            self.prune(self.db,now);self.pending_prune_at=now
            if self.db.total_changes != before_prune:self.projections.clear()
            self.db.commit(); self.next_prune = now+3600; self.revision += 1
        with self.lock:
            height = self.height
            key = (self.revision, json.dumps(site, sort_keys=True), height)
            full=self.requested and (key!=self.key or self.error) and now>=self.next_build
            scopes=[since for since,cache in self.scoped.items() if cache['key']!=key and now>=cache['next_build'] and time.monotonic()-cache.get('used_at',0)<12]
            if full:self.requested=False
        if full:
            data=self.build(site,height)
            with self.lock:self.data=data;self.key=key;self.error='';self.next_build=now+5
        for since in scopes:
            data=self.build(site,height,since)
            with self.lock:
                if since in self.scoped:self.scoped[since].update(data=data,key=key,next_build=now+5)
        self.flush()

    def accumulate_maximum(self,site):
        legacy=self.db.execute("SELECT value FROM coverage_meta WHERE key='legacy_site'").fetchone()
        anchor=json.loads(legacy[0]) if legacy else site
        if not legacy and anchor:
            self.db.execute('INSERT OR IGNORE INTO coverage_meta VALUES (?,?)',('legacy_site',json.dumps(anchor)));self.db.commit()
        sites=[(r[0],dict(lat=r[1],lon=r[2])) for r in self.db.execute('SELECT id,lat,lon FROM footprint_sites')]
        while True:
            pending=self.db.execute('SELECT rowid,time,lat,lon,site_lat,site_lon FROM positions WHERE footprint_saved=0 LIMIT 10000').fetchall()
            if not pending:break
            groups={};saved=[]
            with self.db:
                for rowid,stamp,lat,lon,slat,slon in pending:
                    receiver=dict(lat=slat,lon=slon) if slat is not None and slon is not None else anchor
                    if not receiver:continue
                    match=min(((distance_m(receiver,s),ident,s) for ident,s in sites),default=(float('inf'),None,None))
                    if match[0]>100:
                        ident=self.db.execute('INSERT INTO footprint_sites(lat,lon,first_position,last_position) VALUES (?,?,?,?)',(receiver['lat'],receiver['lon'],stamp,stamp)).lastrowid
                        sites.append((ident,receiver));reference=receiver
                    else:_,ident,reference=match
                    group=groups.setdefault(ident,dict(site=reference,rows=[],first=stamp,last=stamp))
                    group['rows'].append((lat,lon));group['first']=min(group['first'],stamp);group['last']=max(group['last'],stamp);saved.append((rowid,))
                for ident,group in groups.items():
                    for sector in build_footprint(group['site'],group['rows'])['sectors']:
                        self.db.execute('''INSERT INTO footprint_peaks VALUES (?,?,?,?) ON CONFLICT(site_id,sector)
                            DO UPDATE SET radius=MAX(radius,excluded.radius),positions=positions+excluded.positions''',
                            (ident,int(sector['azimuth_deg']//SECTOR_DEGREES),sector['radius_m'],sector['positions']))
                    self.db.execute('UPDATE footprint_sites SET first_position=MIN(first_position,?),last_position=MAX(last_position,?) WHERE id=?',(group['first'],group['last'],ident))
                self.db.executemany('INSERT OR IGNORE INTO dirty_positions SELECT time,hex,lat,lon FROM positions WHERE rowid=?',saved)
                self.db.executemany('UPDATE positions SET footprint_saved=1 WHERE rowid=?',saved)
            if not saved:break
            self.peak_revision+=1

    def build_maximum(self,site):
        matches=[(distance_m(site,dict(lat=r[1],lon=r[2])),r) for r in self.db.execute('SELECT id,lat,lon,first_position,last_position FROM footprint_sites')] if site else []
        match=min(matches,default=(float('inf'),None))
        record=match[1] if match[0]<=100 else None
        peaks={r[0]:[r[1],r[2]] for r in self.db.execute('SELECT sector,radius,positions FROM footprint_peaks WHERE site_id=?',(record[0],))} if record else {}
        reference=dict(lat=record[1],lon=record[2]) if record else site
        count=sum(v[1] for v in peaks.values())
        return dict(status='READY' if peaks else 'EMPTY' if site else 'NO SITE',scope='accumulated maximum',
                    meta=dict(retained_positions=count,first_position=record[3] if record else None,last_position=record[4] if record else None),
                    footprint=footprint_from_peaks(reference,peaks))

    def build(self, site, height, since=None):
        meta = dict(window_since=since,reference=site, reference_height_m=height or 0, reference_height_known=height is not None,
                    retention_days=90, full_retention_days=7, storage_limit=MAX_POINTS,
                    storage_limit_bytes=self.storage.limit, storage_pruned_before=self.storage_before,
                    retained_positions=0, positioned_aircraft=0,
                    altitude_sources={}, horizontal_range_max_km=0, slant_range_max_km=0, max_altitude_ft=None,
                    rssi_min=-40, rssi_max=0)
        empty = dict(status='NO SITE' if not site else 'EMPTY', meta=meta, base=0, points=[], cells=[], aircraft=[], breaks=[], footprint=build_footprint(site,[]))
        if not site: return empty
        legacy = self.db.execute("SELECT value FROM coverage_meta WHERE key='legacy_site'").fetchone()
        if not legacy:
            self.db.execute('INSERT OR IGNORE INTO coverage_meta VALUES (?,?)', ('legacy_site', json.dumps(site)))
            self.db.commit()
        anchor = json.loads(legacy[0]) if legacy else site
        context = (json.dumps(site, sort_keys=True), height, json.dumps(anchor, sort_keys=True))
        key = (since, *context)
        accumulator = self.projections.pop(key, None)
        if accumulator is None and since is not None:
            # Minute-bucket rolling windows keep their already projected history.
            previous = next((k for k in reversed(self.projections)
                             if k[1:] == context and k[0] is not None and 0 < since-k[0] <= 120), None)
            if previous is not None:
                accumulator = self.projections.pop(previous)
                accumulator.advance(since)
        if accumulator is None:
            accumulator = CoverageAccumulator(site, height, since)
        high_water = self.db.execute('SELECT COALESCE(MAX(rowid),0) FROM positions').fetchone()[0]
        if high_water > accumulator.cursor:
            # Force the rowid access path: the time index otherwise scans the
            # whole selected week again just to reject old rowids.
            rows = self.db.execute('SELECT time,hex,lat,lon,altitude,gnss,rssi,label,site_lat,site_lon '
                                   'FROM positions NOT INDEXED WHERE rowid > ? AND time >= ? ORDER BY time,hex',
                                   (accumulator.cursor, since or 0)).fetchall()
            selected = []
            for r in rows:
                receiver = dict(lat=r[8], lon=r[9]) if r[8] is not None and r[9] is not None else anchor
                if receiver == site or distance_m(receiver, site) <= 100:
                    selected.append(r)
                else:
                    accumulator.excluded.append(r[0])
            if selected:
                accumulator.append(project_rows(selected, site, height, ecef(site['lat'], site['lon'], 0)))
            accumulator.cursor = high_water
        self.projections[key] = accumulator
        while len(self.projections) > 5:self.projections.popitem(last=False)
        first = math.floor(accumulator.records[0].stamp) if accumulator.records else 0
        breaks = [r[0] for r in self.db.execute('SELECT time FROM breaks WHERE time >= ? ORDER BY time', (first,))]
        return accumulator.snapshot(meta, breaks, DISPLAY_POINTS)

    def mark_break(self, stamp):
        with self.lock:self.pending_breaks.append(stamp)

    def close(self):
        if self.db is not None:self.flush(force=True);self.db.close();self.db=None
