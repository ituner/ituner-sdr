"""Native touchscreen dongle inventory and rename controls; no browser involved."""
import threading
import time
from station_workspace import StationWorkspace
from dongle_web import dongle_control
from rtl_registry import REGISTRY
from usb_radios import RadioManagement, radio_name


class DongleWorkspace(StationWorkspace):
    def __init__(self,ui,manager):
        super().__init__(ui,None)
        self.manager=manager;self.data={};self.updated=0;self.page=0;self.selected=None;self.working=False;self.intent='rename';self.nickname='';self.history=False
    def show(self):
        self.open=True;self.field=None;self.selected=None;self.message='';self.page=0;self.refresh()
    def refresh(self):
        import usb_radios
        devices=self.manager.devices
        if usb_radios.SERVICE:
            import dongle_notice
            if dongle_notice.SERVICE:devices=dongle_notice.SERVICE.rows
        self.data=(usb_radios.SERVICE or RadioManagement(REGISTRY,getattr(self.manager,'broker',None))).snapshot(devices);self.updated=time.monotonic()
    def submit(self,**data):
        if self.working:return
        self.working=True;self.message='Working…'
        def run():
            try:
                dongle_control(self.manager,data);self.message='Saved' if data['action']=='rename' else 'Assigning new ID…'
            except (ValueError,OSError) as exc:self.message=str(exc)
            finally:self.working=False;self.refresh()
        threading.Thread(target=run,daemon=True,name='dongle-touch').start()
    def key(self,value):
        if self.field is None:return
        if value=='DONE':
            self.nickname=self.value;self.field=None
            if self.intent=='rename':self.submit(action='rename',id=self.selected['id'],nickname=self.nickname);self.selected=None
        elif value=='CANCEL':self.field=None
        elif value=='SHIFT':self.caps=not self.caps
        elif value=='DELETE':self.value=self.value[:-1]
        elif value=='CLEAR':self.value=''
        elif len(self.value)<(48 if self.field=='Nickname · optional' else 8):self.value+=value
    def tap(self,x,y):
        if self.field is not None:return self.keyboard_tap(x,y)
        for box,(kind,value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            if kind=='key':self.key(value)
            elif kind=='back':
                if self.selected:self.selected=None
                else:self.open=False
            elif kind=='page':self.page=max(0,self.page+value)
            elif kind=='history':self.history=value;self.page=0
            elif kind=='select':
                self.selected=value;self.nickname=value.get('nickname','');self.message=''
                self.intent='assign_id' if value['connected'] and not value.get('needs_reconnect') and (value.get('duplicate') or value.get('serial') in ('00000000','00000001')) else 'rename'
            elif kind=='edit':self.field='Nickname · optional';self.value=self.nickname
            elif kind=='apply':self.submit(action='assign_id',id=self.selected['id'],nickname=self.nickname);self.selected=None
            elif kind=='scan':self.submit(action='scan')
            return
    def draw(self,cache):
        self.actions=[]
        if time.monotonic()-self.updated>1:self.refresh()
        if self.field is not None:return self.keyboard(cache)
        ui=self.ui;ui.draw_logical_rect(0,0,1280,800,self.BG)
        self.ink(cache,24,34,'USB-RADIOS',28)
        self.ink(cache,24,72,f"{self.data.get('connected_count',0)} connected · {self.data.get('active_count',0)} in use · shared across decoders",20,self.MUTED,width=980)
        self.draw_back(cache)
        records=self.data.get('dongles',[])
        if self.selected:
            r=next((r for r in records if r['id']==self.selected['id']),self.selected);self.selected=r
            self.ink(cache,32,166,radio_name(r),30,self.CYAN,width=1200)
            self.ink(cache,32,215,'ID '+(r.get('serial') or 'unreadable')+' · USB '+(r.get('usb_path') or 'unknown'),22,self.MUTED,width=1200)
            c=r.get('connection');self.ink(cache,32,262,(c['label']+' · '+c['detail']) if c else 'Disconnected' if not r['connected'] else 'Available',23,self.CYAN,width=1200)
            self.button(cache,(24,310,1256,390),'Nickname · optional: '+(self.nickname or 'use radio name'),('edit',None))
            if r.get('needs_reconnect'):
                self.ink(cache,32,446,'New ID '+r['eeprom']['serial']+' saved. Reconnect only this receiver.',23,self.GOLD,width=1200)
            elif self.intent=='assign_id':
                self.ink(cache,32,446,'Duplicate IDs need a unique ID. A sole factory ID can be kept.',22,self.MUTED,width=1200)
                self.button(cache,(24,490,616,564),'Assign a new USB ID',('apply',None))
                self.ink(cache,32,610,'Reception pauses briefly. Reconnect this receiver after the ID is verified.',20,self.MUTED,width=1200)
        else:
            self.button(cache,(24,94,330,150),'Connected',('history',False),not self.history)
            self.button(cache,(346,94,652,150),'Saved radios',('history',True),self.history)
            records=[r for r in records if self.history or r['connected']]
            last=max(0,(len(records)-1)//6);self.page=min(self.page,last)
            for i,r in enumerate(records[self.page*6:self.page*6+6]):
                y=162+i*76;c=r.get('connection');active=bool(c)
                self.decoder_button(cache,(24,y,536,y+68),radio_name(r),('select',r),'ID '+(r.get('serial') or 'unreadable'),font_size=21,uppercase=False)
                color=self.CYAN if active else self.MUTED
                if active:ui.draw_logical_line(552,y+34,738,y+34,(*color[:3],255),2)
                else:
                    for x in range(552,738,24):ui.draw_logical_line(x,y+34,x+12,y+34,(*self.LINE[:3],255),1)
                ui.draw_logical_polyline([(730,y+27),(740,y+34),(730,y+41)],(*color[:3],255),2)
                label=c['label'] if c else {'disconnected':'Disconnected','conflict':'ID conflict · select to fix','reconnect':'Reconnect to load new ID'}.get(r.get('state'),'Available')
                detail=(c['detail']+' · '+c['status']) if c else 'Waiting: '+', '.join(r.get('waiting',[])) if r.get('waiting') else 'USB '+(r.get('usb_path') or 'unknown')
                self.ink(cache,764,y+22,label,22,self.GOLD if r.get('state') in ('conflict','reconnect') else color,width=488)
                self.ink(cache,764,y+50,detail,18,self.MUTED,width=488)
            if not records:self.ink(cache,32,235,'No USB radios connected. Plug in a receiver; this list updates automatically.',24,self.MUTED,width=1200)
            self.button(cache,(24,644,310,700),'Refresh',('scan',None))
            if last:
                self.ink(cache,454,672,f'{self.page+1} / {last+1}',21,self.MUTED)
                self.button(cache,(650,644,942,700),'Previous',('page',-1));self.button(cache,(964,644,1256,700),'Next',('page',1))
        self.draw_status(cache,self.message or 'Select a radio to edit its nickname or USB ID.','Solid line = active decoder · dashed = idle / disconnected',full_width=True)
