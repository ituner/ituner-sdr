"""ADS-B traffic instruments, shared GLOBE map, receiver controls and visible logs."""
import math
import textwrap
import time
from decoder_style import DecoderStyle
from dongle_workspace import DongleWorkspace
from usb_radio_controls import receiver_rows
from station_workspace import StationWorkspace
from sstv_workspace import SSTVWorkspace
from adsb_touch import AirspaceDashboard
from adsb_coverage_touch import CoverageTouch
from adsb_weather_touch import WeatherTouch
from adsb_compare_touch import ComparisonTouch
from adsb_footprint import projected_frame
from adsb_coverage_gl import draw as draw_footprint_mesh
from station_profile import distance_m
from adsb_view import TrafficView, aged, freshness
from adsb_traffic import TRAIL_RETENTION, TRAIL_WINDOWS, MAP_ZOOM_MIN, MAP_ZOOM_MAX, trail_label, startup_notice_visible, reception_summary, historical_aircraft, position_age


class ADSBWorkspace(DecoderStyle, AirspaceDashboard, SSTVWorkspace):
    MAP = (0, 82, 1024, 716)

    def __init__(self, ui, manager):
        super().__init__(ui, manager)
        self.yaw, self.pitch, self.scale = math.radians(25), math.radians(45), 5.0
        self.centered = False
        self.selected = None
        self.selected_plane = None
        self.following = False
        self.rx_footprint=True;self.rx_frame=None;self.rx_key=None;self.rx_regions=None
        self.coverage_open = False
        self.coverage_view = CoverageTouch(self)
        self.weather_open = False
        self.weather_view = WeatherTouch(self)
        self.comparison_open = False
        self.comparison_view = ComparisonTouch(self)
        self.dongles = DongleWorkspace(ui,manager) if hasattr(manager,"scanner") else None
        self.radio_info=StationWorkspace(ui,manager.station) if getattr(manager,'station',None) is not None else None
        self.view_options=False
        self.options_page=0
        self.settings_open=False
        self.history_window_open=False
        self.navigation=[]
        self.card_position=None;self.card_box=None;self.card_handle=None;self.card_drag=None;self.card_actions=[]
        self.usb_open = False
        self.usb_page = 0
        self.usb_band = '1090'
        self.traffic_open = False
        self.traffic_page = 0
        self.logs_open = False
        self.log_kind = 'flights'
        self.log_page = 0
        self.map_style = 'both'
        self.trail_seconds = 300
        self.traffic_view = TrafficView(time.time())
        self.history_seconds = 90*86400
        self.history_draft=self.history_seconds
        self.rings = False
        self.labels = True
        self.aircraft_icons = True
        self.traffic_sort = 'recent'
        self.dashboard = False
        self.overlay_boxes = []
        self.points = []
        self.tracks = {}
        self.track_time = -float('inf')
        self.drag_origin = None
        self.dragged = False
        self.last_count = None
        self.last_rate_time = 0
        self.rate = 0

    def show(self, *args):
        if not self.open:
            self.traffic_view = TrafficView(time.time())
            self.view_notice_key=None
            self.navigation=[];self.navigate('map',remember=False)
            self.selected=self.selected_plane=None;self.following=False
        self.open = True

    def current_screen(self):
        for name,flag in self.screen_flags():
            if getattr(self,flag):return name
        return 'map'

    def navigate(self,page,remember=True):
        current=self.current_screen()
        if current==page:return
        if remember:self.navigation.append(current)
        for name,flag in self.screen_flags():
            setattr(self,flag,name==page)
        if page=='coverage':self.coverage_view.activate()

    @staticmethod
    def screen_flags():
        return (('history_window','history_window_open'),('options','view_options'),('settings','settings_open'),('weather','weather_open'),('comparison','comparison_open'),('coverage','coverage_open'),('logs','logs_open'),('traffic','traffic_open'),('usb','usb_open'))

    def go_back(self):
        if self.coverage_open and self.coverage_view.window_open:
            self.coverage_view.window_open=False;return
        if self.coverage_open and self.coverage_view.selected_observation is not None:
            self.coverage_view.selected_observation=None;return
        if self.weather_open and self.weather_view.report is not None:
            self.weather_view.action('weather_close_report',None);return
        if self.navigation:self.navigate(self.navigation.pop(),remember=False)
        elif self.current_screen()!='map':self.navigate('map',remember=False)
        else:self.open=False

    def set_traffic_view(self, mode):
        self.traffic_view.mode=mode
        if mode!='live':self.traffic_view.live_armed=False
        self.traffic_view.trail_seconds=min(self.history_seconds,TRAIL_RETENTION) if mode=='history' else 300
        self.traffic_view.coverage_seconds=self.history_seconds if mode=='history' else 300
        self.trail_seconds=self.traffic_view.trail_seconds
        self.selected=self.selected_plane=None;self.following=False;self.traffic_page=0

    def display_aircraft(self, state, map_only=False):
        if self.dashboard:return self.traffic_view.aircraft(state['aircraft'],self.tracks,time.time(),map_only)
        return state['aircraft']

    def zoom(self, factor):
        self.scale=max(MAP_ZOOM_MIN,min(MAP_ZOOM_MAX,self.scale*factor))
        self.centered=True

    def locate(self, plane):
        if self.positioned(plane):
            self.yaw, self.pitch = math.radians(plane['lon']), max(math.radians(-82), min(math.radians(82), math.radians(plane['lat'])))
            self.centered = True

    @staticmethod
    def positioned(plane):
        return bool(plane and isinstance(plane.get('lat'),(int,float)) and isinstance(plane.get('lon'),(int,float)) and plane.get('seen_pos',100)<15)

    def drag_begin(self, x, y):
        if self.radio_info and self.radio_info.open:return False
        if self.dongles and self.dongles.open:return False
        self.card_drag=None
        if self.weather_open:self.weather_view.drag_begin(x,y);self.dragged=False;return
        if self.current_screen()=='map' and self.card_handle and self.ui.contains(self.card_handle,x,y):
            self.card_drag=(self.card_box[0],self.card_box[1]);self.dragged=False;return
        if self.coverage_open:self.coverage_view.drag_begin(x,y)
        self.drag_origin = self.yaw, self.pitch
        self.dragged = False

    def drag_move(self, sx, sy, x, y):
        if self.weather_open:
            if any(self.ui.contains(box,sx,sy) for box,_ in self.actions):return
            if abs(x-sx)+abs(y-sy)>10:self.weather_view.drag_move(sx,sy,x,y);self.dragged=True
            return
        if self.radio_info and self.radio_info.open:return False
        if self.dongles and self.dongles.open:return False
        if self.coverage_open:
            self.coverage_view.drag_move(sx,sy,x,y);return
        if self.card_drag is not None:
            if abs(x-sx)+abs(y-sy)<10:return
            width=self.card_box[2]-self.card_box[0];height=self.card_box[3]-self.card_box[1]
            self.card_position=(max(16,min(1264-width,self.card_drag[0]+x-sx)),max(174,min(700-height,self.card_drag[1]+y-sy)))
            self.dragged=True;return
        if self.current_screen()!='map' or not self.ui.contains(self.MAP, sx, sy): return
        if self.dashboard and any(self.ui.contains(box,sx,sy) for box in self.overlay_boxes):return
        if self.dashboard and any(self.ui.contains(box,sx,sy) for box,_ in self.actions):return
        if abs(x-sx)+abs(y-sy)<10: return
        self.dragged, self.following = True, False
        self.yaw, self.pitch = self.ui.radiogarden_pan_angles(*self.drag_origin,x-sx,y-sy,self.MAP,self.scale)

    def swipe(self, sx=None, sy=None, x=None, y=None):
        if self.coverage_open:self.coverage_view.drag_end()
        if self.radio_info and self.radio_info.open:return False
        if self.dongles and self.dongles.open:return False
        if sy is not None and y is not None and abs(y-sy)>60 and abs(y-sy)>abs(x-sx)*1.5:
            delta = 1 if y<sy else -1
            if self.logs_open: self.log_page=max(0,self.log_page+delta);return True
            if self.traffic_open: self.traffic_page=max(0,self.traffic_page+delta);return True
        self.card_drag=None
        dragged, self.dragged = self.dragged, False
        return dragged

    def tap(self, x, y, *args):
        if self.radio_info and self.radio_info.open:return self.radio_info.tap(x,y)
        if self.dongles and self.dongles.open:return self.dongles.tap(x,y)
        if self.coverage_open and self.coverage_view.panel_contains(x,y):return self.coverage_view.panel_tap(x,y)
        on_card=self.current_screen()=='map' and self.card_box and self.ui.contains(self.card_box,x,y)
        for box,(kind,value) in (self.card_actions if on_card else self.actions):
            if not self.ui.contains(box,x,y): continue
            if kind=='comparison':self.navigate('comparison')
            elif kind=='comparison_range':
                self.comparison_view.span=value;self.comparison_view.next_read=0
            elif kind=='comparison_control':
                try:self.manager.control(value);self.message=''
                except ValueError as exc:self.message=str(exc)
                self.comparison_view.next_read=0
            elif kind=='weather':self.navigate('weather')
            elif kind.startswith('weather_'):self.weather_view.action(kind,value)
            elif kind=='dongles':self.dongles.show()
            elif kind=='usb_band':self.usb_band=value;self.usb_page=0
            elif kind in ('band_assign','band_control'):
                try:
                    self.manager.control('assign' if kind=='band_assign' else value,
                                         value if kind=='band_assign' else None,band=self.usb_band)
                    self.message=''
                except ValueError as exc:self.message=str(exc)
            elif kind=='radio_info' and self.radio_info:self.radio_info.show()
            elif kind.startswith('coverage_'):self.coverage_view.action(kind,value)
            elif kind=='coverage':self.navigate('coverage')
            elif kind=='site':
                self.ui.station_settings.show(parent='adsb')
                self.ui.station_settings.page='location'
                self.open=False
            elif kind=='home': self.open=False
            elif kind in ('back','cancel_history','close_options','close_settings'):self.go_back()
            elif kind=='map_view':self.navigation=[];self.navigate('map',remember=False)
            elif kind=='traffic_view':
                if value=='live':
                    previous=self.traffic_view.mode;self.traffic_view.press_live()
                    if previous!='live':self.set_traffic_view('live')
                else:self.set_traffic_view(value)
            elif kind=='options_page':self.options_page=max(0,min(1,self.options_page+value))
            elif kind=='view_options':
                if self.current_screen() in ('options','history_window'):self.go_back()
                else:self.options_page=0;self.navigate('options')
            elif kind=='settings':
                if self.settings_open:self.go_back()
                else:self.navigate('settings')
            elif kind=='reset_card':self.card_position=None;self.go_back()
            elif kind=='history_window':
                self.history_draft=self.history_seconds;self.navigate('history_window')
            elif kind=='history_choice':self.history_draft=value
            elif kind=='history_apply':
                self.history_seconds=self.history_draft
                if self.traffic_view.mode=='history':self.set_traffic_view('history')
                self.go_back()
            elif kind=='start_fresh':
                self.traffic_view.start_fresh(time.time());self.set_traffic_view('live');self.navigation=[];self.navigate('map',remember=False);self.coverage_view.wake.set()
            elif kind=='backdrop':self.traffic_view.backdrop=not self.traffic_view.backdrop
            elif kind=='history_trails':self.traffic_view.history_trails=not self.traffic_view.history_trails
            elif kind=='labels':
                if self.traffic_view.mode=='history':self.traffic_view.history_labels=not self.traffic_view.history_labels
                else:self.labels=not self.labels
            elif kind=='aircraft_icons':
                if self.traffic_view.mode=='history':self.traffic_view.history_icons=not self.traffic_view.history_icons
                else:self.aircraft_icons=not self.aircraft_icons
            elif kind=='rx_footprint':self.rx_footprint=not self.rx_footprint
            elif kind=='sort':
                sorts=('recent','altitude','callsign');self.traffic_sort=sorts[(sorts.index(self.traffic_sort)+1)%3]
            elif kind=='clear':self.selected=None;self.selected_plane=None;self.following=False
            elif kind=='locate':
                plane=self.selected_plane
                if plane and isinstance(plane.get('lat'),(int,float)) and isinstance(plane.get('lon'),(int,float)):
                    self.yaw,self.pitch=math.radians(plane['lon']),max(math.radians(-82),min(math.radians(82),math.radians(plane['lat'])))
                    self.centered=True;self.following=False
            elif kind in ('usb','logs','traffic'):
                if self.current_screen()==kind:self.go_back()
                else:self.navigate(kind)
            elif kind=='page':
                field='log_page' if self.logs_open else 'traffic_page' if self.traffic_open else 'usb_page'
                setattr(self,field,max(0,getattr(self,field)+value))
            elif kind=='log_kind': self.log_kind=value;self.log_page=0
            elif kind=='zoom': self.zoom(value)
            elif kind=='style': self.map_style={'both':'satellite','satellite':'borders','borders':'both'}[self.map_style]
            elif kind=='trails':
                self.trail_seconds=TRAIL_WINDOWS[(TRAIL_WINDOWS.index(self.trail_seconds)+1)%len(TRAIL_WINDOWS)]
                if self.dashboard:
                    self.traffic_view.trail_seconds=self.trail_seconds
                    if self.traffic_view.mode=='history':self.history_seconds=self.trail_seconds
            elif kind=='rings':
                if self.manager.snapshot().get('receiver_position'): self.rings=not self.rings
                else: self.message='Set antenna coordinates in RECEIVER / ANTENNA SITE.'
            elif kind=='follow':
                live=next((p for p in self.manager.snapshot()['aircraft'] if p.get('hex')==self.selected),None)
                if self.following: self.following=False
                elif self.positioned(live): self.following=True;self.locate(live)
                else: self.message='Select an aircraft with a fresh position to follow.'
            elif kind=='select':
                self.selected=value;self.following=False
                if self.traffic_open:self.navigation=[];self.navigate('map',remember=False)
                plane=next((p for p in self.display_aircraft(self.manager.snapshot()) if p.get('hex')==value),None)
                self.selected_plane=plane;self.locate(plane)
            elif kind=='fit':
                self.following=False;self.centered=False
                if self.dashboard:
                    state=self.manager.snapshot();targets=list(self.display_aircraft(state,True))
                    regions=self.footprint_regions(state);targets.extend(p for r in regions for p in r['vertices'])
                    if targets:self.fit_aircraft(targets,.28 if regions else .34)
            else:
                try:
                    self.manager.control(kind,value);self.message=''
                    if kind=='assign':self.go_back()
                except ValueError as exc: self.message=str(exc)
            return
        if on_card:return
        if self.coverage_open:self.coverage_view.tap(x,y);return
        if self.current_screen()=='map':
            if self.dashboard and any(self.ui.contains(box,x,y) for box in self.overlay_boxes):return
            if not self.ui.contains(self.MAP,x,y):return
            near=[(math.hypot(px-x,py-y),p['hex'],p) for px,py,p in self.points]
            if near and min(near,key=lambda v:v[0])[0]<=35:
                _,self.selected,self.selected_plane=min(near,key=lambda v:v[0]);self.following=False;self.message=''

    def panel(self, box):
        self.ui.draw_logical_rounded_rect(*box,self.RADIUS,self.PANEL,self.LINE,1)

    @staticmethod
    def value(value): return '—' if value is None else str(value)

    def fit_aircraft(self, planes, padding=.34):
        self.yaw=math.atan2(sum(math.sin(math.radians(p['lon'])) for p in planes),sum(math.cos(math.radians(p['lon'])) for p in planes))
        self.pitch=max(math.radians(-82),min(math.radians(82),sum(math.radians(p['lat']) for p in planes)/len(planes)))
        extent=max([.0004]+[max(abs(math.cos(math.radians(p['lat']))*math.sin(math.radians(p['lon'])-self.yaw)),abs(math.cos(self.pitch)*math.sin(math.radians(p['lat']))-math.sin(self.pitch)*math.cos(math.radians(p['lat']))*math.cos(math.radians(p['lon'])-self.yaw))) for p in planes])
        self.scale=max(MAP_ZOOM_MIN,min(1200,padding/(.92*extent)));self.centered=True

    def draw_map(self, cache, state, valid):
        ui=self.ui
        live=next((p for p in state['aircraft'] if p.get('hex')==self.selected),None)
        if live: self.selected_plane=live
        if time.monotonic()-self.track_time>=5:
            tracks=self.manager.track_snapshot()
            if isinstance(tracks,dict): self.tracks=tracks
            self.track_time=time.monotonic()
        if self.dashboard and not self.centered:
            targets=self.display_aircraft(state,True);regions=self.footprint_regions(state)
            if not targets:targets=[p for r in regions for p in r['vertices']]
            if targets:self.fit_aircraft(targets,.28 if regions else .34)
        if self.following and self.positioned(live): self.locate(live)
        elif valid and not self.centered:
            # Fit all current targets around a circular longitude mean.
            self.yaw=math.atan2(sum(math.sin(math.radians(p['lon'])) for p in valid),sum(math.cos(math.radians(p['lon'])) for p in valid))
            self.pitch=max(math.radians(-82),min(math.radians(82),sum(math.radians(p['lat']) for p in valid)/len(valid)))
            extent=max([.03]+[max(abs(math.cos(math.radians(p['lat']))*math.sin(math.radians(p['lon'])-self.yaw)),abs(math.cos(self.pitch)*math.sin(math.radians(p['lat']))-math.sin(self.pitch)*math.cos(math.radians(p['lat']))*math.cos(math.radians(p['lon'])-self.yaw))) for p in valid])
            self.scale=max(.55,min(15,.4/(.92*extent)));self.centered=True
        ui.draw_logical_rect(*self.MAP,(7,19,29,255))
        x0,y0,x1,y1=self.MAP
        corners=[ui.logical_to_native(x,y) for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
        left,right=int(min(p[0] for p in corners)),int(max(p[0] for p in corners))
        top,bottom=int(min(p[1] for p in corners)),int(max(p[1] for p in corners))
        def clip():
            ui.GL.glEnable(ui.GL.GL_SCISSOR_TEST);ui.GL.glScissor(left,ui.NATIVE_H-bottom,right-left,bottom-top)
        ui.GL.glPushAttrib(ui.GL.GL_SCISSOR_BIT|ui.GL.GL_ENABLE_BIT)
        try:
            clip()
            if self.map_style!='borders': ui.draw_receiver_map_satellite(cache,self.yaw,self.pitch,self.MAP,self.scale,interactive=self.dragged)
            clip()
            if self.map_style!='satellite': ui._globe_borders.draw(ui.globe_gpu_matrix(self.yaw,self.pitch,self.MAP,self.scale),(160,190,180,140))
            if self.dashboard:self.draw_footprint(state)
            if self.rings and state.get('receiver_position'): self.draw_rings(state['receiver_position'])
            now=time.time();view=self.traffic_view if self.dashboard else None
            labels_visible=view.labels_visible(self.labels) if view else self.labels
            icons_visible=view.icons_visible(self.aircraft_icons) if view else self.aircraft_icons
            cutoff=view.cutoff(now) if view else now-self.trail_seconds
            def draw_trace(trace,color,alpha,cutoff,until=None,selected=False):
                points=[];dots=[];last_dot=None;last_visible=None;previous_time=None
                for item in trace:
                    if item.get('time',0)<cutoff or (until is not None and item.get('time',0)>=until): continue
                    if previous_time is not None and item.get('time',0)-previous_time>120:
                        if len(points)>1:ui.draw_logical_polyline(points,(*color,alpha),1 if alpha<100 else 2)
                        points=[];last_dot=None
                    previous_time=item.get('time',0)
                    p=ui.radiogarden_project(item,self.yaw,self.pitch,self.MAP,self.scale)
                    # The map scissor clips segments crossing the viewport;
                    # their endpoints need not both be inside a close view.
                    if p:
                        point=p[:2];points.append(point)
                        if x0-3<=point[0]<=x1+3 and y0-3<=point[1]<=y1+3:
                            last_visible=point
                            if last_dot is None or math.hypot(point[0]-last_dot[0],point[1]-last_dot[1])>=6:
                                dots.append(point);last_dot=point
                    elif points:
                        if len(points)>1: ui.draw_logical_polyline(points,(*color,alpha),1 if alpha<100 else 2)
                        points=[];last_dot=None
                if len(points)>1: ui.draw_logical_polyline(points,(*color,alpha),1 if alpha<100 else 2)
                if last_visible is not None and (not dots or last_visible!=dots[-1]):dots.append(last_visible)
                if dots:ui.draw_logical_points(dots,(*color,70 if alpha<100 else 240 if selected else 220),2.4 if alpha<100 else 6 if selected else 4)
            if view and view.backdrop and view.mode!='history':
                for trace in self.tracks.values():draw_trace(trace,self.MUTED,45,now-TRAIL_RETENTION,cutoff if view.mode=='session' else None)
            if self.trail_seconds or (view and view.mode=='session'):
                for key,trace in self.tracks.items():
                    if view and not view.trail_visible(key,state['aircraft'],now,trace):continue
                    draw_trace(trace,self.GOLD if key==self.selected else self.CYAN,150,cutoff,selected=key==self.selected)
            self.points=[]
            historical=([p for p in self.display_aircraft(state,True) if p.get('historical')] if view else historical_aircraft(self.tracks,valid,self.trail_seconds,now)) if 'empty_title' not in state else []
            selected_history=next((p for p in historical if p['hex']==self.selected),None)
            if selected_history:self.selected_plane=selected_history
            label_boxes=[]
            for plane in sorted(valid+historical,key=lambda p:p['hex']!=self.selected):
                if not icons_visible and not labels_visible:continue
                point=ui.radiogarden_project(plane,self.yaw,self.pitch,self.MAP,self.scale)
                if not point or not ui.contains(self.MAP,*point[:2]): continue
                x,y=point[:2];self.points.append((x,y,plane))
                color=self.GOLD if plane['hex']==self.selected else self.MUTED if plane.get('historical') else (120,184,255) if isinstance(plane.get('alt_baro'),(int,float)) and plane['alt_baro']>20000 else self.CYAN
                if view and not plane.get('historical') and plane['hex']!=self.selected:
                    color=tuple(int(c*max(.25,1-plane.get('seen_pos',0)/20)) for c in color)
                angle=math.radians(plane.get('track') or 0)
                if icons_visible and view and view.arrival(plane['hex'],now):
                    ui.draw_logical_polyline([(x+20*math.cos(a*math.pi/18),y+20*math.sin(a*math.pi/18)) for a in range(37)],(*self.CYAN,180),2)
                def vertex(dx,dy): return x+dx*math.cos(angle)-dy*math.sin(angle),y+dx*math.sin(angle)+dy*math.cos(angle)
                if not icons_visible:pass
                elif plane.get('kind')=='ship':
                    ui.draw_logical_polyline([vertex(0,-12),vertex(6,-3),vertex(6,9),vertex(-6,9),vertex(-6,-3),vertex(0,-12)],(*color,255),2)
                elif plane.get('kind') in ('station','balloon'):
                    ui.draw_logical_polyline([vertex(0,-8),vertex(7,0),vertex(0,8),vertex(-7,0),vertex(0,-8)],(*color,255),2)
                else:
                    ui.draw_logical_polyline([vertex(0,-11),vertex(0,10)],(*color,255),3)
                    ui.draw_logical_polyline([vertex(-10,3),vertex(0,-4),vertex(10,3)],(*color,255),2)
                    ui.draw_logical_polyline([vertex(-5,9),vertex(0,6),vertex(5,9)],(*color,255),2)
                label=(plane.get('flight') or plane['hex']).strip()+(' · UAT' if plane.get('band')=='978' else '')
                if plane.get('historical'):label+=' · '+position_age(plane['seen_pos'])
                label_box=(x+14,y-22,x+14+len(label)*7.3,y-2)
                overlaps=any(label_box[0]<box[2] and label_box[2]>box[0] and label_box[1]<box[3] and label_box[3]>box[1] for box in label_boxes)
                if (labels_visible or icons_visible and plane['hex']==self.selected) and not overlaps and x<self.MAP[2]-154 and y>self.MAP[1]+22:
                    self.text(cache,x+14,y-10,label,14,color);label_boxes.append(label_box)
        finally: ui.GL.glPopAttrib()
        if self.dashboard:self.draw_map_hud(cache,state,valid)
        else:
            self.panel((16,96,448,128))
            self.text(cache,28,112,'NORTH UP · GLOBE · '+{'both':'SAT + BORDERS','satellite':'SATELLITE','borders':'BORDERS'}[self.map_style]+f' · {self.scale:g}×',12,self.MUTED)
        if not valid and not (self.dashboard and self.traffic_view.mode=='history') and ('empty_title' in state or (not self.dashboard and not state['enabled']) or startup_notice_visible(state,time.time())):
            self.panel((264,350,760,444));self.text(cache,288,380,state.get('empty_title', 'LISTENING FOR AIRCRAFT' if state['enabled'] else 'RECEIVER STOPPED'),23)
            self.text(cache,288,416,state.get('empty_detail','Waiting for fresh position messages.'),17,self.MUTED)
        if self.following and not self.dashboard:
            self.panel((260,652,764,696));label='FOLLOWING' if self.positioned(live) else 'WAITING FOR SIGNAL'
            self.text(cache,278,674,label+' · '+str((self.selected_plane or {}).get('flight') or self.selected).strip(),18,self.GOLD)

    def footprint_regions(self,state):
        if not self.dashboard or not self.rx_footprint:return []
        coverage=getattr(self.manager,'coverage',None)
        data=coverage.maximum_snapshot() if coverage is not None else None
        if not isinstance(data,dict):return []
        footprint=data.get('footprint') or {};site=state.get('receiver_position')
        if not isinstance(footprint,dict) or not site or distance_m(footprint.get('site'),site)>100:return []
        return footprint.get('regions',[])

    def draw_footprint(self,state):
        regions=self.footprint_regions(state)
        if not regions:return
        key=(self.yaw,self.pitch,self.scale,self.MAP)
        if regions is not self.rx_regions or key!=self.rx_key:
            self.rx_frame=projected_frame(regions,lambda p:self.ui.radiogarden_project(p,self.yaw,self.pitch,self.MAP,self.scale));self.rx_key=key;self.rx_regions=regions
        draw_footprint_mesh(self.ui,self.rx_frame,(0,0,1280,800))

    def draw_rings(self, site):
        ui=self.ui;lat,lon=math.radians(site['lat']),math.radians(site['lon'])
        for distance in (50,100,200):
            angular=distance/3440.065;points=[]
            for degree in range(0,361,3):
                bearing=math.radians(degree)
                la=math.asin(math.sin(lat)*math.cos(angular)+math.cos(lat)*math.sin(angular)*math.cos(bearing))
                lo=lon+math.atan2(math.sin(bearing)*math.sin(angular)*math.cos(lat),math.cos(angular)-math.sin(lat)*math.sin(la))
                point=ui.radiogarden_project(dict(lat=math.degrees(la),lon=math.degrees(lo)),self.yaw,self.pitch,self.MAP,self.scale)
                if point and ui.contains(self.MAP,*point[:2]): points.append(point[:2])
                else:
                    if len(points)>1: ui.draw_logical_polyline(points,(125,166,185,115),1)
                    points=[]
            if len(points)>1: ui.draw_logical_polyline(points,(125,166,185,115),1)

    def draw_logs(self, cache):
        self.panel((24,150,1256,700));self.ink(cache,40,182,'RECEPTION LOGS',24)
        for index,(kind,label) in enumerate((('flights','FLIGHTS'),('receiver','RECEIVER'),('diagnostics','1090 DIAGNOSTICS'),('uat_diagnostics','UAT DIAGNOSTICS'))):
            self.button(cache,(40+index*300,212,324+index*300,268),label,('log_kind',kind),active=kind==self.log_kind)
        data=self.manager.log_snapshot(self.log_kind)
        source=list(reversed(data.get('lines',[]))) if not self.log_kind.endswith('diagnostics') else data.get('lines',[])
        lines=[part for line in source for part in (textwrap.wrap(line,128) or [''])]
        count=max(1,(len(lines)+11)//12);self.log_page=min(self.log_page,count-1)
        if not lines:self.text(cache,40,324,'No entries yet. Receiver and Diagnostics show radio activity.',20,self.MUTED,width=1200)
        for i,line in enumerate(lines[self.log_page*12:(self.log_page+1)*12]):self.text(cache,40,288+i*30,line,17,width=1200)
        self.button(cache,(40,636,344,692),'PREVIOUS',('page',-1))
        self.ink(cache,640,664,f'PAGE {self.log_page+1} / {count} · UTC',16,self.MUTED,anchor='cm')
        self.button(cache,(936,636,1240,692),'NEXT',('page',1))

    def draw_traffic(self, cache, state):
        self.panel((24,150,1256,700));self.ink(cache,40,184,self.traffic_view.label+' AIRCRAFT',24)
        self.button(cache,(936,162,1240,218),{'recent':'LATEST RECEIVED','altitude':'HIGHEST ALTITUDE','callsign':'CALLSIGN A–Z'}[self.traffic_sort],('sort',None))
        planes=self.sorted_aircraft(state);self.traffic_page=min(self.traffic_page,max(0,(len(planes)-1)//5))
        if not planes:self.text(cache,40,324,'No contacts in this viewing window. Saved observations remain in History.',20,self.MUTED,width=1200)
        for i,plane in enumerate(planes[self.traffic_page*5:self.traffic_page*5+5]):
            title=f"{(plane.get('flight') or plane['hex']).strip()} · ICAO {plane['hex'].upper()}"
            if self.traffic_view.arrival(plane['hex'],time.time()):title+=' · NEW'
            self.button(cache,(40,234+i*80,1240,306+i*80),title,('select',plane['hex']),freshness(plane),active=plane['hex']==self.selected)
        self.button(cache,(40,636,344,692),'PREVIOUS',('page',-1));self.button(cache,(936,636,1240,692),'NEXT',('page',1))
        self.ink(cache,640,664,f'PAGE {self.traffic_page+1} / {max(1,(len(planes)+4)//5)}',16,self.MUTED,anchor='cm')

    def draw_usb(self, cache, state):
        self.panel((24,150,1256,704))
        bands=state.get('bands') or [dict(id='1090',name='1090 ES',**{k:state.get(k) for k in ('enabled','status','selection','assigned')})]
        band=next((b for b in bands if b['id']==self.usb_band),bands[0])
        for i,b in enumerate(bands):
            self.button(cache,(40+i*608,164,632+i*608,220),b['name'],('usb_band',b['id']),active=b['id']==self.usb_band)
        self.ink(cache,40,244,band['status']+' · '+str(band.get('messages',0))+' packets',20,self.CYAN,width=1200)
        self.button(cache,(40,266,960,322),'AUTO · '+('SPARE DONGLE' if self.usb_band=='978' else 'FIRST AVAILABLE DONGLE'),('band_assign','auto'),active=band.get('selection','auto')=='auto')
        self.button(cache,(976,266,1240,322),'STOP' if band['enabled'] else 'START',('band_control','stop' if band['enabled'] else 'start'),enabled=band['enabled'] or band.get('installed',True))
        blocked={b['assigned']['id'] for b in bands if b['id']!=self.usb_band and b.get('assigned')}
        self.usb_page,last=receiver_rows(self,cache,state['devices'],state.get('leases',{}),'uat' if self.usb_band=='978' else 'adsb',band.get('selection','auto'),self.usb_page,action='band_assign',unique=self.usb_band=='978',blocked=blocked,top=338,include_auto=False,left=40,right=1240,page_size=3,row_height=60,row_gap=8)
        if not state['devices']:self.text(cache,40,374,'No USB radio connected. Plug in a receiver to begin.',20,self.MUTED,width=1200)
        self.text(cache,40,558,band.get('detail',''),18,self.MUTED,width=1200)
        site=state.get('receiver_position');location=f"RX SITE {site['lat']:.5f}°, {site['lon']:.5f}°" if site else 'RX SITE NOT SET'
        self.ink(cache,40,600,location,16,self.MUTED,width=900)
        self.button(cache,(976,574,1240,630),'ANTENNA SITE',('site',None))
        self.text(cache,40,622,'Edit shared location and GPS under Settings / Radio information.',16,self.MUTED,width=900)
        self.button(cache,(40,636,420,692),'DONGLES / RENAME',('dongles',None));self.button(cache,(436,636,824,692),'PREVIOUS',('page',-1));self.button(cache,(840,636,1240,692),'NEXT',('page',1))

    def close(self): self.manager.close()
