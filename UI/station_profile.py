"""Shared local station identity, antenna position and optional gpsd receiver.

GPS data stays local. No transmit/report permission is implied by a callsign.
Remote receiver metadata is never replaced by this local antenna profile.
"""
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

FIELDS=('station_name','operator_name','callsign','site_label','timezone','local_kiwi_url',
        'latitude','longitude','elevation_m','antenna_height_m','ellipsoid_height_m','gps_enabled','gps_auto','gps_height_offset_m')
DEFAULTS=dict(station_name='iTuner',operator_name='',callsign='',site_label='',timezone='Europe/Bucharest',
              local_kiwi_url='http://kiwisdr.local:8073',latitude=None,longitude=None,elevation_m=None,
              antenna_height_m=None,ellipsoid_height_m=None,gps_enabled=True,gps_auto=True,gps_height_offset_m=0.)


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def grid(lat,lon):
    """Six-character Maidenhead locator, derived from antenna coordinates."""
    if not number(lat) or not number(lon):return ''
    x=min(359.999999999,max(0,lon+180));y=min(179.999999999,max(0,lat+90))
    return chr(65+int(x//20))+chr(65+int(y//10))+str(int(x%20//2))+str(int(y%10))+chr(65+int(x%2*12))+chr(65+int(y%1*24))


def distance_m(a,b):
    if not a or not b:return float('inf')
    p,q=math.radians(a['lat']),math.radians(b['lat']);d=math.radians(b['lon']-a['lon'])
    return 12742000*math.asin(min(1,math.sqrt(math.sin((q-p)/2)**2+math.cos(p)*math.cos(q)*math.sin(d/2)**2)))


def endpoint(value):
    try:
        p=urlsplit(str(value));return (p.hostname or '').lower(),p.port or (443 if p.scheme=='https' else 80),p.path.rstrip('/')
    except ValueError:return ('',0,'')


def validate(values,base=None):
    if not isinstance(values,dict):raise ValueError('Enter station information')
    if set(values)-set(FIELDS):raise ValueError('Unknown station field')
    result=dict(base or DEFAULTS);result.update(values)
    for key,limit in (('station_name',72),('operator_name',72),('callsign',16),('site_label',120),('timezone',64),('local_kiwi_url',200)):
        if not isinstance(result[key],str) or len(result[key])>limit or any(ord(c)<32 for c in result[key]):raise ValueError('Invalid '+key.replace('_',' '))
        result[key]=result[key].strip()
    result['callsign']=result['callsign'].upper()
    if result['callsign'] and not re.fullmatch(r'[A-Z0-9][A-Z0-9/\-]{1,15}',result['callsign']):raise ValueError('Callsign may contain letters, digits, / and -; leave blank if none')
    try:ZoneInfo(result['timezone'])
    except (ZoneInfoNotFoundError,ValueError):raise ValueError('Enter an IANA timezone, e.g. Europe/Bucharest')
    url=result['local_kiwi_url']
    if url:
        p=urlsplit(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment:raise ValueError('Enter the local Kiwi receiver HTTP URL without credentials')
        try:p.port
        except ValueError:raise ValueError('Invalid local Kiwi port')
    for key,low,high in (('latitude',-90,90),('longitude',-180,180),('elevation_m',-500,9000),('antenna_height_m',0,1000),('ellipsoid_height_m',-500,10000),('gps_height_offset_m',-1000,1000)):
        value=result[key]
        if value is not None and (not number(value) or not low<=value<=high):raise ValueError(f'{key.replace("_"," ")} must be {low} to {high}, or blank if unknown')
    if (result['latitude'] is None)!=(result['longitude'] is None):raise ValueError('Enter both latitude and longitude, or leave both blank')
    for key in ('gps_enabled','gps_auto'):
        if type(result[key]) is not bool:raise ValueError('Invalid GPS setting')
    return result


class StationProfile:
    def __init__(self,path=None,start=True,gps_address=('127.0.0.1',2947)):
        self.gps_address=gps_address
        self.path=Path(path or Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'ituner-sdr/radio-user.json')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.listeners=[];self.closed=threading.Event();self.wake=threading.Event()
        self.config=dict(DEFAULTS);self.last_position=None;self.revision=0;self.saved_at=0;self.error=''
        self.gps=dict(connected=False,mode=0,devices=[],satellites=None,used=None,last_fix=None,accuracy_m=None,status='Waiting for gpsd / USB GPS receiver')
        try:
            saved=json.loads(self.path.read_text());self.config=validate(saved['config']);self.last_position=saved.get('last_gps_position');self.revision=int(saved.get('revision',0))
            if self.last_position and (not isinstance(self.last_position,dict) or not all(number(self.last_position.get(k)) for k in ('lat','lon','time')) or not -90<=self.last_position['lat']<=90 or not -180<=self.last_position['lon']<=180):self.last_position=None
        except (OSError,ValueError,KeyError,TypeError):self._migrate()
        self.published_position=copy.deepcopy(self.last_position)
        if self.last_position:self.gps['last_fix']=self.last_position['time']
        self.thread=None
        if start:
            self.thread=threading.Thread(target=self.run,name='station-gps',daemon=True);self.thread.start()

    def _migrate(self):
        root=self.path.parent
        for path in (root/'adsb/settings.json',root/'vhf/station.json'):
            try:
                value=json.loads(path.read_text());p=value.get('position') if path.name=='settings.json' else value
                candidate=validate(dict(latitude=p['lat'],longitude=p['lon']),self.config)
                self.config=candidate;break
            except (OSError,ValueError,TypeError,KeyError):pass
        try:
            height=json.loads((root/'adsb/coverage-settings.json').read_text()).get('height_m')
            self.config=validate(dict(ellipsoid_height_m=height),self.config)
        except (OSError,ValueError,AttributeError):pass
        self._save()

    def _save(self):
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(version=1,config=self.config,last_gps_position=self.last_position,revision=self.revision),allow_nan=False,indent=2))
        os.chmod(temporary,0o600);temporary.replace(self.path);self.saved_at=time.monotonic()

    def _effective(self,now):
        c=self.config
        if c['gps_enabled'] and c['gps_auto'] and self.last_position:
            p=dict(self.last_position);p.update(source='gps',stale=not(self.gps['connected'] and self.gps['mode']>=2 and now-p['time']<=15))
            # Missing GPS altitude stays unknown; do not reuse a home elevation at a new site.
            p.setdefault('ellipsoid_height_m',None);p.setdefault('altitude_msl_m',None)
            for key in ('ellipsoid_height_m','altitude_msl_m'):
                if p[key] is not None:p[key]+=c['gps_height_offset_m'] or 0
            return p
        if c['latitude'] is None:return None
        altitude=c['elevation_m']+c['antenna_height_m'] if c['elevation_m'] is not None and c['antenna_height_m'] is not None else None
        return dict(lat=c['latitude'],lon=c['longitude'],ellipsoid_height_m=c['ellipsoid_height_m'],altitude_msl_m=altitude,
                    source='manual',stale=False,time=None)

    def snapshot(self):
        with self.lock:
            now=time.time();p=self._effective(now);gps=copy.deepcopy(self.gps)
            gps['fix_age_s']=max(0,now-gps['last_fix']) if gps['last_fix'] else None
            gps['fresh']=bool(gps['connected'] and gps['mode']>=2 and gps['fix_age_s'] is not None and gps['fix_age_s']<=15)
            if not self.config['gps_enabled']:gps['status']='GPS disabled'
            elif not gps['fresh'] and gps['last_fix']:gps['status']='GPS fix stale · retaining last known location'
            return dict(config=dict(self.config),position=copy.deepcopy(p),grid=grid(p['lat'],p['lon']) if p else '',gps=gps,revision=self.revision,error=self.error)

    def local_receiver(self,url):
        with self.lock:return bool(self.config['local_kiwi_url'] and endpoint(url)==endpoint(self.config['local_kiwi_url']))

    def subscribe(self,callback):
        with self.lock:self.listeners.append(callback)
        callback(self.snapshot())

    def _notify(self):
        data=self.snapshot()
        for listener in tuple(self.listeners):
            try:listener(data)
            except Exception as exc:self.error='Station consumer: '+str(exc)

    def update(self,values):
        with self.lock:
            config=validate(values,self.config);old=self.config
            self.config=config;self.revision+=1
            try:self._save()
            except OSError:self.config=old;self.revision-=1;raise
        self._notify();self.wake.set();return self.snapshot()

    def message(self,message,now=None):
        """Accept gpsd JSON reports. Unit-tested separately from the socket."""
        now=time.time() if now is None else now
        if not isinstance(message,dict):return False
        kind=message.get('class');notify=False
        with self.lock:
            if kind=='DEVICES':
                self.gps['devices']=[dict(path=str(d.get('path',''))[:200],driver=str(d.get('driver',''))[:80]) for d in message.get('devices',[]) if isinstance(d,dict)][:16]
            elif kind=='DEVICE':
                path=message.get('path')
                if not isinstance(path,str) or not path:return False
                devices=[d for d in self.gps['devices'] if d['path']!=path]
                if message.get('activated',1) not in (0,'0',False):devices.append(dict(path=path[:200],driver=str(message.get('driver',''))[:80]))
                self.gps['devices']=devices[:16]
                if not devices:self.gps.update(mode=0,status='GPS receiver unplugged · keeping last known location',satellites=None,used=None)
            elif kind=='SKY':
                sats=message.get('satellites')
                if isinstance(sats,list):self.gps['satellites']=len(sats);self.gps['used']=sum(bool(s.get('used')) for s in sats if isinstance(s,dict))
            elif kind=='TPV':
                mode=message.get('mode',0);self.gps['mode']=mode if mode in (0,1,2,3) else 0
                if self.gps['mode']<2:self.gps['status']='Receiver connected · waiting for a position fix';return False
                lat,lon=message.get('lat'),message.get('lon')
                if not number(lat) or not number(lon) or not -90<=lat<=90 or not -180<=lon<=180:return False
                try:
                    raw=message['time'];stamp=float(raw) if number(raw) else datetime.fromisoformat(raw.replace('Z','+00:00')).timestamp()
                except (ValueError,KeyError,TypeError,AttributeError,OverflowError):return False
                if not -2<=now-stamp<=15:return False
                accuracy=message.get('eph') if number(message.get('eph')) and message['eph']>=0 else math.hypot(*[max(0.,message[k]) if number(message.get(k)) else 0. for k in ('epx','epy')]) or None
                if accuracy is not None and accuracy>100:self.gps['status']='GPS accuracy poor · keeping previous location';return False
                p=dict(lat=lat,lon=lon,time=stamp,ellipsoid_height_m=message.get('altHAE') if self.gps['mode']==3 and number(message.get('altHAE')) and -1000<=message['altHAE']<=20000 else None,
                       altitude_msl_m=message.get('altMSL') if self.gps['mode']==3 and number(message.get('altMSL')) and -1000<=message['altMSL']<=20000 else None)
                self.gps.update(last_fix=stamp,accuracy_m=accuracy,status='GPS fix · '+('3D' if self.gps['mode']==3 else '2D'))
                if message.get('device') and not self.gps['devices']:self.gps['devices']=[dict(path=str(message['device'])[:200],driver='')]
                old=self.last_position
                published=self.published_position
                moved=distance_m(published,p)>=10 or published is None or (published.get('ellipsoid_height_m') is None)!=(p.get('ellipsoid_height_m') is None) or abs((published.get('ellipsoid_height_m') or 0)-(p.get('ellipsoid_height_m') or 0))>=3
                self.last_position=p
                notify=moved or old is None
                if notify:self.published_position=dict(p)
                if self.config['gps_enabled'] and self.config['gps_auto'] and (time.monotonic()-self.saved_at>=30 or old is None):
                    self.revision+=1;self._save()
            else:return False
        if notify:self._notify()
        return kind=='TPV'

    def run(self):
        while not self.closed.is_set():
            if not self.config['gps_enabled']:
                self.wake.wait(2);self.wake.clear();continue
            try:
                with socket.create_connection(self.gps_address,timeout=2) as stream:
                    stream.settimeout(1);stream.sendall(b'?WATCH={"enable":true,"json":true};\n')
                    with self.lock:self.gps.update(connected=True,status='gpsd connected · waiting for GPS fix')
                    buffer=b''
                    while not self.closed.is_set() and self.config['gps_enabled']:
                        try:chunk=stream.recv(8192)
                        except socket.timeout:continue
                        if not chunk:raise OSError('GPS service disconnected')
                        buffer+=chunk
                        if len(buffer)>65536:raise OSError('Invalid GPS report size')
                        while b'\n' in buffer:
                            line,buffer=buffer.split(b'\n',1)
                            try:self.message(json.loads(line))
                            except (ValueError,TypeError,OSError) as exc:self.error='GPS: '+str(exc)
            except OSError:
                with self.lock:self.gps.update(connected=False,status='Waiting for gpsd / USB GPS receiver')
                self.closed.wait(5)

    def close(self):
        self.closed.set();self.wake.set()
        if self.last_position and self.config['gps_enabled'] and self.config['gps_auto']:
            with self.lock:self._save()
        if self.thread:self.thread.join(timeout=3)


_station=None
_station_lock=threading.Lock()

def get_station():
    global _station
    with _station_lock:
        if _station is None:_station=StationProfile()
        return _station


def peek_station():return _station
