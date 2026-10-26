"""Native Airspace dashboard styling for the 1280 × 800 CM5 touchscreen.

The receiver and GPU globe remain in ADSBWorkspace; this layer lays out the
same instruments and touch actions as the browser without embedding a browser.
"""
import math
import time
from ui_style import APP_UI_STYLE
from adsb_traffic import historical_aircraft, position_age, reception_summary, trail_label
from adsb_view import aged, freshness
from adsb_bands import band_readings


class AirspaceDashboard:
    DASHBOARD_MAP = (0, 0, 1280, 712)

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
        self.ink(cache,24,35,'AIRSPACE',26,bold=True)
        self.ink(cache,24,64,'1090 ES + 978 UAT · local receiver',14,self.CYAN,width=310)
        self.draw_view_controls(cache)
        if self.last_count is None or state['messages']<self.last_count:
            self.last_count,self.last_rate_time=state['messages'],time.monotonic();self.rate=0
        elapsed=time.monotonic()-self.last_rate_time
        if elapsed>=2:
            self.rate=(state['messages']-self.last_count)/elapsed
            self.last_count,self.last_rate_time=state['messages'],time.monotonic()

    def draw_view_controls(self, cache):
        view=self.traffic_view
        controls=(('Live '+view.live_label,('traffic_view','live'),view.mode=='live'),
                  ('History',('traffic_view','history'),view.mode=='history'),
                  ('Dome',('coverage',None),self.coverage_open),
                  ('View',('view_options',None),self.view_options or self.history_window_open),
                  ('Settings',('settings',None),self.settings_open or self.usb_open or self.logs_open))
        for index,(label,action,active) in enumerate(controls):
            x=360+index*180
            self.button(cache,(x,16,x+164,72),label,action,active=active)

    def draw_map_hud(self, cache, state, valid):
        self.overlay_boxes=[]
        if self.current_screen()!='map':return
        self.overlay_boxes=[(16,84,670,128),(16,648,530,672),(16,678,160,710)]
        counts=self.traffic_view.counts(state['aircraft'],time.time(),self.tracks)
        for index,(label,value) in enumerate((('LIVE',counts['live']),('ON MAP',counts['positions']),('NEW',counts['new']),('MSG/S',f'{self.rate:.1f}'),('MESSAGES',self.instrument_value(state['messages'])))):
            x=24+index*128
            self.ink(cache,x,96,label,12,self.MUTED)
            self.ink(cache,x,118,value,19,width=120)
        self.button(cache,(692,88,872,144),'RX '+('ON' if self.rx_footprint else 'OFF'),('rx_footprint',None),active=self.rx_footprint)
        self.button(cache,(888,88,1110,144),'Receivers',('usb',None))
        self.button(cache,(1126,88,1264,144),'Weather',('weather',None))
        self.overlay_boxes.append((16,164,872,216))
        self.ui.draw_logical_rect(16,164,872,216,(*self.BG[:3],160))
        for index,band in enumerate(band_readings(state,time.time())):
            x=24+index*428;color=self.CYAN if band['tone']=='good' else self.GOLD if band['tone']=='warning' else self.MUTED
            self.ink(cache,x,176,band['name'],20,color)
            self.ink(cache,x+128,176,band['status'],18,color,width=284)
            self.ink(cache,x,202,band['details'],16,self.MUTED,width=412)
        view=self.traffic_view;notice_key=(view.mode,view.fresh_at,self.trail_seconds,view.live_seconds,view.history_trails);now=time.monotonic()
        if notice_key!=getattr(self,'view_notice_key',None):
            self.view_notice_key=notice_key;self.view_notice_until=now+5
        if now<self.view_notice_until:
            self.ink(cache,24,150,view.label+' · trails '+('off' if view.mode=='history' and not view.history_trails else trail_label(self.trail_seconds))+((' · keep '+view.live_label) if view.mode=='live' else ''),15,self.CYAN)
            self.overlay_boxes.append((16,134,670,164))
        for box,title,value in (((548,634,608,690),'−',1/1.6),((620,634,788,690),'Fit view',None),((800,634,860,690),'+',1.6)):
            self.button(cache,box,title,('fit',None) if value is None else ('zoom',value))
        for x,label,color in ((30,'Low altitude',self.CYAN),(158,'High altitude',(120,184,255)),(291,'Selected',self.GOLD),(400,'Last known',self.MUTED)):
            self.ui.draw_logical_circle(x,660,3,color);self.text(cache,x+10,660,label,11,self.MUTED)
        radius=min(self.MAP[2]-self.MAP[0],self.MAP[3]-self.MAP[1])*.92*self.scale
        maximum=math.asin(min(.95,120/max(1,radius)))*3440.065
        steps=(.005,.01,.02,.05,.1,.2,.5,1,2,5,10,20,50,100,200,500,1000,2000)
        distance=max((d for d in steps if d<=maximum),default=steps[0]);width=math.sin(distance/3440.065)*radius
        self.ui.draw_logical_polyline([(24,686),(24,691),(24+width,691),(24+width,686)],(*self.MUTED,255),1)
        self.ink(cache,24,706,f'{round(distance*1852)} m' if distance<1 else f'{distance:g} NM',11,self.MUTED)

    def draw_settings(self,cache,state):
        self.surface((340,150,940,686))
        self.ink(cache,368,188,'RADIO & DATA',25)
        primary_enabled=state.get('enabled_1090',state['enabled'])
        for index,(title,action,subtitle) in enumerate((('Receiver & dongles',('usb',None),'1090 ES + 978 UAT · separate USB receivers'),
                    ('Radio / user information',('radio_info',None),'Shared location, callsign and GPS'),
                    ('Logs & diagnostics',('logs',None),'Flights, receiver and diagnostics'),
                    ('Receiver comparison',('comparison',None),'All dongles · live graph / five-minute results'),
                    ('Stop 1090 ES' if primary_enabled else 'Start 1090 ES',('stop' if primary_enabled else 'start',None),'Manage UAT separately under Receiver & dongles'))):
            y=212+index*74;self.button(cache,(368,y,912,y+64),title,action,subtitle,enabled=action[0]!='radio_info' or self.radio_info is not None)
        self.button(cache,(368,584,912,648),'Back',('close_settings',None))

    def draw_view_options(self,cache):
        self.surface((230,150,1050,690));self.ink(cache,258,188,'MAP VIEW',25)
        style={'both':'Satellite + borders','satellite':'Satellite','borders':'Borders'}[self.map_style]
        self.button(cache,(258,218,626,290),'Aircraft list',('traffic',None))
        self.button(cache,(642,218,1022,290),style,('style',None))
        labels=self.traffic_view.labels_visible(self.labels)
        icons=self.traffic_view.icons_visible(self.aircraft_icons)
        for index,(title,kind,active) in enumerate((('Labels '+('on' if labels else 'off'),'labels',labels),('Aircraft icons '+('on' if icons else 'off'),'aircraft_icons',icons),('Dots & trails '+('on' if self.traffic_view.history_trails else 'off'),'history_trails',self.traffic_view.history_trails))):
            x=258+index*260;self.button(cache,(x,308,x+244,372),title,(kind,None),active=active)
        self.button(cache,(258,390,502,462),'Range rings',('rings',None),active=self.rings)
        self.button(cache,(518,390,762,462),'RX footprint',('rx_footprint',None),active=self.rx_footprint)
        self.button(cache,(778,390,1022,462),'History window',('history_window',None),'All recorded' if self.history_seconds>86400 else trail_label(self.history_seconds))
        self.button(cache,(258,480,626,544),'Start fresh',('start_fresh',None))
        self.button(cache,(642,480,1022,544),'Reset panel',('reset_card',None))
        self.text(cache,258,574,'Start fresh clears the view; saved history stays available.',18,self.MUTED,width=760)
        self.button(cache,(258,610,1022,674),'Back',('close_options',None))

    def sorted_aircraft(self, state):
        return sorted(self.display_aircraft(state),key=(lambda p:-(p.get('alt_baro') if isinstance(p.get('alt_baro'),(int,float)) else -1e6)) if self.traffic_sort=='altitude' else (lambda p:(p.get('flight') or p['hex']).strip().lower()) if self.traffic_sort=='callsign' else (lambda p:p.get('seen',100)))

    def draw_history_window(self,cache):
        self.surface((16,150,1264,690))
        self.ink(cache,40,190,'HISTORY WINDOW',25)
        self.text(cache,40,226,'Choose a window, then Apply. Cancel keeps the current window.',18,self.MUTED,width=920)
        choices=(90*86400,86400,43200,21600,10800,3600,1800,900,300)
        for index,value in enumerate(choices):
            x=40+(index%3)*400;y=258+(index//3)*90
            self.button(cache,(x,y,x+376,y+72),'All recorded' if value>86400 else trail_label(value),('history_choice',value),active=value==self.history_draft)
        self.button(cache,(40,592,616,664),'Cancel',('cancel_history',None))
        self.button(cache,(640,592,1216,664),'Apply',('history_apply',None))

    def draw_aircraft_overlay(self, cache, state):
        first_action=len(self.actions)
        plane=self.selected_plane;live=next((p for p in state['aircraft'] if p.get('hex')==self.selected),None)
        historical=next((p for p in self.display_aircraft(state) if p['hex']==self.selected and p.get('historical')),None)
        if live or historical:plane=live if self.positioned(live) else historical or live;self.selected_plane=plane
        if plane:plane=aged(plane,time.time())
        height=300 if plane else 78;width=342
        x,y=self.card_position or (914,700-height)
        x=max(16,min(1264-width,x));y=max(174,min(700-height,y))
        self.card_box=(x,y,x+width,y+height);self.card_handle=(x,y,x+width,y+42)
        self.overlay_boxes.append(self.card_box)
        self.ui.draw_logical_rounded_rect(*self.card_box,12,(*self.PANEL[:3],174),(*self.LINE[:3],120),1)
        self.ink(cache,x+16,y+22,(plane.get('flight') or plane['hex']).strip() if plane else 'SELECT AN AIRCRAFT',23 if plane else 19,self.GOLD if plane else self.TEXT,width=250)
        self.ink(cache,x+width-16,y+22,'DRAG',11,self.MUTED,anchor='rm')
        if not plane:
            self.text(cache,x+16,y+56,'Tap a plane on the map to inspect it.',14,self.MUTED,width=310);return
        self.text(cache,x+16,y+55,'ICAO '+plane['hex'].upper()+' · '+('978 UAT' if plane.get('band')=='978' else '1090 ES')+' · '+str(plane.get('squawk') or '—'),13,self.MUTED,width=310)
        for dx,dy,label,key,unit in ((16,88,'ALTITUDE','alt_baro','ft'),(178,88,'SPEED','gs','kt'),(16,146,'HEADING','track','°'),(178,146,'VERT RATE','baro_rate','ft/min')):
            self.text(cache,x+dx,y+dy,label,12,self.MUTED,width=148)
            self.ink(cache,x+dx,y+dy+24,self.instrument_value(plane.get(key))+' '+unit,19,width=148)
        self.text(cache,x+16,y+203,freshness(plane),12,self.MUTED,width=310)
        located=isinstance(plane.get('lat'),(int,float)) and isinstance(plane.get('lon'),(int,float))
        for dx,title,action,enabled,active in ((12,'Follow',('follow',None),bool(self.positioned(live) or self.following),self.following),(120,'Locate',('locate',None),located,False),(228,'Clear',('clear',None),True,False)):
            self.button(cache,(x+dx,y+232,x+dx+102,y+288),title,action,enabled=enabled,active=active)
        self.card_actions=self.actions[first_action:]

    def draw(self, cache, *args):
        if self.radio_info and self.radio_info.open:return self.radio_info.draw(cache)
        if self.dongles and self.dongles.open:return self.dongles.draw(cache)
        state=self.manager.snapshot();self.actions=[];self.card_actions=[];self.card_box=None;self.card_handle=None
        self.dashboard=True;self.MAP=self.DASHBOARD_MAP
        if self.weather_open:
            self.weather_view.draw(cache);return
        if self.comparison_open:
            self.comparison_view.draw(cache);return
        self.traffic_view.ingest(state['aircraft'],time.time())
        self.trail_seconds=self.traffic_view.trail_seconds
        if self.coverage_open:
            self.coverage_view.draw(cache,state);return
        valid=[p for p in self.display_aircraft(state,True) if not p.get('historical') and self.positioned(p)]
        self.ui.draw_logical_rect(0,0,1280,800,self.BG)
        self.draw_map(cache,state,valid)
        self.header(cache,state,valid)
        if self.history_window_open:self.draw_history_window(cache)
        elif self.view_options:self.draw_view_options(cache)
        elif self.settings_open:self.draw_settings(cache,state)
        elif self.logs_open or self.traffic_open or self.usb_open:
            self.points=[];self.overlay_boxes=[]
            if self.logs_open:self.draw_logs(cache)
            elif self.traffic_open:self.draw_traffic(cache,state)
            else:self.draw_usb(cache,state)
        else:self.draw_aircraft_overlay(cache,state)
        self.draw_back(cache)
        self.draw_status(cache,('1090 ES + 978 UAT' if any(b.get('enabled') and b['id']=='978' for b in state.get('bands',[])) else '1090 ES')+' · '+state['status']+(' · '+self.message if self.message else ''),
                         reception_summary(state,time.time()),full_width=True)
