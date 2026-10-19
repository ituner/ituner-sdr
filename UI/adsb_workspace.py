"""ADS-B traffic instruments, shared GLOBE map, receiver controls and visible logs."""
import math
import textwrap
import time
from decoder_style import DecoderStyle
from sstv_workspace import SSTVWorkspace
from adsb_touch import AirspaceDashboard
from adsb_coverage_touch import CoverageTouch
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
        self.usb_open = False
        self.usb_page = 0
        self.traffic_open = False
        self.traffic_page = 0
        self.logs_open = False
        self.log_kind = 'flights'
        self.log_page = 0
        self.map_style = 'both'
        self.trail_seconds = 300
        self.traffic_view = TrafficView(time.time())
        self.history_seconds = TRAIL_RETENTION
        self.rings = False
        self.labels = True
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
            self.selected=self.selected_plane=None;self.following=False
        self.open = True

    def set_traffic_view(self, mode):
        self.traffic_view.mode=mode
        self.traffic_view.trail_seconds=self.history_seconds if mode=='history' else 300
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
        if self.coverage_open:self.coverage_view.drag_begin(x,y)
        self.drag_origin = self.yaw, self.pitch
        self.dragged = False

    def drag_move(self, sx, sy, x, y):
        if self.coverage_open:
            self.coverage_view.drag_move(sx,sy,x,y);return
        if self.usb_open or self.logs_open or self.traffic_open or not self.ui.contains(self.MAP, sx, sy): return
        if self.dashboard and any(self.ui.contains(box,sx,sy) for box in self.overlay_boxes):return
        if self.dashboard and any(self.ui.contains(box,sx,sy) for box,_ in self.actions):return
        if abs(x-sx)+abs(y-sy)<10: return
        self.dragged, self.following = True, False
        self.yaw, self.pitch = self.ui.radiogarden_pan_angles(*self.drag_origin,x-sx,y-sy,self.MAP,self.scale)

    def swipe(self, sx=None, sy=None, x=None, y=None):
        if sy is not None and y is not None and abs(y-sy)>60 and abs(y-sy)>abs(x-sx)*1.5:
            delta = 1 if y<sy else -1
            if self.logs_open: self.log_page=max(0,self.log_page+delta);return True
            if self.traffic_open: self.traffic_page=max(0,self.traffic_page+delta);return True
        dragged, self.dragged = self.dragged, False
        return dragged

    def tap(self, x, y, *args):
        for box,(kind,value) in self.actions:
            if not self.ui.contains(box,x,y): continue
            if kind.startswith('coverage_'):self.coverage_view.action(kind,value)
            elif kind=='coverage':
                self.coverage_open=True;self.usb_open=self.logs_open=self.traffic_open=False;self.coverage_view.activate()
            elif kind=='home': self.open=False
            elif kind=='back':
                self.coverage_open=self.logs_open=self.traffic_open=self.usb_open=False
                self.open=False
            elif kind=='map_view':self.coverage_open=self.usb_open=self.logs_open=self.traffic_open=False
            elif kind=='traffic_view':self.set_traffic_view(value)
            elif kind=='start_fresh':
                self.traffic_view.reset(time.time());self.traffic_view.ingest(self.manager.snapshot()['aircraft'],time.time());self.set_traffic_view('session')
            elif kind=='backdrop':self.traffic_view.backdrop=not self.traffic_view.backdrop
            elif kind=='labels':self.labels=not self.labels
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
                self.coverage_open=False
                showing = getattr(self,kind+'_open')
                self.usb_open=self.logs_open=self.traffic_open=False
                setattr(self,kind+'_open',not showing)
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
                else: self.message='Set receiver latitude/longitude in the browser Receiver panel.'
            elif kind=='follow':
                live=next((p for p in self.manager.snapshot()['aircraft'] if p.get('hex')==self.selected),None)
                if self.following: self.following=False
                elif self.positioned(live): self.following=True;self.locate(live)
                else: self.message='Select an aircraft with a fresh position to follow.'
            elif kind=='select':
                self.selected=value;self.following=False;self.traffic_open=False
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
                    if kind=='assign': self.usb_open=False
                except ValueError as exc: self.message=str(exc)
            return
        if self.coverage_open:self.coverage_view.tap(x,y);return
        if not (self.usb_open or self.logs_open or self.traffic_open):
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
            cutoff=view.cutoff(now) if view else now-self.trail_seconds
            def draw_trace(trace,color,alpha,cutoff,until=None):
                points=[];previous_time=None
                for item in trace:
                    if item.get('time',0)<cutoff or (until is not None and item.get('time',0)>=until): continue
                    if previous_time is not None and item.get('time',0)-previous_time>120:
                        if len(points)>1:ui.draw_logical_polyline(points,(*color,alpha),1 if alpha<100 else 2)
                        points=[]
                    previous_time=item.get('time',0)
                    p=ui.radiogarden_project(item,self.yaw,self.pitch,self.MAP,self.scale)
                    # The map scissor clips segments crossing the viewport;
                    # their endpoints need not both be inside a close view.
                    if p: points.append(p[:2])
                    elif points:
                        if len(points)>1: ui.draw_logical_polyline(points,(*color,alpha),1 if alpha<100 else 2)
                        points=[]
                if len(points)>1: ui.draw_logical_polyline(points,(*color,alpha),1 if alpha<100 else 2)
            if view and view.backdrop and view.mode!='history':
                for trace in self.tracks.values():draw_trace(trace,self.MUTED,45,now-TRAIL_RETENTION,cutoff if view.mode=='session' else None)
            if self.trail_seconds or (view and view.mode=='session'):
                for key,trace in self.tracks.items():
                    if view and not view.trail_visible(key,state['aircraft'],now):continue
                    draw_trace(trace,self.GOLD if key==self.selected else self.CYAN,150,cutoff)
            self.points=[]
            historical=([p for p in self.display_aircraft(state,True) if p.get('historical')] if view else historical_aircraft(self.tracks,valid,self.trail_seconds,now)) if 'empty_title' not in state else []
            selected_history=next((p for p in historical if p['hex']==self.selected),None)
            if selected_history:self.selected_plane=selected_history
            label_boxes=[]
            for plane in sorted(valid+historical,key=lambda p:p['hex']!=self.selected):
                point=ui.radiogarden_project(plane,self.yaw,self.pitch,self.MAP,self.scale)
                if not point or not ui.contains(self.MAP,*point[:2]): continue
                x,y=point[:2];self.points.append((x,y,plane))
                color=self.GOLD if plane['hex']==self.selected else self.MUTED if plane.get('historical') else (120,184,255) if isinstance(plane.get('alt_baro'),(int,float)) and plane['alt_baro']>20000 else self.CYAN
                if view and not plane.get('historical') and plane['hex']!=self.selected:
                    color=tuple(int(c*max(.25,1-plane.get('seen_pos',0)/20)) for c in color)
                angle=math.radians(plane.get('track') or 0)
                if view and view.arrival(plane['hex'],now):
                    ui.draw_logical_polyline([(x+20*math.cos(a*math.pi/18),y+20*math.sin(a*math.pi/18)) for a in range(37)],(*self.CYAN,180),2)
                def vertex(dx,dy): return x+dx*math.cos(angle)-dy*math.sin(angle),y+dx*math.sin(angle)+dy*math.cos(angle)
                if plane.get('kind')=='ship':
                    ui.draw_logical_polyline([vertex(0,-12),vertex(6,-3),vertex(6,9),vertex(-6,9),vertex(-6,-3),vertex(0,-12)],(*color,255),2)
                elif plane.get('kind') in ('station','balloon'):
                    ui.draw_logical_polyline([vertex(0,-8),vertex(7,0),vertex(0,8),vertex(-7,0),vertex(0,-8)],(*color,255),2)
                else:
                    ui.draw_logical_polyline([vertex(0,-11),vertex(0,10)],(*color,255),3)
                    ui.draw_logical_polyline([vertex(-10,3),vertex(0,-4),vertex(10,3)],(*color,255),2)
                    ui.draw_logical_polyline([vertex(-5,9),vertex(0,6),vertex(5,9)],(*color,255),2)
                label=(plane.get('flight') or plane['hex']).strip()
                if plane.get('historical'):label+=' · '+position_age(plane['seen_pos'])
                label_box=(x+14,y-22,x+14+len(label)*7.3,y-2)
                overlaps=any(label_box[0]<box[2] and label_box[2]>box[0] and label_box[1]<box[3] and label_box[3]>box[1] for box in label_boxes)
                if (self.labels or plane['hex']==self.selected) and not overlaps and x<self.MAP[2]-154 and y>self.MAP[1]+22:
                    self.text(cache,x+14,y-10,label,14,color);label_boxes.append(label_box)
        finally: ui.GL.glPopAttrib()
        if self.dashboard:self.draw_map_hud(cache,state,valid)
        else:
            self.panel((16,96,448,128))
            self.text(cache,28,112,'NORTH UP · GLOBE · '+{'both':'SAT + BORDERS','satellite':'SATELLITE','borders':'BORDERS'}[self.map_style]+f' · {self.scale:g}×',12,self.MUTED)
        if not valid and ('empty_title' in state or not state['enabled'] or startup_notice_visible(state,time.time())):
            self.panel((264,350,760,444));self.text(cache,288,380,state.get('empty_title', 'LISTENING FOR AIRCRAFT' if state['enabled'] else 'RECEIVER STOPPED'),23)
            self.text(cache,288,416,state.get('empty_detail','Waiting for fresh position messages.'),17,self.MUTED)
        if self.following and not self.dashboard:
            self.panel((260,652,764,696));label='FOLLOWING' if self.positioned(live) else 'WAITING FOR SIGNAL'
            self.text(cache,278,674,label+' · '+str((self.selected_plane or {}).get('flight') or self.selected).strip(),18,self.GOLD)

    def footprint_regions(self,state):
        if not self.dashboard or not self.rx_footprint:return []
        coverage=getattr(self.manager,'coverage',None)
        data=coverage.snapshot() if coverage is not None else None
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
        self.panel((16,158,1008,712))
        for index,(kind,label) in enumerate((('flights','FLIGHTS'),('receiver','RECEIVER'),('diagnostics','DIAGNOSTICS'))):
            self.button(cache,(32+index*294,176,310+index*294,226),label,('log_kind',kind),active=kind==self.log_kind)
        data=self.manager.log_snapshot(self.log_kind)
        source=list(reversed(data.get('lines',[]))) if self.log_kind!='diagnostics' else data.get('lines',[])
        lines=[part for line in source for part in (textwrap.wrap(line,100) or [''])]
        count=max(1,(len(lines)+15)//16);self.log_page=min(self.log_page,count-1)
        if not lines:self.text(cache,34,286,'No entries yet. Receiver and Diagnostics show radio activity.',18,self.MUTED,width=940)
        for i,line in enumerate(lines[self.log_page*16:(self.log_page+1)*16]):self.text(cache,34,256+i*24,line,14,width=940)
        self.button(cache,(32,656,250,712),'PREVIOUS',('page',-1))
        self.ink(cache,472,684,f'PAGE {self.log_page+1} / {count} · UTC',14,self.MUTED,anchor='cm')
        self.button(cache,(694,656,992,712),'NEXT',('page',1))

    def draw_traffic(self, cache, state):
        self.panel((16,224,1008,712));self.ink(cache,34,253,self.traffic_view.label+' TRAFFIC',22)
        self.button(cache,(670,232,910,276),{'recent':'LATEST RECEIVED','altitude':'HIGHEST ALTITUDE','callsign':'CALLSIGN A–Z'}[self.traffic_sort],('sort',None))
        planes=self.sorted_aircraft(state)
        self.traffic_page=min(self.traffic_page,max(0,(len(planes)-1)//5))
        if not planes:self.text(cache,34,320,'No contacts in this viewing window. Saved observations remain in History.',18,self.MUTED,width=940)
        for i,plane in enumerate(planes[self.traffic_page*5:self.traffic_page*5+5]):
            title=f"{(plane.get('flight') or plane['hex']).strip()} · ICAO {plane['hex'].upper()}"
            detail=freshness(plane)
            if self.traffic_view.arrival(plane['hex'],time.time()):title+=' · NEW'
            self.button(cache,(32,284+i*72,992,348+i*72),title,('select',plane['hex']),detail,active=plane['hex']==self.selected)
        self.button(cache,(32,656,250,712),'PREVIOUS',('page',-1));self.button(cache,(694,656,992,712),'NEXT',('page',1))
        self.ink(cache,472,684,f'PAGE {self.traffic_page+1} / {max(1,(len(planes)+4)//5)}',14,self.MUTED,anchor='cm')

    def draw_usb(self, cache, state):
        self.panel((16,158,1008,712));self.ink(cache,34,191,'1090 ES · RECEIVER ASSIGNMENT',23)
        self.text(cache,34,224,'978 UAT · future second receiver · not installed',15,self.MUTED)
        self.button(cache,(32,246,992,302),'AUTO · FIRST AVAILABLE DONGLE',('assign','auto'),active=state['selection']=='auto')
        devices=state['devices'];self.usb_page=min(self.usb_page,max(0,(len(devices)-1)//4))
        for i,device in enumerate(devices[self.usb_page*4:self.usb_page*4+4]):self.button(cache,(32,316+i*68,992,374+i*68),device['label'],('assign',device['id']),active=state['selection']==device['id'])
        if not devices:self.text(cache,34,358,'No RTL-SDR detected. Check USB power and connection.',18,self.MUTED,width=930)
        site=state.get('receiver_position');location=f"RX SITE {site['lat']:.5f}°, {site['lon']:.5f}°" if site else 'RX SITE NOT SET · CONFIGURE IN BROWSER / RECEIVER'
        self.ink(cache,34,622,location,14,self.MUTED,width=930)
        self.text(cache,34,640,'Receiver settings and logs are shared with cm5.local:8090',14,self.MUTED,width=930)
        self.button(cache,(32,656,306,712),'SCAN USB',('scan',None));self.button(cache,(322,656,604,712),'PREVIOUS',('page',-1));self.button(cache,(620,656,992,712),'NEXT',('page',1))

    def close(self): self.manager.close()
