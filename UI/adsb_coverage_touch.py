"""Full-screen native reception dome with cached geometry and batched OpenGL."""
import math
import textwrap
import threading
import time
import numpy as np
from PIL import Image, ImageDraw
import adsb_coverage_gl as dome_gl
from adsb_view import CoverageWindow, COVERAGE_WINDOWS

BLUE=(76,157,255); MUTED=(145,170,193); TEXT=(220,236,255)
BOX=(180,154,1100,712)
GL_WIDTH,GL_HEIGHT=BOX[2]-BOX[0],BOX[3]-BOX[1]
WIDTH,HEIGHT=1232,460
AIRCRAFT_PANEL=(848,330,1256,690)


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
        self.expanded=True;self.ground_enabled=False;self.ground_info=None;self.ground_texture=None;self.ground_version=None
        self.selected_observation=None;self.pick_data={};self.panel_actions=[];self.photo_texture=None;self.photo_key=None

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
        if self.window_open or self.panel_contains(sx,sy):return
        if not self.w.ui.contains(BOX,sx,sy) or abs(x-sx)+abs(y-sy)<10:return
        self.w.dragged=True;self.yaw=(self.origin[0]+(x-sx)*.35)%360;self.tilt=max(8,min(90,self.origin[1]+(y-sy)*.25));self.wake.set()

    def tap(self,x,y):
        if self.window_open:return
        if self.panel_contains(x,y):return self.panel_tap(x,y)
        if not self.w.ui.contains(BOX,x,y):return
        with self.lock:frame=self.projected;data=self.pick_data
        if frame is None:return
        index=dome_gl.pick_observation(frame,x-BOX[0],y-BOX[1])
        if index is not None:
            self.selected_observation=dome_gl.observation_info(data,index)
            self.detail='Recorded reception sample'+(' · latest retained sample in this sky cell' if self.mode=='cells' else '')

    def panel_contains(self,x,y):
        return self.selected_observation is not None and not self.window_open and self.w.ui.contains(AIRCRAFT_PANEL,x,y)

    def panel_tap(self,x,y):
        for box,(kind,value) in self.panel_actions:
            if self.w.ui.contains(box,x,y):self.action(kind,value);return

    def action(self,kind,value):
        if kind=='coverage_window':self.window_open=not self.window_open
        elif kind=='coverage_close_aircraft':self.selected_observation=None
        elif kind=='coverage_filter_aircraft' and self.selected_observation:
            key=self.selected_observation['hex'];self.aircraft=None if self.aircraft==key else key
        elif kind=='coverage_span':
            self.window.select(value);self.window_open=False;self.pending=True
            self.detail='All recorded at this site' if not value else 'Rolling '+self.window.label+' · updates automatically'
        elif kind=='coverage_mode':
            if value!=self.mode:self.tilt=25 if value=='space' else 55
            self.mode=value;self.detail='Drag to rotate · tap a cell or position to inspect'
        elif kind=='coverage_ground':self.ground_enabled=not self.ground_enabled
        elif kind=='coverage_height':self.expanded=not self.expanded
        elif kind=='coverage_signal':self.signal=not self.signal
        elif kind=='coverage_reset':self.yaw=0;self.tilt=25 if self.mode=='space' else 55;self.aircraft=None;self.selected_observation=None;self.detail='All aircraft · drag to rotate'
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
                with self.lock:self.hits=self.projected['hits'];self.pick_data=data
            self.draw_ground(frame,meta)
            dome_gl.draw(ui,self.projected,BOX,max(0,min(1,(self.pulse_until-time.monotonic())/.8)))
            for x,y,text,size,color in self.projected['labels']:w.ink(cache,BOX[0]+x,BOX[1]+y,text,size,color,anchor='cm')
        if self.error or w.manager.coverage_error or data.get('status') in (None,'LOADING','EMPTY','NO SITE'):
            text=self.error or w.manager.coverage_error or {'EMPTY':'No aircraft positions in this viewing window yet.','NO SITE':'Set antenna latitude / longitude in Receiver.'}.get(data.get('status'),'Loading reception history…')
            w.ink(cache,640,464,text,22,w.MUTED,anchor='cm',width=1100)
        factor=frame.get('height_scale',1) if frame else 1
        if self.mode=='space':
            w.button(cache,(24,382,152,450),'Ground',('coverage_ground',None),'Map on' if self.ground_enabled else 'Map off',active=self.ground_enabled)
            w.button(cache,(24,468,152,550),'Height',('coverage_height',None),f'Fit ×{factor:g}' if self.expanded else 'True ×1',active=self.expanded)
        caption=(f'HEIGHT EXPANDED ×{factor:g} · DISTANCES UNCHANGED' if factor>1 else 'TRUE SCALE · EQUAL HORIZONTAL / VERTICAL') if self.mode=='space' else 'ANGULAR SKY · 90° ZENITH'
        w.ink(cache,196,176,caption,13,w.MUTED)
        if self.mode=='space' and self.ground_enabled:w.ink(cache,196,196,'NASA Blue Marble / GIBS · flat map reference · aircraft heights in 3D',13,w.MUTED)
        for box,title,kind,value in (((24,568,152,624),'− 30°','coverage_turn',-30),((24,636,152,692),'+ 30°','coverage_turn',30),((1128,568,1256,624),'Tilt −','coverage_tilt',-10),((1128,636,1256,692),'Tilt +','coverage_tilt',10)):
            self.button(cache,box,title,kind,value)
        w.ink(cache,24,700,'BLUE · RECEIVED / GREY · UNKNOWN',13,w.MUTED,width=310)
        site=meta.get('reference');reference=f"{site['lat']:.5f}°, {site['lon']:.5f}°" if site else 'SITE NOT SET'
        h=f"{meta.get('reference_height_m',0):g} m ellipsoid height" if meta.get('reference_height_known') else 'Height unknown; 0 m assumed · Settings / Radio info'
        w.draw_status(cache,self.detail,reference+' · '+h,full_width=True)
        self.draw_aircraft(cache,state)

    def draw_ground(self,scene,meta):
        if self.mode!='space' or not self.ground_enabled or not meta.get('reference'):return
        service=getattr(self.w.manager,'ground_map',None)
        if service is None:return
        info=service.snapshot(meta['reference'],scene['radius'])
        if not isinstance(info,dict):return
        ui=self.w.ui;gl=ui.GL
        if info.get('status')=='READY' and (info['key'],info['revision'])!=self.ground_version:
            raw=service.image(info['key'],raw=True)
            if raw:
                if self.ground_texture:gl.glDeleteTextures([self.ground_texture])
                self.ground_texture=gl.glGenTextures(1);gl.glBindTexture(gl.GL_TEXTURE_2D,self.ground_texture)
                for flag in (gl.GL_TEXTURE_MIN_FILTER,gl.GL_TEXTURE_MAG_FILTER):gl.glTexParameteri(gl.GL_TEXTURE_2D,flag,gl.GL_LINEAR)
                gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA,info['width'],info['height'],0,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE,raw)
                self.ground_info=info;self.ground_version=(info['key'],info['revision'])
        if not self.ground_texture or not self.ground_info:return
        if self.ground_info['radius']!=scene['radius']:return
        if self.ground_info['reference']!={k:round(meta['reference'][k],5) for k in ('lat','lon')}:return
        matrix,scale,center=self.projected['camera'];r=self.ground_info['radius']/scene['radius']
        world=np.asarray(((-r,r,0),(r,r,0),(r,-r,0),(-r,-r,0)),dtype=np.float32)
        vertices=(world@matrix.T)[:,:2]*scale+center
        vertices=np.asarray([ui.logical_to_native(BOX[0]+x,BOX[1]+y) for x,y in vertices],dtype=np.float32)
        uv=np.asarray(((0,0),(1,0),(1,1),(0,1)),dtype=np.float32)
        gl.glEnable(gl.GL_TEXTURE_2D);gl.glBindTexture(gl.GL_TEXTURE_2D,self.ground_texture);gl.glColor4f(1,1,1,.72)
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY);gl.glEnableClientState(gl.GL_TEXTURE_COORD_ARRAY)
        try:
            gl.glVertexPointer(2,gl.GL_FLOAT,0,vertices);gl.glTexCoordPointer(2,gl.GL_FLOAT,0,uv);gl.glDrawArrays(gl.GL_TRIANGLE_FAN,0,4)
        finally:
            gl.glDisableClientState(gl.GL_TEXTURE_COORD_ARRAY);gl.glDisableClientState(gl.GL_VERTEX_ARRAY);gl.glColor4f(1,1,1,1)
        p=self.selected_observation
        if p:
            foot=(p['east']/scene['radius'],p['north']/scene['radius'],0);top=(*foot[:2],p['up']/scene['radius']*scene['height_scale'])
            projected=(np.asarray((foot,top),dtype=np.float32)@matrix.T)[:,:2]*scale+center
            frame=dict(native=None,batches=[('lines',projected,np.asarray(((1,.84,.46,.85),)*2,dtype=np.float32))])
            dome_gl.draw(ui,frame,BOX)

    def draw_photo(self,path,box):
        """One small texture; decoding/resizing/network happens in the lookup worker."""
        ui=self.w.ui
        if self.photo_key!=str(path):
            if self.photo_texture:ui.GL.glDeleteTextures([self.photo_texture])
            self.photo_texture=None;self.photo_key=None
            try:
                surface=ui.pygame.image.load(str(path)).convert_alpha();width,height=surface.get_size()
                tex=ui.GL.glGenTextures(1);ui.GL.glBindTexture(ui.GL.GL_TEXTURE_2D,tex)
                for flag in (ui.GL.GL_TEXTURE_MIN_FILTER,ui.GL.GL_TEXTURE_MAG_FILTER):ui.GL.glTexParameteri(ui.GL.GL_TEXTURE_2D,flag,ui.GL.GL_LINEAR)
                ui.GL.glTexImage2D(ui.GL.GL_TEXTURE_2D,0,ui.GL.GL_RGBA,width,height,0,ui.GL.GL_RGBA,ui.GL.GL_UNSIGNED_BYTE,ui.pygame.image.tostring(surface,'RGBA',False))
                self.photo_texture=tex;self.photo_key=str(path);self.photo_size=width,height
            except (OSError,ValueError,ui.pygame.error):return
        width,height=self.photo_size;x,y,x1,y1=box;scale=min((x1-x)/width,(y1-y)/height);w,h=width*scale,height*scale
        ui.draw_textured_quad(self.photo_texture,(x+x1-w)/2,(y+y1-h)/2,(x+x1+w)/2,(y+y1+h)/2,0,0,1,1)

    def draw_aircraft(self,cache,state):
        p=self.selected_observation;self.panel_actions=[]
        if p is None:return
        w=self.w;x,y,x1,y1=AIRCRAFT_PANEL
        w.ui.draw_logical_rounded_rect(x,y,x1,y1,14,(*w.PANEL[:3],235),(*BLUE,200),1)
        first=len(w.actions)
        w.ink(cache,x+12,y+22,p['label'],24,w.GOLD,width=300)
        w.ink(cache,x+12,y+46,'ICAO '+p['hex'].upper()+(' · latest cell sample' if self.mode=='cells' else ''),15,w.MUTED,width=300)
        w.button(cache,(x1-68,y+8,x1-12,y+64),'×',('coverage_close_aircraft',None))
        service=getattr(w.manager,'aircraft_details',None)
        info=service.snapshot(p['hex']) if service is not None else {}
        if not isinstance(info,dict):info={}
        photo=info.get('photo_cached') and info.get('photo')
        width=268 if photo else 382
        maker=info.get('manufacturer') or ('Looking up aircraft…' if info.get('status')=='loading' else 'Aircraft')
        w.ink(cache,x+12,y+82,maker,18,w.TEXT,width=width)
        model=info.get('model') or info.get('icao_type') or ('Model unavailable' if info.get('status')!='loading' else '')
        lines=textwrap.wrap(model,width=27 if photo else 38)
        for index,line in enumerate(lines[:2]):w.ink(cache,x+12,y+105+index*21,line,17,w.TEXT,width=width)
        if info.get('registration'):
            w.ink(cache,x+12,y+46,'ICAO '+p['hex'].upper()+' · '+info['registration'],15,w.MUTED,width=300)
        if photo:
            self.draw_photo(service.photo_path(p['hex']),(x+290,y+68,x1-12,y+132))
            w.ink(cache,x+290,y+142,'Airport-Data.com',11,w.MUTED,width=106)
        stamp=time.strftime('%d %b %Y · %H:%M:%S UTC',time.gmtime(p['time']))
        w.ink(cache,x+12,y+160,'Recorded · '+stamp,15,w.MUTED,width=368)
        fields=(('Alt ft',f"{p['altitude']:,.0f} "+('GNSS' if p['gnss'] else 'BARO≈')),
                ('RSSI','—' if p['rssi'] is None else f"{p['rssi']:.1f} dBFS"),
                ('Horiz',f"{p['horizontal']:.2f} km"),('Slant',f"{p['slant']:.2f} km"),
                ('Az',f"{p['azimuth']:.1f}°"),('El',f"{p['elevation']:.1f}°"))
        for index,(label,value) in enumerate(fields):
            px=x+12+(index%2)*198;py=y+194+(index//2)*30
            w.ink(cache,px,py,label,13,w.MUTED,width=42);w.ink(cache,px+44,py,value,20,w.TEXT,width=142)
        live=next((a for a in state.get('aircraft',[]) if a.get('hex')==p['hex'] and time.time()-(a.get('last_seen_at') or 0)<15),None)
        current='No current radio contact'
        if live:
            current='LIVE NOW · '+w.instrument_value(live.get('gs'))+' kt · '+w.instrument_value(live.get('track'))+'°'
            if live.get('squawk'):current+=' · SQ '+str(live['squawk'])
        w.ink(cache,x+12,y+282,current,15,w.CYAN if live else w.MUTED,width=368)
        w.button(cache,(x+12,y1-68,x1-12,y1-12),'All aircraft' if self.aircraft==p['hex'] else 'Only this plane',('coverage_filter_aircraft',None),active=self.aircraft==p['hex'])
        self.panel_actions=w.actions[first:]
