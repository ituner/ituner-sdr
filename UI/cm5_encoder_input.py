"""V4 mechanical encoder inputs; actions are applied by the UI thread."""
import errno
import threading
from collections import Counter
from datetime import timedelta
from pathlib import Path


class Quadrature:
    # Clockwise was observed as 00 -> 10 -> 11 -> 01 -> 00 on both knobs.
    FORWARD = {(0, 2), (2, 3), (3, 1), (1, 0)}
    REVERSE = {(b, a) for a, b in FORWARD}

    def __init__(self, state, edges_per_step=4):
        self.state = state
        self.partial = 0
        self.edges_per_step = edges_per_step

    def reset(self, state):
        self.state = state
        self.partial = 0

    def feed(self, state):
        old, self.state = self.state, state
        if old == state:
            return 0
        transition = (old, state)
        if transition in self.FORWARD:
            self.partial += 1
        elif transition in self.REVERSE:
            self.partial -= 1
        else:
            self.partial = 0
            return 0
        if abs(self.partial) >= self.edges_per_step:
            step = 1 if self.partial > 0 else -1
            self.partial -= step * self.edges_per_step
            return step
        return 0


class EncoderReader:
    PAIRS = {"zoom": (26, 13), "volume": (6, 5)}

    def __init__(self, *, pairs=None, debounce_us=200, pending_limit=100, edges_per_step=4):
        import gpiod
        from gpiod.line import Bias, Direction, Edge, Value
        self._gpiod, self._value = gpiod, Value
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending = Counter()
        self.PAIRS = dict(self.PAIRS if pairs is None else pairs)
        self._lines = [line for pair in self.PAIRS.values() for line in pair]
        self._pending_limit = pending_limit
        self._edges_per_step = edges_per_step
        chip_path = None
        for path in sorted(Path('/dev').glob('gpiochip*'), key=lambda p: int(p.name[8:])):
            with gpiod.Chip(str(path)) as chip:
                if chip.get_info().label == 'pinctrl-rp1':
                    for line in self._lines:
                        if chip.get_line_info(line).used:
                            raise RuntimeError(f'Encoder GPIO{line} already owned')
                    chip_path = str(path)
                    break
        if chip_path is None:
            raise RuntimeError('RP1 GPIO controller not found')
        settings = dict(direction=Direction.INPUT, edge_detection=Edge.BOTH,
                        bias=Bias.DISABLED)
        self.debounce_us = debounce_us
        try:
            self._request = gpiod.request_lines(
                chip_path, consumer='ituner-v4-encoders',
                config={tuple(self._lines): gpiod.LineSettings(
                    **settings, debounce_period=timedelta(microseconds=self.debounce_us))},
                event_buffer_size=8192)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.EOPNOTSUPP, errno.ENOTSUP):
                raise
            self.debounce_us = 0
            self._request = gpiod.request_lines(
                chip_path, consumer='ituner-v4-encoders',
                config={tuple(self._lines): gpiod.LineSettings(**settings)},
                event_buffer_size=8192)
        self._levels = {}
        self._decoders = {}
        self._resync()
        self._thread = threading.Thread(target=self._run, name='v4-encoders', daemon=True)
        self._thread.start()
        print(f'V4 encoders active: {self.PAIRS}; '
              f'GPIO debounce={self.debounce_us}us; {self._edges_per_step} edges/step', flush=True)

    def _state(self, role):
        a, b = self.PAIRS[role]
        return self._levels[a] * 2 + self._levels[b]

    def _resync(self):
        self._levels = {n: int(v == self._value.ACTIVE) for n, v in
                        zip(self._lines, self._request.get_values(self._lines))}
        for role in self.PAIRS:
            if role in self._decoders:
                self._decoders[role].reset(self._state(role))
            else:
                self._decoders[role] = Quadrature(self._state(role), self._edges_per_step)

    def _run(self):
        last_sequence = None
        try:
            while not self._stop.is_set():
                if not self._request.wait_edge_events(timedelta(milliseconds=100)):
                    continue
                events = self._request.read_edge_events(max_events=1024)
                expected = last_sequence
                lost = False
                for event in events:
                    if expected is not None and event.global_seqno != expected + 1:
                        lost = True
                    expected = event.global_seqno
                last_sequence = expected
                if lost:
                    # Drop buffered transitions and partial counts rather than guess movement.
                    while self._request.wait_edge_events(timedelta(0)):
                        batch = self._request.read_edge_events(max_events=1024)
                        if batch:
                            last_sequence = batch[-1].global_seqno
                    with self._lock:
                        self._pending.clear()
                    self._resync()
                    print('V4 encoders: event gap, partial movement discarded', flush=True)
                    continue
                for event in events:
                    role = next(k for k, pair in self.PAIRS.items() if event.line_offset in pair)
                    self._levels[event.line_offset] = int(
                        event.event_type == self._gpiod.EdgeEvent.Type.RISING_EDGE)
                    delta = self._decoders[role].feed(self._state(role))
                    if delta:
                        with self._lock:
                            self._pending[role] = max(-self._pending_limit, min(self._pending_limit, self._pending[role] + delta))
        except Exception as exc:
            with self._lock:
                self._pending.clear()
            print(f'V4 encoder reader stopped: {exc}', flush=True)
        finally:
            self._request.release()

    def poll(self):
        with self._lock:
            result = [(role, count) for role, count in self._pending.items() if count]
            self._pending.clear()
        return result

    def close(self):
        self._stop.set()
        self._thread.join(timeout=1.0)


class OpticalEncoderReader(EncoderReader):
    """V4 CN13: 360 pulses/revolution, clockwise positive, no debounce."""
    def __init__(self):
        super().__init__(pairs={"tune": (23, 24)}, debounce_us=0, pending_limit=5760, edges_per_step=1)
