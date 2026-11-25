"""CM5 power-key requests: one confirmation per press, never direct shutdown."""
import fcntl
import os
from pathlib import Path
import select
import struct
import threading
import time

EVENT = struct.Struct('@llHHi')
EV_KEY, KEY_POWER, EVIOCGRAB = 1, 116, 0x40044590


class PowerButton:
    def __init__(self, input_root='/sys/class/input', device_root='/dev/input'):
        self.fd=None;self.closed=threading.Event();self.pending=threading.Event()
        self.down=False;self.last_press=None;self.thread=None;self.buffer=b''
        for entry in sorted(Path(input_root).glob('event*')):
            try:
                if (entry/'device/name').read_text().strip()!='pwr_button':continue
                fd=os.open(str(Path(device_root)/entry.name),os.O_RDONLY|os.O_NONBLOCK)
                try:fcntl.ioctl(fd,EVIOCGRAB,1)
                except OSError:os.close(fd);raise
                self.fd=fd
                self.thread=threading.Thread(target=self._run,name='power-button',daemon=True)
                self.thread.start()
                print('Hardware power button ready: confirmation required',flush=True)
                break
            except OSError as exc:print('Hardware power button unavailable: '+str(exc),flush=True)

    def event(self,kind,code,value,now=None):
        if kind!=EV_KEY or code!=KEY_POWER:return
        if value==0:self.down=False;return
        if value!=1 or self.down:return
        self.down=True;now=time.monotonic() if now is None else now
        if self.last_press is None or now-self.last_press>=.5:
            self.last_press=now;self.pending.set()

    def consume(self):
        if not self.pending.is_set():return False
        self.pending.clear();return True

    def _run(self):
        try:
            while not self.closed.is_set():
                if not select.select([self.fd],[],[],1)[0]:continue
                try:data=os.read(self.fd,EVENT.size*16)
                except BlockingIOError:continue
                if not data:break
                self.buffer+=data
                while len(self.buffer)>=EVENT.size:
                    _,_,kind,code,value=EVENT.unpack(self.buffer[:EVENT.size]);self.buffer=self.buffer[EVENT.size:]
                    self.event(kind,code,value)
        except OSError as exc:
            if not self.closed.is_set():print('Hardware power input stopped: '+str(exc),flush=True)

    def close(self):
        self.closed.set()
        if self.thread:self.thread.join(timeout=1.2)
        if self.fd is not None:
            try:fcntl.ioctl(self.fd,EVIOCGRAB,0)
            finally:os.close(self.fd);self.fd=None
