"""Bounded log tails shared by the touchscreen and browser."""
from datetime import datetime, timezone
import json

LOG_FILES = {'flights': 'flights.jsonl', 'receiver': 'receiver.jsonl', 'diagnostics': 'readsb.txt'}
LOG_TITLES = {'flights': 'FLIGHTS', 'receiver': 'RECEIVER', 'diagnostics': 'DIAGNOSTICS'}


def log_line(item, kind):
    if kind == 'diagnostics':
        return str(item)
    stamp = item.get('time')
    try: clock = datetime.fromtimestamp(float(stamp), timezone.utc).strftime('%m-%d %H:%M:%S UTC')
    except (ValueError, TypeError, OverflowError, OSError): clock = 'Unknown time'
    if kind == 'flights':
        plane = item.get('aircraft') or {}
        call = str(plane.get('flight') or '').strip()
        label = f"{clock}  {call or plane.get('hex', '?')}  ICAO {plane.get('hex', '?')}"
        label += f"  ALT {plane.get('alt_baro', '—')} ft  SPEED {plane.get('gs', '—')} kt"
        if 'lat' in plane and 'lon' in plane:
            label += f"  POS {plane['lat']}, {plane['lon']}"
        else: label += '  NO POSITION'
        return label
    device = item.get('device') or {}
    detail = item.get('detail') or device.get('label') or item.get('selection') or ''
    return f"{clock}  {str(item.get('event', 'event')).upper()}  {detail}".rstrip()


def read_log_tail(root, kind, limit=160, max_bytes=65536):
    """Read only bounded tails, including rotated history when the active file is empty."""
    if kind not in LOG_FILES: raise ValueError('Unknown log type')
    filename = LOG_FILES[kind]
    records = []
    limit = max(1, min(200, int(limit)))
    for suffix in ('', '.1', '.2', '.3', '.4', '.5', '.6') if kind != 'diagnostics' else ('',):
        path = root/(filename+suffix)
        try:
            with path.open('rb') as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size-max_bytes))
                data = stream.read(max_bytes)
            lines = data.splitlines()
            if size > max_bytes: lines = lines[1:]
        except FileNotFoundError:
            continue
        current = []
        for line in lines:
            text = line.decode('utf-8', 'replace')
            if not text: continue
            if kind == 'diagnostics': current.append(text)
            else:
                try:
                    item = json.loads(text)
                    if isinstance(item, dict): current.append(item)
                except ValueError: pass  # Ignore an incomplete final write.
        records = current + records
        if len(records) >= limit: break
    records = records[-limit:]
    return dict(kind=kind, title=LOG_TITLES[kind], entries=records,
                lines=[log_line(item, kind) for item in records], filename=filename)
