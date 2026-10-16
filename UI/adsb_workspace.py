"""ADS-B traffic instruments, shared GLOBE map, receiver controls and visible logs."""
import math
import textwrap
import time
from sstv_workspace import SSTVWorkspace
from adsb_traffic import TRAIL_RETENTION, TRAIL_WINDOWS, MAP_ZOOM_MIN, MAP_ZOOM_MAX, trail_label, startup_notice_visible, reception_summary, historical_aircraft, position_age


class ADSBWorkspace(SSTVWorkspace):
    MAP = (0, 82, 1024, 716)
    BG = (8, 16, 24, 255)
    PANEL = (14, 30, 42, 255)
    MUTED = (147, 175, 192)
    CYAN = (101, 227, 210)
    GOLD = (255, 200, 116)

    def __init__(self, ui, manager):
        super().__init__(ui, manager)
        self.yaw, self.pitch, self.scale = math.radians(25), math.radians(45), 5.0
        self.centered = False
        self.selected = None
        self.selected_plane = None
        self.following = False
        self.usb_open = False
        self.usb_page = 0
        self.traffic_open = False
        self.traffic_page = 0
        self.logs_open = False
        self.log_kind = 'flights'
        self.log_page = 0
        self.map_style = 'both'
        self.trail_seconds = TRAIL_RETENTION
        self.rings = False
        self.points = []
        self.tracks = {}
        self.track_time = -float('inf')
        self.drag_origin = None
        self.dragged = False
        self.last_count = None
        self.last_rate_time = 0
        self.rate = 0

    def show(self, *args): self.open = True

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
        self.drag_origin = self.yaw, self.pitch
        self.dragged = False

    def drag_move(self, sx, sy, x, y):
        if self.usb_open or self.logs_open or self.traffic_open or not self.ui.contains(self.MAP, sx, sy): return
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
            if kind=='home': self.open=False
            elif kind=='back':
                if self.logs_open or self.traffic_open or self.usb_open: self.logs_open=self.traffic_open=self.usb_open=False
                else: self.open=False
            elif kind in ('usb','logs','traffic'):
                showing = getattr(self,kind+'_open')
                self.usb_open=self.logs_open=self.traffic_open=False
                setattr(self,kind+'_open',not showing)
            elif kind=='page':
                field='log_page' if self.logs_open else 'traffic_page' if self.traffic_open else 'usb_page'
                setattr(self,field,max(0,getattr(self,field)+value))
            elif kind=='log_kind': self.log_kind=value;self.log_page=0
            elif kind=='zoom': self.zoom(value)
            elif kind=='style': self.map_style={'both':'satellite','satellite':'borders','borders':'both'}[self.map_style]
            elif kind=='trails': self.trail_seconds=TRAIL_WINDOWS[(TRAIL_WINDOWS.index(self.trail_seconds)+1)%len(TRAIL_WINDOWS)]
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
                plane=next((p for p in self.manager.snapshot()['aircraft'] if p.get('hex')==value),None)
                self.selected_plane=plane;self.locate(plane)
            elif kind=='fit': self.following=False;self.centered=False
            else:
                try:
                    self.manager.control(kind,value);self.message=''
                    if kind=='assign': self.usb_open=False
                except ValueError as exc: self.message=str(exc)
            return
        if not (self.usb_open or self.logs_open or self.traffic_open):
            near=[(math.hypot(px-x,py-y),p['hex'],p) for px,py,p in self.points]
            if near and min(near,key=lambda v:v[0])[0]<=35:
                _,self.selected,self.selected_plane=min(near,key=lambda v:v[0]);self.following=False;self.message=''

    def panel(self, box):
        self.ui.draw_logical_rounded_rect(*box,7,self.PANEL,(48,77,96,255),1)

    @staticmethod
    def value(value): return '—' if value is None else str(value)

    def header(self, cache, state, valid):
        self.ui.draw_logical_rect(0,0,1024,82,self.PANEL)
        self.ui.draw_text(cache,18,31,'AIRSPACE',(222,237,246),27,True,False,'lm',family='Oxanium')
        self.text(cache,20,62,'ADS-B / 1090 ES',13,self.MUTED)
        if self.last_count is None or state['messages']<self.last_count:
            self.last_count,self.last_rate_time=state['messages'],time.monotonic()
        if time.monotonic()-self.last_rate_time>=2:
            self.rate=(state['messages']-self.last_count)/(time.monotonic()-self.last_rate_time)
            self.last_count,self.last_rate_time=state['messages'],time.monotonic()
        for x,label,value in ((310,'ON MAP',len(valid)),(470,'TRACKED',len(state['aircraft'])),(640,'MSG / SEC',f'{self.rate:.1f}'),(820,'MESSAGES',state['messages'])):
            self.text(cache,x,20,label,11,self.MUTED)
            self.ui.draw_text(cache,x,53,str(value),(217,239,250),27,False,False,'lm',family='Oxanium')

    def draw_map(self, cache, state, valid):
        ui=self.ui
        live=next((p for p in state['aircraft'] if p.get('hex')==self.selected),None)
        if live: self.selected_plane=live
        if self.following and self.positioned(live): self.locate(live)
        elif valid and not self.centered:
            # Fit all current targets around a circular longitude mean.
            self.yaw=math.atan2(sum(math.sin(math.radians(p['lon'])) for p in valid),sum(math.cos(math.radians(p['lon'])) for p in valid))
            self.pitch=max(math.radians(-82),min(math.radians(82),sum(math.radians(p['lat']) for p in valid)/len(valid)))
            extent=max([.03]+[max(abs(math.cos(math.radians(p['lat']))*math.sin(math.radians(p['lon'])-self.yaw)),abs(math.cos(self.pitch)*math.sin(math.radians(p['lat']))-math.sin(self.pitch)*math.cos(math.radians(p['lat']))*math.cos(math.radians(p['lon'])-self.yaw))) for p in valid])
            self.scale=max(.55,min(15,.4/(.92*extent)));self.centered=True
        if time.monotonic()-self.track_time>=5:
            tracks=self.manager.track_snapshot()
            if isinstance(tracks,dict): self.tracks=tracks
            self.track_time=time.monotonic()
        ui.draw_logical_rect(*self.MAP,(7,19,29,255))
        corners=[ui.logical_to_native(x,y) for x,y in ((0,82),(1024,82),(1024,716),(0,716))]
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
            if self.rings and state.get('receiver_position'): self.draw_rings(state['receiver_position'])
            cutoff=time.time()-self.trail_seconds
            if self.trail_seconds:
                for key,trace in self.tracks.items():
                    points=[];previous_time=None
                    color=self.GOLD if key==self.selected else self.CYAN
                    for item in trace:
                        if item.get('time',0)<cutoff: continue
                        if previous_time is not None and item.get('time',0)-previous_time>120:
                            if len(points)>1:ui.draw_logical_polyline(points,(*color,150),2)
                            points=[]
                        previous_time=item.get('time',0)
                        p=ui.radiogarden_project(item,self.yaw,self.pitch,self.MAP,self.scale)
                        # The map scissor clips segments crossing the viewport;
                        # their endpoints need not both be inside a close view.
                        if p: points.append(p[:2])
                        elif points:
                            if len(points)>1: ui.draw_logical_polyline(points,(*color,150),2)
                            points=[]
                    if len(points)>1: ui.draw_logical_polyline(points,(*color,150),2)
            self.points=[]
            historical=historical_aircraft(self.tracks,valid,self.trail_seconds,time.time()) if 'empty_title' not in state else []
            selected_history=next((p for p in historical if p['hex']==self.selected),None)
            if selected_history:self.selected_plane=selected_history
            for plane in valid+historical:
                point=ui.radiogarden_project(plane,self.yaw,self.pitch,self.MAP,self.scale)
                if not point or not ui.contains(self.MAP,*point[:2]): continue
                x,y=point[:2];self.points.append((x,y,plane))
                color=self.GOLD if plane['hex']==self.selected else self.MUTED if plane.get('historical') else (120,184,255) if isinstance(plane.get('alt_baro'),(int,float)) and plane['alt_baro']>20000 else self.CYAN
                angle=math.radians(plane.get('track') or 0)
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
                if x<870 and y>105: self.text(cache,x+14,y-10,label,14,color)
        finally: ui.GL.glPopAttrib()
        self.panel((16,96,448,128));self.text(cache,28,112,'NORTH UP · GLOBE · '+{'both':'SAT + BORDERS','satellite':'SATELLITE','borders':'BORDERS'}[self.map_style]+f' · {self.scale:g}×',12,self.MUTED)
        if not valid and ('empty_title' in state or not state['enabled'] or startup_notice_visible(state,time.time())):
            self.panel((264,350,760,444));self.text(cache,288,380,state.get('empty_title', 'LISTENING FOR AIRCRAFT' if state['enabled'] else 'RECEIVER STOPPED'),23)
            self.text(cache,288,416,state.get('empty_detail','Waiting for fresh position messages.'),17,self.MUTED)
        if self.following:
            self.panel((260,652,764,696));label='FOLLOWING' if self.positioned(live) else 'WAITING FOR SIGNAL'
            self.text(cache,278,674,label+' · '+str((self.selected_plane or {}).get('flight') or self.selected).strip(),18,self.GOLD)

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
        self.panel((12,90,1012,706))
        for index,(kind,label) in enumerate((('flights','FLIGHTS'),('receiver','RECEIVER'),('diagnostics','DIAGNOSTICS'))):
            self.button(cache,(28+index*324,106,336+index*324,160),label,('log_kind',kind),active=kind==self.log_kind)
        data=self.manager.log_snapshot(self.log_kind)
        source=list(reversed(data.get('lines',[]))) if self.log_kind!='diagnostics' else data.get('lines',[])
        lines=[part for line in source for part in (textwrap.wrap(line,110) or [''])]
        count=max(1,(len(lines)+16)//17);self.log_page=min(self.log_page,count-1)
        if not lines: self.text(cache,32,210,'No entries yet. Receiver and Diagnostics show radio activity.',19,self.MUTED)
        for i,line in enumerate(lines[self.log_page*17:(self.log_page+1)*17]): self.text(cache,30,192+i*24,line,14,width=950)
        self.button(cache,(28,632,268,688),'PREVIOUS',('page',-1))
        self.text(cache,300,658,f'PAGE {self.log_page+1} / {count} · UTC',16,self.MUTED)
        self.button(cache,(744,632,984,688),'NEXT',('page',1))

    def draw_traffic(self, cache, state):
        self.panel((12,90,1012,706));self.text(cache,30,118,'LIVE TRAFFIC · SELECT AN AIRCRAFT',22)
        planes=sorted(state['aircraft'],key=lambda p:p.get('seen',100))
        self.traffic_page=min(self.traffic_page,max(0,(len(planes)-1)//6))
        if not planes: self.text(cache,30,185,'No aircraft currently tracked. View Flights for saved observations.',18,self.MUTED)
        for i,plane in enumerate(planes[self.traffic_page*6:self.traffic_page*6+6]):
            title=f"{(plane.get('flight') or plane['hex']).strip()} · ICAO {plane['hex'].upper()}"
            detail=f"{self.value(plane.get('alt_baro'))} FT · {self.value(plane.get('gs'))} KT · "+('POSITION' if self.positioned(plane) else 'NO POSITION')
            self.button(cache,(28,144+i*74,984,210+i*74),title,('select',plane['hex']),detail,active=plane['hex']==self.selected)
        self.button(cache,(28,632,268,688),'PREVIOUS',('page',-1));self.button(cache,(744,632,984,688),'NEXT',('page',1))

    def draw_usb(self, cache, state):
        self.panel((12,90,1012,706));self.text(cache,28,118,'1090 ES · ASSIGN RTL-SDR',23)
        self.text(cache,28,151,'978 UAT · NOT INSTALLED · RESERVED FOR A SECOND RECEIVER',15,self.MUTED)
        self.button(cache,(28,174,984,230),'AUTO · FIRST AVAILABLE DONGLE',('assign','auto'))
        devices=state['devices'];self.usb_page=min(self.usb_page,max(0,(len(devices)-1)//4))
        for i,device in enumerate(devices[self.usb_page*4:self.usb_page*4+4]): self.button(cache,(28,246+i*70,984,304+i*70),device['label'],('assign',device['id']),active=state['selection']==device['id'])
        if not devices: self.text(cache,28,285,'No RTL-SDR detected. Check USB power and connection.',19,self.MUTED)
        site=state.get('receiver_position');location=f"SITE {site['lat']:.4f}, {site['lon']:.4f}" if site else 'SITE NOT SET · CONFIGURE IN BROWSER / RECEIVER'
        self.text(cache,28,565,location,15,self.MUTED)
        self.button(cache,(28,632,290,688),'SCAN USB',('scan',None));self.button(cache,(320,632,582,688),'PREVIOUS',('page',-1));self.button(cache,(612,632,984,688),'NEXT',('page',1))

    def draw(self, cache, *args):
        ui,state=self.ui,self.manager.snapshot();self.actions=[]
        valid=[p for p in state['aircraft'] if self.positioned(p)]
        ui.draw_logical_rect(0,0,1280,800,self.BG);self.header(cache,state,valid)
        if self.logs_open: self.draw_logs(cache)
        elif self.traffic_open: self.draw_traffic(cache,state)
        elif self.usb_open: self.draw_usb(cache,state)
        else: self.draw_map(cache,state,valid)
        ui.draw_logical_rect(1024,0,1280,800,self.PANEL)
        trails=trail_label(self.trail_seconds)
        for box,label,action in (
            ((1034,8,1270,72),'STOP' if state['enabled'] else 'START',('stop' if state['enabled'] else 'start',None)),
            ((1034,96,1146,152),'TRAFFIC',('traffic',None)),((1158,96,1270,152),'LOGS',('logs',None)),
            ((1034,164,1146,220),'USB',('usb',None)),((1158,164,1270,220),'RANGE',('rings',None)),
            ((1034,232,1146,288),'ZOOM +',('zoom',1.6)),((1158,232,1270,288),'ZOOM -',('zoom',1/1.6)),
            ((1034,300,1146,356),'MAP',('style',None)),((1158,300,1270,356),'TRAILS',('trails',None)),
            ((1034,368,1146,424),'FIT ALL',('fit',None)),((1158,368,1270,424),'FOLLOW' if not self.following else 'FOLLOW ON',('follow',None)),
            ((1034,728,1270,792),'BACK',('back',None))):
            active=action[0]=='stop' or (action[0]=='logs' and self.logs_open) or (action[0]=='traffic' and self.traffic_open) or (action[0]=='usb' and self.usb_open) or (action[0]=='follow' and self.following) or (action[0]=='rings' and self.rings)
            subtitle=({'both':'SAT + BORDERS','satellite':'SATELLITE','borders':'BORDERS'}[self.map_style] if action[0]=='style' else trails if action[0]=='trails' else '')
            self.button(cache,box,label,action,subtitle,active=active)
        plane=self.selected_plane
        if plane:
            self.text(cache,1038,457,(plane.get('flight') or plane['hex']).strip(),22,self.GOLD,width=226)
            self.text(cache,1038,485,'ICAO '+plane['hex'].upper(),14,self.MUTED)
            for x,y,label,value,unit in ((1038,518,'ALTITUDE',plane.get('alt_baro'),'FT'),(1158,518,'SPEED',plane.get('gs'),'KT'),(1038,584,'HEADING',plane.get('track'),'DEG'),(1158,584,'V/S',plane.get('baro_rate'),'FPM')):
                self.text(cache,x,y,label,10,self.MUTED);self.text(cache,x,y+26,self.value(value),19);self.text(cache,x,y+45,unit,9,self.MUTED)
            if plane.get('historical'):self.text(cache,1038,644,'LAST KNOWN · '+position_age(time.time()-plane['last_position_at']),11,self.MUTED)
        else:
            self.text(cache,1038,462,'SELECT A TARGET',16,self.MUTED)
            self.text(cache,1038,492,'Tap an aircraft or',14,self.MUTED);self.text(cache,1038,516,'open Traffic.',14,self.MUTED)
        self.text(cache,1038,664,'1090 ES · '+state['status'],11,self.CYAN,width=226)
        self.text(cache,1038,688,'978 UAT · NOT INSTALLED',11,self.MUTED)
        detail=reception_summary(state,time.time()) if state['enabled'] and state['status']=='RECEIVING' else state['detail'].split('\n')[-1]
        self.text(cache,18,741,self.message or detail,14,self.MUTED,width=990)
        self.text(cache,18,776,f"{time.strftime('%H:%M:%S',time.gmtime())} UTC · TRAILS {trails} · cm5.local:{state['port']}",14,self.MUTED)

    def close(self): self.manager.close()
