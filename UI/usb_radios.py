"""Shared USB radio names, choices and actual decoder connections."""
import time
import re
from rtl_registry import REGISTRY

SERVICE=None
LABELS={'home':'HOME receiver','home_am':'AM Radio','home_fm':'FM Radio','none':'Stop receiving','adsb':'ADS-B · 1090 ES','uat':'ADS-B · 978 UAT','spectrum':'Spectrum Analyzer','ism':'rtl_433 sensors','ais':'AIS','aprs':'APRS','meteor':'Meteor-M','cubesat':'CubeSat','sonde':'Radiosonde','dongle-maintenance':'USB ID update'}


def owner_label(owner):
    if not owner:return 'Available'
    if owner.startswith('adsb-compare:'):return 'ADS-B comparison'
    if owner.startswith('ism:') or owner.startswith('ism-'):return 'rtl_433 sensors'
    return LABELS.get(owner,owner.replace('_',' ').replace('-',' ').title())


def radio_name(device):
    return device.get('nickname') or device.get('product') or (device.get('label') or device.get('name') or 'RTL-SDR').split(' · USB ')[0]


def choices(devices,leases=None,owner='',selection='auto',unique=True,blocked=()):
    leases=leases or {};result=[dict(id='auto',name='Auto',detail='Use an available radio',enabled=True,selected=selection=='auto')]
    for d in devices:
        use=leases.get(d['id']);reason='Selected' if use==owner else 'In use · '+owner_label(use) if use else 'Available'
        invalid=unique and not d.get('persistent',False)
        if invalid:reason='Assign a unique ID' if d.get('duplicate') else 'Identity needs checking'
        e=d.get('eeprom',{})
        if e.get('status')=='verified' and e.get('serial') and e['serial']!=d.get('serial'):reason='Reconnect to load new ID'
        result.append(dict(id=d['id'],name=radio_name(d),detail='ID '+(d.get('serial') or 'unreadable')+' · '+reason,enabled=not invalid and d['id'] not in blocked,selected=d['id']==selection,owner=use))
    if selection!='auto' and not any(r['id']==selection for r in result):
        result.append(dict(id=selection,name='Assigned radio',detail='Disconnected · waiting for this receiver',enabled=True,selected=True))
    return result


class RadioManagement:
    def __init__(self,registry,broker,adsb=None,vhf=None,home=None,home_request=None):
        self.registry,self.broker,self.adsb,self.vhf=registry,broker,adsb,vhf
        self.home,self.home_request=home,home_request
        import threading
        self.route_lock=threading.Lock()
    def services(self):
        owners=['none']
        if self.home_request:owners.extend(('home','home_am','home_fm'))
        if self.adsb:owners.extend(('adsb','uat'))
        if self.vhf:
            owners.append('spectrum')
            owners.extend(k for k in LABELS if k in getattr(self.vhf,'sessions',{}) or k=='ism' and k in getattr(self.vhf,'sensor_receivers',{}))
        return [(owner,owner_label(owner)) for owner in dict.fromkeys(owners)]
    def route(self,key,owner,devices):
        if not self.route_lock.acquire(blocking=False):raise ValueError('Another receiver switch is in progress')
        try:
            if owner not in dict(self.services()):raise ValueError('Unknown receiving service')
            device=next((d for d in devices if d['id']==key),None)
            if device is None:raise ValueError('Reconnect this USB receiver first')
            if owner!='none' and not device.get('persistent'):raise ValueError('Assign a unique USB ID before routing this receiver')
            requested_owner=owner
            mode={'home_am':'AM','home_fm':'WFM'}.get(owner)
            if mode:owner='home'
            previous=self.broker.snapshot().get(key)
            if previous and previous!=owner:
                stop=self.broker.stoppers.get(previous)
                if stop is None:raise ValueError('Current receiver owner cannot be stopped here')
                stop()
                deadline=time.monotonic()+10
                while self.broker.snapshot().get(key)==previous:
                    if time.monotonic()>deadline:raise ValueError('Previous service has not released USB. Try again.')
                    time.sleep(.05)
            if owner=='none':return 'Receiver released'
            if owner=='home':
                if mode:self.home_request(key,mode)
                else:self.home_request(key)
            elif owner in ('adsb','uat'):
                self.adsb.control('assign',selection=key,band='978' if owner=='uat' else '1090')
                self.adsb.control('start',band='978' if owner=='uat' else '1090')
            else:
                self.vhf.control(owner,'configure',selection=key)
                self.vhf.control(owner,'start')
            return 'Requested '+owner_label(requested_owner)
        finally:self.route_lock.release()
    def connection(self,owner):
        a,v=self.adsb,self.vhf;session=None;frequency=None
        if owner=='home' and self.home:
            data=self.home.snapshot()
            return dict(owner=owner,label=owner_label(owner),status=data['status'],detail='Local USB audio and waterfall')
        if owner=='adsb' and a:session=a;frequency=1090000000
        elif owner=='uat' and a:session=a.uat;frequency=978000000
        elif owner=='spectrum' and v:session=v.spectrum
        elif v:session={**getattr(v,'sessions',{}),**getattr(v,'sensor_receivers',{})}.get(owner)
        settings=getattr(session,'settings',{})
        frequency=getattr(session,'active_frequency',None) or frequency or settings.get('frequency')
        if owner=='spectrum':
            frequency=settings.get('frequency') if settings.get('purpose')=='investigate' else None
        detail=(f'{frequency/1e6:g} MHz' if frequency else '1090 MHz' if owner.startswith('adsb-compare:') else 'Sweeping spectrum' if owner=='spectrum' else '')
        return dict(owner=owner,label=owner_label(owner),status=str(getattr(session,'status','Connected')),detail=detail)
    def snapshot(self,devices):
        data=self.registry.snapshot(devices);leases=self.broker.snapshot() if self.broker else {}
        waiting={}
        candidates=[]
        if self.adsb:candidates.extend((('adsb',self.adsb),('uat',self.adsb.uat)))
        if self.vhf:
            candidates.extend({**getattr(self.vhf,'sessions',{}),**getattr(self.vhf,'sensor_receivers',{})}.items())
            candidates.append(('spectrum',self.vhf.spectrum))
        for owner,s in candidates:
            if getattr(s,'enabled',False) and owner not in leases.values():
                selected=getattr(s,'settings',{}).get('selection',getattr(s,'selection','auto'))
                if selected!='auto':waiting.setdefault(selected,[]).append(owner_label(owner))
        pending_ids={'serial:'+r['eeprom']['serial'] for r in data['dongles'] if r.get('needs_reconnect')}
        known={r.get('serial') for r in data['dongles'] if r.get('usb_path')}
        data['dongles']=[r for r in data['dongles'] if not (not r['connected'] and (r['id'] in pending_ids or r['id'].startswith('slot:') and (not r.get('serial') or r.get('serial') in known)))]
        def order(r):
            port=r.get('usb_path') or 'z'
            return (not r['connected'],tuple((0,int(v)) if v.isdigit() else (1,v) for v in re.split(r'(\d+)',port)),r.get('serial',''),r['id'])
        data['dongles'].sort(key=order)
        for r in data['dongles']:
            r['name']=radio_name(r);owner=leases.get(r['id'])
            r['connection']=self.connection(owner) if owner and r['connected'] else None
            r['waiting']=waiting.get(r['id'],[])
            r['state']='disconnected' if not r['connected'] else 'reconnect' if r.get('needs_reconnect') else 'conflict' if r.get('duplicate') else 'connected' if owner else 'available'
        return dict(data,leases=leases,connected_count=len(devices),active_count=sum(r['connection'] is not None for r in data['dongles']),now=time.time())


def snapshot(manager,registry=None):
    if SERVICE:
        import dongle_notice
        devices=dongle_notice.SERVICE.rows if dongle_notice.SERVICE else manager.devices
        return SERVICE.snapshot(devices)
    return RadioManagement(registry or REGISTRY,getattr(manager,'broker',None)).snapshot(manager.scanner())


def acquire_home_receiver(broker, devices, selection, stop_event):
    """Wait on the I/Q worker, never the UI, for the previous owner to release."""
    selected=broker.request('home',devices,selection)
    device=next((d for d in devices if d['id']==selected),None)
    if device is None:raise ValueError('Selected USB receiver is disconnected')
    deadline=time.monotonic()+10
    while not stop_event.is_set():
        if broker.acquire('home',selected):return device
        if time.monotonic()>deadline:raise ValueError('Previous service did not release the USB receiver')
        stop_event.wait(.05)
    raise ValueError('USB receiver start cancelled')
