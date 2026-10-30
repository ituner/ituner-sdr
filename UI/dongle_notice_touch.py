"""Global native USB discovery prompt; no keyboard or serial-number form."""
import math
import textwrap
import time
import threading
from dongle_notice import NoticeView,scan_status
from station_workspace import StationWorkspace


class USBNoticePopup(StationWorkspace):
    def __init__(self,ui,service):
        super().__init__(ui,None);self.service=service;self.view=NoticeView();self.error='';self.submitting=False;self.selected=None;self.page=0;self.inventory_id=None
    def current(self):
        self.view.update(self.service.snapshot().get('notice'),time.monotonic())
        return self.view.notice
    def visible(self):
        n=self.current()
        return n is not None and (n['kind']!='arrival' or n.get('duplicate_warning',False))
    def dismiss(self):
        if self.view.notice:self.service.dismiss(self.view.notice['id'])
        self.view.dismiss();self.error=''
    def tap(self,x,y):
        for box,(kind,_value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            if kind=='dismiss':self.dismiss()
            elif kind=='refresh':self.service.refresh()
            elif kind=='review':self.service.review(self.view.notice['id']);self.selected=None
            elif kind=='select':self.selected=_value;self.error='';self.view.until=None
            elif kind=='page':self.page=max(0,self.page+_value)
            elif kind in ('assign','choose'):
                if self.submitting:return
                n=self.view.notice;target=self.selected;self.submitting=True
                def run():
                    try:
                        if kind=='choose':self.service.choose(n['id'],target)
                        else:self.service.assign(n['id'],target)
                        self.error=''
                    except (OSError,ValueError) as exc:self.error=str(exc)
                    finally:self.submitting=False
                threading.Thread(target=run,name='usb-notice-action',daemon=True).start()
            return
    def draw(self,cache):
        n=self.current()
        if not n:return
        self.actions=[];ui=self.ui
        if n['kind']=='arrival':
            duplicate=n.get('duplicate_warning',False)
            if duplicate:ui.draw_logical_rect(0,0,1280,800,(0,0,0,125))
            ui.draw_logical_rounded_rect(220,210,1060,590,18,self.PANEL,self.GOLD if duplicate else self.CYAN,1)
            self.ink(cache,256,260,n['title'],32,self.GOLD if duplicate else self.CYAN,width=768)
            for i,row in enumerate(n['receivers'][:2]):
                self.ink(cache,256,312+i*57,row['name'],26,width=768)
                self.ink(cache,256,342+i*57,'ID '+row['serial']+' · USB '+row['port'],21,self.MUTED,width=768)
            text='Same ID as another connected receiver.' if duplicate else n['message']
            self.ink(cache,256,440,text,23,self.MUTED,width=768)
            remaining=max(0,math.ceil((self.view.until or 0)-time.monotonic()))
            self.ink(cache,256,476,f'Closes automatically in {remaining} seconds.',20,self.MUTED,width=768)
            if duplicate:
                self.button(cache,(256,514,616,574),'Later',('dismiss',None))
                self.button(cache,(640,514,1024,574),'Fix now',('review',None))
            return
        ui.draw_logical_rect(0,0,1280,800,(0,0,0,170))
        ui.draw_logical_rounded_rect(180,64,1100,752,self.RADIUS,self.PANEL,self.CYAN,1)
        self.ink(cache,208,122,n['title'],28,width=788)
        self.button(cache,(1016,92,1080,156),'×',('dismiss',None))
        for i,line in enumerate(textwrap.wrap(n['message'],width=67)[:3]):self.ink(cache,208,181+i*27,line,22,self.MUTED,width=864)
        receivers=n.get('receivers',[])
        if self.inventory_id!=n['id']:
            arrived=n.get('arrived_ports',[])
            new_index=next((i for i,r in enumerate(receivers) if r['port'] in arrived),None)
            if new_index is not None:self.page=new_index//4
            self.inventory_id=n['id']
        candidates=[r for r in receivers if r.get('can_assign') or r.get('can_choose')]
        if not any(r['id']==self.selected for r in candidates):self.selected=next((r['id'] for r in candidates if r['id']==n.get('target')),None)
        self.page=min(self.page,max(0,(len(receivers)-1)//4))
        for i,row in enumerate(receivers[self.page*4:self.page*4+4]):
            y=270+i*68;target=row['id']==self.selected
            self.ink(cache,208,y,('→ ' if target else '')+row['name'],22,self.GOLD if row['conflict'] or target else self.CYAN,width=590)
            state=row.get('state','ready')
            status='Reconnect → '+row.get('new_serial','') if state=='reconnect' else dict(queued='Queued',working='Writing…',conflict='ID conflict · select to resolve',failed='Failed',ready='Available',busy='In use',unverified='Identity needs checking').get(state,state)
            self.ink(cache,208,y+26,row['serial']+' · USB '+row['port']+' · '+status,18,self.MUTED,width=640)
            if row.get('can_assign') or row.get('can_choose'):self.decoder_button(cache,(860,y-8,1072,y+48),'Selected' if target else 'Select' if n['kind']=='select' else 'Assign ID',('select',row['id']),font_size=21,uppercase=False)
        if len(receivers)>4:
            self.button(cache,(208,548,368,604),'Previous',('page',-1))
            self.ink(cache,388,566,f'{self.page+1} / {math.ceil(len(receivers)/4)}',20,self.MUTED)
            self.button(cache,(508,548,668,604),'Next',('page',1))
        state=self.service.snapshot()
        self.ink(cache,208,626,scan_status(state),18,self.GOLD if state.get('scan_error') else self.CYAN,width=864)
        self.button(cache,(208,682,412,738),'Refresh',('refresh',None))
        if n['kind']=='discovery':
            remaining=max(0,math.ceil((self.view.until or 0)-time.monotonic()))
            self.ink(cache,208,652,f'Later is selected automatically after {remaining} seconds.',18,self.MUTED,width=864)
            self.button(cache,(432,682,608,738),'Later',('dismiss',None))
            self.decoder_button(cache,(628,682,1072,738),'Review receivers',('review',None),font_size=21,uppercase=False)
        elif self.selected:
            hint=self.error or ('Use this receiver for '+n['title'].split(' · ',1)[-1]+'.' if n['kind']=='select' else 'Select a receiver, then Yes. Reconnect it afterward, then press Start again.')
            self.ink(cache,208,652,hint,18,self.GOLD if self.error else self.MUTED,width=864)
            self.button(cache,(432,682,608,738),'Cancel',('dismiss',None))
            self.decoder_button(cache,(628,682,1072,738),'Please wait…' if self.submitting else 'Use receiver' if n['kind']=='select' else 'Yes, assign a new ID',('choose' if n['kind']=='select' else 'assign',None),enabled=not self.submitting,font_size=21,uppercase=False)
        else:
            remaining=max(0,math.ceil((self.view.until or 0)-time.monotonic()))
            pending=n.get('pending_reconnects',[])
            note=f'Closes automatically in {remaining} seconds.' if n['kind']=='ready' else 'Select a receiver above.' if n['kind']=='select' and receivers else 'No available receivers. Plug in a USB SDR.' if n['kind']=='select' else ('Reconnect: '+', '.join('USB '+p['port']+' → '+p['serial'] for p in pending) if pending else 'New plug-ins remain visible. ID changes run one at a time.')
            self.ink(cache,208,652,self.error or note,18,self.MUTED,width=864)
            self.button(cache,(808,682,1072,738),'Close',('dismiss',None))



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
