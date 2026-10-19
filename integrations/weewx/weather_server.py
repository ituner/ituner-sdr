#!/usr/bin/env python3
"""Independent local WeeWX/Belchertown UI and read-only shared-radio weather feed."""
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from urllib.parse import urlsplit
from urllib.request import urlopen
from weather_feed import candidates

ROOT=Path(os.environ.get('WEATHER_ROOT','/var/lib/ituner-weather'))
PUBLIC=ROOT/'public_html';PUBLIC.mkdir(parents=True,exist_ok=True)
SOURCE=Path(__file__).parent;CONFIG=ROOT/'source.json';TOKEN=secrets.token_urlsafe(32)
LOCK=threading.RLock();STATE=dict(candidates=[],reading=None,fresh=False,selection='auto',status='Waiting for compatible weather sensors',last_poll=None,error='')
try:SETTINGS=json.loads(CONFIG.read_text())
except (OSError,ValueError):SETTINGS=dict(selection='auto')

def save_settings():
 temporary=CONFIG.with_suffix('.tmp');temporary.write_text(json.dumps(SETTINGS));temporary.replace(CONFIG)

def collect():
 while True:
  try:
   with urlopen('http://127.0.0.1:8092/api/state',timeout=5) as response:state=json.load(response)
   try:
    with urlopen('http://127.0.0.1:8092/api/station',timeout=2) as response:station=json.load(response)
    station.pop('control_token',None)
   except (OSError,ValueError):station=STATE.get('station')
   rows=candidates(state);selection=SETTINGS.get('selection','auto')
   # Auto selection locks to the first compatible identity, never mixes stations.
   fresh=[r for r in rows if 0<=time.time()-r['time']<=120]
   with LOCK:
    if selection=='auto' and fresh:
     selection=fresh[0]['id'];SETTINGS['selection']=selection;save_settings()
    row=next((r for r in rows if r['id']==selection),None)
    valid=row is not None and 0<=time.time()-row['time']<=120
    status='Receiving weather data' if valid else 'Weather sensor is stale / awaiting its next transmission' if row else 'Waiting for compatible weather sensors'
    STATE.update(station=station,candidates=rows,reading=row,fresh=valid,selection=selection,status=status,last_poll=time.time(),error='')
  except (OSError,ValueError,KeyError) as exc:
   with LOCK:STATE.update(fresh=False,status='Shared receiver feed unavailable',error=str(exc))
  time.sleep(2)

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(PUBLIC),**kwargs)
 def send(self,data,kind='application/json',status=200):
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-cache');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):
  path=urlsplit(self.path).path
  if path=='/api/weather':
   with LOCK:payload=dict(STATE,control_token=TOKEN,dashboard_ready=(PUBLIC/"index.html").is_file())
   self.send(json.dumps(payload,allow_nan=False).encode());return
  if path in ('/receiver','/weather-status.js'):
   file=SOURCE/('receiver.html' if path=='/receiver' else 'weather-status.js');self.send(file.read_bytes(),'text/html; charset=utf-8' if path=='/receiver' else 'text/javascript; charset=utf-8');return
  relative='index.html' if path=='/' else path.lstrip('/')
  file=(PUBLIC/relative).resolve()
  if not file.is_relative_to(PUBLIC.resolve()):self.send(b'Invalid path','text/plain',403);return
  if file.suffix=='.html' and file.is_file():
   body=file.read_text();body=re.sub(r'(<body[^>]*>)',r'\1<div id="ituner-weather-status" role="status" style="padding:12px 20px;background:#17332e;color:#c4ffee;font:14px system-ui">Connecting to local weather feed…</div>',body,count=1,flags=re.I)
   body=body.replace('</body>','<script src="/weather-status.js"></script></body>');self.send(body.encode(),'text/html; charset=utf-8');return
  if path=='/' and not file.exists():
   self.send((SOURCE/'waiting.html').read_bytes(),'text/html; charset=utf-8');return
  # No directory listing or access to station configuration/database files.
  if file.is_dir():self.send(b'Not found','text/plain',404);return
  super().do_GET()
 def do_POST(self):
  if self.path!='/api/source':self.send(b'{}',status=404);return
  origin=self.headers.get('Origin')
  if self.headers.get('X-Weather-Token')!=TOKEN or (origin and urlsplit(origin).netloc!=self.headers.get('Host')):self.send(b'{"error":"Reload the weather page before changing the source"}',status=403);return
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=2048:raise ValueError('Invalid request size')
   selection=json.loads(self.rfile.read(length)).get('selection')
   with LOCK:
    if selection not in ('auto','none') and not any(row['id']==selection for row in STATE['candidates']):raise ValueError('Choose a discovered weather sensor')
    SETTINGS['selection']=selection;save_settings();STATE.update(selection=selection,reading=None,fresh=False,status='Waiting for selected weather sensor')
   self.send(b'{"ok":true}')
  except (ValueError,TypeError,OSError) as exc:self.send(json.dumps(dict(error=str(exc))).encode(),status=400)
 def log_message(self,format,*args):pass

if __name__=='__main__':
 threading.Thread(target=collect,daemon=True).start();ThreadingHTTPServer(('0.0.0.0',8094),Handler).serve_forever()
