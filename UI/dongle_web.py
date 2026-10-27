"""One dongle registry exposed by both decoder servers and native controls."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from rtl_registry import REGISTRY
from dongle_notice import notice_get, notice_post
import dongle_notice
import usb_radios


def maintenance_busy(manager):
    if getattr(manager,'enabled',False):return True
    sessions={**getattr(manager,'sessions',{}),**getattr(manager,'sensor_receivers',{})}
    if any(s.enabled for s in sessions.values()):return True
    spectrum=getattr(manager,'spectrum',None)
    return bool(spectrum and spectrum.snapshot().get('enabled'))


def dongle_control(manager,data):
    action=data.get('action');key=data.get('id')
    if action=='rename':REGISTRY.rename(key,data.get('nickname'))
    elif action=='assign_id':
        service=dongle_notice.SERVICE
        if service and any(r['id']==key and r.get('can_assign') for r in (service.snapshot().get('notice') or {}).get('receivers',[])):
            REGISTRY.rename(key,data.get('nickname',''))
            service.assign(service.snapshot()['notice']['id'],key)
        else:REGISTRY.assign_id(key,data.get('nickname',''),manager.scanner,getattr(manager,'broker',None),lambda:maintenance_busy(manager))
    elif action=='scan':manager.devices=manager.scanner()
    elif action in ('probe','program'):
        REGISTRY.start(key,action,manager.scanner,getattr(manager,'broker',None),data.get('serial'),lambda:maintenance_busy(manager))
    else:raise ValueError('Unknown dongle action')
    return usb_radios.snapshot(manager,REGISTRY)


def dongle_get(handler,path):
    if notice_get(handler,path):return True
    if path not in ('/dongles','/usb-radios','/dongles.js','/dongles.css','/usb-radio-select.js','/api/dongles','/api/usb-radios'):return False
    try:
        if path in ('/api/dongles','/api/usb-radios'):
            manager=handler.server.manager
            handler.send(json.dumps(dict(usb_radios.snapshot(manager,REGISTRY),control_token=manager.token)).encode())
        else:
            name='dongles.html' if path in ('/dongles','/usb-radios') else path[1:]
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
