"""Native Airspace dashboard styling for the 1280 × 800 CM5 touchscreen.

The receiver and GPU globe remain in ADSBWorkspace; this layer lays out the
same instruments and touch actions as the browser without embedding a browser.
"""
import math
import time
from ui_style import APP_UI_STYLE
from decoder_style import full_width_back_box
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
        visual=APP_UI_STYLE.button.resolve()
        self.ui.draw_logical_rounded_rect(16,16,208,80,APP_UI_STYLE.button.radius,(*visual.fill[:3],100),visual.border,visual.border_width)
        self.ink(cache,112,36,'AIRSPACE',26,anchor='cm',bold=True)
        self.ink(cache,112,62,'1090 ES + 978 UAT',14,self.CYAN,width=172,anchor='cm')
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
            x=216+index*200
            self.button(cache,(x,16,x+192,80),label,action,active=active)

    def draw_map_hud(self, cache, state, valid):
        self.overlay_boxes=[]
        if self.current_screen()!='map':return
        self.overlay_boxes=[(16,16,208,80),(16,224,670,272),(16,648,530,672),(16,678,160,710)]
        counts=self.traffic_view.counts(state['aircraft'],time.time(),self.tracks)
        for index,(label,value) in enumerate((('LIVE',counts['live']),('ON MAP',counts['positions']),('NEW',counts['new']),('MSG/S',f'{self.rate:.1f}'),('MESSAGES',self.instrument_value(state['messages'])))):
            x=24+index*128
            self.ink(cache,x,240,label,12,self.MUTED)
            self.ink(cache,x,262,value,19,width=120)
        self.button(cache,(216,88,408,152),'RX '+('ON' if self.rx_footprint else 'OFF'),('rx_footprint',None),active=self.rx_footprint)
        self.button(cache,(416,88,608,152),'Receivers',('usb',None))
        self.button(cache,(616,88,808,152),'Weather',('weather',None))
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
            self.ink(cache,24,286,view.label+' · trails '+('off' if view.mode=='history' and not view.history_trails else trail_label(self.trail_seconds))+((' · keep '+view.live_label) if view.mode=='live' else ''),15,self.CYAN)
            self.overlay_boxes.append((16,272,670,300))
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

    def draw_options_rail(self,cache,title,options,page=0):
        # Full-canvas decoder coordinates already follow the chosen theme side.
        x=full_width_back_box()[0]-10
        self.ui.draw_logical_rect(x,0,x+256,800,self.color('sidebar'))
        self.ui.draw_logical_rect(x,0,x+256,64,self.color('sidebar_header'))
        self.ui.draw_text(cache,x+128,32,title,self.color('sidebar_title'),15,True,False,'cm',family='Liberation Sans')
        self.ui.draw_logical_line(x+10,64,x+246,64,self.color('divider'),1)
        for index,(label,action,subtitle,active,enabled) in enumerate(options[page*7:page*7+7]):
            y=80+index*72
            self.button(cache,(x+10,y,x+246,y+64),label,action,subtitle,active=active,enabled=enabled)
        if len(options)>7:
            self.button(cache,(x+10,608,x+124,672),'PREVIOUS',('options_page',-1),enabled=page>0)
            self.button(cache,(x+132,608,x+246,672),'NEXT',('options_page',1),enabled=(page+1)*7<len(options))
            self.ink(cache,x+128,696,f'{page+1} / {(len(options)+6)//7}',16,self.MUTED,anchor='cm')

    def draw_settings(self,cache,state):
        primary_enabled=state.get('enabled_1090',state['enabled'])
        options=[(title,action,subtitle,False,action[0]!='radio_info' or self.radio_info is not None)
                 for title,action,subtitle in (
                    ('Receiver & dongles',('usb',None),'1090 ES + 978 UAT'),
                    ('Radio / user information',('radio_info',None),'Location, callsign and GPS'),
                    ('Logs & diagnostics',('logs',None),'Flights and receiver'),
                    ('Receiver comparison',('comparison',None),'Live graph / results'),
                    ('Stop 1090 ES' if primary_enabled else 'Start 1090 ES',('stop' if primary_enabled else 'start',None),'1090 ES receiver'))]
        self.draw_options_rail(cache,'SETTINGS',options)

    def draw_view_options(self,cache):
        style={'both':'Satellite + borders','satellite':'Satellite','borders':'Borders'}[self.map_style]
        labels=self.traffic_view.labels_visible(self.labels)
        icons=self.traffic_view.icons_visible(self.aircraft_icons)
        options=[('Aircraft list',('traffic',None),'',False,True),
                 (style,('style',None),'',False,True),
                 ('Labels '+('on' if labels else 'off'),('labels',None),'',labels,True),
                 ('Aircraft icons '+('on' if icons else 'off'),('aircraft_icons',None),'',icons,True),
                 ('Dots & trails '+('on' if self.traffic_view.history_trails else 'off'),('history_trails',None),'',self.traffic_view.history_trails,True),
                 ('Range rings',('rings',None),'',self.rings,True),
                 ('RX footprint',('rx_footprint',None),'',self.rx_footprint,True),
                 ('History window',('history_window',None),'All recorded' if self.history_seconds>86400 else trail_label(self.history_seconds),False,True),
                 ('Start fresh',('start_fresh',None),'Saved history stays available',False,True),
                 ('Reset panel',('reset_card',None),'',False,True)]
        self.draw_options_rail(cache,'VIEW',options,self.options_page)

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
        height=300 if plane else 64;width=342
        x,y=self.card_position or (914,700-height)
        x=max(16,min(1264-width,x));y=max(174,min(700-height,y))
        self.card_box=(x,y,x+width,y+height);self.card_handle=(x,y,x+width,y+42)
        self.overlay_boxes.append(self.card_box)
        self.ui.draw_logical_rounded_rect(*self.card_box,APP_UI_STYLE.button.radius,(*self.PANEL[:3],174),(*self.LINE[:3],120),1)
        self.ink(cache,x+16,y+22,(plane.get('flight') or plane['hex']).strip() if plane else 'SELECT AN AIRCRAFT',23 if plane else 19,self.GOLD if plane else self.TEXT,width=250)
        self.ink(cache,x+width-16,y+22,'DRAG',11,self.MUTED,anchor='rm')
        if not plane:
            self.text(cache,x+16,y+46,'Tap a plane on the map to inspect it.',14,self.MUTED,width=310);return
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
        if not (self.view_options or self.settings_open):self.header(cache,state,valid)
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
