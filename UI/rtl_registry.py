"""Shared RTL inventory, saved names and deliberate, backed-up EEPROM changes."""
import ctypes
import ctypes.util
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid


def usb_inventory(root=Path('/sys/bus/usb/devices')):
    rows = []
    for path in root.glob('*'):
        try:
            read = lambda key: (path/key).read_text().strip()
            vid, pid = read('idVendor'), read('idProduct')
            if (vid, pid) not in (('0bda', '2832'), ('0bda', '2838')): continue
            rows.append(dict(usb_path=path.name, vendor=vid, product_id=pid,
                bus=int(read('busnum')), address=int(read('devnum')),
                serial=read('serial') if (path/'serial').exists() else '',
                manufacturer=read('manufacturer') if (path/'manufacturer').exists() else '',
                product=read('product') if (path/'product').exists() else 'RTL-SDR'))
        except (OSError, ValueError): continue
    return rows


def usb_order():
    """libusb order, as used by librtlsdr; never infer indices from sorted ports."""
    class Descriptor(ctypes.Structure):
        _fields_ = [(k, ctypes.c_uint16 if k in ('idVendor','idProduct','bcdUSB','bcdDevice') else ctypes.c_uint8) for k in
            ('bLength','bDescriptorType','bcdUSB','bDeviceClass','bDeviceSubClass','bDeviceProtocol','bMaxPacketSize0','idVendor','idProduct','bcdDevice','iManufacturer','iProduct','iSerialNumber','bNumConfigurations')]
    lib = ctypes.CDLL(ctypes.util.find_library('usb-1.0') or 'libusb-1.0.so.0')
    ptr = ctypes.c_void_p
    lib.libusb_init.argtypes=[ctypes.POINTER(ptr)]
    lib.libusb_get_device_list.argtypes=[ptr,ctypes.POINTER(ctypes.POINTER(ptr))]
    lib.libusb_get_device_list.restype=ctypes.c_ssize_t
    lib.libusb_get_device_descriptor.argtypes=[ptr,ctypes.POINTER(Descriptor)]
    lib.libusb_get_bus_number.argtypes=[ptr];lib.libusb_get_bus_number.restype=ctypes.c_uint8
    lib.libusb_get_device_address.argtypes=[ptr];lib.libusb_get_device_address.restype=ctypes.c_uint8
    lib.libusb_free_device_list.argtypes=[ctypes.POINTER(ptr),ctypes.c_int]
    lib.libusb_exit.argtypes=[ptr]
    ctx=ptr();devices=ctypes.POINTER(ptr)();order=[]
    if lib.libusb_init(ctypes.byref(ctx)) != 0:return []
    try:
        n=lib.libusb_get_device_list(ctx,ctypes.byref(devices))
        for i in range(max(0,n)):
            desc=Descriptor()
            if lib.libusb_get_device_descriptor(devices[i],ctypes.byref(desc)) == 0 and (desc.idVendor,desc.idProduct) in ((0x0bda,0x2832),(0x0bda,0x2838)):
                order.append((lib.libusb_get_bus_number(devices[i]),lib.libusb_get_device_address(devices[i])))
    finally:
        if devices:lib.libusb_free_device_list(devices,1)
        lib.libusb_exit(ctx)
    return order


def identify(rows, physical, order, shared=()):
    """Enrich exact port matches; unknown descriptors must never imply uniqueness."""
    signature=hashlib.sha256(repr((rows,physical,order)).encode()).hexdigest()[:16]
    by_address={(r['bus'],r['address']):r for r in physical}
    matched=len(order)==len(rows) and len(set(order))==len(rows) and all(k in by_address for k in order)
    if matched:
        matched=all(not r.get('serial') or r['serial']==by_address[k]['serial'] for r,k in zip(rows,order))
    for row in rows:
        if matched:
            p=by_address[order[row['index']]]
            row.update({k:p[k] for k in ('usb_path','bus','address','vendor','product_id')})
            for key in ('manufacturer','product','serial'):
                if not row.get(key):row[key]=p[key]
    counts=Counter(r.get('serial') for r in rows)
    physical_counts=Counter(r['serial'] for r in physical)
    unknown=any(not r.get('serial') for r in rows)
    for row in rows:
        serial=row.get('serial','')
        collision=bool(serial) and max(counts[serial],physical_counts[serial])>1
        duplicate=bool(serial) and (serial in shared or collision)
        unique=bool(serial) and not duplicate and not unknown
        row.update(duplicate=duplicate,collision=collision,persistent=unique,
            id='serial:'+serial if unique else 'port:'+row['usb_path'] if row.get('usb_path') else f"slot:{row['index']}:{signature}")
        row['label']=f"USB {row['index']} · {row.get('product') or row['name']} · {serial or 'serial unreadable'}"+(' · DUPLICATE — Rename' if duplicate else '' if unique else ' · identity unverified')
    return rows


class DongleRegistry:
    def __init__(self, root=None):
        self.root=Path(root or Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'ituner-sdr/dongles')
        self.lock=threading.RLock();self.operation=None;self.current_rows=[]
        try:data=json.loads((self.root/'registry.json').read_text())
        except (OSError,ValueError):data={}
        modern=data.get('version')==2
        self.records=data.get('dongles',{}) if modern else data
        self.shared=set(data.get('shared_serials',[])) if modern else {r.get('serial') for r in self.records.values() if r.get('duplicate') and r.get('serial')}
        self.aliases=dict(data.get('aliases',{})) if modern else {}
        if not modern:
            # Earlier versions copied a duplicate flag into the newly programmed record.
            for key,r in list(self.records.items()):
                e=r.get('eeprom',{});serial=r.get('serial')
                if e.get('status')=='verified' and e.get('serial')==serial:
                    ports={v.get('usb_path') for v in self.records.values() if v.get('serial')==serial}
                    if len(ports)<=1:self.shared.discard(serial);r['duplicate']=False
                replacement=r.get('replacement_id')
                if replacement and replacement in self.records:
                    self.aliases[key]=replacement
                    if r.get('serial')==self.records[replacement].get('serial'):
                        target=self.records[replacement]
                        if r.get('nickname'):target['nickname']=r['nickname']
                        target['last_seen']=max(target.get('last_seen',0),r.get('last_seen',0))
                        self.records.pop(key,None)
            if data:self.save()

    def save(self):
        self.root.mkdir(parents=True,exist_ok=True)
        tmp=self.root/('registry-'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(dict(version=2,dongles=self.records,shared_serials=sorted(self.shared),aliases=self.aliases),indent=2));tmp.replace(self.root/'registry.json')

    def remember(self, rows):
        with self.lock:
            changed=False;now=time.time()
            for row in rows:
                key=row['id'];record=self.records.get(key)
                portkey='port:'+(row.get('usb_path') or '')
                prior=self.records.get(portkey)
                if row.get('persistent') and prior and portkey!=key and prior.get('serial')==row.get('serial'):
                    merged={**prior,**(record or {}),'id':key,'duplicate':False}
                    if prior.get('nickname') and not merged.get('nickname'):merged['nickname']=prior['nickname']
                    self.records[key]=record=merged;self.records.pop(portkey);self.aliases[portkey]=key;changed=True
                if row.get('collision') and row.get('serial'):self.shared.add(row['serial'])
                for old in list(self.records):
                    if self.records[old].get('replacement_id')==key:
                        self.records.pop(old);changed=True
                if record and record.get('eeprom',{}).get('serial')==row.get('serial') and record.get('eeprom',{}).get('status')=='verified':
                    record['eeprom']=dict(record['eeprom'],message='Unique ID assigned · verified')
                if record is None:
                    record=dict(id=key,nickname='',first_seen=now);self.records[key]=record;changed=True
                # Rate-limit disk writes while retaining disconnected history indefinitely.
                if now-record.get('last_seen',0)>60 or record.get('serial')!=row.get('serial') or record.get('duplicate')!=row.get('duplicate',False):
                    record.update(last_seen=now,serial=row.get('serial',''),usb_path=row.get('usb_path'),product=row.get('product') or row['name'],duplicate=row.get('duplicate',False));changed=True
                row['nickname']=record.get('nickname','');row['registry_id']=key
                row['eeprom']=dict(record.get('eeprom',{}))
                if row['nickname']:row['label']=row['nickname']+' · '+row['label']
            # Once a programmed receiver is seen under its new identity, a sole
            # remaining factory serial is no longer a collision. Preserve flags
            # for genuinely disconnected siblings still in the saved inventory.
            for row in rows:
                record=self.records[row['id']];e=record.get('eeprom',{})
                if not row.get('persistent') or e.get('status')!='verified' or e.get('serial')!=row.get('serial'):continue
                old=record.get('previous_serial')
                if not old and e.get('backup'):
                    try:
                        raw=Path(e['backup']).read_bytes();offset=9
                        for _ in range(2):offset+=raw[offset]
                        old=raw[offset+2:offset+raw[offset]].decode('utf-16le')
                        record['previous_serial']=old;changed=True
                    except (OSError,ValueError,IndexError):continue
                remaining=[r for r in self.records.values() if r.get('serial')==old]
                if old in self.shared and len({r.get('usb_path') or r.get('id') for r in remaining})<=1 and sum(r.get('serial')==old for r in rows)<=1:
                    self.shared.discard(old);changed=True
            self.current_rows=[dict(row) for row in rows]
            if changed:self.save()
        return rows

    def shared_serials(self):
        with self.lock:return set(self.shared)

    def resolve(self,key,rows):
        with self.lock:
            available={r['id'] for r in rows};seen=set();original=key
            while key not in available and key in self.aliases and key not in seen:
                seen.add(key);key=self.aliases[key]
            return key if key in available else original

    def next_serial(self):
        used={r.get('serial') for r in self.records.values()}|self.shared
        for value in range(10000011,100000000):
            serial=str(value)
            if serial not in used:return serial
        raise ValueError('No free receiver IDs remain')

    def assign_id(self,key,nickname,scanner,broker,busy=lambda:False):
        self.validate_nickname(nickname)
        with self.lock:
            if self.operation and self.operation.get('running'):raise ValueError('A receiver update is already running')
            rows=scanner();device=next((r for r in rows if r['id']==key),None)
            if len(rows)!=1:raise ValueError('Leave only the receiver being assigned connected, then try again')
            if not device or not device.get('usb_path'):raise ValueError('Receiver identity is unavailable; scan USB again')
            if not device.get('duplicate'):raise ValueError('This receiver already has a unique ID. Use Rename for its nickname.')
            serial=self.next_serial();self.operation=dict(running=True,id=key,action='assign_id',message='Assigning new ID…')
        def run():
            resume=lambda:None
            try:
                if broker:resume=broker.pause()
                elif busy():raise ValueError('Stop reception before assigning an ID')
                self.rename(key,nickname)
                self._operate(key,device,'program',serial,scanner,broker,busy)
            except (ValueError,OSError) as exc:
                with self.lock:self.operation=dict(running=False,id=key,action='assign_id',ok=False,message=str(exc))
            finally:resume()
        threading.Thread(target=run,daemon=True,name='rtl-assign-id').start()


    def snapshot(self,rows):
        with self.lock:
            online={r['id']:r for r in rows}
            records=[dict(r,connected=k in online,device=online.get(k)) for k,r in self.records.items()]
            return dict(dongles=sorted(records,key=lambda r:(not r['connected'],-r.get('last_seen',0))),operation=self.operation)

    @staticmethod
    def validate_nickname(nickname):
        if not isinstance(nickname,str) or len(nickname.strip())>48 or any(ord(c)<32 for c in nickname):raise ValueError('Use a nickname of up to 48 printable characters')
    def rename(self,key,nickname):
        self.validate_nickname(nickname)
        with self.lock:
            if key not in self.records:raise ValueError('Unknown saved dongle')
            self.records[key]['nickname']=nickname.strip();self.save()

    @staticmethod
    def tool(index,*args):
        try:
            result=subprocess.run(['rtl_eeprom','-d',str(index),*map(str,args)],input='y\n',text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=15)
        except subprocess.TimeoutExpired:raise ValueError('EEPROM check timed out; reconnect the receiver before retrying')
        except OSError as exc:raise ValueError('rtl_eeprom is unavailable: '+str(exc))
        # Debian's tool can exit 1 after a successful read (the last I2C byte count).
        dumped=args and str(args[0])=='-r' and 'Dump to ' in result.stdout and ' successful.' in result.stdout and Path(args[1]).is_file() and Path(args[1]).stat().st_size==256
        if result.returncode not in (0,1) or result.returncode==1 and not dumped:raise ValueError('EEPROM access failed: '+result.stdout[-700:])
        return result.stdout

    @staticmethod
    def program(target,backup,serial):
        try:
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('rtl_eeprom_access.py')),str(target['index']),str(target['bus']),str(target['address']),str(backup),serial],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=20)
        except subprocess.TimeoutExpired:raise ValueError('EEPROM programming timed out. Backup retained; reconnect and inspect before retrying')
        if result.returncode:raise ValueError(result.stdout[-700:])

    def start(self,key,action,scanner,broker,serial=None,busy=lambda:False):
        if action not in ('probe','program'):raise ValueError('Unknown dongle action')
        if action=='program' and (not isinstance(serial,str) or not re.fullmatch(r'[0-9]{8}',serial) or serial in ('00000000','00000001')):
            raise ValueError('Use eight digits, excluding 00000000 and 00000001')
        with self.lock:
            if self.operation and self.operation.get('running'):raise ValueError('A dongle operation is already running')
            rows=scanner();device=next((r for r in rows if r['id']==key),None)
            if not device:raise ValueError('Reconnect this dongle before testing or programming')
            if broker and broker.snapshot() or busy():raise ValueError('Stop SDR reception before EEPROM operations')
            if not device.get('usb_path'):raise ValueError('Physical USB identity could not be verified')
            if action=='program':
                if len(rows)!=1:raise ValueError('Leave only the receiver you want to program connected, then Scan USB')
                if any(r.get('serial')==serial for r in self.records.values()):raise ValueError('That serial is already in the saved dongle list')
                if self.records[key].get('eeprom',{}).get('status')!='readable':raise ValueError('Run Test EEPROM successfully first')
            self.operation=dict(running=True,id=key,action=action,message='Testing EEPROM…' if action=='probe' else 'Backing up and programming…')
        threading.Thread(target=self._operate,args=(key,device,action,serial,scanner,broker,busy),daemon=True,name='rtl-eeprom').start()

    def _operate(self,key,device,action,serial,scanner,broker,busy):
        info={};backup=None
        try:
            # Hold the shared lease throughout all USB access. Every decoder must wait.
            if broker and not broker.acquire('dongle-maintenance',key):raise ValueError('Receiver became busy; stop it and retry')
            current=getattr(scanner,'fresh',scanner)();target=next((r for r in current if r['id']==key),None)
            if not target or (target.get('bus'),target.get('address'))!=(device['bus'],device['address']) or busy():raise ValueError('USB inventory or reception changed; scan and retry')
            if action=='program' and len(current)!=1:raise ValueError('Connect only the receiver being programmed')
            self.root.joinpath('backups').mkdir(parents=True,exist_ok=True)
            backup=self.root/'backups'/(uuid.uuid4().hex+'.bin')
            self.tool(target['index'],'-r',backup)
            raw=backup.read_bytes()
            if len(raw)!=256 or raw[:2]!=b'\x28\x32':raise ValueError('No valid 256-byte RTL EEPROM was read')
            info=dict(status='readable',checked_at=time.time(),backup=str(backup),message='EEPROM readable; write support is unverified')
            if action=='program':
                latest=getattr(scanner,'fresh',scanner)()
                if len(latest)!=1 or latest[0]['id']!=key or latest[0].get('address')!=target['address']:raise ValueError('USB inventory changed; programming cancelled')
                serial_image(raw,serial)  # Validate the complete layout before any write.
                self.program(target,backup,serial)
                info.update(status='verified',serial=serial,message='Serial written and read back. Unplug/reconnect this receiver to use '+serial)
                with self.lock:
                    newkey='serial:'+serial
                    self.records[newkey]=dict(self.records[key],id=newkey,serial=serial,eeprom=info,duplicate=False,previous_serial=self.records[key].get('serial'))
                    self.records[newkey].pop('replacement_id',None)
                    self.aliases[key]=newkey
                    self.records[key]['replacement_id']=newkey
            with self.lock:self.operation=dict(running=False,id=key,action=action,ok=True,message=info['message'])
        except (ValueError,OSError) as exc:
            info=dict(status='failed',checked_at=time.time(),message=str(exc),backup=str(backup) if backup and backup.exists() else None)
            with self.lock:self.operation=dict(running=False,id=key,action=action,ok=False,message=str(exc))
        finally:
            try:
                with self.lock:
                    if key in self.records:self.records[key]['eeprom']=info
                    self.save()
            finally:
                if broker:broker.release('dongle-maintenance')


def serial_image(raw,serial):
    """Expected rtl_eeprom serial-only update, preserving all other EEPROM fields."""
    if len(raw)!=256 or raw[:2]!=b'\x28\x32' or raw[6]!=0xa5:
        raise ValueError('Nonstandard EEPROM layout; serial programming is unavailable')
    image=bytearray(raw);offset=9
    for _ in range(2):
        length=image[offset]
        if length<2 or length%2 or offset+length>254 or image[offset+1]!=3:raise ValueError('Invalid EEPROM string layout')
        offset+=length
    encoded=serial.encode('utf-16le');length=len(encoded)+2
    if offset+length>256 or image[offset]!=length or image[offset+1]!=3:raise ValueError('Serial length differs from the EEPROM layout; refusing an unverified rewrite')
    image[offset:offset+length]=bytes([length,3])+encoded
    return bytes(image)


REGISTRY=DongleRegistry()
