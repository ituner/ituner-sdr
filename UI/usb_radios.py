"""Shared USB radio names, choices and actual decoder connections."""
import time
import re
from rtl_registry import REGISTRY

SERVICE=None
LABELS={'adsb':'ADS-B · 1090 ES','uat':'ADS-B · 978 UAT','spectrum':'Spectrum Analyzer','ism':'rtl_433 sensors','ais':'AIS','aprs':'APRS','meteor':'Meteor-M','cubesat':'CubeSat','sonde':'Radiosonde','dongle-maintenance':'USB ID update'}


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
    def __init__(self,registry,broker,adsb=None,vhf=None):self.registry,self.broker,self.adsb,self.vhf=registry,broker,adsb,vhf
    def connection(self,owner):
        a,v=self.adsb,self.vhf;session=None;frequency=None
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
