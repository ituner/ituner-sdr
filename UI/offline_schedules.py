"""Local EiBi/HFCC schedule index. Network access is bulk refresh only."""
import bisect
import calendar
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

MAX_DOWNLOAD = 8*1024*1024
CHANNEL_MATCH_LIMIT_KHZ = 2.25
CHANNEL_AMBIGUITY_KHZ = .25
COUNTRIES = {'USA':'United States', 'CHN':'China', 'RUS':'Russia', 'D':'Germany',
             'ROU':'Romania', 'G':'United Kingdom', 'GBR':'United Kingdom',
             'F':'France', 'J':'Japan', 'JPN':'Japan', 'KOR':'South Korea',
             'KRE':'North Korea', 'B':'Brazil', 'BRA':'Brazil', 'NZL':'New Zealand',
             'CAN':'Canada', 'AUS':'Australia', 'CUB':'Cuba', 'IND':'India',
             'TWN':'Taiwan', 'EQA':'Ecuador'}


def shortwave_channel(frequency):
    """Nearest 5 kHz broadcast channel, leaving the midpoint unresolved."""
    if not 2300 <= frequency <= 30000:
        return None
    channel = math.floor(frequency/5+.5)*5
    return float(channel) if abs(channel-frequency) <= CHANNEL_MATCH_LIMIT_KHZ else None


def season_for(day):
    def last_sunday(year, month):
        end = date(year, month, calendar.monthrange(year, month)[1])
        return end-timedelta(days=(end.weekday()+1)%7)
    march, october = last_sunday(day.year, 3), last_sunday(day.year, 10)
    if day < march:
        return f'b{(day.year-1)%100:02d}', last_sunday(day.year-1,10), march
    if day < october:
        return f'a{day.year%100:02d}', march, october
    return f'b{day.year%100:02d}', october, last_sunday(day.year+1,3)


def decode(data):
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('latin1')


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent':'iTuner SDR offline schedule updater'}), timeout=12) as response:
        data = response.read(MAX_DOWNLOAD+1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('Schedule download exceeds size limit')
    return data


def code_table(text, width=3):
    return {line[:width].strip():line[width:].strip() for line in text.splitlines()
            if line.strip() and not line.lstrip('\ufeff').startswith(';')}


def eibi_codes(readme):
    countries, languages, sites = {}, {}, {}
    section, country = '', ''
    for line in readme.splitlines():
        if re.match(r'\s+I\) Language codes\.', line):
            section = 'language'
        elif re.match(r'\s+II\) Country codes\.', line):
            section = 'country'
        elif re.match(r'\s+III\) Target-area codes\.', line):
            section = ''
        elif re.match(r'\s+IV\) Transmitter site codes\.', line):
            section = 'sites'
        if section in ('country','language'):
            match = re.match(r'^   (\S{1,5})\s{2,}(.+)', line)
            if match:
                key, value = match.groups()
                if section == 'country':
                    countries[key] = COUNTRIES.get(key, value.strip())
                else:
                    languages[key] = re.split(r'[:(\[]', value)[0].strip()
        elif section == 'sites':
            match = re.match(r'^   ([A-Z]{1,3}):\s*(.*)', line)
            if match:
                country, line = match.groups()
            match = re.match(r'^\s*([A-Za-z0-9]{1,4})-([^\d]+)', line)
            if match and country:
                sites[(country, match[1])] = match[2].strip().rstrip(',')
    return countries, languages, sites


def parse_eibi(data, readme, season, start, stop):
    countries, languages, sites = eibi_codes(readme)
    result = []
    for fields in csv.reader(io.StringIO(decode(data)), delimiter=';'):
        try:
            frequency = float(fields[0])
            if len(fields) < 11 or not re.fullmatch(r'\d{4}-\d{4}', fields[1]):
                continue
            persistence = int(fields[8] or '0')
            # The same file contains utility, time-signal and inactive rows.
            if persistence >= 90 or persistence == 8 or fields[5].startswith('-'):
                continue
            itu, site = fields[3], fields[7]
            site_country = itu
            if site.startswith('/'):
                parts = site[1:].split('-',1)
                site_country, site = parts[0], parts[1] if len(parts)>1 else ''
            transmitter = sites.get((site_country,site), '')
            if not transmitter and site:
                transmitter = site_country+'-'+site
            row = dict(frequency_khz=frequency, time=fields[1], days=fields[2],
                       country=countries.get(itu,COUNTRIES.get(itu,itu)), station=fields[4],
                       language=languages.get(fields[5],fields[5]), transmitter=transmitter,
                       power_kw='', source='EiBi '+season.upper(),
                       valid_from=start.isoformat(), valid_until=stop.isoformat(),
                       day_system='monday')
            # Partial-season dates are DDMM; use the year that falls inside
            # this A/B season, including B-season dates after New Year.
            for key, value in (('valid_from',fields[9]),('valid_until',fields[10])):
                if persistence == 6 and re.fullmatch(r'\d{4}',value):
                    choices = [date(y,int(value[2:]),int(value[:2])) for y in (start.year,stop.year)]
                    chosen = next((d for d in choices if start <= d < stop), None)
                    if chosen:
                        row[key] = (chosen+(timedelta(days=1) if key=='valid_until' else timedelta())).isoformat()
            result.append(row)
        except (ValueError,IndexError):
            continue
    return result


def parse_hfcc(data, season):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = {Path(n).name.lower():n for n in archive.namelist()}
        if sum(info.file_size for info in archive.infolist()) > 20*1024*1024:
            raise ValueError('Expanded HFCC archive exceeds size limit')
        def text(name):
            return decode(archive.read(names[name]))
        broadcasters = code_table(text('broadcas.txt'))
        countries = {line[:3].strip():line[4:54].strip() for line in text('admin.txt').splitlines()
                     if line.strip() and not line.startswith(';')}
        languages = code_table(text('language.txt'))
        sites = {line[:3].strip():line[4:35].strip() for line in text('site.txt').splitlines()
                 if line.strip() and not line.startswith(';')}
        schedule = text(season.lower()+'all00.txt')
    result = []
    for line in schedule.splitlines():
        if line.startswith(';') or len(line) < 121:
            continue
        try:
            if line[94:96].strip() != 'D':  # AM DSB; N is digital/DRM.
                continue
            begin = datetime.strptime(line[80:87].strip(),'%d%m%y').date()
            end = datetime.strptime(line[87:94].strip(),'%d%m%y').date()+timedelta(days=1)
            itu, broadcaster = line[113:117].strip(), line[117:121].strip()
            language = line[102:113].strip()
            result.append(dict(frequency_khz=float(line[:6]),
                time=line[6:11].strip()+'-'+line[11:16].strip(),
                days=line[72:80].strip(), day_system='sunday',
                station=broadcasters.get(broadcaster,broadcaster),
                country=COUNTRIES.get(itu,countries.get(itu,itu)),
                language=languages.get(language,language),
                transmitter=sites.get(line[47:51].strip(),line[47:51].strip()),
                power_kw=line[51:56].strip(), source='HFCC '+season.upper(),
                valid_from=begin.isoformat(), valid_until=end.isoformat()))
        except ValueError:
            continue
    return result


def active(row, moment):
    """Respect UTC dates, weekday conventions and broadcasts across midnight."""
    try:
        start, stop = (int(value[:2])*60+int(value[2:]) for value in row['time'].split('-'))
        if not 0 <= start < 1440 or not 0 <= stop <= 1440:
            return False
        minute = moment.hour*60+moment.minute
        overnight = stop < start
        if start != stop and not (minute >= start or minute < stop if overnight else start <= minute < stop):
            return False
        day = moment.date()-timedelta(days=1) if overnight and minute < stop else moment.date()
        if not row['valid_from'] <= day.isoformat() < row['valid_until']:
            return False
        days = row.get('days','').strip()
        if not days or days in ('daily','irr','tent','test'):
            return True
        weekday = (day.weekday()+1 if row.get('day_system') == 'monday'
                   else (day.weekday()+1)%7+1)
        if days.isdigit():
            return str(weekday) in days
        names = ('Mo','Tu','We','Th','Fr','Sa','Su')
        if re.fullmatch(r'(Mo|Tu|We|Th|Fr|Sa|Su)+',days):
            return names[day.weekday()] in days
        if days == 'alt' or days in ('harm','imod','USB','LSB'):
            return False
        if match := re.fullmatch(r'(\d)\.(Mo|Tu|We|Th|Fr|Sa|Su)',days):
            return (day.day-1)//7+1 == int(match[1]) and names[day.weekday()] == match[2]
        if match := re.fullmatch(r'Last([1-7])',days):
            return day.weekday()+1 == int(match[1]) and (day+timedelta(days=7)).month != day.month
        if match := re.fullmatch(r'(\d{1,2})([A-Z][a-z]{2})',days):
            return day.day == int(match[1]) and day.strftime('%b') == match[2]
        # Do not claim irregular/ambiguous day codes are on air every day.
        return False
    except (KeyError,ValueError):
        return False


class ScheduleStore:
    REFRESH_SECONDS = 86400

    def __init__(self, directory=None, downloader=fetch):
        self.directory = Path(directory or os.environ.get('ITUNER_SCHEDULE_DIR',
                                     str(Path.home()/'.cache/ituner/broadcast-schedules')))
        self.downloader = downloader
        self.lock = threading.RLock()
        self.providers = {}
        self.rows, self.frequencies = [], []
        self.loaded = False
        self.refreshing = False
        self.last_attempt = 0
        self.generation = 0
        self.errors = {}

    def _index(self):
        self.rows = sorted((row for p in self.providers.values() for row in p['rows']),
                           key=lambda row:row['frequency_khz'])
        self.frequencies = [row['frequency_khz'] for row in self.rows]
        self.generation += 1

    def load(self):
        with self.lock:
            if self.loaded:
                return
            for provider in ('eibi','hfcc'):
                try:
                    payload = json.loads((self.directory/(provider+'.json')).read_text())
                    if (payload.get('version') == 1 and isinstance(payload.get('rows'),list)
                            and isinstance(payload.get('fetched_at'),(int,float))
                            and all(isinstance(row,dict) and isinstance(row.get('frequency_khz'),(int,float))
                                    and all(isinstance(row.get(k),str) for k in
                                        ('station','transmitter','source','time','valid_from','valid_until'))
                                    for row in payload['rows'])):
                        self.providers[provider] = payload
                except (OSError,ValueError):
                    pass
            self._index()
            self.loaded = True

    def refresh_if_due(self):
        self.load()
        with self.lock:
            now = time.time()
            if self.refreshing or now-self.last_attempt < 3600:
                return
            if len(self.providers)==2 and all(now-p['fetched_at'] < self.REFRESH_SECONDS for p in self.providers.values()):
                return
            self.last_attempt = now
            self.refreshing = True
        threading.Thread(target=self.refresh, name='broadcast-database', daemon=True).start()

    def refresh(self, day=None):
        self.load()
        day = day or datetime.now(timezone.utc).date()
        season,start,stop = season_for(day)
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            for provider in ('hfcc','eibi'):
                with self.lock:
                    previous = self.providers.get(provider)
                if previous and time.time()-previous['fetched_at'] < self.REFRESH_SECONDS:
                    continue
                try:
                    selected = season
                    if provider == 'hfcc':
                        url = f'https://new.hfcc.org/data/{season}/{season}allx2.zip'
                        raw = self.downloader(url)
                        rows = parse_hfcc(raw,season)
                    else:
                        try:
                            url = f'http://www.eibispace.de/dx/sked-{season}.csv'
                            raw = self.downloader(url)
                        except HTTPError as error:
                            if error.code != 404:
                                raise
                            selected,start,stop = season_for(start-timedelta(days=1))
                            url = f'http://www.eibispace.de/dx/sked-{selected}.csv'
                            raw = self.downloader(url)
                        readme = decode(self.downloader('http://www.eibispace.de/dx/README.TXT'))
                        rows = parse_eibi(raw,readme,selected,start,stop)
                        usage = self.directory/'eibi-README.txt.next'
                        usage.write_text(readme)
                        usage.replace(self.directory/'eibi-README.txt')
                    if not rows:
                        raise ValueError('No valid broadcast rows in schedule')
                    payload = dict(version=1,source=provider,season=selected.upper(),
                                   url=url,fetched_at=time.time(),rows=rows)
                    temporary = self.directory/(provider+'.json.next')
                    temporary.write_text(json.dumps(payload,ensure_ascii=False))
                    temporary.replace(self.directory/(provider+'.json'))
                    with self.lock:
                        self.providers[provider] = payload
                        self.errors.pop(provider,None)
                        self._index()
                except (OSError,ValueError,KeyError,zipfile.BadZipFile) as error:
                    with self.lock:
                        self.errors[provider] = str(error)
        except OSError as error:
            with self.lock:
                self.errors['cache'] = str(error)
        finally:
            with self.lock:
                self.refreshing = False

    def lookup(self, frequency, timestamp=None, tolerance=1):
        self.load()
        moment = datetime.fromtimestamp(time.time() if timestamp is None else timestamp,timezone.utc)
        def nearby(center, radius):
            low = bisect.bisect_left(self.frequencies,center-radius)
            high = bisect.bisect_right(self.frequencies,center+radius)
            return [dict(row) for row in self.rows[low:high] if active(row,moment)]
        with self.lock:
            rows = nearby(frequency,tolerance)
            kind = 'direct'
            if not rows:
                if 2300 <= frequency <= 30000:
                    channel = shortwave_channel(frequency)
                    rows = nearby(channel,.25) if channel is not None else []
                elif 150 <= frequency <= 1710:
                    # Use actual schedules for LW/MW; do not assume whether
                    # this receiver's region uses 9 or 10 kHz channels.
                    rows = nearby(frequency,CHANNEL_MATCH_LIMIT_KHZ)
                rows = [row for row in rows
                        if abs(row['frequency_khz']-frequency) <= CHANNEL_MATCH_LIMIT_KHZ]
                kind = 'channel'
        if rows:
            closest = min(abs(row['frequency_khz']-frequency) for row in rows)
            rows = [row for row in rows if abs(row['frequency_khz']-frequency)
                    <= closest+CHANNEL_AMBIGUITY_KHZ]
            for row in rows:
                row['measured_frequency_khz'] = frequency
                row['match_kind'] = kind
        # Prefer named EiBi entries; merge a matching HFCC entry only when the
        # broadcaster AND transmitter match. Preserve genuine ambiguity.
        result = []
        for row in sorted(rows,key=lambda r:('EiBi' not in r['source'],abs(r['frequency_khz']-frequency))):
            key = tuple(re.sub(r'[^a-z0-9]','',row[k].casefold()) for k in ('station','transmitter'))
            old = next((p for p in result if tuple(re.sub(r'[^a-z0-9]','',p[k].casefold())
                        for k in ('station','transmitter'))==key
                        and (not p.get('country') or not row.get('country') or p['country']==row['country'])
                        and abs(p['frequency_khz']-row['frequency_khz'])<.1),None)
            if old is None:
                result.append(row)
            else:
                for field in ('power_kw','country','language','transmitter'):
                    if not old.get(field):
                        old[field] = row.get(field,'')
                if row['source'] not in old['source']:
                    old['source'] += ' + '+row['source']
        return frequency,result,None

    def status(self):
        self.load()
        with self.lock:
            current = season_for(datetime.now(timezone.utc).date())[0].upper()
            sources = ' + '.join(p['source'].upper()+' '+p['season']+
                       (' (old season)' if p['season']!=current else '') for p in self.providers.values())
            label = 'Offline: '+sources if sources else 'Offline database unavailable'
            if self.refreshing:
                label += ' · updating'
            elif self.errors:
                label += ' · update incomplete'
            return self.generation,label


store = ScheduleStore()


def lookup(frequency, timestamp=None, tolerance=1):
    store.refresh_if_due()
    return store.lookup(float(frequency),timestamp,tolerance)
