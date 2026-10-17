"""One station settings page served by both local decoder web servers."""
import json
from pathlib import Path
from urllib.parse import urlsplit


def station_get(handler,path):
    if path not in ('/settings','/station.html','/station.css','/station.js','/api/station'):return False
    if path=='/api/station':
        station=getattr(handler.server.manager,'station',None)
        if station is None:handler.send(b'{"error":"Shared station profile unavailable"}',status=503)
        else:handler.send(json.dumps(dict(station.snapshot(),control_token=handler.server.manager.token)).encode())
    else:
        name='station.html' if path=='/settings' else path[1:]
        mime='text/html' if name.endswith('.html') else 'text/css' if name.endswith('.css') else 'text/javascript'
        handler.send(Path(__file__).with_name(name).read_bytes(),mime+'; charset=utf-8')
    return True


def station_post(handler):
    manager=handler.server.manager;origin=handler.headers.get('Origin')
    if handler.headers.get('X-Station-Token')!=manager.token or origin and urlsplit(origin).netloc!=handler.headers.get('Host'):
        handler.send(b'{"error":"Reload station settings before saving"}',status=403);return
    try:
        size=int(handler.headers.get('Content-Length','0'))
        if not 0<size<=8192:raise ValueError('Invalid request size')
        if getattr(manager,'station',None) is None:raise ValueError('Shared station profile unavailable')
        data=manager.station.update(json.loads(handler.rfile.read(size)))
        handler.send(json.dumps(dict(data,control_token=manager.token)).encode())
    except (ValueError,TypeError,OSError) as exc:handler.send(json.dumps(dict(error=str(exc))).encode(),status=400)
