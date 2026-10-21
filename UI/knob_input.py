"""Nonblocking input for the r2 CM5's three encoders.

Only the board's named devices are opened; mouse wheels and the touchscreen
are never consumed or grabbed. The kernel already decodes quadrature clicks.
"""
from dataclasses import dataclass
import os
import fcntl
from pathlib import Path
import struct
import time

EVENT = struct.Struct('@llHHi')
AXES = {'ituner-tune-encoder': ('TUNE', 7),
        'ituner-view-encoder': ('VIEW', 8),
        'ituner-nav-encoder': ('NAV', 6)}
BUTTON_DEVICE = 'iTuner encoder buttons'
BUTTONS = {0x100: 'VIEW', 0x101: 'NAV'}


@dataclass(frozen=True)
class KnobEvent:
    role: str
    kind: str
    value: int = 0


class KnobDecoder:
    """Decode clicks and short/long presses; discard lost synchronization."""
    def __init__(self, hold_seconds=0.65):
        self.hold_seconds = hold_seconds
        self.pressed = {}
        self.dropped = set()

    def disconnect(self, name):
        self.dropped.discard(name)
        if name == BUTTON_DEVICE:
            self.pressed.clear()

    def feed(self, name, event_type, code, value, now):
        if event_type == 0 and code == 3:  # SYN_DROPPED
            self.disconnect(name)
            self.dropped.add(name)
            return []
        if name in self.dropped:
            if event_type == 0 and code == 0:
                self.dropped.remove(name)
            return []
        if name in AXES and event_type == 2 and code == AXES[name][1] and value:
            return [KnobEvent(AXES[name][0], 'turn', value)]
        if name == BUTTON_DEVICE and event_type == 1 and code in BUTTONS:
            role = BUTTONS[code]
            if value == 1 and role not in self.pressed:
                self.pressed[role] = (now, False)
            elif value == 0:
                press = self.pressed.pop(role, None)
                if press is not None and not press[1]:
                    kind = 'hold' if now - press[0] >= self.hold_seconds else 'click'
                    return [KnobEvent(role, kind)]
        return []

    def poll(self, now):
        events = []
        for role, (started, held) in tuple(self.pressed.items()):
            if not held and now - started >= self.hold_seconds:
                self.pressed[role] = (started, True)
                events.append(KnobEvent(role, 'hold'))
        return events


class LinuxKnobReader:
    """Discover by sysfs name, reconnect automatically, and bound work per frame."""
    def __init__(self, sysfs='/sys/class/input', dev='/dev/input'):
        self.sysfs, self.dev = Path(sysfs), Path(dev)
        self.decoder = KnobDecoder()
        self.devices = {}
        self.next_scan = 0
        self.errors = {}

    def scan(self, now):
        self.next_scan = now + 2
        found = set()
        for entry in self.sysfs.glob('event*'):
            try:
                name = (entry / 'device/name').read_text().strip()
            except OSError:
                continue
            if name not in AXES and name != BUTTON_DEVICE:
                continue
            path = self.dev / entry.name
            found.add(path)
            if path not in self.devices:
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                except OSError as exc:
                    self.errors[str(path)] = str(exc)
                    continue
                try:
                    # Kernel timestamps share the clock used for hold deadlines.
                    fcntl.ioctl(fd, 0x400445A0, struct.pack("i", time.CLOCK_MONOTONIC))
                except OSError as exc:
                    os.close(fd)
                    self.errors[str(path)] = str(exc)
                    continue
                self.errors.pop(str(path), None)
                self.devices[path] = (fd, name)
        for path in set(self.devices) - found:
            self._remove(path)

    def _remove(self, path):
        fd, name = self.devices.pop(path)
        os.close(fd)
        self.decoder.disconnect(name)

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        if now >= self.next_scan:
            self.scan(now)
        events = []
        for path, (fd, name) in tuple(self.devices.items()):
            try:
                # At most 256 events per device per frame, including syncs.
                data = os.read(fd, EVENT.size * 256)
                if not data:
                    self._remove(path)
                    continue
                for sec, usec, kind, code, value in EVENT.iter_unpack(data):
                    events.extend(self.decoder.feed(name, kind, code, value, sec + usec / 1_000_000))
            except BlockingIOError:
                pass
            except OSError:
                self._remove(path)
        events.extend(self.decoder.poll(now))
        return events

    def close(self):
        for path in tuple(self.devices):
            self._remove(path)
