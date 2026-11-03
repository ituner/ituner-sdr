"""Find possible station/country matches in measured history, entirely offline."""
from concurrent.futures import CancelledError
import unicodedata

import offline_schedules


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(text).casefold())
                   if not unicodedata.combining(c))


def search_history(history, query, lookup=None, cancelled=None):
    words = normalized(query).split()
    available = True
    if lookup is None:
        offline_schedules.store.load()
        available = bool(offline_schedules.store.rows)
        lookup = offline_schedules.store.lookup
    cache = {}
    tracks,bands = set(),set()
    def matches(frequency, stamp):
        if cancelled is not None and cancelled.is_set():
            raise CancelledError()
        key = frequency,int(stamp//60)
        if key not in cache:
            _,rows,_ = lookup(frequency,stamp,tolerance=2.5,allow_old_season=True)
            cache[key] = any(all(word in normalized((row.get('station') or '')+' '+(row.get('country') or ''))
                                for word in words) for row in rows)
        return cache[key]
    def remember(band, frequency):
        tracks.add((band,round(frequency,1)))
        bands.add(band)
    points = []
    for point in history.get('points',()):
        stamp,band,frequency,_strength = point
        if matches(frequency,stamp):
            points.append(point)
            remember(band,frequency)
    def segments(values):
        result = []
        for segment in values:
            start,end,band,frequency,_strength = segment
            # A possible identity must match both observed ends; do not label
            # an entire trace from a broadcaster found only at another time.
            if matches(frequency,start) and matches(frequency,end):
                result.append(segment)
                remember(band,frequency)
        return result
    joined = segments(history.get('segments',()))
    tails = segments(history.get('tails',()))
    return dict(start=history['start'],end=history['end'],points=points,segments=joined,
                tails=tails,gaps=(),tracks=tuple(sorted(tracks)),bands=frozenset(bands),
                matched_traces=len(tracks),database_available=available)
