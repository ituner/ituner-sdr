"""Display-only ADS-B viewing windows. Never changes recording or RF state."""
import math
from adsb_traffic import TRAIL_RETENTION, position_age


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
        self.reset(now)

    def reset(self, now):
        self.opened_at = now
        self.records = {}
        self.initialized = False

    def ingest(self, planes, now):
        for raw in planes:
            if not raw.get('hex'): continue
            p = aged(raw, now)
            if not 0 <= p['seen'] < 15: continue
            key = p['hex']
            previous = self.records.get(key)
            if previous and p['last_seen_at'] <= previous['plane']['last_seen_at']: continue
            self.records[key] = dict(plane=p, new=previous['new'] if previous else self.initialized and p['last_seen_at'] >= self.opened_at,
                                     arrived=previous['arrived'] if previous else now)
        self.initialized = True
        self.records = {k: v for k, v in self.records.items() if v['plane']['last_seen_at'] >= now-TRAIL_RETENTION}
        if len(self.records) > 4096:
            self.records = dict(sorted(self.records.items(), key=lambda item: item[1]['plane']['last_seen_at'])[-4096:])

    def live(self, planes, now):
        return [p for p in (aged(row, now) for row in planes) if p['seen'] < 15]

    def cutoff(self, now):
        return max(self.opened_at, now-TRAIL_RETENTION) if self.mode == 'session' else now-self.trail_seconds

    def endpoints(self, tracks, now):
        result = []
        for key, points in tracks.items():
            if not points: continue
            p = points[-1]
            if not all(number(p.get(k)) for k in ('time', 'lat', 'lon')): continue
            if not self.cutoff(now) <= p['time'] <= now or abs(p['lat']) > 90 or abs(p['lon']) > 180: continue
            result.append(aged(dict(hex=key, lat=p['lat'], lon=p['lon'], flight=p.get('flight'),
                                     alt_baro=p.get('alt'), track=p.get('track'), gs=p.get('gs'),
                                     baro_rate=p.get('baro_rate'), last_seen_at=p['time'], position_time=p['time'],
                                     last_position_at=p['time'], historical=True, contact_known=False), now))
        return result

    def aircraft(self, planes, tracks, now, map_only=False):
        live = self.live(planes, now)
        if self.mode == 'live': return [p for p in live if positioned(p)] if map_only else live
        rows = {p['hex']: p for p in self.endpoints(tracks, now)} if self.mode == 'session' or self.trail_seconds else {}
        if not map_only and self.mode == 'session':
            rows.update({key: aged(v['plane'], now) for key, v in self.records.items() if v['plane']['last_seen_at'] >= self.cutoff(now)})
        for p in live:
            if self.mode == 'session' and p['last_seen_at'] < self.cutoff(now): continue
            if map_only and (not positioned(p) or (self.mode == 'session' and p.get('position_time', 0) < self.cutoff(now))): continue
            rows[p['hex']] = p
        return list(rows.values())

    def counts(self, planes, now):
        live = self.live(planes, now)
        return dict(live=len(live), positions=sum(positioned(p) for p in live), new=sum(v['new'] for v in self.records.values()))

    def arrival(self, key, now):
        v = self.records.get(key)
        return bool(v and v['new'] and 0 <= now-v['arrived'] < 12)

    def trail_visible(self, key, planes, now):
        return self.mode != 'live' or any(p['hex'] == key and positioned(p) for p in self.live(planes, now))

    @property
    def label(self):
        return dict(live='LIVE', session='SINCE OPENED', history='HISTORY')[self.mode]
