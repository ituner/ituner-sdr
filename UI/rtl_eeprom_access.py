"""Serial-only EEPROM writes through one verified RTL-SDR handle."""
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import sys
from rtl_registry import serial_image, usb_inventory, usb_order


def usb_handles(root=Path('/proc/self/fd')):
    handles={}
    for path in root.iterdir():
        try:target=os.readlink(path)
        except OSError:continue
        if target.startswith('/dev/bus/usb/'):handles[int(path.name)]=target
    return handles


def serial_bounds(raw):
    offset=9
    for _ in range(2):offset+=raw[offset]
    return offset,raw[offset]


def change_serial(device,original,serial):
    expected=serial_image(original,serial)
    if device.read()!=original:raise ValueError('EEPROM differs from its backup; programming cancelled')
    offset,length=serial_bounds(original)
    device.write(offset,expected[offset:offset+length])
    if device.read()!=expected:raise ValueError('EEPROM read-back differs from the expected serial-only update; original backup retained')


class EepromDevice:
    def __init__(self,index,bus,address):
        self.lib=ctypes.CDLL(ctypes.util.find_library('rtlsdr') or 'librtlsdr.so.0');self.handle=ctypes.c_void_p()
        ptr=ctypes.c_void_p;data=ctypes.POINTER(ctypes.c_uint8)
        self.lib.rtlsdr_open.argtypes=[ctypes.POINTER(ptr),ctypes.c_uint32]
        self.lib.rtlsdr_close.argtypes=[ptr]
        for name in ('rtlsdr_read_eeprom','rtlsdr_write_eeprom'):
            getattr(self.lib,name).argtypes=[ptr,data,ctypes.c_uint8,ctypes.c_uint16]
        order=usb_order();physical=usb_inventory();identity=(bus,address)
        target=next((p for p in physical if (p['bus'],p['address'])==identity),None)
        if (not target or self.lib.rtlsdr_get_device_count()!=len(order) or
                not 0<=index<len(order) or order[index]!=identity):
            raise ValueError('USB order changed before opening the selected receiver')
        self.identity=identity;self.usb_path=target['usb_path'];self.node=f'/dev/bus/usb/{bus:03d}/{address:03d}'
        before=set(usb_handles())
        result=self.lib.rtlsdr_open(ctypes.byref(self.handle),index)
        if result<0:raise ValueError(f'Could not open the receiver ({result})')
        try:
            opened={fd:path for fd,path in usb_handles().items() if fd not in before}
            if len(opened)!=1 or list(opened.values())!=[self.node]:
                raise ValueError('Opened USB handle does not match the selected physical receiver')
            self.usb_fd=next(iter(opened));self.verify_target()
        except Exception:
            self.close();raise
    def verify_target(self):
        current=next((p for p in usb_inventory() if p['usb_path']==self.usb_path),None)
        if (not current or (current['bus'],current['address'])!=self.identity or
                usb_handles().get(self.usb_fd)!=self.node):
            raise ValueError('Selected USB receiver changed or disconnected; programming cancelled')
    def read(self):
        self.verify_target()
        data=(ctypes.c_uint8*256)()
        result=self.lib.rtlsdr_read_eeprom(self.handle,data,0,256)
        if result<0:raise ValueError(f'EEPROM read failed ({result})')
        return bytes(data)
    def write(self,offset,data):
        self.verify_target()
        buf=(ctypes.c_uint8*len(data)).from_buffer_copy(data)
        result=self.lib.rtlsdr_write_eeprom(self.handle,buf,offset,len(data))
        if result<0:raise ValueError(f'EEPROM serial write failed ({result}); backup retained')
    def close(self):self.lib.rtlsdr_close(self.handle)


def main():
    index,bus,address,backup,serial=sys.argv[1:]
    devices=usb_inventory()
    if sum((d['bus'],d['address'])==(int(bus),int(address)) for d in devices)!=1:raise ValueError('USB inventory changed before programming')
    original=Path(backup).read_bytes();serial_image(original,serial)
    device=EepromDevice(int(index),int(bus),int(address))
    try:change_serial(device,original,serial)
    finally:device.close()
    print(json.dumps(dict(ok=True,serial=serial)))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
