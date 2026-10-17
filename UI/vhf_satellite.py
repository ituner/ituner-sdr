"""Cached orbital data and observer-based predictions, never guessed pass times."""
import datetime
import json
import math
from pathlib import Path
import time
from urllib.request import urlopen


def refresh_tle(root, norad):
    norad = int(norad)
    if not 1 <= norad <= 999999: raise ValueError('Invalid satellite number')
    with urlopen(f'https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=TLE', timeout=12) as response:
        lines = response.read(4096).decode('ascii').strip().splitlines()
    if len(lines) < 3 or not lines[-2].startswith('1 ') or not lines[-1].startswith('2 '):
        raise ValueError('Orbital elements are unavailable for this satellite')
    import ephem
    ephem.readtle(*lines[-3:])  # validate checksums before replacing cache
    path = Path(root)/f'{norad}.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(fetched=time.time(), lines=lines[-3:])))
    temporary.replace(path)


def prediction(root, norad, site, frequency):
    if not norad: return None
    try:
        import ephem
        saved = json.loads((Path(root)/f'{int(norad)}.json').read_text())
        satellite = ephem.readtle(*saved['lines'])
        epoch = satellite._epoch.datetime().replace(tzinfo=datetime.timezone.utc).timestamp()
        result = dict(norad=norad, fetched=saved['fetched'], epoch=epoch,
                      stale=abs(time.time()-epoch)>14*86400, passes=[])
        if not site: return dict(result, detail='Set receiver location for pass predictions and Doppler correction.')
        observer = ephem.Observer(); observer.lat = str(site['lat']); observer.lon = str(site['lon'])
        observer.elevation = float(site.get('alt',0)); observer.pressure = 0; observer.horizon = '0'
        observer.date = ephem.now(); satellite.compute(observer)
        result.update(elevation=round(math.degrees(float(satellite.alt)),1), azimuth=round(math.degrees(float(satellite.az)),1),
            range_km=round(float(satellite.range)/1000), doppler_hz=round(-float(satellite.range_velocity)/299792458*frequency))
        if result['stale']: result['doppler_hz'] = 0
        for _ in range(3):
            try:
                rise, az, peak, elevation, setting, _ = observer.next_pass(satellite)
                if rise is None or setting is None: break
                result['passes'].append(dict(rise=rise.datetime().replace(tzinfo=datetime.timezone.utc).timestamp(),
                    peak=peak.datetime().replace(tzinfo=datetime.timezone.utc).timestamp(),
                    setting=setting.datetime().replace(tzinfo=datetime.timezone.utc).timestamp(),
                    elevation=round(math.degrees(float(elevation)),1)))
                observer.date = setting+ephem.minute
            except (ValueError, TypeError): break
        return result
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return dict(norad=norad, passes=[], detail='Update orbital data to calculate local passes.')
