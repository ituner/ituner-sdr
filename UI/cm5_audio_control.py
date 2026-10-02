"""Opt-in CM5 codec controls; active only with ITUNER_CM5_AUDIO=1."""
import atexit
import os
import time
import logging
import math
import subprocess
import threading
_volume = 0.75
# Honor the app's saved mute state before opening the playback device.
import json
from pathlib import Path
try:
    _saved = json.loads((Path.home()/'.local/state/kiwi-gl-display-receiver.json').read_text())
    _muted = bool(_saved.get('preferences', {}).get('audio', {}).get('audio_mute', False))
except (OSError, ValueError):
    _muted = False
_ready = False
_gate = None
_lock = threading.RLock()
_jack_path = os.environ.get('ITUNER_CM5_JACK_STATE')
# Unknown/stale detection inhibits only the speaker, never the codec.
_headphone_blocked = bool(_jack_path)
_jack_stop = threading.Event()

def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, timeout=2)

def gate():
    global _gate
    enabled = _ready and not _muted and _volume > 0 and not _headphone_blocked
    if enabled != _gate:
        run('pinctrl', 'set', '13', 'op', 'dh' if enabled else 'dl')
        _gate = enabled

def card_available():
    try:
        return any(p.read_text().strip() == "CM5ES8316"
                   for p in Path("/sys/class/sound").glob("card*/id"))
    except OSError:
        return False

def get_volume():
    return _volume

def set_volume(value):
    global _volume, _ready
    with _lock:
        value = min(1.0, max(0.0, float(value)))
        _volume = value
        if not card_available():
            _ready = False
            gate()
            return value
        raw = 0 if value == 0 else max(1, min(192, round(192 + 40 * math.log10(value))))
        run('amixer', '-q', '-c', 'CM5ES8316', 'sset', 'DAC', str(raw))
        _volume = value
        gate()
        return value

def set_mute(value):
    global _muted
    with _lock:
        _muted = bool(value)
        gate()

def prepare():
    global _ready
    with _lock:
        _ready = False
        gate()
        if not card_available():
            return False
        for name, value in [('Headphone','3'), ('Headphone Mixer','11'),
                            ('Left Headphone Mixer LLIN','off'), ('Right Headphone Mixer RLIN','off'),
                            ('Left Headphone Mixer Left DAC','on'), ('Right Headphone Mixer Right DAC','on')]:
            run('amixer','-q','-c','CM5ES8316','sset',name,value)
        set_volume(_volume)

def ready(value=True):
    global _ready
    with _lock:
        _ready = bool(value) and card_available()
        gate()

def _watch_headphones():
    global _headphone_blocked
    while not _jack_stop.is_set():
        blocked = True
        try:
            state = json.loads(Path(_jack_path).read_text())
            age = time.monotonic() - float(state['monotonic'])
            if 0 <= age <= 2.0 and type(state['inserted']) is bool:
                blocked = state['inserted']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        with _lock:
            changed = blocked != _headphone_blocked
            _headphone_blocked = blocked
            try:
                gate()
                if changed:
                    print('CM5 speaker: ' + ('inhibited by headphone detection' if blocked else 'following SDR volume/mute'), flush=True)
            except (OSError, subprocess.SubprocessError):
                logging.exception('Could not update CM5 speaker enable')
        _jack_stop.wait(0.1)

def _shutdown():
    _jack_stop.set()
    ready(False)

atexit.register(_shutdown)
if _jack_path:
    threading.Thread(target=_watch_headphones, name='cm5-headphone-gate', daemon=True).start()
