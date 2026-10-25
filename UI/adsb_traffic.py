"""Traffic history and the band contract shared by both ADS-B interfaces."""
from collections import OrderedDict, deque
import gzip
import json
import math

TRAIL_RETENTION = 24*60*60
TRAIL_WINDOWS = (0, 300, 900, 1800, 3600, 10800, 21600, 43200, TRAIL_RETENTION)
MAP_ZOOM_MIN = .55
# Tracking stays useful well beyond the imagery's native resolution.
MAP_ZOOM_MAX = 12000.0


def trail_label(seconds):
    return 'OFF' if not seconds else f'{seconds//3600} H' if seconds>=3600 else f'{seconds//60} MIN'


def startup_notice_visible(state, now):
    started=state.get('started_at')
    return bool(state.get('enabled') and isinstance(started,(int,float)) and 0<=now-started<5)


def reception_summary(state, now):
    def age(stamp):
        if not isinstance(stamp,(int,float)) or not math.isfinite(stamp):return 'none'
        seconds=max(0,int(now-stamp))
        return 'now' if seconds<1 else f'{seconds}s ago' if seconds<60 else f'{seconds//60}m ago' if seconds<3600 else f'{seconds//3600}h ago'
    return 'Last message: '+age(state.get('last_message_at'))+' · Last position: '+age(state.get('last_position_at'))


def position_age(seconds):
    seconds=max(0,int(seconds))
    return f'{seconds}s ago' if seconds<60 else f'{seconds//60}m ago' if seconds<3600 else f'{seconds//3600}h ago'


def historical_aircraft(tracks, live, window, now):
    """Saved endpoints are selectable history, never fresh receiver targets."""
    if not window:return []
    current={p['hex'] for p in live}
    result=[]
    for key, points in tracks.items():
        if key in current or not points:continue
        point=points[-1];at=point.get('time')
        lat,lon=point.get('lat'),point.get('lon')
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (at,lat,lon)):continue
        age=now-at
        if not 15<=age<=min(window,TRAIL_RETENTION) or not -90<=lat<=90 or not -180<=lon<=180:continue
        result.append(dict(hex=key,lat=lat,lon=lon,alt_baro=point.get('alt'),
                           flight=point.get('flight'),track=point.get('track'),gs=point.get('gs'),
                           baro_rate=point.get('baro_rate'),seen_pos=age,
                           last_position_at=at,historical=True))
    return result


def point_metadata(plane):
    result={}
    if plane.get('band') in ('1090','978'):result['band']=plane['band']
    if isinstance(plane.get('flight'),str):result['flight']=plane['flight'][:32]
    for key in ('track','gs','baro_rate'):
        value=plane.get(key)
        if isinstance(value,(int,float)) and math.isfinite(value):result[key]=value
    return result

BANDS = (
    dict(id='1090', name='1090 ES', frequency_mhz=1090, installed=True, description='ADS-B / Mode S'),
    dict(id='978', name='978 UAT', frequency_mhz=978, installed=False, description='ADS-B / TIS-B · dump978-fa'),
)


def receiver_position(value):
    if value is None: return None
    if not isinstance(value, dict): raise ValueError('Enter latitude and longitude')
    try: lat, lon = float(value['lat']), float(value['lon'])
    except (KeyError, ValueError, TypeError): raise ValueError('Enter latitude and longitude')
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Latitude must be −90 to 90; longitude −180 to 180')
    return dict(lat=lat, lon=lon)


class TrafficHistory:
    def __init__(self, limit=1024, points=2048, retention=TRAIL_RETENTION, max_points=65536):
        self.tracks = OrderedDict()
        self.limit, self.points, self.retention = limit, points, retention
        self.max_points = max_points

    def ingest(self, aircraft, stamp):
        for plane in aircraft:
            lat, lon = plane.get('lat'), plane.get('lon')
            if not isinstance(lat, (int,float)) or not isinstance(lon, (int,float)) or not plane.get('hex'): continue
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180: continue
            age = plane.get('seen_pos', 0)
            if not isinstance(age, (int,float)) or not 0 <= age < 15: continue
            at = float(stamp)-age
            track = self.tracks.setdefault(plane['hex'], deque(maxlen=self.points))
            if track and at <= track[-1]['time']: continue
            if track and at-track[-1]['time'] < 4: continue
            altitude=plane.get('alt_baro')
            if not isinstance(altitude,(int,float)) or not math.isfinite(altitude):altitude=None
            track.append(dict(lat=lat, lon=lon, time=at, alt=altitude, **point_metadata(plane)))
            self.tracks.move_to_end(plane['hex'])
        self.prune(stamp)

    def prune(self, stamp):
        cutoff, recent = stamp-self.retention, stamp-1800
        for key, track in list(self.tracks.items()):
            while track and track[0]['time'] < cutoff:track.popleft()
            if not track:
                del self.tracks[key];continue
            # Keep 4-second detail for 30 minutes and minute samples thereafter.
            # Retain endpoints around reception gaps so they remain discontinuous.
            compact=[];source=list(track)
            for index, point in enumerate(source):
                previous=source[index-1] if index else None
                following=source[index+1] if index+1<len(source) else None
                gap=(previous and point['time']-previous['time']>120) or (following and following['time']-point['time']>120)
                if not compact or point['time']>=recent or point['time']-compact[-1]['time']>=60 or following is None or gap:
                    compact.append(point)
            self.tracks[key]=deque(compact,maxlen=self.points)
        while len(self.tracks) > self.limit: self.tracks.popitem(last=False)
        total=sum(len(track) for track in self.tracks.values())
        while total>self.max_points and self.tracks:
            _,track=self.tracks.popitem(last=False);total-=len(track)

    def snapshot(self):
        return {key: [dict(point) for point in points] for key, points in self.tracks.items()}

    def latest_position_time(self, stamp):
        return max((track[-1]['time'] for track in self.tracks.values()
                    if track and 0<=stamp-track[-1]['time']<=self.retention),default=None)

    def save(self, path, stamp):
        self.prune(stamp)
        temporary=path.with_suffix('.tmp')
        with gzip.open(temporary,'wt',encoding='utf-8',compresslevel=1) as stream:
            json.dump(self.snapshot(),stream,separators=(',',':'),allow_nan=False)
        temporary.replace(path)

    def load(self, path, stamp):
        try:
            with gzip.open(path,'rt',encoding='utf-8') as stream:
                # Bound decompressed input even if a saved file is corrupt.
                text=stream.read(16*1024*1024+1)
                if len(text)>16*1024*1024:return
                saved=json.loads(text)
            if not isinstance(saved,dict):return
            for key, points in list(saved.items())[-self.limit:]:
                if not isinstance(key,str) or not isinstance(points,list):continue
                track=deque(maxlen=self.points)
                for point in points[-self.points:]:
                    if not isinstance(point,dict):continue
                    at,lat,lon=(point.get(k) for k in ('time','lat','lon'))
                    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (at,lat,lon)):continue
                    if not stamp-self.retention<=at<=stamp or not -90<=lat<=90 or not -180<=lon<=180:continue
                    if track and at<=track[-1]['time']:continue
                    track.append(dict(time=at,lat=lat,lon=lon,alt=point.get('alt'),**point_metadata(point)))
                if track:self.tracks[key]=track
            self.tracks=OrderedDict(sorted(self.tracks.items(),key=lambda item:item[1][-1]['time']))
            self.prune(stamp)
        except (OSError,ValueError,EOFError):pass
