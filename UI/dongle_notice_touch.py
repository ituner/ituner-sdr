"""Global native USB discovery prompt; no keyboard or serial-number form."""
import math
import textwrap
import time
import threading
from dongle_notice import NoticeView
from station_workspace import StationWorkspace


class USBNoticePopup(StationWorkspace):
    def __init__(self,ui,service):
        super().__init__(ui,None);self.service=service;self.view=NoticeView();self.error='';self.submitting=False;self.selected=None;self.page=0
    def visible(self):
        self.view.update(self.service.snapshot().get('notice'),time.monotonic())
        return self.view.notice is not None
    def dismiss(self):self.view.dismiss();self.error=''
    def tap(self,x,y):
        for box,(kind,_value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            if kind=='dismiss':self.dismiss()
            elif kind=='select':self.selected=_value;self.error='';self.view.until=None
            elif kind=='page':self.page=max(0,self.page+_value)
            elif kind=='assign':
                if self.submitting:return
                n=self.view.notice;target=self.selected;self.submitting=True
                def run():
                    try:self.service.assign(n['id'],target);self.error=''
                    except (OSError,ValueError) as exc:self.error=str(exc)
                    finally:self.submitting=False
                threading.Thread(target=run,name='usb-notice-action',daemon=True).start()
            return
    def draw(self,cache):
        if not self.visible():return
        n=self.view.notice;self.actions=[];ui=self.ui
        ui.draw_logical_rect(0,0,1280,800,(0,0,0,170))
        ui.draw_logical_rounded_rect(180,80,1100,720,18,self.PANEL,self.CYAN,1)
        self.ink(cache,208,122,n['title'],28,width=788)
        self.button(cache,(1016,92,1080,156),'×',('dismiss',None))
        for i,line in enumerate(textwrap.wrap(n['message'],width=67)[:3]):self.ink(cache,208,181+i*27,line,22,self.MUTED,width=864)
        receivers=n.get('receivers',[])
        candidates=[r for r in receivers if r.get('can_assign')]
        if not any(r['id']==self.selected for r in candidates):self.selected=next((r['id'] for r in candidates if r['id']==n.get('target')),None)
        self.page=min(self.page,max(0,(len(receivers)-1)//4))
        for i,row in enumerate(receivers[self.page*4:self.page*4+4]):
            y=270+i*68;target=row['id']==self.selected
            self.ink(cache,208,y,('→ ' if target else '')+row['name'],22,self.GOLD if row['conflict'] or target else self.CYAN,width=590)
            state=row.get('state','ready')
            status='Reconnect → '+row.get('new_serial','') if state=='reconnect' else dict(queued='Queued',working='Writing…',conflict='ID conflict',failed='Failed',ready='Ready').get(state,state)
            self.ink(cache,208,y+26,row['serial']+' · USB '+row['port']+' · '+status,18,self.MUTED,width=640)
            if row.get('can_assign'):self.decoder_button(cache,(860,y-8,1072,y+48),'Selected' if target else 'Assign ID',('select',row['id']),font_size=21,uppercase=False)
        if len(receivers)>4:
            self.button(cache,(208,548,368,604),'Previous',('page',-1))
            self.ink(cache,388,566,f'{self.page+1} / {math.ceil(len(receivers)/4)}',20,self.MUTED)
            self.button(cache,(508,548,668,604),'Next',('page',1))
        if self.selected:
            hint=self.error or 'Select a receiver, then Yes. Changes are queued; reconnect each receiver afterward.'
            self.ink(cache,208,620,hint,18,self.GOLD if self.error else self.MUTED,width=864)
            self.button(cache,(208,650,460,706),'Cancel',('dismiss',None))
            self.decoder_button(cache,(480,650,1072,706),'Queuing…' if self.submitting else 'Yes, assign a new ID',('assign',None),enabled=not self.submitting,font_size=21,uppercase=False)
        else:
            remaining=max(0,math.ceil((self.view.until or 0)-time.monotonic()))
            pending=n.get('pending_reconnects',[])
            note=f'Closes automatically in {remaining} seconds.' if n['kind']=='ready' else ('Reconnect: '+', '.join('USB '+p['port']+' → '+p['serial'] for p in pending) if pending else 'New plug-ins remain visible. ID changes run one at a time.')
            self.ink(cache,208,620,self.error or note,18,self.MUTED,width=864)
            self.button(cache,(808,650,1072,706),'Close',('dismiss',None))



class NoticeTouchCapture:
    """Consume a complete gesture; a finger lift need not contain coordinates."""
    def __init__(self):self.start=None;self.last=None;self.allowed=False
    def handle(self,active,x,y,popup,tap_px,underlying_started=False):
        if not popup.visible() and self.start is None:return False
        if active:
            if self.start is None:self.start=(x,y);self.allowed=not underlying_started
            self.last=(x,y)
        else:
            if self.start is not None and self.allowed and popup.visible() and max(abs(self.last[i]-self.start[i]) for i in (0,1))<=tap_px:popup.tap(*self.last)
            self.start=self.last=None;self.allowed=False
        return True
