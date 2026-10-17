"""Full-screen native reception dome. Raster work stays off the GL/touch thread."""
import math
import threading
import time
from PIL import Image, ImageDraw

BLUE=(76,157,255); MUTED=(145,170,193); TEXT=(220,236,255)
BOX=(24,234,1256,694)
WIDTH,HEIGHT=1232,460


class RasterDraw:
    """Two-times antialiasing and alpha compositing for translucent sky cells."""
    def __init__(self,image):self.draw=ImageDraw.Draw(image,'RGBA')
    def line(self,points,fill,width=1):self.draw.line([(2*x,2*y) for x,y in points],fill=fill,width=max(1,2*width))
    def polygon(self,points,fill):self.draw.polygon([(2*x,2*y) for x,y in points],fill=fill)
    def ellipse(self,box,fill=None,outline=None,width=1):self.draw.ellipse(tuple(2*x for x in box),fill=fill,outline=outline,width=max(1,2*width))


def vector(az, el, radius=1):
    a,e=math.radians(az),math.radians(el)
    return radius*math.sin(a)*math.cos(e),radius*math.cos(a)*math.cos(e),radius*math.sin(e)


def paint(data, mode, yaw, tilt, signal, aircraft=None):
    """Return a black dome raster plus logical text and pick targets."""
    meta=data.get('meta',{}); yaw,tilt=math.radians(yaw),math.radians(tilt)
    scale=min((WIDTH-100)/2,(HEIGHT-110)/(1+math.sin(tilt)));cx=WIDTH/2;cy=HEIGHT/2+scale*(1-math.sin(tilt))/2+22
    def project(v):
        e,n,u=v;x=e*math.cos(yaw)-n*math.sin(yaw);y=e*math.sin(yaw)+n*math.cos(yaw)
        return (cx+x*scale,cy+(-y*math.sin(tilt)-u*math.cos(tilt))*scale,-y*math.cos(tilt)+u*math.sin(tilt))
    image=Image.new('RGB',(WIDTH*2,HEIGHT*2),(0,0,0));draw=RasterDraw(image)
    radius=max(5000,math.ceil(max(meta.get('horizontal_range_max_km',0),(meta.get('max_altitude_ft') or 0)*.0003048)/5)*5000)
    height=meta.get('reference_height_m',0);points=[];hits=[];labels=[];cells={}
    names=data.get('aircraft',[])
    for p in data.get('points',[]):
        if aircraft and names[p[1]]['hex']!=aircraft:continue
        up=p[4]-height;distance=math.hypot(p[2],p[3]);az=math.degrees(math.atan2(p[2],p[3]))%360;el=math.degrees(math.atan2(up,distance))
        world=(p[2]/radius,p[3]/radius,up/radius) if mode=='space' else vector(az,el)
        points.append((p,world,el,az,distance))
        if el>=0:
            cell=cells.setdefault((int(az//4)*4,min(88,int(el//2)*2)),[0,0,0,0])
            cell[0]+=1
            if p[6] is not None:cell[1]+=p[6];cell[2]+=1
            cell[3]=max(cell[3],distance)
    if not aircraft:
        cells={(a,e):[count,level or 0,1 if level is not None else 0,max_distance] for a,e,count,level,_,max_distance in data.get('cells',[])}
    max_count=max([1]+[c[0] for c in cells.values()])
    def colour(level,count=1):
        if signal and level is not None:
            strength=.3+.7*max(0,min(1,(level-meta.get('rssi_min',-40))/(meta.get('rssi_max',0)-meta.get('rssi_min',-40) or 1)))
        else:strength=.55+.45*math.log1p(count)/math.log1p(max_count)
        return tuple(round(v*strength) for v in BLUE)+(255,)
    def path(vertices,fill=(48,62,79,255),width=1):
        draw.line([project(v)[:2] for v in vertices],fill=fill,width=width)
    if mode=='cells':
        polygons=[]
        for el in range(0,90,2):
            for az in range(0,360,4):
                cell=cells.get((az,el));center=project(vector(az+2,el+1));verts=[project(vector(a,e))[:2] for a,e in ((az+.22,el+.12),(az+3.78,el+.12),(az+3.78,el+1.88),(az+.22,el+1.88))]
                polygons.append((center[2],verts,colour(cell[1]/cell[2] if cell[2] else None,cell[0]) if cell else (145,170,193,12)))
                if cell:hits.append((center[0],center[1],f'{az}–{az+4}° az / {el}–{el+2}° el · {cell[0]} positions · max {cell[3]/1000:.1f} km',None))
        for _,verts,fill in sorted(polygons,key=lambda p:p[0]):draw.polygon(verts,fill=fill)
    if mode=='space':
        for index in range(1,int(radius/5000)+1):
            r=index*5000/radius;path([vector(a,0,r) for a in range(0,361,3)])
            x,y,_=project(vector(95,0,r));labels.append((x+16,y,f'{index*5} km',16,MUTED))
        for a in range(0,360,45):path([(0,0,0),vector(a,0)])
    else:
        for el in range(0,90,15):path([vector(a,el) for a in range(0,361,3)])
        for az in range(0,360,30):path([vector(az,e) for e in range(0,91,3)])
        for el in (30,60):
            x,y,_=project(vector(90,el));labels.append((x+15,y,f'{el}°',18,MUTED))
    if mode!='cells':
        last={};breaks=data.get('breaks',[])
        for point,world,el,az,distance in points:
            previous=last.get(point[1]);last[point[1]]=(point,world)
            if previous:
                a,av=previous;dt=point[0]-a[0];moved=math.dist(a[2:5],point[2:5])
                if 0<dt<=15 and moved<=500+400*dt and not any(data['base']+a[0]<t<=data['base']+point[0] for t in breaks):
                    if mode=='space' or el>=0:path([av,world],(37,88,151,255),2)
        for point,world,el,az,distance in sorted(points,key=lambda item:project(item[1])[2]):
            if mode!='space' and el<0:continue
            x,y,_=project(world);fill=colour(point[6]);r=3 if not aircraft else 4
            draw.ellipse((x-r,y-r,x+r,y+r),fill=fill if point[7] else None,outline=fill,width=2)
            name=point[8] or names[point[1]]['label'];source='GNSS' if point[7] else 'BARO ≈'
            hits.append((x,y,f'{name} · {point[5]:,.0f} ft {source} · {distance/1000:.1f} km · {az:.0f}° az / {el:.1f}° el',names[point[1]]['hex']))
    for name,az in (('N',0),('E',90),('S',180),('W',270)):
        x,y,_=project(vector(az,0,1.13));labels.append((x,y,name,23,TEXT))
    x,y,_=project((0,0,0));draw.ellipse((x-4,y-4,x+4,y+4),fill=TEXT+(255,));labels.append((x,y+24,'RECEIVER',16,MUTED))
    alt=meta.get('max_altitude_ft')
    if alt is not None:
        z=max([1000]+[p[4]-height for p,_,_,_,_ in points])/radius if mode=='space' else 1.06
        x,y,_=project((0,0,z))
        if mode=='space':path([(0,0,0),(0,0,z)],(88,123,158,255))
        labels.append((cx,max(26,y-34),f'MAX ALT {alt:,.0f} ft / {alt*.0003048:.2f} km',23,(176,213,255)))
        labels.append((cx,max(52,y-8),f"{meta.get('max_altitude_source','')} · {meta.get('max_altitude_aircraft','')} · not necessarily overhead",15,MUTED))
    return image.resize((WIDTH,HEIGHT),Image.Resampling.LANCZOS).convert('RGBA').tobytes(),labels,hits


class CoverageTouch:
    def __init__(self, workspace):
        self.w=workspace;self.mode='cells';self.yaw=0;self.tilt=55;self.signal=False;self.aircraft=None;self.detail='Drag to rotate · tap a cell or position to inspect'
        self.frame=None;self.frame_id=0;self.uploaded=-1;self.texture=None;self.labels=[];self.hits=[];self.data={};self.error=''
        self.lock=threading.Lock();self.wake=threading.Event();self.worker=None;self.origin=(0,55)

    def activate(self):
        if self.worker is None:
            self.worker=threading.Thread(target=self.run,name='adsb-coverage-touch',daemon=True);self.worker.start()
        self.wake.set()

    def run(self):
        last=None
        while not self.w.manager.closed.is_set():
            self.wake.wait(.15);self.wake.clear()
            if not self.w.open or not self.w.coverage_open:continue
            data=self.w.manager.coverage.snapshot();settings=(self.mode,self.yaw,self.tilt,self.signal,self.aircraft)
            key=(id(data),settings)
            if key==last:continue
            try:
                frame,labels,hits=paint(data,*settings)
                with self.lock:self.frame=frame;self.labels=labels;self.hits=hits;self.data=data;self.frame_id+=1;self.error=''
                last=key
            except Exception as exc:self.error=str(exc)

    def drag_begin(self,x,y):self.origin=(self.yaw,self.tilt)

    def drag_move(self,sx,sy,x,y):
        if not self.w.ui.contains(BOX,sx,sy) or abs(x-sx)+abs(y-sy)<10:return
        self.w.dragged=True;self.yaw=(self.origin[0]+(x-sx)*.35)%360;self.tilt=max(8,min(90,self.origin[1]+(y-sy)*.25));self.wake.set()

    def tap(self,x,y):
        if not self.w.ui.contains(BOX,x,y):return
        with self.lock:hits=self.hits
        near=sorted((math.hypot(px+BOX[0]-x,py+BOX[1]-y),label,aircraft) for px,py,label,aircraft in hits)
        if near and near[0][0]<24:
            self.detail=near[0][1]
            if near[0][2]:self.aircraft=near[0][2];self.wake.set()

    def action(self,kind,value):
        if kind=='coverage_mode':self.mode=value;self.detail='Drag to rotate · tap a cell or position to inspect'
        elif kind=='coverage_signal':self.signal=not self.signal
        elif kind=='coverage_reset':self.yaw=0;self.tilt=55;self.aircraft=None;self.detail='All aircraft · drag to rotate'
        elif kind=='coverage_turn':self.yaw=(self.yaw+value)%360
        elif kind=='coverage_tilt':self.tilt=max(8,min(90,self.tilt+value))
        self.wake.set()

    def button(self,cache,box,title,kind,value=None,active=False):
        w=self.w;w.surface(box,(14,31,48,255) if not active else (25,57,90,255),(54,82,111,255),7)
        w.ink(cache,(box[0]+box[2])/2,(box[1]+box[3])/2,title,20,TEXT,anchor='cm',width=box[2]-box[0]-20)
        w.actions.append((box,(kind,value)))

    def draw(self,cache,state):
        w=self.w;ui=w.ui;ui.draw_logical_rect(0,0,1280,800,(0,0,0,255))
        w.ink(cache,24,27,'AIRSPACE / RECEPTION DOME',25,TEXT)
        with self.lock:data=self.data;frame=self.frame;labels=self.labels;identity=self.frame_id
        meta=data.get('meta',{});count=meta.get('retained_positions',0)
        summary=f"{count:,} positions · {meta.get('positioned_aircraft',0)} aircraft · up to 90 days"
        w.ink(cache,24,61,summary,18,MUTED)
        self.button(cache,(1024,16,1256,78),'Back to traffic','map_view')
        for box,title,kind,value,active in (((24,96,218,152),'Sky cells','coverage_mode','cells',self.mode=='cells'),((230,96,424,152),'Sky trails','coverage_mode','trails',self.mode=='trails'),((436,96,654,152),'True 3D distance','coverage_mode','space',self.mode=='space'),((666,96,912,152),'Signal' if not self.signal else 'Signal colour ON','coverage_signal',None,self.signal),((924,96,1124,152),'All aircraft','coverage_reset',None,False),((1136,96,1256,152),'Site','usb',None,False)):
            self.button(cache,box,title,kind,value,active)
        r=meta.get('horizontal_range_max_km',0);alt=meta.get('max_altitude_ft')
        for i,(label,value) in enumerate((('RX HORIZONTAL RADIUS',f'{r:.2f} km'),('DIAMETER · 2 × R',f'{2*r:.2f} km'),('MAX SLANT RANGE',f"{meta.get('slant_range_max_km',0):.2f} km"),('HIGHEST RECEIVED',f'{alt:,.0f} ft' if alt is not None else '—'))):
            x=24+i*312;w.surface((x,168,x+296,230),(4,11,19,255),(28,47,66,255),7);w.ink(cache,x+14,185,label,12,MUTED);w.ink(cache,x+14,213,value,24,(176,213,255))
        if frame is not None:
            gl=ui.GL
            if self.texture is None:self.texture=gl.glGenTextures(1)
            if identity!=self.uploaded:
                gl.glBindTexture(gl.GL_TEXTURE_2D,self.texture)
                for flag in (gl.GL_TEXTURE_MIN_FILTER,gl.GL_TEXTURE_MAG_FILTER):gl.glTexParameteri(gl.GL_TEXTURE_2D,flag,gl.GL_LINEAR)
                gl.glTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA,WIDTH,HEIGHT,0,gl.GL_RGBA,gl.GL_UNSIGNED_BYTE,frame);self.uploaded=identity
            ui.draw_textured_quad(self.texture,*BOX,0,0,1,1)
            for x,y,text,size,color in labels:w.ink(cache,BOX[0]+x,BOX[1]+y,text,size,color,anchor='cm')
        if self.error or w.manager.coverage_error or data.get('status') in (None,'LOADING','EMPTY','NO SITE'):
            text=self.error or w.manager.coverage_error or {'EMPTY':'No positioned aircraft retained yet.','NO SITE':'Set antenna latitude / longitude in Receiver.'}.get(data.get('status'),'Loading reception history…')
            w.ink(cache,640,464,text,22,MUTED,anchor='cm',width=1100)
        w.ink(cache,34,256,'TRUE DISTANCE · NO VERTICAL EXAGGERATION' if self.mode=='space' else 'ANGULAR SKY · 90° ZENITH',13,MUTED)
        for box,title,kind,value in (((24,636,126,692),'− 30°','coverage_turn',-30),((138,636,240,692),'+ 30°','coverage_turn',30),((1040,636,1142,692),'Tilt −','coverage_tilt',-10),((1154,636,1256,692),'Tilt +','coverage_tilt',10)):
            self.button(cache,box,title,kind,value)
        w.ink(cache,24,718,self.detail,18,TEXT,width=1232)
        w.ink(cache,24,750,'BLUE · RECEIVED     GREY · UNOBSERVED / UNKNOWN     Radius = furthest horizontal position; 2 × R is a scale.',15,MUTED,width=1232)
        site=meta.get('reference');reference=f"{site['lat']:.5f}°, {site['lon']:.5f}°" if site else 'SITE NOT SET'
        h=f"{meta.get('reference_height_m',0):g} m ellipsoid height" if meta.get('reference_height_known') else 'Height unknown; 0 m assumed · Settings / Radio info'
        w.ink(cache,24,783,reference+' · '+h,13,MUTED,width=1000)
        w.ink(cache,1256,783,'HISTORY · '+state['status'],13,MUTED,anchor='rm')
