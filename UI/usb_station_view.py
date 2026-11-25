"""USB scan results and decoded RDS; source-local and touch-modal."""
from station_workspace import StationWorkspace
import theme_system
import math
import time


def draw_scan_border(ui,box,now=None):
    """Theme-shaped button outline; one gentle pulse only while scanning."""
    now=time.monotonic() if now is None else now
    palette=ui.APP_UI_STYLE.palette
    color=(*palette.focus[:3],int(palette.focus[3]*(.45+.4*(.5+.5*math.sin(now*math.tau/1.8)))))
    ui.draw_logical_rounded_rect(*box,ui.APP_UI_STYLE.button.radius,(0,0,0,0),color,3)


class USBStationView(StationWorkspace):
    def __init__(self,ui,search,rds,receiver,state):
        super().__init__(ui,None);self.search=search;self.rds=rds;self.receiver=receiver;self.state=state;self.page=0;self.first=0;self.max_first=0;self.dragged=False;self.drag_start=None
        self.seen_stations=set();self.was_scanning=False;self.centered_station=None
    @property
    def open(self):return getattr(self,'search',None) is not None and self.search.open
    @open.setter
    def open(self,value):
        if getattr(self,'search',None) is not None:self.search.open=value
    def close(self):
        if self.search.active:self.search.stop()
        self.search.open=False
        self.centered_station=None
    def drag_begin(self,x,y):
        offset=256 if theme_system.runtime_theme['sidebar']=='left' else 0
        self.drag_start=(y,self.first) if offset+24<=x<=offset+988 and 110<=y<=630 else None
        self.dragged=False
    def drag_move(self,x,y):
        if self.drag_start is None:return
        start,first=self.drag_start
        if abs(y-start)>16:self.dragged=True
        if self.dragged:self.first=max(0,min(self.max_first,first+round((start-y)/64)))
    def release(self,x,y,tap=True):
        self.drag_move(x,y)
        if tap and not self.dragged:self.tap(x,y)
        self.drag_start=None
    def tap(self,x,y):
        for box,(action,value) in self.actions:
            if not self.ui.contains(box,x,y):continue
            if action=='back':self.close()
            elif action=='scan':self.search.toggle_scan()
            elif action=='page':self.first=max(0,min(self.max_first,self.first+value*5))
            elif action=='station':
                if self.search.active:return
                self.state.set_view(freq_khz=value/1000)
                self.centered_station=None
                self.message='Listening · waiting for broadcast RDS updates'
            return
    def update_scroll(self,rows):
        self.max_first=max(0,len(rows)-5)
        keys={row['hz'] for row in rows}
        if self.search.active:
            new=[i for i,row in enumerate(rows) if row['hz'] not in self.seen_stations]
            if new:
                # Follow discoveries once, leaving manual browsing usable between them.
                self.first=max(0,min(self.max_first,new[-1]-4))
                if self.drag_start is not None:self.drag_start=None;self.dragged=True
        else:
            frequency=self.state.snapshot()[1]*1000
            selected=next((i for i,row in enumerate(rows) if abs(row['hz']-frequency)<1000),None)
            station=rows[selected]['hz'] if selected is not None else None
            if selected is not None and (self.was_scanning or station!=self.centered_station):
                self.first=selected-2
                self.drag_start=None
            self.centered_station=station
        self.first=max(0,min(self.first,self.max_first))
        self.seen_stations=keys
        self.was_scanning=self.search.active

    def draw(self,cache):
        self.actions=[];ui=self.ui
        offset=256 if theme_system.runtime_theme["sidebar"]=="left" else 0
        rail=10 if offset else 1034
        ui.draw_logical_rect(0,0,1280,800,self.BG);self.draw_back(cache)
        self.ink(cache,offset+24,34,'USB STATIONS · RDS',28)
        self.ink(cache,offset+24,74,'Swipe up/down to browse. Stop scanning before selecting a station.',19,self.MUTED,width=960)
        rows=self.rds.store.snapshot(self.receiver.source_id,self.receiver.receiver_selection)
        self.update_scroll(rows)
        frequency=self.state.snapshot()[1]*1000
        for i,row in enumerate(rows[self.first:self.first+5]):
            y=110+i*104;active=abs(row['hz']-frequency)<1000
            title=f"{row['hz']/1e6:.4f} MHz · "+(row['ps'] or 'Unnamed signal')
            detail=row['radiotext'] or ('RDS PI '+row['pi']+' · no RadioText received' if row['pi'] else 'No RDS decoded')
            if not active and row['updated']:detail='Last decoded · '+detail
            box=(offset+24,y,offset+988,y+92)
            self.decoder_button(cache,box,title,('station',row['hz']),detail,active=active,font_size=22,uppercase=False,prefix=f"{self.first+i+1:02d}.  ")
            if active:
                ui.draw_logical_rounded_rect(*box,self.RADIUS,(0,0,0,0),self.color('selected_border'),3)
        if self.max_first:
            # A slim, subdued position indicator, updated by swipes and paging.
            x=offset+1000;top=110;height=508
            thumb=max(28,height*5/len(rows))
            y=top+(height-thumb)*self.first/self.max_first
            track=self.color('slider_track');fill=self.color('slider_thumb')
            ui.draw_logical_rect(x,top,x+3,top+height,(*track[:3],int(track[3]*.25)))
            ui.draw_logical_rect(x,y,x+3,y+thumb,(*fill[:3],int(fill[3]*.35)))
        if not rows:self.ink(cache,offset+32,190,'No stations listed yet. Select WFM and use SCAN.',24,self.MUTED,width=950)
        self.button(cache,(offset+24,652,offset+230,714),'PREVIOUS',('page',-1))
        self.button(cache,(offset+246,652,offset+452,714),'NEXT',('page',1))
        self.ink(cache,offset+480,682,f'{self.first+1 if rows else 0}–{min(self.first+5,len(rows))} / {len(rows)}',20,self.MUTED)
        self.button(cache,(rail,120,rail+236,186),'STOP SCAN' if self.search.active else 'SCAN',('scan',None),self.search.active)
        self.ink(cache,rail+10,222,'Tap again to stop' if self.search.active else 'Scan entire range',17,self.MUTED,width=220)
        if self.search.active:draw_scan_border(ui,(rail,120,rail+236,186))
        self.draw_status(cache,'Scanning…' if self.search.active else self.message or self.rds.status,
                         'RDS names and RadioText require a decodable WFM broadcast.',full_width=True)
