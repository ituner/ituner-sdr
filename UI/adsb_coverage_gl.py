"""Cached reception geometry and batched OpenGL drawing, without dome bitmaps."""
import math
from functools import lru_cache
import numpy as np

BLUE=(76/255,157/255,1); MUTED=(145/255,170/255,193/255)


def vector(az,el,r=1):
    a,e=math.radians(az),math.radians(el)
    return (r*math.sin(a)*math.cos(e),r*math.cos(a)*math.cos(e),r*math.sin(e))


@lru_cache(maxsize=1)
def sky_grid():
    cells=[(az,el) for el in range(0,90,2) for az in range(0,360,4)]
    vertices=np.asarray([[vector(a,e) for a,e in ((az+.22,el+.12),(az+3.78,el+.12),(az+3.78,el+1.88),(az+.22,el+1.88))] for az,el in cells],dtype=np.float32)
    return cells,vertices


def prepare(data,mode,signal=False,aircraft=None):
    """Build immutable world coordinates only when history or filters change."""
    meta=data.get('meta',{});names=data.get('aircraft',[]);height=meta.get('reference_height_m',0)
    radius=max(5000,math.ceil(max(meta.get('horizontal_range_max_km',0),(meta.get('max_altitude_ft') or 0)*.0003048)/5)*5000)
    points=[];cells={};lines=[];line_colours=[];labels=[]
    for p in data.get('points',[]):
        if aircraft and names[p[1]]['hex']!=aircraft:continue
        up=p[4]-height;distance=math.hypot(p[2],p[3]);az=math.degrees(math.atan2(p[2],p[3]))%360;el=math.degrees(math.atan2(up,distance))
        world=(p[2]/radius,p[3]/radius,up/radius) if mode=='space' else vector(az,el)
        label=f"{p[8] or names[p[1]]['label']} · {p[5]:,.0f} ft {'GNSS' if p[7] else 'BARO ≈'} · {distance/1000:.1f} km · {az:.0f}° az / {el:.1f}° el"
        points.append((p,world,el,label,names[p[1]]['hex']))
        if el>=0:
            cell=cells.setdefault((int(az//4)*4,min(88,int(el//2)*2)),[0,0,0,0]);cell[0]+=1
            if p[6] is not None:cell[1]+=p[6];cell[2]+=1
            cell[3]=max(cell[3],distance)
    if not aircraft:cells={(a,e):[count,level or 0,1 if level is not None else 0,d] for a,e,count,level,_,d in data.get('cells',[])}
    max_count=max([1]+[c[0] for c in cells.values()])
    def colour(level,count=1):
        if signal and level is not None:s=.3+.7*max(0,min(1,(level-meta.get('rssi_min',-40))/(meta.get('rssi_max',0)-meta.get('rssi_min',-40) or 1)))
        else:s=.55+.45*math.log1p(count)/math.log1p(max_count)
        return (*[v*s for v in BLUE],1)
    def path(vertices,colour=(*MUTED,.3)):
        lines.extend(zip(vertices[:-1],vertices[1:]));line_colours.extend([colour]*(len(vertices)-1))
    if mode=='space':
        for i in range(1,int(radius/5000)+1):
            r=i*5000/radius;path([vector(a,0,r) for a in range(0,361,3)]);labels.append((vector(95,0,r),f'{i*5} km',16,(145,170,193)))
        for az in range(0,360,45):path([(0,0,0),vector(az,0)])
    else:
        for el in range(0,90,15):path([vector(a,el) for a in range(0,361,3)])
        for az in range(0,360,30):path([vector(az,e) for e in range(0,91,3)])
        for el in (30,60):labels.append((vector(90,el),f'{el}°',18,(145,170,193)))
    if mode!='cells':
        last={};breaks=data.get('breaks',[])
        for p,world,el,_,_ in points:
            previous=last.get(p[1]);last[p[1]]=(p,world)
            if previous:
                a,av=previous;dt=p[0]-a[0]
                if 0<dt<=15 and math.dist(a[2:5],p[2:5])<=500+400*dt and not any(data['base']+a[0]<t<=data['base']+p[0] for t in breaks):
                    if mode=='space' or el>=0:path([av,world],(37/255,88/255,151/255,1))
    for name,az in (('N',0),('E',90),('S',180),('W',270)):labels.append((vector(az,0,1.10),name,23,(220,236,255)))
    labels.append(((0,0,-.08),'RECEIVER',16,(145,170,193)))
    result=dict(mode=mode,lines=np.asarray(lines,dtype=np.float32).reshape(-1,2,3),line_colours=np.asarray(line_colours,dtype=np.float32),labels=labels,meta=meta,radius=radius,highest=max([1000]+[p[4]-height for p,_,_,_,_ in points])/radius if mode=='space' else 1.06)
    if mode=='cells':
        keys,verts=sky_grid();colors=[];hits=[]
        for az,el in keys:
            cell=cells.get((az,el));colors.append(colour(cell[1]/cell[2] if cell[2] else None,cell[0]) if cell else (*MUTED,.047))
            hits.append((f'{az}–{az+4}° az / {el}–{el+2}° el · {cell[0]} positions · max {cell[3]/1000:.1f} km',None) if cell else (f'{az}–{az+4}° az / {el}–{el+2}° el · unobserved / unknown',None))
        result.update(cells=verts,colours=np.asarray(colors,dtype=np.float32),hit_labels=hits)
    else:
        visible=[p for p in points if mode=='space' or p[2]>=0]
        result.update(dots=np.asarray([p[1] for p in visible],dtype=np.float32).reshape(-1,3),colours=np.asarray([colour(p[0][6]) for p in visible],dtype=np.float32).reshape(-1,4),solid=np.asarray([bool(p[0][7]) for p in visible]),hit_labels=[(p[3],p[4]) for p in visible])
    return result


def project(scene,yaw,tilt,width,height):
    """Vectorize rotation and depth ordering; no trigonometry per vertex."""
    a,t=math.radians(yaw),math.radians(tilt);sa,ca,st,ct=math.sin(a),math.cos(a),math.sin(t),math.cos(t)
    matrix=np.asarray(((ca,-sa,0),(-sa*st,-ca*st,-ct),(-sa*ct,-ca*ct,st)),dtype=np.float32)
    scale=min((width-72)/2,(height-94)/(1+st));center=np.asarray((width/2,height/2+scale*(1-st)/2+16),dtype=np.float32)
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
    meta=scene['meta'];alt=meta.get('max_altitude_ft')
    if alt is not None:
        world=np.asarray((0,0,scene['highest']),dtype=np.float32);x,y=screen(world)
        if scene['mode']=='space':
            batches.append(('lines',screen(np.asarray(((0,0,0),world),dtype=np.float32)),np.asarray(((.35,.48,.62,1),)*2,dtype=np.float32)))
        labels.extend(((width/2,max(28,float(y)-38),f'MAX ALT {alt:,.0f} ft / {alt*.0003048:.2f} km',23,(176,213,255)),(width/2,max(54,float(y)-12),f"{meta.get('max_altitude_source','')} · {meta.get('max_altitude_aircraft','')} · not necessarily overhead",15,(145,170,193))))
    return dict(batches=batches,labels=labels,hits=hits,native=None)


def draw(ui,frame,box):
    """A few array draw calls replace thousands of Python GL calls/bitmap upload."""
    origin=np.asarray(ui.logical_to_native(box[0],box[1]),dtype=np.float32)
    basis=np.asarray((np.asarray(ui.logical_to_native(box[0]+1,box[1]))-origin,np.asarray(ui.logical_to_native(box[0],box[1]+1))-origin),dtype=np.float32)
    key=tuple(origin)+tuple(basis.ravel())
    if frame['native'] is None or frame['native'][0]!=key:
        frame['native']=(key,[(kind,np.ascontiguousarray(vertices[:,0,None]*basis[0]+vertices[:,1,None]*basis[1]+origin,dtype=np.float32),np.ascontiguousarray(colors,dtype=np.float32)) for kind,vertices,colors in frame['batches']])
    gl=ui.GL;gl.glDisable(gl.GL_TEXTURE_2D);gl.glEnableClientState(gl.GL_VERTEX_ARRAY);gl.glEnableClientState(gl.GL_COLOR_ARRAY)
    try:
        gl.glLineWidth(1.2)
        for kind,vertices,colors in frame['native'][1]:
            gl.glVertexPointer(2,gl.GL_FLOAT,0,vertices);gl.glColorPointer(4,gl.GL_FLOAT,0,colors)
            gl.glDrawArrays(gl.GL_TRIANGLES if kind=='triangles' else gl.GL_LINES,0,len(vertices))
    finally:
        gl.glDisableClientState(gl.GL_COLOR_ARRAY);gl.glDisableClientState(gl.GL_VERTEX_ARRAY);gl.glEnable(gl.GL_TEXTURE_2D)
