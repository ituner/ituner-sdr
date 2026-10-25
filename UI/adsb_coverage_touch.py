"""Full-screen native reception dome with cached geometry and batched OpenGL."""
import math
import threading
import time
from PIL import Image, ImageDraw
import adsb_coverage_gl as dome_gl
from adsb_view import CoverageWindow, COVERAGE_WINDOWS

BLUE=(76,157,255); MUTED=(145,170,193); TEXT=(220,236,255)
BOX=(180,154,1100,712)
GL_WIDTH,GL_HEIGHT=BOX[2]-BOX[0],BOX[3]-BOX[1]
WIDTH,HEIGHT=1232,460


class RasterDraw:
    """Two-times antialiasing and alpha compositing for translucent sky cells."""
    def __init__(self,image):self.draw=ImageDraw.Draw(image,'RGBA')
    def line(self,points,fill,width=1):self.draw.line([(2*x,2*y) for x,y in points],fill=fill,width=max(1,2*width))
    def polygon(self,points,fill):self.draw.polygon([(2*x,2*y) for x,y in points],fill=fill)
    def ellipse(self,box,fill=None,outline=None,width=1):self.draw.ellipse(tuple(2*x for x in box),fill=fill,outline=outline,width=max(1,2*width))


def paint(data, mode, yaw, tilt, signal, aircraft=None):
    """Offline bitmap export of the same scene used by the native GL view."""
    frame=dome_gl.project(dome_gl.prepare(data,mode,signal,aircraft),yaw,tilt,WIDTH,HEIGHT)
    image=Image.new('RGB',(WIDTH*2,HEIGHT*2),(0,0,0));draw=RasterDraw(image)
    for kind,vertices,colours in frame['batches']:
        count=3 if kind=='triangles' else 2
        for index in range(0,len(vertices),count):
            points=[tuple(p) for p in vertices[index:index+count]];fill=tuple(round(float(v)*255) for v in colours[index])
            if kind=='triangles':draw.polygon(points,fill)
            else:draw.line(points,fill)
    return image.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS).convert('RGBA').tobytes(),frame['labels'],frame['hits']


class CoverageTouch:
    def __init__(self, workspace):
        self.w=workspace;self.mode='cells';self.yaw=0;self.tilt=55;self.signal=False;self.aircraft=None;self.detail='Drag to rotate · tap a cell or position to inspect'
        self.frame=None;self.frame_id=0;self.uploaded=-1;self.texture=None;self.labels=[];self.hits=[];self.data={};self.error=''
        self.lock=threading.Lock();self.wake=threading.Event();self.worker=None;self.origin=(0,55);self.projected=None;self.project_key=None
        self.last_key=None;self.pending=False;self.pulse_until=0
        self.window=CoverageWindow();self.window_open=False
        self.expanded=True

    def activate(self):
        if self.worker is None:
            self.worker=threading.Thread(target=self.run,name='adsb-coverage-touch',daemon=True);self.worker.start()
        self.wake.set()

    def run(self):
        while not self.w.manager.closed.is_set():
            self.wake.wait(.15);self.wake.clear()
            if not self.w.open or not self.w.coverage_open:continue
            try:
                self.update_data(self.w.manager.coverage.snapshot(self.window.since(time.time())))
            except Exception as exc:self.error=str(exc)

    def update_data(self,data):
        self.pending=data.get('status')=='LOADING'
        if self.pending:
            if self.frame is None:return False
            data=self.data
        settings=(self.mode,self.signal,self.aircraft);key=(id(data),settings,self.expanded)
        if key==self.last_key:return False
        added=dome_gl.new_point_keys(self.data,data)
        frame=dome_gl.prepare(data,*settings,new_points=added,expanded=self.expanded)
        # Publish a complete scene in one swap. Never expose an empty loading scene.
        with self.lock:
            self.frame=frame;self.data=data;self.frame_id+=1;self.error=''
            self.pulse_until=time.monotonic()+.8 if len(frame['highlights']) else 0
        self.last_key=key
        return True

    def drag_begin(self,x,y):self.origin=(self.yaw,self.tilt)

    def drag_move(self,sx,sy,x,y):
        if self.window_open:return
        if not self.w.ui.contains(BOX,sx,sy) or abs(x-sx)+abs(y-sy)<10:return
        self.w.dragged=True;self.yaw=(self.origin[0]+(x-sx)*.35)%360;self.tilt=max(8,min(90,self.origin[1]+(y-sy)*.25));self.wake.set()

    def tap(self,x,y):
        if self.window_open:return
        if not self.w.ui.contains(BOX,x,y):return
        with self.lock:hits=self.hits
        near=sorted((math.hypot(px+BOX[0]-x,py+BOX[1]-y),label,aircraft) for px,py,label,aircraft in hits)
        if near and near[0][0]<24:
            self.detail=near[0][1]
            if near[0][2]:self.aircraft=near[0][2];self.wake.set()

    def action(self,kind,value):
        if kind=='coverage_window':self.window_open=not self.window_open
        elif kind=='coverage_span':
            self.window.select(value);self.window_open=False;self.pending=True
            self.detail='All recorded at this site' if not value else 'Rolling '+self.window.label+' · updates automatically'
        elif kind=='coverage_mode':
            if value!=self.mode:self.tilt=25 if value=='space' else 55
            self.mode=value;self.detail='Drag to rotate · tap a cell or position to inspect'
        elif kind=='coverage_height':self.expanded=not self.expanded
        elif kind=='coverage_signal':self.signal=not self.signal
        elif kind=='coverage_reset':self.yaw=0;self.tilt=25 if self.mode=='space' else 55;self.aircraft=None;self.detail='All aircraft · drag to rotate'
        elif kind=='coverage_turn':self.yaw=(self.yaw+value)%360
        elif kind=='coverage_tilt':self.tilt=max(8,min(90,self.tilt+value))
        self.wake.set()

    def button(self,cache,box,title,kind,value=None,active=False):
        self.w.button(cache,box,title,(kind,value),active=active)

    def draw(self,cache,state):
        w=self.w;ui=w.ui;ui.draw_logical_rect(0,0,1280,800,w.BG)
        w.ink(cache,24,27,'AIRSPACE / RECEPTION DOME',25,w.TEXT)
        with self.lock:data=self.data;frame=self.frame;labels=self.labels;identity=self.frame_id
        meta=data.get('meta',{});count=meta.get('retained_positions',0)
        summary=f"{self.window.label.upper()} · {count:,} positions · {meta.get('positioned_aircraft',0)} aircraft"+(' · updating…' if self.pending else '')
        w.ink(cache,24,61,summary,18,w.MUTED)
        w.draw_back(cache,('back',None))
        self.button(cache,(780,10,1110,72),'Time · '+self.window.label,'coverage_window',active=self.window_open)
        if self.window_open:
            w.ink(cache,80,135,'DOME TIMESPAN',25,w.TEXT)
            w.ink(cache,80,176,'Rolling reception history · independent of the live map',20,w.MUTED)
            for index,(seconds,label) in enumerate(COVERAGE_WINDOWS):
                x=80+(index%3)*376;y=220+(index//3)*96
                self.button(cache,(x,y,x+352,y+72),label,'coverage_span',seconds,seconds==self.window.seconds)
            w.draw_status(cache,'Choose a timespan · Back cancels','Retains up to 90 days / 250,000 positions',full_width=True)
            return
        for box,title,kind,value,active in (((24,96,218,152),'Sky cells','coverage_mode','cells',self.mode=='cells'),((230,96,424,152),'Sky trails','coverage_mode','trails',self.mode=='trails'),((436,96,654,152),'3D distance','coverage_mode','space',self.mode=='space'),((666,96,912,152),'Signal' if not self.signal else 'Signal colour ON','coverage_signal',None,self.signal),((924,96,1124,152),'All aircraft','coverage_reset',None,False),((1136,96,1256,152),'Site','usb',None,False)):
            self.button(cache,box,title,kind,value,active)
        r=meta.get('horizontal_range_max_km',0);alt=meta.get('max_altitude_ft')
        for x,y,title,value in ((24,244,'Radius',f'{r:.1f} km'),(24,312,'Diameter',f'{2*r:.1f} km'),(1124,244,'Slant range',f"{meta.get('slant_range_max_km',0):.1f} km"),(1124,312,'Highest',f'{alt:,.0f} ft' if alt is not None else '—')):
            w.ink(cache,x,y,title,14,w.MUTED);w.ink(cache,x,y+25,value,19,w.TEXT,width=140)
        if frame is not None:
            key=(identity,self.yaw,self.tilt)
            if key!=self.project_key:
                self.projected=dome_gl.project(frame,self.yaw,self.tilt,GL_WIDTH,GL_HEIGHT);self.project_key=key
                with self.lock:self.hits=self.projected['hits']
            dome_gl.draw(ui,self.projected,BOX,max(0,min(1,(self.pulse_until-time.monotonic())/.8)))
            for x,y,text,size,color in self.projected['labels']:w.ink(cache,BOX[0]+x,BOX[1]+y,text,size,color,anchor='cm')
        if self.error or w.manager.coverage_error or data.get('status') in (None,'LOADING','EMPTY','NO SITE'):
            text=self.error or w.manager.coverage_error or {'EMPTY':'No aircraft positions in this viewing window yet.','NO SITE':'Set antenna latitude / longitude in Receiver.'}.get(data.get('status'),'Loading reception history…')
            w.ink(cache,640,464,text,22,w.MUTED,anchor='cm',width=1100)
        factor=frame.get('height_scale',1) if frame else 1
        if self.mode=='space':
            w.button(cache,(24,468,152,550),'Height',('coverage_height',None),f'Fit ×{factor:g}' if self.expanded else 'True ×1',active=self.expanded)
        caption=(f'HEIGHT EXPANDED ×{factor:g} · DISTANCES UNCHANGED' if factor>1 else 'TRUE SCALE · EQUAL HORIZONTAL / VERTICAL') if self.mode=='space' else 'ANGULAR SKY · 90° ZENITH'
        w.ink(cache,196,176,caption,13,w.MUTED)
        for box,title,kind,value in (((24,568,152,624),'− 30°','coverage_turn',-30),((24,636,152,692),'+ 30°','coverage_turn',30),((1128,568,1256,624),'Tilt −','coverage_tilt',-10),((1128,636,1256,692),'Tilt +','coverage_tilt',10)):
            self.button(cache,box,title,kind,value)
        w.ink(cache,24,700,'BLUE · RECEIVED / GREY · UNKNOWN',13,w.MUTED,width=310)
        site=meta.get('reference');reference=f"{site['lat']:.5f}°, {site['lon']:.5f}°" if site else 'SITE NOT SET'
        h=f"{meta.get('reference_height_m',0):g} m ellipsoid height" if meta.get('reference_height_known') else 'Height unknown; 0 m assumed · Settings / Radio info'
        w.draw_status(cache,self.detail,reference+' · '+h,full_width=True)
