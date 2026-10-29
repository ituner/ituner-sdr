"""Display-only ADS-B viewing windows. Never changes recording or RF state."""
import math
import time
from adsb_traffic import TRAIL_RETENTION, position_age

LIVE_WINDOWS=(15,30,60,120,300)
COVERAGE_WINDOWS=((60,'1 min'),(300,'5 min'),(1800,'30 min'),(3600,'1 hour'),
                  (21600,'6 hours'),(86400,'24 hours'),(604800,'7 days'),(0,'All recorded'))


class CoverageWindow:
    """Independent rolling dome window, with minute buckets for snapshot reuse."""
    def __init__(self):self.seconds=3600;self.started_at=None;self.revision=0

    def select(self, seconds, now=None):
        if seconds not in dict(COVERAGE_WINDOWS):raise ValueError('Invalid dome timespan')
        self.seconds=seconds;self.revision+=1
        self.started_at=None

    def reset(self, now=None):
        """Restart this display window without changing duration or stored history."""
        self.started_at=time.time() if now is None else now
        self.revision+=1

    @property
    def label(self):return dict(COVERAGE_WINDOWS)[self.seconds]

    def since(self, now):
        bucket=10 if self.seconds==60 else 60
        cutoff=max(0,math.floor(now/bucket)*bucket-self.seconds) if self.seconds else 0
        return max(self.started_at or 0,cutoff)


def number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def aged(plane, now):
    p = dict(plane)
    if not number(p.get('last_seen_at')):
        p['last_seen_at'] = now - p.get('seen', 100)
    if 'position_time' not in p:
        p['position_time'] = now-p['seen_pos'] if number(p.get('seen_pos')) else None
    p['seen'] = max(0, now - p['last_seen_at'])
    p['seen_pos'] = max(0, now - p['position_time']) if number(p.get('position_time')) else 1e9
    return p


def positioned(p):
    return bool(p and all(number(p.get(k)) for k in ('lat', 'lon', 'seen_pos'))
                and -90 <= p['lat'] <= 90 and -180 <= p['lon'] <= 180 and p['seen_pos'] < 15)


def freshness(p):
    if p.get('contact_known') is False:
        contact = 'Recorded ' + position_age(p['seen_pos'])
    else:
        contact = ('Contact ' if p.get('seen', 100) < 15 else 'Last heard ') + position_age(p.get('seen', 1e9))
    stamp = p.get('position_time', p.get('last_position_at'))
    position = ('Position ' if positioned(p) else 'Position old · ') + position_age(p['seen_pos']) if number(stamp) else 'No position'
    return contact + ' · ' + position


class TrafficView:
    def __init__(self, now):
        self.mode, self.trail_seconds, self.backdrop = 'live', 300, False
        self.history_trails = False
        self.history_labels = False
        self.history_icons = True
        self.live_seconds=15;self.live_armed=False
        self.fresh_at=None
        self.reset(now)

    def reset(self, now):
        self.opened_at = now
        self.coverage_live_since = None
        self.records = {}
        self.positions = {}
        self.initialized = False

    def start_fresh(self,now):
        self.reset(now);self.coverage_live_since=now;self.fresh_at=now;self.backdrop=False;self.mode='live';self.live_armed=False;self.trail_seconds=300;self.coverage_seconds=300

    def press_live(self):
        if self.mode!='live' or not self.live_armed:
            self.mode='live';self.live_armed=True;return False
        self.live_seconds=LIVE_WINDOWS[(LIVE_WINDOWS.index(self.live_seconds)+1)%len(LIVE_WINDOWS)]
        return True

    @property
    def live_label(self):return f'{self.live_seconds} s' if self.live_seconds<60 else f'{self.live_seconds//60} min'

    def coverage_since(self,now):
        span=getattr(self,'coverage_seconds',self.trail_seconds) or 300
        if self.mode=='history' and span>=90*86400:return 0
        if self.mode!='history':
            if self.coverage_live_since is None:
                self.coverage_live_since=max(0,math.floor(now/10)*10-span)
            cutoff=self.opened_at if self.mode=='session' else self.coverage_live_since
            return max(cutoff,self.fresh_at) if self.fresh_at is not None else cutoff
        cutoff=math.floor(now/10)*10-span
        return cutoff

    def ingest(self, planes, now):
        for raw in planes:
            if not raw.get('hex'): continue
            p = aged(raw, now)
            if positioned(p) and (self.fresh_at is None or p['position_time']>=self.fresh_at):
                previous_position=self.positions.get(p['hex'])
                if previous_position is None or p['position_time']>=previous_position['position_time']:self.positions[p['hex']]=p
            if not 0 <= p['seen'] < 15 or (self.fresh_at is not None and p['last_seen_at']<self.fresh_at): continue
            key = p['hex']
            previous = self.records.get(key)
            if previous and p['last_seen_at'] <= previous['plane']['last_seen_at']: continue
            self.records[key] = dict(plane=p, new=previous['new'] if previous else self.initialized and p['last_seen_at'] >= self.opened_at,
                                     arrived=previous['arrived'] if previous else now)
        self.initialized = True
        self.positions={k:p for k,p in self.positions.items() if p['position_time']>now-max(LIVE_WINDOWS)}
        if len(self.positions)>4096:self.positions=dict(sorted(self.positions.items(),key=lambda item:item[1]['position_time'])[-4096:])
        self.records = {k: v for k, v in self.records.items() if v['plane']['last_seen_at'] >= now-TRAIL_RETENTION}
        if len(self.records) > 4096:
            self.records = dict(sorted(self.records.items(), key=lambda item: item[1]['plane']['last_seen_at'])[-4096:])

    def live(self, planes, now):
        return [p for p in (aged(row, now) for row in planes) if p['seen'] < 15 and (self.mode=='history' or self.fresh_at is None or p['last_seen_at']>=self.fresh_at)]

    def cutoff(self, now):
        cutoff=max(self.opened_at, now-TRAIL_RETENTION) if self.mode == 'session' else now-self.trail_seconds
        return max(cutoff,self.fresh_at) if self.mode!='history' and self.fresh_at is not None else cutoff

    def endpoints(self, tracks, now):
        result = []
        for key, points in tracks.items():
            if not points: continue
            p = points[-1]
            if not all(number(p.get(k)) for k in ('time', 'lat', 'lon')): continue
            if not self.cutoff(now) <= p['time'] <= now or abs(p['lat']) > 90 or abs(p['lon']) > 180: continue
            result.append(aged(dict(hex=key, lat=p['lat'], lon=p['lon'], flight=p.get('flight'),
                                     alt_baro=p.get('alt'), track=p.get('track'), gs=p.get('gs'),
                                     baro_rate=p.get('baro_rate'), band=p.get('band','1090'), last_seen_at=p['time'], position_time=p['time'],
                                     last_position_at=p['time'], historical=True, contact_known=False), now))
        return result

    def aircraft(self, planes, tracks, now, map_only=False):
        live = self.live(planes, now)
        if self.mode == 'live':
            rows=self.live_positions(planes,tracks,now)
            if map_only:return list(rows.values())
            return list({**{p['hex']:p for p in live},**rows}.values())
        rows = {p['hex']: p for p in self.endpoints(tracks, now)} if self.mode == 'session' or self.trail_seconds else {}
        if not map_only and self.mode == 'session':
            rows.update({key: aged(v['plane'], now) for key, v in self.records.items() if v['plane']['last_seen_at'] >= self.cutoff(now)})
        for p in live:
            if self.mode == 'session' and p['last_seen_at'] < self.cutoff(now): continue
            if map_only and (not positioned(p) or (self.mode == 'session' and p.get('position_time', 0) < self.cutoff(now))): continue
            rows[p['hex']] = p
        return list(rows.values())

    def live_positions(self,planes,tracks,now,only_key=None):
        live=self.live(planes,now);contacts={p['hex']:p for p in live};rows={}
        cached=list(self.positions.values()) if only_key is None else [self.positions[only_key]] if only_key in self.positions else []
        candidates=([*cached,*self.endpoints(tracks,now)] if self.live_seconds>15 else [])+live
        for raw in candidates:
            p=aged(raw,now)
            if not number(p.get('position_time')) or not positioned(dict(p,seen_pos=0)) or not 0<=now-p['position_time']<self.live_seconds:continue
            if self.fresh_at is not None and p['position_time']<self.fresh_at:continue
            previous=rows.get(p['hex'])
            if previous and previous['position_time']>p['position_time']:continue
            contact=contacts.get(p['hex'])
            if contact:
                combined=dict(p,**contact)
                for key in ('lat','lon','position_time','seen_pos'):combined[key]=p[key]
                p=combined;p['contact_known']=True
            p['historical']=not positioned(p) or contact is None
            rows[p['hex']]=p
        return rows

    def counts(self, planes, now, tracks=None):
        live = self.live(planes, now)
        positions=len(self.live_positions(planes,tracks or {},now)) if self.mode=='live' else sum(positioned(p) for p in live)
        return dict(live=len(live), positions=positions, new=sum(v['new'] for v in self.records.values()))

    def arrival(self, key, now):
        v = self.records.get(key)
        return bool(v and v['new'] and 0 <= now-v['arrived'] < 12)

    def trail_visible(self, key, planes, now, trace=None):
        if self.mode == 'history':return self.history_trails
        return self.mode != 'live' or key in self.live_positions([p for p in planes if p.get('hex')==key],{key:trace} if trace else {},now,key)

    def labels_visible(self, live_labels=True):
        return self.history_labels if self.mode == 'history' else live_labels

    def icons_visible(self, live_icons=True):
        return self.history_icons if self.mode == 'history' else live_icons

    @property
    def label(self):
        return dict(live='LIVE', session='SINCE OPENED', history='HISTORY')[self.mode]
