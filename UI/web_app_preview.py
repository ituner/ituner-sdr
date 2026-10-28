"""Managed Chromium previews for separately installed satellite applications."""
import html
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.request import urlopen
from urllib.error import URLError


WEB_APPS = {
    'groundstation': dict(name='Ground Station', port=7000, path='/earthview'),
    'satvisor': dict(name='Satvisor', port=8095, path='/'),
}


class WebAppPreviews:
    def __init__(self, port=8092):
        self.port = port
        self.rotation = 0
        self.hostname = os.environ.get("ITUNER_SATELLITE_HOST", "").strip()
        self.process = None
        self.key = None
        self.resume_at = 0
        self.return_to_decoders = False
        self.lock = threading.RLock()
        self.error_notice = None
        self.error_until = 0

    @property
    def active(self):
        with self.lock:
            if self.process and self.process.poll() is not None:
                if self.process.returncode:
                    self._show_error(self.key, "Browser closed unexpectedly. Please try again.")
                self.process = None
                self.key = None
                self.resume_at = time.monotonic() + .5
                self.return_to_decoders = True
            return self.process is not None

    @property
    def blocks_touch(self):
        return self.active or time.monotonic() < self.resume_at

    def _show_error(self, key, detail):
        name = WEB_APPS.get(key, {}).get('name', 'Application')
        self.error_notice = (f'Could not open {name}', detail)
        self.error_until = time.monotonic() + 8

    @property
    def notice(self):
        """Native feedback remains visible until the browser covers the SDR."""
        with self.lock:
            if self.active:
                return (f'Loading {WEB_APPS[self.key]["name"]}…', 'Please wait')
            if time.monotonic() < self.error_until:
                return self.error_notice
            return None

    def open(self, key):
        with self.lock:
            try:
                self._open(key)
            except (OSError, ValueError) as exc:
                if not self.active:
                    self._show_error(key, str(exc))
                raise
            self.error_notice = None
            self.error_until = 0

    def validate_destination(self, key):
        """Do not surrender native navigation to a missing service or wrong port."""
        try:
            with urlopen(f'http://127.0.0.1:{self.port}/apps/{key}', timeout=2) as response:
                if b'id="back"' not in response.read(32768):
                    raise ValueError('Preview is unavailable. Return to Decoders and retry.')
        except (OSError, URLError) as exc:
            raise ValueError('Preview is unavailable. Return to Decoders and retry.') from exc
        app = WEB_APPS[key]
        host = self.hostname or '127.0.0.1'
        if ':' in host:host=f'[{host}]'
        try:
            with urlopen(f'http://{host}:{app["port"]}{app["path"]}', timeout=2) as response:
                body=response.read(65536).lower().replace(b' ', b'')
                if app['name'].lower().replace(' ', '').encode() not in body:
                    raise ValueError(f'{app["name"]} is not available at its configured address.')
        except (OSError, URLError) as exc:
            raise ValueError(f'{app["name"]} is not running or reachable.') from exc

    def _open(self, key):
        if key not in WEB_APPS:
            raise ValueError('Unknown satellite application')
        with self.lock:
            if self.active:
                if self.key == key:
                    return
                raise ValueError('Return to Decoders before opening another preview')
            if sys.platform == 'darwin':
                candidates = [base / f'{name}.app/Contents/MacOS/{name}'
                              for base in (Path('/Applications'), Path.home() / 'Applications')
                              for name in ('Google Chrome', 'Chromium')]
                browser = next((str(path) for path in candidates if path.is_file()), None)
                if not browser:
                    raise ValueError('Install Google Chrome or Chromium to open satellite previews')
                profile = Path.home()/'Library/Application Support/iTuner/web-app-preview'
                platform_args = ['--window-size=1280,800']
                env = os.environ.copy()
            else:
                browser = shutil.which('chromium') or shutil.which('chromium-browser')
                if not browser:
                    raise ValueError('Chromium is required for touchscreen web previews')
                profile = Path.home()/'.local/share/ituner-sdr/web-app-preview'
                platform_args = ['--ozone-platform=wayland', '--kiosk', '--password-store=basic']
                env = dict(os.environ, WAYLAND_DISPLAY=os.environ.get('WAYLAND_DISPLAY', 'wayland-0'),
                           XDG_RUNTIME_DIR=os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
            self.validate_destination(key)
            profile.mkdir(mode=0o700, parents=True, exist_ok=True)
            url = f'http://127.0.0.1:{self.port}/apps/{key}?touch=1&rotation={self.rotation}'
            self.process = subprocess.Popen([
                browser, *platform_args, '--no-first-run',
                '--no-default-browser-check', '--disable-session-crashed-bubble',
                '--disable-pinch', f'--user-data-dir={profile}', f'--app={url}',
            ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            self.key = key

    def close(self):
        with self.lock:
            process = self.process
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
                except ProcessLookupError:
                    pass
            self.process = None
            self.key = None
            self.error_notice = None
            self.error_until = 0
            self.resume_at = time.monotonic() + .5
            self.return_to_decoders = True


def preview_html(key, hostname, token, *, touch=False, rotation=0):
    app = WEB_APPS[key]
    host = f'[{hostname}]' if ':' in hostname else hostname
    source = f'http://{host}:{app["port"]}{app["path"]}'
    title = html.escape(app['name'])
    # Rotate the entire viewport as the native renderer does, including its
    # return controls. CSS transforms also transform browser touch hit testing.
    css = ('width:100vh;height:100vw;left:100vw;transform:rotate(90deg);' if rotation == 90
           else 'width:100vh;height:100vw;top:100vh;transform:rotate(-90deg);' if rotation == 270
           else 'width:100vw;height:100vh;')
    return ('''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>iTuner · TITLE preview</title><style>
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#080e15;color:#e4edf5;font-family:system-ui,sans-serif}
.preview{position:absolute;transform-origin:0 0;display:flex;flex-direction:column;SHELL}
header{height:64px;flex:none;display:flex;align-items:center;gap:14px;padding:4px 12px;background:#101d29;border-bottom:1px solid #355065}
button,a{min-height:56px;padding:10px 18px;border:1px solid #557b8f;border-radius:8px;background:#20384a;color:inherit;font-size:20px;text-decoration:none;cursor:pointer}
strong{font-size:20px}small{color:#a3bacb;font-size:14px;margin-left:auto}iframe{flex:1;width:100%;min-height:0;border:0;background:#000}
#loading{position:absolute;inset:64px 0 0;display:grid;place-items:center;background:#080e15}
#loading[hidden]{display:none}#loading .card{text-align:center;padding:24px 36px;border:1px solid #557b8f;border-radius:12px;background:#101d29;font-size:24px}
#loading p{font-size:18px;color:#a3bacb;margin-bottom:0}
#error{position:absolute;top:75px;left:20px;padding:15px;background:#632c28;border-radius:8px;font-size:20px}
</style></head><body><div class="preview"><header><button id="back">← Decoders</button>
<strong>TITLE</strong><small>WEB PREVIEW</small><button id="reload">Reload</button></header>
<iframe title="TITLE application" sandbox="allow-scripts allow-same-origin allow-forms allow-downloads" data-source="SOURCE"></iframe>
<div id="loading" role="status" aria-live="polite"><div class="card"><strong>Loading TITLE…</strong><p id="loading-detail">Please wait</p></div></div>
<div id="error" hidden></div></div>
<script>
const frame=document.querySelector('iframe');
const loading=document.getElementById('loading');
const detail=document.getElementById('loading-detail');
let loadingTimer;
function loadApp(){
 loading.hidden=false;detail.textContent='Please wait';
 clearTimeout(loadingTimer);
 loadingTimer=setTimeout(()=>{detail.textContent='Taking longer than expected. Try Reload or return to Decoders.';},20000);
 frame.src=frame.dataset.source;
}
frame.onload=()=>{if(frame.getAttribute('src')){clearTimeout(loadingTimer);loading.hidden=true;}};
document.getElementById('reload').onclick=loadApp;
loadApp();
document.getElementById('back').onclick=async()=>{
 if(!TOUCH){location.href='/';return;}
 try{const r=await fetch('/api/web-app',{method:'POST',headers:{'Content-Type':'application/json','X-VHF-Token':TOKEN},body:JSON.stringify({action:'close'})});if(!r.ok)throw Error('Could not return to Decoders');}
 catch(e){const box=document.getElementById('error');box.hidden=false;box.textContent=e.message;}
};
</script></body></html>'''.replace('SHELL', css).replace('TITLE', title)
            .replace('SOURCE', html.escape(source, quote=True))
            .replace('TOUCH', 'true' if touch else 'false').replace('TOKEN', json.dumps(token)))
