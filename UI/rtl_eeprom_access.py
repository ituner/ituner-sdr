"""Serial-only EEPROM writes through one verified RTL-SDR handle."""
import ctypes
import ctypes.util
import json
from pathlib import Path
import sys
from rtl_registry import serial_image, usb_inventory


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
    def __init__(self,index):
        self.lib=ctypes.CDLL(ctypes.util.find_library('rtlsdr') or 'librtlsdr.so.0');self.handle=ctypes.c_void_p()
        ptr=ctypes.c_void_p;data=ctypes.POINTER(ctypes.c_uint8)
        self.lib.rtlsdr_open.argtypes=[ctypes.POINTER(ptr),ctypes.c_uint32]
        self.lib.rtlsdr_close.argtypes=[ptr]
        for name in ('rtlsdr_read_eeprom','rtlsdr_write_eeprom'):
            getattr(self.lib,name).argtypes=[ptr,data,ctypes.c_uint8,ctypes.c_uint16]
        if self.lib.rtlsdr_get_device_count()!=1:raise ValueError('Only the receiver being programmed may be connected')
        result=self.lib.rtlsdr_open(ctypes.byref(self.handle),index)
        if result<0:raise ValueError(f'Could not open the receiver ({result})')
    def read(self):
        data=(ctypes.c_uint8*256)()
        result=self.lib.rtlsdr_read_eeprom(self.handle,data,0,256)
        if result<0:raise ValueError(f'EEPROM read failed ({result})')
        return bytes(data)
    def write(self,offset,data):
        buf=(ctypes.c_uint8*len(data)).from_buffer_copy(data)
        result=self.lib.rtlsdr_write_eeprom(self.handle,buf,offset,len(data))
        if result<0:raise ValueError(f'EEPROM serial write failed ({result}); backup retained')
    def close(self):self.lib.rtlsdr_close(self.handle)


def main():
    index,bus,address,backup,serial=sys.argv[1:]
    devices=usb_inventory()
    if len(devices)!=1 or (devices[0]['bus'],devices[0]['address'])!=(int(bus),int(address)):raise ValueError('USB inventory changed before programming')
    original=Path(backup).read_bytes();serial_image(original,serial)
    device=EepromDevice(int(index))
    try:change_serial(device,original,serial)
    finally:device.close()
    print(json.dumps(dict(ok=True,serial=serial)))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
