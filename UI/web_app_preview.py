"""Managed Chromium previews for separately installed satellite applications."""
import html
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time


WEB_APPS = {
    'groundstation': dict(name='Ground Station', port=7000, path='/earthview'),
    'satvisor': dict(name='Satvisor', port=8095, path='/'),
}


class WebAppPreviews:
    def __init__(self, port=8092):
        self.port = port
        self.rotation = 0
        self.process = None
        self.key = None
        self.resume_at = 0
        self.return_to_decoders = False
        self.lock = threading.RLock()

    @property
    def active(self):
        with self.lock:
            if self.process and self.process.poll() is not None:
                self.process = None
                self.key = None
                self.resume_at = time.monotonic() + .5
                self.return_to_decoders = True
            return self.process is not None

    @property
    def blocks_touch(self):
        return self.active or time.monotonic() < self.resume_at

    def open(self, key):
        if key not in WEB_APPS:
            raise ValueError('Unknown satellite application')
        with self.lock:
            if self.active:
                if self.key == key:
                    return
                raise ValueError('Return to Decoders before opening another preview')
            browser = shutil.which('chromium') or shutil.which('chromium-browser')
            if not browser:
                raise ValueError('Chromium is required for touchscreen web previews')
            profile = Path.home()/'.local/share/ituner-sdr/web-app-preview'
            profile.mkdir(mode=0o700, parents=True, exist_ok=True)
            url = f'http://127.0.0.1:{self.port}/apps/{key}?touch=1&rotation={self.rotation}'
            env = dict(os.environ, WAYLAND_DISPLAY=os.environ.get('WAYLAND_DISPLAY', 'wayland-0'),
                       XDG_RUNTIME_DIR=os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
            self.process = subprocess.Popen([
                browser, '--ozone-platform=wayland', '--kiosk', '--no-first-run',
                '--no-default-browser-check', '--disable-session-crashed-bubble',
                '--disable-pinch', '--password-store=basic', f'--user-data-dir={profile}',
                f'--app={url}',
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
#error{position:absolute;top:75px;left:20px;padding:15px;background:#632c28;border-radius:8px;font-size:20px}
</style></head><body><div class="preview"><header><button id="back">← Decoders</button>
<strong>TITLE</strong><small>WEB PREVIEW</small><button id="reload">Reload</button></header>
<iframe title="TITLE application" src="SOURCE"></iframe><div id="error" hidden></div></div>
<script>
const frame=document.querySelector('iframe');
document.getElementById('reload').onclick=()=>{frame.src=frame.src;};
document.getElementById('back').onclick=async()=>{
 if(!TOUCH){location.href='/';return;}
 try{const r=await fetch('/api/web-app',{method:'POST',headers:{'Content-Type':'application/json','X-VHF-Token':TOKEN},body:JSON.stringify({action:'close'})});if(!r.ok)throw Error('Could not return to Decoders');}
 catch(e){const box=document.getElementById('error');box.hidden=false;box.textContent=e.message;}
};
</script></body></html>'''.replace('SHELL', css).replace('TITLE', title)
            .replace('SOURCE', html.escape(source, quote=True))
            .replace('TOUCH', 'true' if touch else 'false').replace('TOKEN', json.dumps(token)))
