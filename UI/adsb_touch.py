"""Native Airspace dashboard styling for the 1280 × 800 CM5 touchscreen.

The receiver and GPU globe remain in ADSBWorkspace; this layer lays out the
same instruments and touch actions as the browser without embedding a browser.
"""
import math
import time
from decoder_style import footer_content_box
from ui_style import APP_UI_STYLE
from adsb_traffic import historical_aircraft, position_age, reception_summary, trail_label
from adsb_view import aged, freshness


class AirspaceDashboard:
    DASHBOARD_MAP = (0, 224, 944, 720)

    def ink(self, cache, x, y, value, size=16, color=None, width=None, anchor='lm', bold=False):
        value=str(value)
        bold=bold or size>=20
        if width:value=self.ui.fit_station_text(cache,value,width,size,bold,False,'Oxanium')
        self.ui.draw_text(cache,x,y,value,color or self.TEXT,size,bold,False,anchor,family='Oxanium')

    def surface(self, box, fill=None, border=None, radius=8):
        self.ui.draw_logical_rounded_rect(*box,APP_UI_STYLE.button.radius,fill or self.PANEL,border or self.LINE,1)

    def button(self, cache, box, title, action, subtitle='', active=False, enabled=True, font_size=None):
        self.decoder_button(cache,box,title,action,subtitle,active,enabled,font_size or 16)

    @staticmethod
    def instrument_value(value, digits=0):
        if value=='ground':return 'GROUND'
        if isinstance(value,(int,float)) and math.isfinite(value):return f'{value:,.{digits}f}'
        return '—'

    def plane_symbol(self, x, y, color, size=1):
        self.ui.draw_logical_polyline([(x,y-14*size),(x,y+13*size)],(*color,255),3)
        self.ui.draw_logical_polyline([(x-13*size,y+3*size),(x,y-5*size),(x+13*size,y+3*size)],(*color,255),2)
        self.ui.draw_logical_polyline([(x-6*size,y+11*size),(x,y+7*size),(x+6*size,y+11*size)],(*color,255),2)

    def header(self, cache, state, valid):
        ui=self.ui
        ui.draw_logical_rect(0,0,1280,88,self.PANEL)
        ui.draw_logical_rect(0,0,680,88,self.PANEL)
        ui.draw_logical_rect(0,87,1280,88,self.LINE)
        self.plane_symbol(35,45,self.CYAN,1.05)
        self.ink(cache,66,24,'iTUNER / VHF + UHF',10,self.MUTED)
        self.ink(cache,64,56,'A I R S P A C E',27,bold=True)
        for box,title,sub,ready in (((300,14,476,75),'1090 ES',state['status'],True),((488,14,664,75),'978 UAT','NOT INSTALLED',False)):
            self.surface(box,self.PANEL,self.LINE,6)
            self.ui.draw_logical_circle(box[0]+15,box[1]+20,3,self.CYAN if ready and state['enabled'] else self.MUTED)
            self.ink(cache,box[0]+30,box[1]+22,title,22,self.TEXT if ready else self.MUTED)
            self.ink(cache,box[0]+30,box[1]+46,sub,10,self.CYAN if ready else self.MUTED,width=138)
            self.actions.append((box,('usb',None)))
        self.ink(cache,1098,33,time.strftime('%H:%M:%S UTC',time.gmtime()),20,self.MUTED,anchor='rm')
        self.ink(cache,1098,60,'LOCAL GROUND RECEIVER',10,self.MUTED,anchor='rm')
        self.button(cache,(1120,16,1264,74),'STOP' if state['enabled'] else 'START',('stop' if state['enabled'] else 'start',None),active=state['enabled'])
        ui.draw_logical_rect(0,88,1280,146,self.PANEL)
        ui.draw_logical_rect(0,145,1280,146,self.LINE)
        showing=self.logs_open or self.usb_open or self.traffic_open
        for box,label,kind,active in (((16,96,116,136),'MAP','map_view',not showing),((126,96,266,136),f"TRAFFIC  {len(self.display_aircraft(state))}",'traffic',self.traffic_open),((276,96,376,136),'LOGS','logs',self.logs_open),((386,96,526,136),'RECEIVER','usb',self.usb_open)):
            self.button(cache,box,label,(kind,None),active=active)
        status=reception_summary(state,time.time()) if state['enabled'] else state['status']
        self.text(cache,546,117,status,13,self.MUTED,width=598)
        if self.last_count is None or state['messages']<self.last_count:
            self.last_count,self.last_rate_time=state['messages'],time.monotonic();self.rate=0
        elapsed=time.monotonic()-self.last_rate_time
        if elapsed>=2:
            self.rate=(state['messages']-self.last_count)/elapsed
            self.last_count,self.last_rate_time=state['messages'],time.monotonic()

    def draw_view_controls(self, cache):
        view=self.traffic_view
        self.ui.draw_logical_rect(0,146,944,224,self.PANEL)
        for box,label,action,active,enabled in (
            ((16,156,92,212),'Live',('traffic_view','live'),view.mode=='live',True),
            ((100,156,300,212),'Reception dome',('coverage',None),self.coverage_open,True),
            ((308,156,504,212),'Since opened',('traffic_view','session'),view.mode=='session',True),
            ((512,156,616,212),'History',('traffic_view','history'),view.mode=='history',True),
            ((624,156,788,212),'Start fresh',('start_fresh',None),False,True),
            ((796,156,928,212),'Past trails',('backdrop',None),view.backdrop,view.mode!='history')):
            self.button(cache,box,label,action,subtitle=('ON' if view.backdrop else 'OFF') if action[0]=='backdrop' else '',active=active,enabled=enabled,font_size=18)

    def draw_map_hud(self, cache, state, valid):
        # Compact instruments and buttons float above the same GPU map as GLOBE.
        self.draw_view_controls(cache)
        self.overlay_boxes=[(16,240,492,320),(16,332,690,382),(16,630,530,658),(16,678,160,710)]
        self.surface((16,240,492,320),self.PANEL)
        counts=self.traffic_view.counts(state['aircraft'],time.time())
        for index,(label,value) in enumerate((('LIVE CONTACTS',counts['live']),('FRESH POSITIONS',counts['positions']),('NEW THIS VISIT',counts['new']),('MSG / SEC',f'{self.rate:.1f}'))):
            x=32+index*118
            if index:self.ui.draw_logical_rect(x-16,241,x-15,319,self.LINE)
            self.ink(cache,x,259,label,9,self.MUTED)
            self.ink(cache,x,293,value,27,width=100)
        self.surface((16,332,690,382),self.PANEL,radius=4)
        view=self.traffic_view
        window=('since '+time.strftime('%H:%M',time.localtime(view.opened_at))) if view.mode=='session' else 'trails '+trail_label(self.trail_seconds)
        self.ink(cache,26,348,view.label+' · '+window+' · LOGS RETAINED',15,self.CYAN)
        self.ink(cache,26,369,f'Contact & position age independently · GLOBE {self.scale:,.1f}×',12,self.MUTED)
        style={'both':'SAT + BORDERS','satellite':'SATELLITE','borders':'BORDERS'}[self.map_style]
        for index,(label,kind,value,active) in enumerate((('+   ZOOM IN','zoom',1.6,False),('−   ZOOM OUT','zoom',1/1.6,False),('FIT TRAFFIC','fit',None,False),(style,'style',None,False),('TRAILS · '+trail_label(self.trail_seconds),'trails',None,False),('LABELS '+('ON' if self.labels else 'OFF'),'labels',None,self.labels),('RANGE RINGS','rings',None,self.rings))):
            y=240+index*52
            if kind=='trails' and view.mode=='session':label='SINCE OPENED'
            self.button(cache,(778,y,928,y+44),label,(kind,value),active=active,enabled=not(kind=='trails' and view.mode=='session'))
        if self.following:
            self.surface((240,666,714,710),self.PANEL,self.color('waiting'))
            live=next((p for p in state['aircraft'] if p['hex']==self.selected),None)
            label='FOLLOWING' if self.positioned(live) else 'WAITING FOR POSITION'
            name=((self.selected_plane or {}).get('flight') or self.selected or '').strip()
            self.ink(cache,477,688,label+' · '+name,15,self.GOLD,anchor='cm')
            self.overlay_boxes.append((240,666,714,710))
        self.surface((16,630,530,658),self.PANEL,radius=4)
        for x,label,color in ((30,'Low altitude',self.CYAN),(158,'High altitude',(120,184,255)),(291,'Selected',self.GOLD),(400,'Last known',self.MUTED)):
            self.ui.draw_logical_circle(x,644,3,color)
            self.text(cache,x+10,644,label,11,self.MUTED)
        radius=min(self.MAP[2]-self.MAP[0],self.MAP[3]-self.MAP[1])*.92*self.scale
        maximum=math.asin(min(.95,120/max(1,radius)))*3440.065
        steps=(.005,.01,.02,.05,.1,.2,.5,1,2,5,10,20,50,100,200,500,1000,2000)
        distance=max((d for d in steps if d<=maximum),default=steps[0])
        width=math.sin(distance/3440.065)*radius
        self.ui.draw_logical_polyline([(24,686),(24,691),(24+width,691),(24+width,686)],(*self.MUTED,255),1)
        label=f'{round(distance*1852)} m' if distance<1 else f'{distance:g} NM'
        self.ink(cache,24,706,label,11,self.MUTED)

    def sorted_aircraft(self, state):
        return sorted(self.display_aircraft(state),key=(lambda p:-(p.get('alt_baro') if isinstance(p.get('alt_baro'),(int,float)) else -1e6)) if self.traffic_sort=='altitude' else (lambda p:(p.get('flight') or p['hex']).strip().lower()) if self.traffic_sort=='callsign' else (lambda p:p.get('seen',100)))

    def draw_aircraft_sidebar(self, cache, state, valid):
        ui=self.ui
        ui.draw_logical_rect(944,146,1280,720,self.PANEL)
        ui.draw_logical_rect(944,146,945,720,self.LINE)
        self.ink(cache,962,168,self.traffic_view.label+' TRAFFIC',11,self.MUTED)
        self.ink(cache,960,197,'Aircraft',25)
        self.ink(cache,1260,190,len(self.display_aircraft(state)),34,self.MUTED,anchor='rm')
        sort={'recent':'LATEST RECEIVED','altitude':'HIGHEST ALTITUDE','callsign':'CALLSIGN A–Z'}[self.traffic_sort]
        self.button(cache,(960,216,1264,256),sort+' · TAP TO SORT',('sort',None))
        plane=self.selected_plane
        live=next((p for p in state['aircraft'] if p.get('hex')==self.selected),None)
        historical=next((p for p in self.display_aircraft(state) if p['hex']==self.selected and p.get('historical')),None)
        if live or historical:plane=live if self.positioned(live) else historical or live;self.selected_plane=plane
        if plane:plane=aged(plane,time.time())
        self.surface((960,270,1264,592),self.color('selected_surface') if plane else self.PANEL,self.color('selected_border') if plane else self.LINE)
        if plane:
            self.ink(cache,976,291,'TARGET DETAILS',10,self.MUTED)
            self.ink(cache,976,321,(plane.get('flight') or plane['hex']).strip(),25,self.GOLD,width=212)
            self.ink(cache,1248,293,'1090 ES',10,self.MUTED,anchor='rm')
            identity='ICAO '+plane['hex'].upper()+((' · '+str(plane['squawk'])) if plane.get('squawk') else '')
            self.text(cache,976,349,identity,12,self.MUTED,width=268)
            for x,y,label,key,unit in ((976,376,'ALTITUDE','alt_baro','ft'),(1124,376,'GROUND SPEED','gs','kt'),(976,440,'HEADING','track','°'),(1124,440,'VERTICAL RATE','baro_rate','ft/min')):
                self.ink(cache,x,y,label,9,self.MUTED)
                self.ink(cache,x,y+26,self.instrument_value(plane.get(key)),24,width=124)
                self.text(cache,x,y+45,unit,10,self.MUTED)
            contact,position=freshness(plane).split(' · ',1)
            self.ink(cache,976,499,contact,13,self.MUTED,width=270)
            self.ink(cache,976,515,position,12,self.CYAN if self.positioned(plane) else self.MUTED,width=270)
            if isinstance(plane.get('lat'),(int,float)) and isinstance(plane.get('lon'),(int,float)):
                self.text(cache,976,528,f"{plane['lat']:.5f}°, {plane['lon']:.5f}°",12,self.MUTED,width=270)
            for box,label,kind,enabled in (((976,542,1064,586),'FOLLOW','follow',self.positioned(live) or self.following),((1072,542,1160,586),'LOCATE','locate',isinstance(plane.get('lat'),(int,float)) and isinstance(plane.get('lon'),(int,float))),((1168,542,1250,586),'CLEAR','clear',True)):
                self.button(cache,box,label,(kind,None),active=kind=='follow' and self.following,enabled=enabled)
        else:
            self.ink(cache,978,294,'TARGET DETAILS',10,self.MUTED)
            self.ink(cache,978,331,'Select an aircraft',23)
            self.plane_symbol(1109,407,self.CYAN,2.2)
            self.text(cache,984,478,'Tap a plane on the map',17,self.MUTED)
            self.text(cache,984,505,'or choose live traffic below.',17,self.MUTED)
            self.text(cache,984,554,'Grey planes show last-known positions.',12,self.MUTED,width=262)
        self.ink(cache,962,616,'LATEST CONTACTS',10,self.MUTED)
        planes=self.sorted_aircraft(state)
        for index,plane in enumerate(planes[:2]):
            y=600+index*58;selected=plane['hex']==self.selected
            box=(960,y,1264,y+52)
            self.surface(box,self.color('selected_surface') if selected else self.PANEL,self.LINE,5)
            if selected:ui.draw_logical_rect(960,y+5,963,y+47,(*self.GOLD,255))
            self.ink(cache,974,y+17,(plane.get('flight') or plane['hex']).strip(),16,self.GOLD if selected else self.TEXT,width=170)
            self.ink(cache,1250,y+17,self.instrument_value(plane.get('alt_baro'))+' ft',12,self.MUTED,anchor='rm')
            detail=freshness(plane)
            if self.traffic_view.arrival(plane['hex'],time.time()):detail='NEW · '+detail
            self.text(cache,974,y+39,detail,10,self.MUTED,width=276)
            self.actions.append((box,('select',plane['hex'])))
        if not planes:
            self.text(cache,976,657,'No contacts in this view.',16,self.MUTED)
            self.text(cache,976,686,'Choose History for earlier observations.',12,self.MUTED,width=272)
            self.text(cache,976,710,'Flights and receiver activity are in Logs.',12,self.MUTED,width=272)

    def draw(self, cache, *args):
        state=self.manager.snapshot();self.actions=[]
        self.dashboard=True;self.MAP=self.DASHBOARD_MAP
        self.traffic_view.ingest(state['aircraft'],time.time())
        self.trail_seconds=self.traffic_view.trail_seconds
        if self.coverage_open:
            self.coverage_view.draw(cache,state);return
        valid=[p for p in self.display_aircraft(state,True) if not p.get('historical') and self.positioned(p)]
        self.ui.draw_logical_rect(0,0,1280,800,self.BG)
        self.header(cache,state,valid)
        if self.logs_open or self.traffic_open or self.usb_open:
            self.points=[];self.overlay_boxes=[]
            if self.logs_open:self.draw_logs(cache)
            elif self.traffic_open:self.draw_traffic(cache,state);self.draw_view_controls(cache)
            else:self.draw_usb(cache,state)
        else:self.draw_map(cache,state,valid)
        self.draw_aircraft_sidebar(cache,state,valid)
        self.ui.draw_logical_rect(0,724,1280,800,self.BG)
        self.ui.draw_logical_rect(0,724,1280,725,self.LINE)
        x0,_,x1,_=footer_content_box()
        self.draw_back(cache)
        self.ui.draw_logical_circle(x0,747,3,self.CYAN if state['enabled'] else self.MUTED)
        status='1090 ES · '+state['status']
        self.ink(cache,x0+12,747,status,10,self.CYAN if state['enabled'] else self.MUTED,width=180)
        detail=self.message or 'NASA BLUE MARBLE / GIBS · NATURAL EARTH'
        self.text(cache,x0,777,detail,11,self.GOLD if self.message else self.MUTED,width=650)
        self.ink(cache,x1,747,f'TRAILS {trail_label(self.trail_seconds)} · cm5.local:{state["port"]}',10,self.MUTED,anchor='rm')
