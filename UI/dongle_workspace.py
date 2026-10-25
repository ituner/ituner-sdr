"""Native touchscreen dongle inventory and rename controls; no browser involved."""
import threading
import time
from station_workspace import StationWorkspace
from dongle_web import dongle_control
from rtl_registry import REGISTRY


class DongleWorkspace(StationWorkspace):
    def __init__(self,ui,manager):
        super().__init__(ui,None)
        self.manager=manager;self.data={};self.updated=0;self.page=0;self.selected=None;self.working=False;self.intent='rename';self.nickname=''
    def show(self):
        self.open=True;self.field=None;self.selected=None;self.message='';self.page=0;self.refresh()
    def refresh(self):
        self.data=REGISTRY.snapshot(self.manager.devices);self.updated=time.monotonic()
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
        if value=='DONE':
            self.nickname=self.value;self.field=None
            if self.intent=='rename':self.submit(action='rename',id=self.selected['id'],nickname=self.nickname);self.selected=None
        elif value=='CANCEL':self.field=None
        elif value=='SHIFT':self.caps=not self.caps
        elif value=='DELETE':self.value=self.value[:-1]
        elif value=='CLEAR':self.value=''
        elif len(self.value)<(48 if self.field=='Nickname · optional' else 8):self.value+=value
    def tap(self,x,y):
        for box,(kind,value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            if kind=='key':self.key(value)
            elif kind=='back':
                if self.selected:self.selected=None
                else:self.open=False
            elif kind=='page':self.page=max(0,self.page+value)
            elif kind=='select':
                self.selected=value;self.nickname=value.get('nickname','');self.message=''
                self.intent='assign_id' if value['connected'] and value.get('duplicate') else 'rename'
                if self.intent=='rename':self.field='Nickname · optional';self.value=self.nickname
            elif kind=='edit':self.field='Nickname · optional';self.value=self.nickname
            elif kind=='apply':self.submit(action='assign_id',id=self.selected['id'],nickname=self.nickname);self.selected=None
            elif kind=='scan':self.submit(action='scan')
            return
    def draw(self,cache):
        self.actions=[]
        if time.monotonic()-self.updated>1:self.refresh()
        if self.field is not None:return self.keyboard(cache)
        ui=self.ui;ui.draw_logical_rect(0,0,1280,800,self.BG)
        self.ink(cache,24,38,'USB RECEIVERS',28);self.ink(cache,24,80,'Saved across decoders · disconnected receivers remain in this list',20,self.MUTED)
        self.draw_back(cache)
        records=self.data.get('dongles',[])
        if self.selected:
            r=next((r for r in records if r['id']==self.selected['id']),self.selected);self.selected=r
            self.ink(cache,32,144,r.get('nickname') or r.get('product','RTL-SDR'),28,self.CYAN,width=1200)
            self.ink(cache,32,198,f"Serial {r.get('serial') or 'unreadable'} · USB port {r.get('usb_path') or 'unknown'} · "+('Connected' if r['connected'] else 'Disconnected'),22,width=1200)
            self.ink(cache,32,250,'A unique ID will be generated automatically.',22,self.MUTED,width=1200)
            self.button(cache,(24,300,1256,382),'Nickname · optional: '+(getattr(self,'nickname','') or 'leave blank'),('edit',None))
            self.button(cache,(646,430,1256,510),'Assign new ID',('apply',None))
            self.ink(cache,32,562,'Connect only this receiver. Reception pauses briefly; reconnect it afterward.',20,self.MUTED,width=1200)

        else:
            self.page=min(self.page,max(0,(len(records)-1)//4))
            for i,r in enumerate(records[self.page*4:self.page*4+4]):
                y=120+i*125;d=r.get('device') or {};title=r.get('nickname') or r.get('product') or 'RTL-SDR'
                label=('CONNECTED' if r['connected'] else 'DISCONNECTED')+(' · DUPLICATE ID' if r.get('duplicate') or d.get('duplicate') else '')
                self.ink(cache,32,y+20,title,24,self.CYAN,width=880)
                self.ink(cache,32,y+58,f"{r.get('serial') or 'Unreadable serial'} · USB {r.get('usb_path') or 'unknown'} · {label}",20,self.GOLD if r.get('duplicate') else self.MUTED,width=880)
                self.button(cache,(964,y,1256,y+78),'Assign new ID' if r['connected'] and r.get('duplicate') else 'Rename',('select',r))
            if not records:self.ink(cache,32,170,'Connect an RTL-SDR receiver and Scan USB.',24,self.MUTED)
            self.button(cache,(24,640,326,702),'Scan USB',('scan',None));self.button(cache,(650,640,942,702),'Previous',('page',-1));self.button(cache,(964,640,1256,702),'Next',('page',1))
        op=self.data.get('operation')
        self.draw_status(cache,op['message'] if op else self.message or 'Dongle registry',self.message if op else 'Names shared across local and web decoders',full_width=True)
