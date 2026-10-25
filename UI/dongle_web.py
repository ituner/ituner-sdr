"""One dongle registry exposed by both decoder servers and native controls."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from rtl_registry import REGISTRY


def maintenance_busy(manager):
    if getattr(manager,'enabled',False):return True
    sessions={**getattr(manager,'sessions',{}),**getattr(manager,'sensor_receivers',{})}
    if any(s.enabled for s in sessions.values()):return True
    spectrum=getattr(manager,'spectrum',None)
    return bool(spectrum and spectrum.snapshot().get('enabled'))


def dongle_control(manager,data):
    action=data.get('action');key=data.get('id')
    if action=='rename':REGISTRY.rename(key,data.get('nickname'))
    elif action=='assign_id':REGISTRY.assign_id(key,data.get('nickname',''),manager.scanner,getattr(manager,'broker',None),lambda:maintenance_busy(manager))
    elif action=='scan':manager.devices=manager.scanner()
    elif action in ('probe','program'):
        REGISTRY.start(key,action,manager.scanner,getattr(manager,'broker',None),data.get('serial'),lambda:maintenance_busy(manager))
    else:raise ValueError('Unknown dongle action')
    return REGISTRY.snapshot(manager.scanner())


def dongle_get(handler,path):
    if path not in ('/dongles','/dongles.js','/dongles.css','/api/dongles'):return False
    try:
        if path=='/api/dongles':
            manager=handler.server.manager
            handler.send(json.dumps(dict(REGISTRY.snapshot(manager.scanner()),control_token=manager.token)).encode())
        else:
            name='dongles.html' if path=='/dongles' else path[1:]
            mime='text/html' if name.endswith('.html') else 'text/css' if name.endswith('.css') else 'text/javascript'
            handler.send(Path(__file__).with_name(name).read_bytes(),mime+'; charset=utf-8')
    except (OSError,ValueError) as exc:handler.send(json.dumps(dict(error=str(exc))).encode(),status=400)
    return True


def dongle_post(handler):
    manager=handler.server.manager;origin=handler.headers.get('Origin')
    if handler.headers.get('X-Dongle-Token')!=manager.token or origin and urlsplit(origin).netloc!=handler.headers.get('Host'):
        handler.send(b'{"error":"Reload dongle settings before making changes"}',status=403);return
    try:
        size=int(handler.headers.get('Content-Length','0'))
        if not 0<size<=4096:raise ValueError('Invalid request size')
        data=json.loads(handler.rfile.read(size))
        handler.send(json.dumps(dict(dongle_control(manager,data),control_token=manager.token)).encode())
    except (ValueError,TypeError,OSError) as exc:handler.send(json.dumps(dict(error=str(exc))).encode(),status=400)
