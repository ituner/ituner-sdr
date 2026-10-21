"""Native Airspace dashboard styling for the 1280 × 800 CM5 touchscreen.

The receiver and GPU globe remain in ADSBWorkspace; this layer lays out the
same instruments and touch actions as the browser without embedding a browser.
"""
import math
import time
from ui_chrome import RAIL_BACK_BOX
from ui_style import APP_UI_STYLE
from adsb_traffic import historical_aircraft, position_age, reception_summary, trail_label
from adsb_view import aged, freshness


class AirspaceDashboard:
    DASHBOARD_MAP = (0, 224, 1024, 712)

    def ink(self, cache, x, y, value, size=16, color=None, width=None, anchor='lm', bold=False):
        value=str(value)
        bold=bold or size>=20
        if width:value=self.ui.fit_station_text(cache,value,width,size,bold,False,'Oxanium')
        self.ui.draw_text(cache,x,y,value,color or self.TEXT,size,bold,False,anchor,family='Oxanium')

    def surface(self, box, fill=None, border=None, radius=8):
        self.ui.draw_logical_rounded_rect(*box,APP_UI_STYLE.button.radius,fill or self.PANEL,border or self.LINE,1)

    def button(self, cache, box, title, action, subtitle='', active=False, enabled=True, font_size=None):
        # Use the same renderer, type scale and pressed state as HOME's rail.
        self.ui.draw_styled_two_line_button(cache,box,str(title).upper(),str(subtitle).upper(),active=active,enabled=enabled)
        if enabled:
            self.actions.append((box,action))

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
        ui.draw_logical_rect(0,0,1024,146,self.PANEL)
        self.ink(cache,18,34,'ADS-B / AIRSPACE',27,bold=True)
        self.text(cache,18,66,'Aircraft received by your local radio',18,self.MUTED,width=450)
        self.button(cache,(500,12,740,76),'1090 ES',('usb',None),state['status'],active=state['enabled'])
        self.button(cache,(752,12,1008,76),'978 UAT',('usb',None),'NOT INSTALLED',enabled=False)
        showing=self.logs_open or self.usb_open or self.traffic_open
        for i,(label,kind,active) in enumerate((('MAP','map_view',not showing),('TRAFFIC','traffic',self.traffic_open),('LOGS','logs',self.logs_open),('RECEIVER','usb',self.usb_open))):
            x=16+i*250
            self.button(cache,(x,88,x+242,144),label,(kind,None),active=active)
        if self.last_count is None or state['messages']<self.last_count:
            self.last_count,self.last_rate_time=state['messages'],time.monotonic();self.rate=0
        elapsed=time.monotonic()-self.last_rate_time
        if elapsed>=2:
            self.rate=(state['messages']-self.last_count)/elapsed
            self.last_count,self.last_rate_time=state['messages'],time.monotonic()

    def draw_view_controls(self, cache):
        view=self.traffic_view
        self.ui.draw_logical_rect(0,146,1024,224,self.PANEL)
        for index,(box,label,action,active,enabled) in enumerate((
            ((16,156,92,212),'Live',('traffic_view','live'),view.mode=='live',True),
            ((100,156,300,212),'Reception dome',('coverage',None),self.coverage_open,True),
            ((308,156,504,212),'Since opened',('traffic_view','session'),view.mode=='session',True),
            ((512,156,616,212),'History',('traffic_view','history'),view.mode=='history',True),
            ((624,156,788,212),'Start fresh',('start_fresh',None),False,True),
            ((796,156,928,212),'Past trails',('backdrop',None),view.backdrop,view.mode!='history'))):
            x=16+index*(1000/6)
            box=(x,156,x+1000/6-8,212)
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
        self.ink(cache,26,369,('RX footprint · retained history · ' if self.footprint_regions(state) else '')+f'GLOBE {self.scale:,.1f}×',12,self.MUTED)
        style={'both':'SAT + BORDERS','satellite':'SATELLITE','borders':'BORDERS'}[self.map_style]
        for index,(label,kind,value,active) in enumerate((('+   ZOOM IN','zoom',1.6,False),('−   ZOOM OUT','zoom',1/1.6,False),('FIT VIEW','fit',None,False),(style,'style',None,False),('TRAILS · '+trail_label(self.trail_seconds),'trails',None,False),('LABELS '+('ON' if self.labels else 'OFF'),'labels',None,self.labels),('RANGE RINGS','rings',None,self.rings),('RX FOOTPRINT','rx_footprint',None,self.rx_footprint))):
            y=232+index*60
            if kind=='trails' and view.mode=='session':label='SINCE OPENED'
            self.button(cache,(858,y,1008,y+56),label,(kind,value),active=active,enabled=not(kind=='trails' and view.mode=='session'))
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
        ui.draw_logical_rect(1024,0,1280,800,self.color('sidebar'))
        self.button(cache,(1034,12,1270,76),'STOP' if state['enabled'] else 'START',
                    ('stop' if state['enabled'] else 'start',None),active=state['enabled'])
        self.ink(cache,1034,110,'AIRCRAFT',20,width=180)
        self.ink(cache,1270,110,len(self.display_aircraft(state)),20,self.MUTED,anchor='rm')
        plane=self.selected_plane
        live=next((p for p in state['aircraft'] if p.get('hex')==self.selected),None)
        historical=next((p for p in self.display_aircraft(state) if p['hex']==self.selected and p.get('historical')),None)
        if live or historical:plane=live if self.positioned(live) else historical or live;self.selected_plane=plane
        if plane:plane=aged(plane,time.time())
        self.surface((1034,206,1270,440))
        if plane:
            self.ink(cache,1044,228,(plane.get('flight') or plane['hex']).strip(),24,self.GOLD,width=216)
            self.text(cache,1044,257,'ICAO '+plane['hex'].upper()+' · '+str(plane.get('squawk') or '—'),14,self.MUTED,width=216)
            for x,y,label,key,unit in ((1044,284,'ALTITUDE','alt_baro','ft'),(1158,284,'SPEED','gs','kt'),(1044,342,'HEADING','track','°'),(1158,342,'VERT RATE','baro_rate','ft/min')):
                self.text(cache,x,y,label,13,self.MUTED,width=102)
                self.ink(cache,x,y+26,self.instrument_value(plane.get(key))+' '+unit,18,width=102)
            self.text(cache,1044,397,freshness(plane),13,self.MUTED,width=216)
            if isinstance(plane.get('lat'),(int,float)) and isinstance(plane.get('lon'),(int,float)):
                self.text(cache,1044,424,f"{plane['lat']:.4f}°, {plane['lon']:.4f}°",14,self.MUTED,width=216)
        else:
            self.text(cache,1044,238,'SELECT AN AIRCRAFT',18,width=216)
            self.plane_symbol(1152,312,self.CYAN,1.8)
            self.text(cache,1044,378,'Tap a plane or contact',16,self.MUTED,width=216)
            self.text(cache,1044,410,'History shows older data',14,self.MUTED,width=216)
        located=bool(plane and isinstance(plane.get('lat'),(int,float)) and isinstance(plane.get('lon'),(int,float)))
        self.button(cache,(1034,448,1148,504),'FOLLOW',('follow',None),active=self.following,enabled=bool(self.positioned(live) or self.following))
        self.button(cache,(1156,448,1270,504),'LOCATE',('locate',None),enabled=located)
        self.button(cache,(1034,512,1270,568),'CLEAR SELECTION',('clear',None),enabled=bool(plane))
        planes=self.sorted_aircraft(state)
        for index,plane in enumerate(planes[:2]):
            y=576+index*64
            title=(plane.get('flight') or plane['hex']).strip()
            detail=self.instrument_value(plane.get('alt_baro'))+' ft · '+freshness(plane)
            if self.traffic_view.arrival(plane['hex'],time.time()):title='NEW · '+title
            self.button(cache,(1034,y,1270,y+56),title,('select',plane['hex']),detail,active=plane['hex']==self.selected)
        if not planes:
            self.text(cache,1034,604,'No contacts in this view.',16,self.MUTED,width=236)
            self.text(cache,1034,638,'Choose History to look back.',16,self.MUTED,width=236)
        self.button(cache,RAIL_BACK_BOX,'BACK',('back',None))

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
        status='1090 ES · '+state['status']
        self.draw_status(cache,status+' · '+(self.message or 'NASA BLUE MARBLE / GIBS · NATURAL EARTH'),
                         'TRAILS '+trail_label(self.trail_seconds)+' · cm5.local:'+str(state['port']))
