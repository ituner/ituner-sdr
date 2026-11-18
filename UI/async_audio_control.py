"""Coalesce UI codec requests without waiting on hardware or reconnect locks."""
import atexit
import logging
import math
import threading
from collections import deque


class AsyncAudioControl:
    def __init__(self, backend):
        self.backend = backend
        self._volume = backend.get_volume()
        self._condition = threading.Condition()
        self._commands = deque()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name='codec-control', daemon=True)
        self._thread.start()
        atexit.register(self.close)

    def get_volume(self):
        with self._condition:
            return self._volume

    def _control(self, name, value):
        with self._condition:
            if self._closed:
                return False
            if name == 'volume':
                self._volume = value
            # Only merge adjacent controls: prepare/ready are ordering barriers.
            if not self._commands or self._commands[-1][0] != 'controls':
                self._commands.append(('controls', {}, None))
            self._commands[-1][1][name] = value
            self._condition.notify()
            return True

    def set_volume(self, value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError('Volume must be finite')
        value = min(1.0, max(0.0, value))
        return value if self._control('volume', value) else None

    def set_mute(self, value):
        self._control('mute', bool(value))

    def _barrier(self, method, *args):
        # Called by audio workers, never the render loop during listening.
        done = threading.Event()
        result = {}
        with self._condition:
            if self._closed:
                return False
            self._commands.append((method, args, (done, result)))
            self._condition.notify()
        done.wait()
        if 'error' in result:
            raise result['error']
        return result.get('value')

    def prepare(self):
        return self._barrier('prepare')

    def ready(self, value=True):
        return self._barrier('ready', value)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._commands or self._closed)
                if not self._commands:
                    return
                method, args, completion = self._commands.popleft()
            try:
                if method == 'controls':
                    # Mute before changing level; unmute only after the new level.
                    if args.get('mute') is True:
                        self.backend.set_mute(True)
                    if 'volume' in args:
                        self.backend.set_volume(args['volume'])
                    if args.get('mute') is False:
                        self.backend.set_mute(False)
                else:
                    completion[1]['value'] = getattr(self.backend, method)(*args)
            except Exception as exc:
                logging.exception('Codec control request failed')
                if completion:
                    completion[1]['error'] = exc
            finally:
                if completion:
                    completion[0].set()

    def close(self):
        with self._condition:
            if self._closed:
                return
            self._closed = True
            for _method, _args, completion in self._commands:
                if completion:
                    completion[1]['value'] = False
                    completion[0].set()
            self._commands.clear()
            # Last command disables the amp even if a hardware call was in flight.
            self._commands.append(('ready', (False,), (threading.Event(), {})))
            self._condition.notify()
        self._thread.join(timeout=3.0)
