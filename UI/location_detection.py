"""On-demand IP location estimate; never changes the saved station position."""
import copy
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ENDPOINT = 'https://api.ipapi.is/'
CACHE_SECONDS = 24 * 60 * 60


def parse_estimate(data, now=None):
    if not isinstance(data, dict) or data.get('error') or data.get('is_bogon'):
        raise ValueError('Location service could not locate this connection.')
    # Anonymous and authenticated response shapes are both documented by ipapi.is.
    location = data.get('location') if isinstance(data.get('location'), dict) else data
    lat, lon = location.get('lat', location.get('latitude')), location.get('lon', location.get('longitude'))
    if isinstance(lat, bool) or isinstance(lon, bool):raise ValueError('Invalid location response.')
    try:lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):raise ValueError('No coordinates returned for this connection.')
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Invalid location response.')
    place = ', '.join(str(location[k])[:80] for k in ('city','region','country') if location.get(k))
    return dict(lat=lat, lon=lon, place=place or 'Place name unavailable', source='IP estimate · ipapi.is',
                accuracy_m=None, detected_at=time.time() if now is None else now)


def fetch_estimate():
    request=Request(ENDPOINT,headers={'User-Agent':'iTuner-SDR location lookup','Accept':'application/json'})
    with urlopen(request,timeout=8) as response:
        raw=response.read(32769)
    if len(raw)>32768:raise ValueError('Location service returned an invalid response.')
    return parse_estimate(json.loads(raw))


class LocationDetector:
    def __init__(self, path, fetch=fetch_estimate, clock=time.time):
        self.path=Path(path);self.fetch=fetch;self.clock=clock;self.lock=threading.Lock()
        self.result=None;self.busy=False;self.error='';self.cached=False;self.last_request=None;self.blocked_until=0
        try:
            saved=json.loads(self.path.read_text())
            result=parse_estimate(saved,now=float(saved['detected_at']))
            result['place']=str(saved.get('place','Place name unavailable'))[:240]
            if 0 <= self.clock()-result['detected_at'] < CACHE_SECONDS:self.result=result
        except (OSError,ValueError,TypeError,KeyError):pass

    def snapshot(self):
        with self.lock:return dict(result=copy.deepcopy(self.result),busy=self.busy,error=self.error,cached=self.cached)

    def request(self, refresh=False):
        with self.lock:
            if self.busy:return False
            now=self.clock()
            if not refresh and self.result and 0<=now-self.result['detected_at']<CACHE_SECONDS:
                self.cached=True;self.error='';return True
            if now<self.blocked_until:
                self.error='Location service limit reached. Try tomorrow or enter coordinates manually.';return False
            if self.last_request is not None and now-self.last_request<60:
                self.error='Wait one minute before requesting another estimate.';return False
            self.busy=True;self.error='';self.cached=False;self.last_request=now
        threading.Thread(target=self._run,name='location-lookup',daemon=True).start()
        return True

    def _run(self):
        try:
            result=self.fetch()
            # Validate injected/provider results as strictly as cached data.
            checked=parse_estimate(result,now=self.clock());checked['place']=str(result.get('place',checked['place']))[:240]
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(checked,allow_nan=False))
                os.chmod(temporary,0o600);temporary.replace(self.path)
            except OSError:pass  # Detection still works if caching is unavailable.
            with self.lock:self.result=checked
        except HTTPError as exc:
            with self.lock:
                if exc.code==429:
                    self.blocked_until=self.clock()+CACHE_SECONDS
                    self.error='Location service limit reached. Try tomorrow or enter coordinates manually.'
                else:self.error='Location service unavailable. Keep the saved location or try again later.'
        except (OSError,ValueError,TypeError):
            with self.lock:self.error='Could not detect location. Check internet access or enter coordinates manually.'
        finally:
            with self.lock:self.busy=False
