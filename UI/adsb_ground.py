"""Cached ENU ground-map patches from the existing GLOBE imagery and tile cache."""
from collections import OrderedDict
import hashlib
from io import BytesIO
import math
import threading
import time
import numpy as np
from PIL import Image
import globe_tiles

PIXELS=512


def ground_coordinates(site,east,north):
    """Intersect receiver east/north coordinates with the WGS84 ellipsoid."""
    lat,lon=math.radians(site['lat']),math.radians(site['lon'])
    sp,cp,sl,cl=math.sin(lat),math.cos(lat),math.sin(lon),math.cos(lon)
    e2=6.6943799901413165e-3;a=6378137.;b=a*math.sqrt(1-e2)
    n=a/math.sqrt(1-e2*sp*sp)
    x=n*cp*cl-east*sl-north*sp*cl;y=n*cp*sl+east*cl-north*sp*sl;z=n*(1-e2)*sp+north*cp
    ux,uy,uz=cp*cl,cp*sl,sp
    aa=(ux*ux+uy*uy)/a**2+uz*uz/b**2
    bb=2*((x*ux+y*uy)/a**2+z*uz/b**2)
    cc=(x*x+y*y)/a**2+z*z/b**2-1
    u=-2*cc/(bb+np.sqrt(np.maximum(0,bb*bb-4*aa*cc)))
    x,y,z=x+u*ux,y+u*uy,z+u*uz
    p=np.hypot(x,y);phi=np.arctan2(z,p*(1-e2))
    for _ in range(5):phi=np.arctan2(z+e2*a/np.sqrt(1-e2*np.sin(phi)**2)*np.sin(phi),p)
    return np.degrees(phi),np.degrees(np.arctan2(y,x))


def tile_keys(lat,lon):
    """At most sixteen geographic GIBS tiles, including the date-line seam."""
    for level in range(globe_tiles.MAX_LEVEL,1,-1):
        span=288/(1<<level);rows=np.clip(np.floor((90-lat)/span).astype(int),0,math.ceil(180/span)-1);cols=np.floor((lon+180)/span).astype(int)%round(360/span)
        # Include every actually sampled tile, not only corner approximations.
        pairs=set(map(tuple,np.unique(np.stack((rows.ravel(),cols.ravel()),axis=1),axis=0)))
        if len(pairs)<=16:break
    return tuple(globe_tiles.TileKey(level,int(row),int(col)) for row,col in sorted(pairs))


def raster(site,radius,base,tiles,pixels=PIXELS):
    axis=np.linspace(-radius,radius,pixels);east,north=np.meshgrid(axis,axis[::-1])
    lat,lon=ground_coordinates(site,east,north)
    h,w=base.shape[:2];iy=np.clip(((90-lat)/180*h).astype(int),0,h-1);ix=((lon+180)/360*w).astype(int)%w
    rgb=base[iy,ix].copy()
    for key,image in tiles:
        west,south,east_bound,north_bound=key.bounds
        mask=(lon>=west)&(lon<east_bound)&(lat>south)&(lat<=north_bound)
        if not mask.any():continue
        data=np.asarray(image);th,tw=data.shape[:2]
        x=np.clip(((lon[mask]-west)/key.span*tw).astype(int),0,tw-1);y=np.clip(((north_bound-lat[mask])/key.span*th).astype(int),0,th-1)
        rgb[mask]=data[y,x,:3]
    alpha=np.clip((radius-np.hypot(east,north))/(2*radius/pixels),0,1)*255
    return Image.fromarray(np.dstack((rgb,alpha.astype(np.uint8))),'RGBA'),lat,lon


class GroundMap:
    """One background renderer; two map patches, no work on decoder/draw threads."""
    def __init__(self,globe):
        self.globe=globe;self.lock=threading.Lock();self.wake=threading.Event();self.closed=threading.Event()
        self.frames=OrderedDict();self.request=None;self.thread=None;self.base=None;self.revision=0

    def snapshot(self,site,radius):
        if not isinstance(site,dict) or not all(isinstance(site.get(k),(int,float)) and math.isfinite(site[k]) for k in ('lat','lon')) or not -90<=site['lat']<=90 or not -180<=site['lon']<=180:
            return dict(status='NO SITE')
        if not isinstance(radius,(int,float)) or not math.isfinite(radius) or not 5000<=radius<=2_000_000:raise ValueError('Invalid ground-map radius')
        site={k:round(site[k],5) for k in ('lat','lon')};radius=int(math.ceil(radius/5000)*5000)
        key=hashlib.sha256(f"{site['lat']}:{site['lon']}:{radius}".encode()).hexdigest()[:20]
        with self.lock:
            previous=self.request
            self.request=(key,site,radius,time.monotonic())
            if self.thread is None:
                self.thread=threading.Thread(target=self._worker,name='adsb-ground-map',daemon=True);self.thread.start()
            if previous is None or previous[0]!=key:self.wake.set()
            frame=self.frames.get(key)
            return dict(frame['info']) if frame else dict(status='LOADING',key=key,reference=site,radius=radius)

    def image(self,key,raw=False):
        with self.lock:
            frame=self.frames.get(key)
            return frame['rgba' if raw else 'png'] if frame else None

    def _worker(self):
        last=None;ready_ids=();last_build=0
        while not self.closed.is_set():
            self.wake.wait(1);self.wake.clear()
            with self.lock:request=self.request
            if not request or time.monotonic()-request[3]>15:continue
            key,site,radius,_=request
            try:
                if self.base is None:
                    with Image.open(self.globe.assets/'nasa-blue-marble-2048.jpg') as image:self.base=np.asarray(image.convert('RGB'))
                if key!=last:
                    axis=np.linspace(-radius,radius,33);east,north=np.meshgrid(axis,axis)
                    lat,lon=ground_coordinates(site,east,north);keys=tile_keys(lat,lon);last=key;ready_ids=();last_build=0
                with self.globe.lock:
                    if self.globe.fetcher is None:self.globe.fetcher=globe_tiles.GlobeTileFetcher(memory_limit=32,workers=2,cache_dir=globe_tiles.default_cache_dir())
                    self.globe.fetcher.prefetch(keys);available=[(k,self.globe.fetcher.ready(k)) for k in keys];available=[(k,b) for k,b in available if b]
                ids=tuple(k for k,_ in available)
                with self.lock:cached=self.frames.get(key)
                if cached and cached.get('tile_ids')==ids:continue
                if last_build and time.monotonic()-last_build<2:continue
                tiles=[]
                for k,body in available:
                    try:
                        with Image.open(BytesIO(body)) as image:tiles.append((k,image.convert('RGB')))
                    except (OSError,ValueError):pass
                image,_,_=raster(site,radius,self.base,tiles);buf=BytesIO();image.save(buf,format='PNG')
                self.revision+=1
                info=dict(status='READY',key=key,reference=site,radius=radius,width=PIXELS,height=PIXELS,revision=self.revision,quality='Regional satellite' if tiles else 'World imagery · loading regional detail',attribution='NASA Blue Marble / GIBS',surface='Flat map reference; terrain elevation is not modelled')
                with self.lock:
                    self.frames[key]=dict(info=info,png=buf.getvalue(),rgba=image.tobytes(),tile_ids=ids);self.frames.move_to_end(key)
                    while len(self.frames)>2:self.frames.popitem(last=False)
                ready_ids=ids;last_build=time.monotonic()
            except (OSError,ValueError):
                # Retry only on the background worker; existing patches remain usable.
                self.closed.wait(2)

    def close(self):self.closed.set();self.wake.set()
