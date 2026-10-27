"""Cached reception geometry and batched OpenGL drawing, without dome bitmaps."""
import math
from functools import lru_cache
import numpy as np

BLUE=(76/255,157/255,1); MUTED=(145/255,170/255,193/255)


def observation_info(data,index):
    p=data['points'][index];aircraft=data['aircraft'][p[1]]
    up=p[4]-(data.get('meta',{}).get('reference_height_m') or 0);horizontal=math.hypot(p[2],p[3])
    return dict(hex=aircraft['hex'],label=p[8] or aircraft['label'],time=data.get('base',0)+p[0],
                altitude=p[5],gnss=bool(p[7]),rssi=p[6],east=p[2],north=p[3],up=up,horizontal=horizontal/1000,
                slant=math.hypot(horizontal,up)/1000,azimuth=math.degrees(math.atan2(p[2],p[3]))%360,
                elevation=math.degrees(math.atan2(up,horizontal)))


def pick_observation(frame,x,y,radius=22):
    """Pick actual samples at dots, observed cells or anywhere along a trail."""
    candidates=[(math.hypot(px-x,py-y),-order,index) for order,(px,py,_label,_hex,index) in enumerate(frame.get('hits',[])) if index is not None]
    near=min(candidates,default=(float('inf'),0,None))
    if near[0]<8:return near[2]
    paths=frame.get('pick_segments')
    if paths is not None and len(paths):
        a=paths[:,0];v=paths[:,1]-a;q=np.asarray((x,y))-a
        t=np.clip(np.sum(q*v,axis=1)/np.maximum(np.sum(v*v,axis=1),1e-9),0,1)
        distances=np.linalg.norm(a+t[:,None]*v-(x,y),axis=1);i=int(np.argmin(distances))
        if distances[i]<min(radius,near[0]):return int(frame['pick_indices'][i,0 if t[i]<.5 else 1])
    return near[2] if near[0]<radius else None


def scene_scope(data):
    meta=data.get('meta',{});site=meta.get('reference') or {}
    return (meta.get('window_since'),site.get('lat'),site.get('lon'),meta.get('reference_height_m'))


def point_key(data,point):
    return (round(data.get('base',0)+point[0],3),data['aircraft'][point[1]]['hex'])


def new_point_keys(previous,data):
    """Only newly received samples glow; a filter/site change is not new RF."""
    if not previous or scene_scope(previous)!=scene_scope(data):return set()
    old={point_key(previous,p) for p in previous.get('points',[])}
    latest=max(previous.get('meta',{}).get('last_position') or 0,data.get('meta',{}).get('last_position') or 0)
    return {point_key(data,p) for p in data.get('points',[])
            if data.get('base',0)+p[0]>=latest-15 and point_key(data,p) not in old}


def vector(az,el,r=1):
    a,e=math.radians(az),math.radians(el)
    return (r*math.sin(a)*math.cos(e),r*math.cos(a)*math.cos(e),r*math.sin(e))


def sky_arc(a,b):
    """Keep trail connectors on the sky shell rather than cutting through it."""
    angle=math.acos(max(-1,min(1,sum(x*y for x,y in zip(a,b)))))
    steps=max(1,math.ceil(math.degrees(angle)/3));result=[]
    for i in range(steps+1):
        t=i/steps;sine=math.sin(angle)
        wa,wb=(math.sin((1-t)*angle)/sine,math.sin(t*angle)/sine) if abs(sine)>1e-7 else (1-t,t)
        v=tuple(wa*x+wb*y for x,y in zip(a,b));length=math.sqrt(sum(x*x for x in v))
        result.append(tuple(x/length for x in v) if length>1e-8 else (0,0,1))
    return result


def distance_step(radius, divisions):
    """Choose a readable metric interval rather than labelling every 5 km."""
    target=radius/max(1,divisions);unit=10**math.floor(math.log10(target))
    return next(n*unit for n in (1,2,2.5,5,10) if n*unit>=target)


def distance_ticks(radius, pixels):
    """One radial scale, with at least 72 px between its number labels."""
    step=distance_step(radius,max(1,min(4,int(pixels/72))))
    ticks=list(np.arange(step,radius,step))
    if ticks and (radius-ticks[-1])/radius*pixels<72:ticks.pop()
    return ticks+[radius]


def space_height_scale(radius, highest, expanded):
    return max(1,min(12,math.floor(.7*radius/max(1000,highest)*2)/2)) if expanded else 1


def space_frame(vertices, highest, yaw, tilt, width, height):
    """Fit the ground disk, height axis and every aircraft with one uniform zoom."""
    a,t=math.radians(yaw),math.radians(tilt);sa,ca,st,ct=math.sin(a),math.cos(a),math.sin(t),math.cos(t)
    low=np.asarray((-1.1,-1.1*st),dtype=float);high=-low
    if len(vertices):
        v=np.asarray(vertices);q=np.stack((v[:,0]*ca-v[:,1]*sa,-(v[:,0]*sa+v[:,1]*ca)*st-v[:,2]*ct),axis=1)
        low=np.minimum(low,q.min(axis=0));high=np.maximum(high,q.max(axis=0))
    low[1]=min(low[1],-highest*ct)
    scale=min(max(1,width-72)/(high[0]-low[0]),max(1,height-140)/max(.1,high[1]-low[1]))
    center=np.asarray((width/2,height/2),dtype=np.float32)-(low+high)*scale/2
    return scale,center


@lru_cache(maxsize=1)
def sky_grid():
    cells=[(az,el) for el in range(0,90,2) for az in range(0,360,4)]
    vertices=np.asarray([[vector(a,e) for a,e in ((az+.22,el+.12),(az+3.78,el+.12),(az+3.78,el+1.88),(az+.22,el+1.88))] for az,el in cells],dtype=np.float32)
    return cells,vertices


def prepare(data,mode,signal=False,aircraft=None,new_points=(),expanded=True):
    """Build immutable world coordinates only when history or filters change."""
    meta=data.get('meta',{});names=data.get('aircraft',[]);height=meta.get('reference_height_m',0)
    radius=max(5000,math.ceil(max(meta.get('horizontal_range_max_km',0),(meta.get('max_altitude_ft') or 0)*.0003048)/5)*5000)
    selected=[p for p in data.get('points',[]) if not aircraft or names[p[1]]['hex']==aircraft]
    if aircraft:radius=max(5000,math.ceil(max([0]+[math.hypot(p[2],p[3])/1000 for p in selected])/5)*5000)
    highest=max([1000]+[p[4]-height for p in selected]);axis_height=math.ceil(highest/1000)*1000
    height_scale=space_height_scale(radius,axis_height,expanded) if mode=='space' else 1
    points=[];cells={};cell_samples={};lines=[];line_colours=[];labels=[];highlights=[];pick_paths=[];pick_indices=[]
    indexes={id(p):i for i,p in enumerate(data.get('points',[]))}
    for p in data.get('points',[]):
        if aircraft and names[p[1]]['hex']!=aircraft:continue
        up=p[4]-height;distance=math.hypot(p[2],p[3]);az=math.degrees(math.atan2(p[2],p[3]))%360;el=math.degrees(math.atan2(up,distance))
        world=(p[2]/radius,p[3]/radius,up/radius*height_scale) if mode=='space' else vector(az,el)
        label=f"{p[8] or names[p[1]]['label']} · {p[5]:,.0f} ft {'GNSS' if p[7] else 'BARO ≈'} · {distance/1000:.1f} km · {az:.0f}° az / {el:.1f}° el"
        points.append((p,world,el,label,names[p[1]]['hex']))
        if (mode=='space' or el>=0) and point_key(data,p) in new_points:highlights.append(world)
        if el>=0:
            cell_samples[(int(az//4)*4,min(88,int(el//2)*2))]=indexes[id(p)]
            cell=cells.setdefault((int(az//4)*4,min(88,int(el//2)*2)),[0,0,0,0]);cell[0]+=1
            if p[6] is not None:cell[1]+=p[6];cell[2]+=1
            cell[3]=max(cell[3],distance)
    if not aircraft:cells={(a,e):[count,level or 0,1 if level is not None else 0,d] for a,e,count,level,_,d in data.get('cells',[])}
    # Fixed scales keep unrelated new reception from dimming old cells.
    def colour(level,count=1):
        if signal and level is not None:s=.3+.7*max(0,min(1,(level+45)/45))
        else:s=.55+.45*(1-math.exp(-count/8))
        return (*[v*s for v in BLUE],1)
    def path(vertices,colour=(*MUTED,.3)):
        lines.extend(zip(vertices[:-1],vertices[1:]));line_colours.extend([colour]*(len(vertices)-1))
    if mode=='space':
        step=distance_step(radius,4)
        for distance in list(np.arange(step,radius,step))+[radius]:
            path([vector(a,0,distance/radius) for a in range(0,361,3)])
        for az in range(0,360,45):path([(0,0,0),vector(az,0)])
    else:
        for el in range(0,90,15):path([vector(a,el) for a in range(0,361,3)])
        for az in range(0,360,30):path([vector(az,e) for e in range(0,91,3)])
        for el in (30,60):labels.append((vector(90,el),f'{el}°',18,(145,170,193)))
    if mode!='cells':
        last={};breaks=data.get('breaks',[])
        confirmed={tuple(pair) for pair in data.get('segments',[])} if 'segments' in data else None
        for p,world,el,_,_ in points:
            previous=last.get(p[1]);last[p[1]]=(p,world)
            if previous:
                a,av=previous;dt=p[0]-a[0]
                joined=((indexes[id(a)],indexes[id(p)]) in confirmed if confirmed is not None else
                        0<dt<=15 and math.dist(a[2:5],p[2:5])<=500+400*dt and not any(data['base']+a[0]<t<=data['base']+p[0] for t in breaks))
                if joined and (mode=='space' or el>=0 and av[2]>=0):
                    vertices=[av,world] if mode=='space' else sky_arc(av,world)
                    path(vertices,(.24,.53,.9,1))
                    pick_paths.extend(zip(vertices[:-1],vertices[1:]));pick_indices.extend([(indexes[id(a)],indexes[id(p)])]*(len(vertices)-1))
    for name,az in (('N',0),('E',90),('S',180),('W',270)):labels.append((vector(az,0,1.10),name,23,(220,236,255)))
    labels.append(((0,0,-.08),'RECEIVER',16,(145,170,193)))
    result=dict(mode=mode,lines=np.asarray(lines,dtype=np.float32).reshape(-1,2,3),line_colours=np.asarray(line_colours,dtype=np.float32),labels=labels,meta=meta,radius=radius,height_scale=height_scale,axis_height=axis_height,pick_paths=np.asarray(pick_paths,dtype=np.float32).reshape(-1,2,3),pick_indices=np.asarray(pick_indices,dtype=np.int32).reshape(-1,2),highlights=np.asarray(highlights[-256:],dtype=np.float32).reshape(-1,3),highest=highest/radius*height_scale if mode=='space' else 1.06)
    if mode=='cells':
        keys,verts=sky_grid();colors=[];hits=[]
        for az,el in keys:
            cell=cells.get((az,el));colors.append(colour(cell[1]/cell[2] if cell[2] else None,cell[0]) if cell else (*MUTED,.047))
            index=cell_samples.get((az,el));hex=names[data['points'][index][1]]['hex'] if index is not None else None
            hits.append((f'{az}–{az+4}° az / {el}–{el+2}° el · {cell[0]} positions · max {cell[3]/1000:.1f} km',hex,index) if cell else (f'{az}–{az+4}° az / {el}–{el+2}° el · unobserved / unknown',None,None))
        result.update(cells=verts,colours=np.asarray(colors,dtype=np.float32),hit_labels=hits)
    else:
        visible=[p for p in points if mode=='space' or p[2]>=0]
        result.update(dots=np.asarray([p[1] for p in visible],dtype=np.float32).reshape(-1,3),colours=np.asarray([colour(p[0][6]) for p in visible],dtype=np.float32).reshape(-1,4),solid=np.asarray([bool(p[0][7]) for p in visible]),hit_labels=[(p[3],p[4],indexes[id(p[0])]) for p in visible])
    return result


def project(scene,yaw,tilt,width,height):
    """Vectorize rotation and depth ordering; no trigonometry per vertex."""
    a,t=math.radians(yaw),math.radians(tilt);sa,ca,st,ct=math.sin(a),math.cos(a),math.sin(t),math.cos(t)
    matrix=np.asarray(((ca,-sa,0),(-sa*st,-ca*st,-ct),(-sa*ct,-ca*ct,st)),dtype=np.float32)
    scale=min((width-72)/2,(height-94)/(1+st));center=np.asarray((width/2,height/2+scale*(1-st)/2+16),dtype=np.float32)
    if scene['mode']=='space':
        scale,center=space_frame(scene.get('dots',[]),scene['axis_height']/scene['radius']*scene['height_scale'],yaw,tilt,width,height)
    def rotate(vertices):return vertices@matrix.T
    def screen(vertices):return rotate(vertices)[...,:2]*scale+center
    batches=[];hits=[]
    if 'cells' in scene:
        rotated=rotate(scene['cells']);order=np.argsort(rotated[:,:,2].mean(axis=1),kind='stable')
        quads=rotated[order,:,:2]*scale+center
        batches.append(('triangles',quads[:,[0,1,2,0,2,3]].reshape(-1,2),np.repeat(scene['colours'][order],6,axis=0)))
        centers=quads.mean(axis=1)
        hits=[(float(x),float(y),*scene['hit_labels'][i]) for (x,y),i in zip(centers,order)]
    if len(scene['lines']):batches.append(('lines',screen(scene['lines']).reshape(-1,2),np.repeat(scene['line_colours'],2,axis=0)))
    if 'dots' in scene and len(scene['dots']):
        rotated=rotate(scene['dots']);order=np.argsort(rotated[:,2],kind='stable');centers=rotated[order,:2]*scale+center
        angles=np.arange(9,dtype=np.float32)*math.tau/8;offsets=np.stack((np.cos(angles),np.sin(angles)),axis=1)*3
        solid=scene['solid'][order];colors=scene['colours'][order]
        if solid.any():
            q=centers[solid];v=np.stack((np.broadcast_to(q[:,None,:],(len(q),8,2)),q[:,None,:]+offsets[:-1],q[:,None,:]+offsets[1:]),axis=2)
            batches.append(('triangles',v.reshape(-1,2),np.repeat(colors[solid],24,axis=0)))
        if (~solid).any():
            q=centers[~solid];v=np.stack((q[:,None,:]+offsets[:-1],q[:,None,:]+offsets[1:]),axis=2)
            batches.append(('lines',v.reshape(-1,2),np.repeat(colors[~solid],16,axis=0)))
        hits=[(float(x),float(y),*scene['hit_labels'][i]) for (x,y),i in zip(centers,order)]
    labels=[]
    for world,text,size,color in scene['labels']:
        x,y=screen(np.asarray(world,dtype=np.float32));labels.append((float(x),float(y),text,size,color))
    if scene['mode']=='space':
        # This screen-right radius lies on the ground plane for every camera
        # rotation. Keep the single ruler readable even when the disk is edge-on.
        x,y=map(float,center);ruler=[((x,y),(x+scale,y))]
        for distance in distance_ticks(scene['radius'],scale):
            px=x+distance/scene['radius']*scale
            ruler.append(((px,y-4),(px,y+5)))
            labels.append((px,y+19,f'{distance/1000:g}',18,(190,210,230)))
        labels.append((x+scale/2,y+43,'Ground range · km',16,(145,170,193)))
        vertices=np.asarray(ruler,dtype=np.float32).reshape(-1,2)
        batches.append(('lines',vertices,np.tile((.57,.67,.76,.85),(len(vertices),1)).astype(np.float32)))
        axis=scene['axis_height'];axis_world=axis/scene['radius']*scene['height_scale']
        top=screen(np.asarray((0,0,axis_world),dtype=np.float32));axis_pixels=abs(float(top[1])-y)
        if axis_pixels>90:
            for d in distance_ticks(axis,axis_pixels):
                px,py=screen(np.asarray((0,0,d/scene['radius']*scene['height_scale']),dtype=np.float32))
                labels.append((float(px)+38,float(py),f'{d/1000:g} km',16,(145,170,193)))
    meta=scene['meta'];alt=meta.get('max_altitude_ft')
    if alt is not None:
        world=np.asarray((0,0,scene['highest']),dtype=np.float32);x,y=screen(world)
        if scene['mode']=='space':
            axis_top=(0,0,scene['axis_height']/scene['radius']*scene['height_scale'])
            batches.append(('lines',screen(np.asarray(((0,0,0),axis_top),dtype=np.float32)),np.asarray(((.35,.48,.62,1),)*2,dtype=np.float32)))
        labels.extend(((width/2,max(28,float(y)-38),f'MAX ALT {alt:,.0f} ft / {alt*.0003048:.2f} km',23,(176,213,255)),(width/2,max(54,float(y)-12),f"{meta.get('max_altitude_source','')} · {meta.get('max_altitude_aircraft','')} · not necessarily overhead",15,(145,170,193))))
    pulse=np.empty((0,2),dtype=np.float32)
    if len(scene['highlights']):
        q=screen(scene['highlights']);angles=np.arange(13,dtype=np.float32)*math.tau/12
        offsets=np.stack((np.cos(angles),np.sin(angles)),axis=1)*7
        pulse=np.stack((q[:,None,:]+offsets[:-1],q[:,None,:]+offsets[1:]),axis=2).reshape(-1,2)
    return dict(batches=batches,labels=labels,hits=hits,native=None,pulse=pulse,pulse_native=None,
                pick_segments=screen(scene['pick_paths']),pick_indices=scene['pick_indices'],
                ground_quad=screen(np.asarray(((-1,1,0),(1,1,0),(1,-1,0),(-1,-1,0)),dtype=np.float32)),
                camera=(matrix,scale,center))


def draw(ui,frame,box,pulse_alpha=0):
    """A few array draw calls replace thousands of Python GL calls/bitmap upload."""
    origin=np.asarray(ui.logical_to_native(box[0],box[1]),dtype=np.float32)
    basis=np.asarray((np.asarray(ui.logical_to_native(box[0]+1,box[1]))-origin,np.asarray(ui.logical_to_native(box[0],box[1]+1))-origin),dtype=np.float32)
    key=tuple(origin)+tuple(basis.ravel())
    if frame['native'] is None or frame['native'][0]!=key:
        frame['native']=(key,[(kind,np.ascontiguousarray(vertices[:,0,None]*basis[0]+vertices[:,1,None]*basis[1]+origin,dtype=np.float32),np.ascontiguousarray(colors,dtype=np.float32)) for kind,vertices,colors in frame['batches']])
    gl=ui.GL;gl.glDisable(gl.GL_TEXTURE_2D);gl.glEnableClientState(gl.GL_VERTEX_ARRAY);gl.glEnableClientState(gl.GL_COLOR_ARRAY)
    try:
        gl.glLineWidth(1.2)
        for index,(kind,vertices,colors) in enumerate(frame['native'][1]):
            if kind=='lines':gl.glLineWidth(frame.get('line_widths',{}).get(index,1.2))
            gl.glVertexPointer(2,gl.GL_FLOAT,0,vertices);gl.glColorPointer(4,gl.GL_FLOAT,0,colors)
            gl.glDrawArrays(gl.GL_TRIANGLES if kind=='triangles' else gl.GL_LINES,0,len(vertices))
        pulse=frame.get('pulse',())
        if pulse_alpha>0 and len(pulse):
            if frame['pulse_native'] is None or frame['pulse_native'][0]!=key:
                frame['pulse_native']=(key,np.ascontiguousarray(pulse[:,0,None]*basis[0]+pulse[:,1,None]*basis[1]+origin,dtype=np.float32))
            vertices=frame['pulse_native'][1]
            gl.glDisableClientState(gl.GL_COLOR_ARRAY);gl.glColor4f(.65,1,.83,pulse_alpha)
            gl.glLineWidth(1.8);gl.glVertexPointer(2,gl.GL_FLOAT,0,vertices);gl.glDrawArrays(gl.GL_LINES,0,len(vertices))
    finally:
        gl.glLineWidth(1.2)
        gl.glDisableClientState(gl.GL_COLOR_ARRAY);gl.glDisableClientState(gl.GL_VERTEX_ARRAY);gl.glEnable(gl.GL_TEXTURE_2D)
        if pulse_alpha>0:gl.glColor4f(1,1,1,1)
