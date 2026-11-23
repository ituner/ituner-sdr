"""Debounced V4 expander buttons; never own reset, amplifier, or jack lines."""
from collections import deque
from pathlib import Path
import threading
import time


class PressFilter:
    def __init__(self, pressed=False, debounce=.04):
        self.stable = self.candidate = bool(pressed)
        self.changed_at = 0.0
        self.debounce = debounce

    def feed(self, pressed, now):
        pressed = bool(pressed)
        if pressed != self.candidate:
            self.candidate = pressed
            self.changed_at = now
        if self.candidate != self.stable and now - self.changed_at >= self.debounce:
            self.stable = self.candidate
            return self.stable
        return False


class ButtonReader:
    # The installed top volume knob's push contact was measured on ENC2_D/P10.
    LINES = {0: 'ptt', 1: 'map', 2: 'display', 3: 'band', 4: 'mode', 8: 'mute',
             9: 'scan', 11: 'mute'}

    def __init__(self):
        import gpiod
        from gpiod.line import Bias, Direction, Value
        self._value = Value
        path = None
        for candidate in Path('/dev').glob('gpiochip*'):
            with gpiod.Chip(str(candidate)) as chip:
                if chip.get_info().label == '1-0020':
                    for line in self.LINES:
                        if chip.get_line_info(line).used:
                            raise RuntimeError(f'V4 button line {line} is already owned')
                    path = str(candidate)
                    break
        if path is None:
            raise RuntimeError('V4 button expander not found')
        self._request = gpiod.request_lines(path, consumer='ituner-v4-buttons',
            config={tuple(self.LINES): gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.DISABLED)})
        try:
            initial = self._request.get_values(list(self.LINES))
            self._filters = {line: PressFilter(value == Value.INACTIVE)
                             for line, value in zip(self.LINES, initial)}
        except Exception:
            self._request.release()
            raise
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending = deque(maxlen=32)
        self._thread = threading.Thread(target=self._run, name='v4-buttons', daemon=True)
        self._thread.start()
        print('V4 buttons active; 40ms debounce, one action per press', flush=True)

    def _run(self):
        try:
            while not self._stop.wait(.02):
                values = self._request.get_values(list(self.LINES))
                now = time.monotonic()
                for line, value in zip(self.LINES, values):
                    if self._filters[line].feed(value == self._value.INACTIVE, now):
                        with self._lock:
                            self._pending.append(self.LINES[line])
        except Exception as exc:
            print(f'V4 button reader stopped: {exc}', flush=True)
        finally:
            self._request.release()

    def poll(self):
        with self._lock:
            result = list(self._pending)
            self._pending.clear()
            return result

    def close(self):
        self._stop.set()
        self._thread.join(timeout=1.0)


if __name__ == '__main__':
    reader = ButtonReader()
    try:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            for button in reader.poll():
                print(f'{time.strftime("%H:%M:%S")} PRESS {button}', flush=True)
            time.sleep(.02)
    finally:
        reader.close()
