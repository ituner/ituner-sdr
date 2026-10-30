"""Full-screen native reception dome with cached geometry and batched OpenGL."""
import math
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageDraw
import adsb_coverage_gl as dome_gl
from adsb_view import CoverageWindow, COVERAGE_WINDOWS, dome_contact, dome_altitude, reception_age

BLUE=(76,157,255); MUTED=(145,170,193); TEXT=(220,236,255)
BOX=(154,154,1120,712)
GL_WIDTH,GL_HEIGHT=BOX[2]-BOX[0],BOX[3]-BOX[1]
WIDTH,HEIGHT=1232,460
AIRCRAFT_PANEL=(940,364,1256,690)


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
        if kind=='points':
            r=frame['dot_radius']
            for (x,y),colour in zip(vertices,colours):draw.ellipse((x-r,y-r,x+r,y+r),fill=tuple(round(float(v)*255) for v in colour))
            continue
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
        self.latest_contact=None
        self.interaction_until=time.monotonic();self.zoom=1;self.pointer_active=False;self.connections=False
        self.tap_frame=None;self.tap_data=None
        self.projection_pool=None;self.projection_future=None;self.projection_requested=None

    def activate(self):
        self.interaction_until=time.monotonic()
        if self.worker is None:
            self.worker=threading.Thread(target=self.run,name='adsb-coverage-touch',daemon=True);self.worker.start()
        self.wake.set()

    def run(self):
        while not self.w.manager.closed.is_set():
            self.wake.wait(.15);self.wake.clear()
            if not self.w.open or not self.w.coverage_open:continue
            if self.pointer_active:continue
            try:
                revision=self.window.revision
                self.update_data(self.w.manager.coverage.snapshot(self.window.since(time.time())),revision)
            except Exception as exc:self.error=str(exc)

    def update_data(self,data,revision=None):
        if revision is not None and revision!=self.window.revision:return False
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
            if revision is not None and revision!=self.window.revision:return False
            self.frame=frame;self.data=data;self.frame_id+=1;self.error=''
            self.selected_observation=dome_gl.latest_observation(data,self.selected_observation)
            self.pulse_until=time.monotonic()+.8 if len(frame['highlights']) else 0
        self.last_key=key
        return True

    def drag_begin(self,x,y):
        self.origin=(self.yaw,self.tilt)
        self.pointer_active=not self.window_open and not self.panel_contains(x,y) and self.w.ui.contains(BOX,x,y)
        self.tap_frame=self.projected if self.pointer_active else None
        self.tap_data=self.pick_data if self.pointer_active else None

    def drag_end(self):
        if self.pointer_active:self.interaction_until=time.monotonic()
        self.pointer_active=False

    def drag_move(self,sx,sy,x,y):
        if self.window_open or self.panel_contains(sx,sy):return
        if not self.w.ui.contains(BOX,sx,sy) or abs(x-sx)+abs(y-sy)<10:return
        self.w.dragged=True;self.yaw=(self.origin[0]+(x-sx)*.35)%360;self.tilt=max(8,min(90,self.origin[1]+(y-sy)*.25));self.interaction_until=time.monotonic()+.16;self.wake.set()
        self.tap_frame=None;self.tap_data=None

    def tap(self,x,y):
        if self.window_open:return
        if self.panel_contains(x,y):return self.panel_tap(x,y)
        if not self.w.ui.contains(BOX,x,y):return
        with self.lock:
            frame=self.tap_frame if self.tap_frame is not None else self.projected
            data=self.tap_data if self.tap_frame is not None else self.pick_data
            self.tap_frame=None;self.tap_data=None
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
        self.interaction_until=time.monotonic()+.16
        if kind=='coverage_window':self.window_open=not self.window_open
        elif kind=='coverage_close_aircraft':self.selected_observation=None
        elif kind=='coverage_filter_aircraft' and self.selected_observation:
            key=self.selected_observation['hex'];self.aircraft=None if self.aircraft==key else key
        elif kind=='coverage_span':
            self.window.select(value);self.window_open=False
            self.pending=True
            self.detail='All recorded at this site' if not value else 'Rolling '+self.window.label+' · updates automatically'
        elif kind=='coverage_clock_reset':
            self.window.reset();self.window_open=False
            # Reset only the displayed window. Reject late snapshots using revision.
            meta={k:v for k,v in self.data.get('meta',{}).items() if k in ('reference','reference_height_m','reference_height_known','retention_days','storage_limit')}
            meta.update(window_since=self.window.started_at,retained_positions=0,positioned_aircraft=0,horizontal_range_max_km=0,slant_range_max_km=0,max_altitude_ft=None)
            self.aircraft=None;self.selected_observation=None
            self.update_data(dict(status='EMPTY',meta=meta,base=0,points=[],cells=[],aircraft=[],breaks=[]))
            self.pending=True
            self.detail='Clock reset · collecting new positions · saved history kept'
        elif kind=='coverage_mode':
            if value!=self.mode:self.tilt=25 if value=='space' else 55
            self.mode=value;self.detail='Drag to rotate · tap a cell or position to inspect'
        elif kind=='coverage_ground':
            self.ground_enabled=not self.ground_enabled
            if self.ground_enabled and self.mode!='space':self.mode='space';self.tilt=25
        elif kind=='coverage_height':self.expanded=not self.expanded
        elif kind=='coverage_zoom':self.zoom=max(.5,min(4,round(self.zoom+value,2)))
        elif kind=='coverage_signal':self.signal=not self.signal
        elif kind=='coverage_reset':self.yaw=0;self.tilt=25 if self.mode=='space' else 55;self.aircraft=None;self.selected_observation=None;self.detail='All aircraft · drag to rotate'
        elif kind=='coverage_turn':self.yaw=(self.yaw+value)%360
        elif kind=='coverage_tilt':self.tilt=max(8,min(90,self.tilt+value))
        self.wake.set()

    def button(self,cache,box,title,kind,value=None,active=False):
        self.w.button(cache,box,title,(kind,value),active=active)

    def projection(self,frame,identity,asynchronous=False):
        idle=time.monotonic()-self.interaction_until;moving=bool(self.pointer_active) or idle<0
        budget=dome_gl.detail_budget(len(frame.get('dots',())),idle,moving)
        fine=False
        key=(identity,self.yaw,self.tilt,self.zoom,(budget,fine),self.connections,moving)
        if key==self.project_key:return self.projected
        if asynchronous and not moving and (budget>8000 or fine):
            if self.projection_future is not None and self.projection_future.done():
                result=self.projection_future.result();self.projection_future=None
                if self.projection_requested==key:
                    self.projected=result;self.project_key=key;return result
            if self.projection_future is None:
                if self.projection_pool is None:self.projection_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='dome-detail')
                self.projection_requested=key
                self.projection_future=self.projection_pool.submit(dome_gl.project,frame,self.yaw,self.tilt,GL_WIDTH,GL_HEIGHT,zoom=self.zoom,point_limit=budget,connections=self.connections,fine_cells=fine)
            # Keep the completed lower-detail image visible while refining it.
            if self.project_key is not None and self.project_key[:4]==key[:4] and self.project_key[-2:]==key[-2:]:return self.projected
            budget=8000;fine=False;key=(identity,self.yaw,self.tilt,self.zoom,(budget,fine),self.connections,False)
        if key!=self.project_key:
            self.projected=dome_gl.project(frame,self.yaw,self.tilt,GL_WIDTH,GL_HEIGHT,interactive=moving,zoom=self.zoom,point_limit=budget,connections=self.connections,fine_cells=fine)
            self.project_key=key
        return self.projected

    def draw_scene(self,cache,data,frame,identity):
        if frame is None:return
        w=self.w;ui=w.ui;gl=ui.GL
        self.projection(frame,identity,asynchronous=True)
        with self.lock:self.hits=self.projected['hits'];self.pick_data=data
        def clip(box):
            corners=[ui.logical_to_native(x,y) for x,y in ((box[0],box[1]),(box[2],box[1]),(box[2],box[3]),(box[0],box[3]))]
            left=int(min(p[0] for p in corners));right=int(max(p[0] for p in corners))
            top=int(min(p[1] for p in corners));bottom=int(max(p[1] for p in corners))
            gl.glScissor(left,ui.NATIVE_H-bottom,right-left,bottom-top)
        gl.glEnable(gl.GL_SCISSOR_TEST)
        try:
            if self.zoom>1:
                clip((12,80,1268,BOX[3]));dome_gl.draw(ui,self.projected,BOX,opacity=.14)
                ui.draw_logical_rect(*BOX,w.BG)
            clip(BOX);self.draw_ground(frame,data.get('meta',{}))
            dome_gl.draw(ui,self.projected,BOX,max(0,min(1,(self.pulse_until-time.monotonic())/.8)))
            for x,y,text,size,color in self.projected['labels']:
                if 12<=x<=GL_WIDTH-12 and 12<=y<=GL_HEIGHT-12:w.ink(cache,BOX[0]+x,BOX[1]+y,text,size,color,anchor='cm')
        finally:gl.glDisable(gl.GL_SCISSOR_TEST)

    def draw(self,cache,state):
        w=self.w;ui=w.ui;ui.draw_logical_rect(0,0,1280,800,w.BG)
        w.ink(cache,24,27,'AIRSPACE / RECEPTION DOME',25,w.TEXT)
        with self.lock:data=self.data;frame=self.frame;labels=self.labels;identity=self.frame_id
        meta=data.get('meta',{});count=meta.get('retained_positions',0)
        summary=f"{self.window.label.upper()}"+(' · SINCE RESET' if self.window.started_at is not None else '')+f" · {count:,} positions · {meta.get('positioned_aircraft',0)} aircraft"+(' · updating…' if self.pending else '')
        w.ink(cache,24,61,summary,18,w.MUTED,width=550)
        w.draw_back(cache,('back',None))
        self.button(cache,(580,10,820,72),'Time · '+self.window.label,'coverage_window',active=self.window_open)
        self.button(cache,(832,10,990,72),'Reset','coverage_clock_reset')
        if self.window_open:
            w.ink(cache,80,135,'DOME TIMESPAN',25,w.TEXT)
            w.ink(cache,80,176,'Choose rolling history · Reset starts the selected window from now',20,w.MUTED)
            for index,(seconds,label) in enumerate(COVERAGE_WINDOWS):
                x=80+(index%3)*376;y=220+(index//3)*96
                self.button(cache,(x,y,x+352,y+72),label,'coverage_span',seconds,seconds==self.window.seconds)
            w.draw_status(cache,'Choose a timespan · Back cancels','All receptions kept for 7 days · older history bounded',full_width=True)
            return
        self.draw_scene(cache,data,frame,identity)
        self.button(cache,(1002,10,1110,72),'Map ON' if self.ground_enabled else 'Map OFF','coverage_ground',active=self.ground_enabled)
        for box,title,kind,value,active in (((24,96,260,152),'Sky cells','coverage_mode','cells',self.mode=='cells'),((272,96,508,152),'3D distance','coverage_mode','space',self.mode=='space'),((520,96,824,152),'Signal' if not self.signal else 'Signal colour ON','coverage_signal',None,self.signal),((836,96,1100,152),'All aircraft','coverage_reset',None,False),((1112,96,1256,152),'Site','site',None,False)):
            self.button(cache,box,title,kind,value,active)
        r=meta.get('horizontal_range_max_km',0);alt=meta.get('max_altitude_ft')
        for x,y,title,value in ((24,244,'Radius',f'{r:.1f} km'),(24,312,'Diameter',f'{2*r:.1f} km'),(1124,244,'Slant range',f"{meta.get('slant_range_max_km',0):.1f} km"),(1124,312,'Highest',f'{alt:,.0f} ft' if alt is not None else '—')):
            w.ink(cache,x,y,title,14,w.MUTED);w.ink(cache,x,y+25,value,19,w.TEXT,width=140)
        if self.error or w.manager.coverage_error or data.get('status') in (None,'LOADING','EMPTY','NO SITE'):
            text=self.error or w.manager.coverage_error or {'EMPTY':'No aircraft positions in this viewing window yet.','NO SITE':'Tap Site to enter antenna latitude / longitude.'}.get(data.get('status'),'Loading reception history…')
            w.ink(cache,640,464,text,22,w.MUTED,anchor='cm',width=880)
        factor=frame.get('height_scale',1) if frame else 1
        w.ink(cache,24,374,f'Zoom {self.zoom:.0%}',14,w.MUTED)
        self.button(cache,(24,390,80,446),'−','coverage_zoom',-.25)
        self.button(cache,(96,390,152,446),'+','coverage_zoom',.25)
        if self.mode=='space':
            w.button(cache,(24,468,152,550),'Height',('coverage_height',None),f'Fit ×{factor:g}' if self.expanded else 'True ×1',active=self.expanded)
        if self.mode=='space':
            if alt is not None:
                w.ink(cache,1124,362,f'{alt*.0003048:.2f} km',13,w.MUTED,width=140)
                w.ink(cache,1124,384,' · '.join(str(meta[k]) for k in ('max_altitude_source','max_altitude_aircraft') if meta.get(k)),12,w.MUTED,width=140)
            if self.projected is not None:
                shown=self.projected.get('drawn_positions',0);total=len(frame.get('dots',())) if frame else 0
                w.ink(cache,1124,420,'DOTS',14,w.MUTED)
                w.ink(cache,1124,444,f'{shown:,}',19,w.TEXT,width=140)
                available=meta.get('retained_positions',total)
                w.ink(cache,1124,470,f'of {available:,}'+(' · refining' if shown<total else ' · sample' if meta.get('sampled') else ' · detailed'),12,w.MUTED,width=140)
            if self.ground_enabled:
                w.ink(cache,24,456,'NASA / GIBS · flat',10,w.MUTED,width=128)
        else:
            w.ink(cache,1124,420,'CELLS',14,w.MUTED)
            preview=self.projected is not None and self.projected.get('cell_degrees')==8
            w.ink(cache,1124,444,'8° × 4°' if preview else '4° × 2°',19,w.TEXT,width=140)
            w.ink(cache,1124,470,'Preview' if preview else 'Reception cells',12,w.MUTED,width=140)
        for box,title,kind,value in (((24,568,152,624),'− 30°','coverage_turn',-30),((24,636,152,692),'+ 30°','coverage_turn',30),((1128,568,1256,624),'Tilt −','coverage_tilt',-10),((1128,636,1256,692),'Tilt +','coverage_tilt',10)):
            self.button(cache,box,title,kind,value)
        if self.signal:
            w.ink(cache,24,700,'WEAK −45',12,w.MUTED)
            for index in range(40):
                colour=dome_gl.signal_colour(-45+index*40/39)
                ui.draw_logical_rect(94+index*4,694,98+index*4,706,tuple(round(v*255) for v in colour))
            w.ink(cache,266,700,'−5 dBFS STRONG · grey: no signal value',12,w.MUTED,width=320)
        else:w.ink(cache,24,700,'BLUE · RECEIVED / GREY · UNKNOWN',13,w.MUTED,width=310)
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
        if p is None:self.latest_contact=None;return
        w=self.w;x,y,x1,y1=AIRCRAFT_PANEL
        w.ui.draw_logical_rounded_rect(x,y,x1,y1,w.RADIUS,(*w.PANEL[:3],235),(*BLUE,200),1)
        first=len(w.actions)
        w.button(cache,(x1-68,y+8,x1-12,y+64),'×',('coverage_close_aircraft',None))
        service=getattr(w.manager,'aircraft_details',None)
        info=service.snapshot(p['hex']) if service is not None else {}
        if not isinstance(info,dict):info={}
        photo=info.get('photo_cached') and info.get('photo')
        title_x=x+104 if photo else x+12;title_width=132 if photo else 224
        w.ink(cache,title_x,y+22,p['label'],22,w.GOLD,width=title_width)
        w.ink(cache,title_x,y+42,'ICAO '+p['hex'].upper(),13,w.MUTED,width=title_width)
        if info.get('registration'):w.ink(cache,title_x,y+58,info['registration'],12,w.MUTED,width=title_width)
        maker=info.get('manufacturer') or ('Looking up aircraft…' if info.get('status')=='loading' else 'Aircraft')
        model=info.get('model') or info.get('icao_type') or ('Model unavailable' if info.get('status')!='loading' else '')
        for index,line in enumerate(textwrap.wrap(' · '.join(v for v in (maker,model) if v),width=34)[:2]):
            w.ink(cache,x+12,y+78+index*18,line,16,w.TEXT,width=292)
        if photo:
            self.draw_photo(service.photo_path(p['hex']),(x+12,y+12,x+92,y+52))
            w.ink(cache,x+12,y+63,'Airport-Data.com',9,w.MUTED,width=80)
        position_report=dict(hex=p['hex'],last_seen_at=p['time'],**({'alt_geom':p['altitude']} if p['gnss'] else {'alt_baro':p['altitude']}))
        self.latest_contact=dome_contact([*state.get('aircraft',[]),position_report],p['hex'],time.time(),self.latest_contact)
        live=self.latest_contact;altitude=dome_altitude(live)
        received=reception_age(live['seen']) if live else 'Age unavailable'
        w.ink(cache,x+12,y+118,received,17,w.CYAN if live and live['live'] else w.MUTED,width=292)
        altitude_value=altitude.split(' ft',1)[0]+' ft' if altitude and ' ft' in altitude else altitude or f"{p['altitude']:,.0f} ft"
        fields=(('Altitude',altitude_value),
                ('RSSI','—' if p['rssi'] is None else f"{p['rssi']:.1f} dBFS"),
                ('Horiz',f"{p['horizontal']:.2f} km"),('Slant',f"{p['slant']:.2f} km"),
                ('Az',f"{p['azimuth']:.1f}°"),('El',f"{p['elevation']:.1f}°"))
        for index,(label,value) in enumerate(fields):
            px=x+12+(index%2)*148;py=y+138+(index//2)*34
            w.ink(cache,px,py,label,12,w.MUTED,width=136)
            w.ink(cache,px,py+18,value,20,w.TEXT,width=136)
        current='Latest received position · '+f"{p['altitude']:,.0f} ft"
        if live:
            current=w.instrument_value(live.get('gs'))+' kt · '+w.instrument_value(live.get('track'))+'° · '+('Live' if live['live'] else 'Last report')
            if live.get('squawk'):current+=' · SQ '+str(live['squawk'])
        w.ink(cache,x+12,y+246,current,13,w.CYAN if live and live['live'] else w.MUTED,width=292)
        w.button(cache,(x+12,y1-68,x1-12,y1-12),'All aircraft' if self.aircraft==p['hex'] else 'Only this plane',('coverage_filter_aircraft',None),active=self.aircraft==p['hex'])
        self.panel_actions=w.actions[first:]
