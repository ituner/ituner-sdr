"""Historical maximum reception range by bearing; never fills unobserved sectors."""
import math
from station_profile import distance_m

SECTOR_DEGREES=5


def destination(site,bearing,radius):
    a=math.radians(bearing);p=math.radians(site['lat']);l=math.radians(site['lon']);d=radius/6371000
    q=math.asin(max(-1,min(1,math.sin(p)*math.cos(d)+math.cos(p)*math.sin(d)*math.cos(a))))
    lon=l+math.atan2(math.sin(a)*math.sin(d)*math.cos(p),math.cos(d)-math.sin(p)*math.sin(q))
    return dict(lat=math.degrees(q),lon=(math.degrees(lon)+180)%360-180,east=radius*math.sin(a),north=radius*math.cos(a))


def build_footprint(site,rows):
    """Use the complete retained, site-filtered observations, before dot thinning."""
    empty=dict(sector_degrees=SECTOR_DEGREES,site=site,sectors=[],regions=[])
    if not site:return empty
    buckets={}
    for lat,lon in rows:
        p,q=math.radians(site['lat']),math.radians(lat);d=math.radians(lon-site['lon'])
        bearing=math.degrees(math.atan2(math.sin(d)*math.cos(q),math.cos(p)*math.sin(q)-math.sin(p)*math.cos(q)*math.cos(d)))%360
        radius=distance_m(site,dict(lat=lat,lon=lon))
        if radius<1:continue
        index=int(bearing//SECTOR_DEGREES);cell=buckets.setdefault(index,[0,0]);cell[0]=max(cell[0],radius);cell[1]+=1
    return footprint_from_peaks(site,buckets)


def footprint_from_peaks(site,buckets):
    """Render persisted maxima without needing to retain every old observation."""
    if not site or not buckets:return dict(sector_degrees=SECTOR_DEGREES,site=site,sectors=[],regions=[])
    count=360//SECTOR_DEGREES
    # Start after an unobserved direction so a run crossing north stays joined.
    start=next(((i+1)%count for i in range(count) if i not in buckets),0)
    runs=[];run=[];sectors=[]
    for offset in range(count):
        index=(start+offset)%count
        if index not in buckets:
            if run:runs.append(run);run=[]
            continue
        radius,positions=buckets[index];az=index*SECTOR_DEGREES
        arc=[destination(site,b,radius) for b in (az,az+SECTOR_DEGREES/2,az+SECTOR_DEGREES)]
        sectors.append(dict(azimuth_deg=az,radius_m=round(radius,2),positions=positions))
        run.extend(arc)
    if run:runs.append(run)
    center=dict(lat=site['lat'],lon=site['lon'],east=0,north=0)
    regions=[dict(vertices=[center,*run,center],outline=([*run,run[0]] if len(buckets)==count else [center,*run,center])) for run in runs]
    return dict(sector_degrees=SECTOR_DEGREES,site=site,sectors=sorted(sectors,key=lambda s:s['azimuth_deg']),regions=regions)


def projected_frame(regions,project):
    """Prepare a small cached 2D mesh for the native globe, behind its traffic."""
    import numpy as np
    triangles=[];lines=[]
    for region in regions:
        polygon=[project(p) for p in region['vertices']];outline=[project(p) for p in region['outline']]
        if not all(p is not None for p in polygon+outline):continue
        for i in range(1,len(polygon)-1):triangles.extend((polygon[0][:2],polygon[i][:2],polygon[i+1][:2]))
        for a,b in zip(outline,outline[1:]):lines.extend((a[:2],b[:2]))
    batches=[];line_widths={}
    for kind,vertices,rgba,width in (('triangles',triangles,(152/255,116/255,237/255,.24),0),
                                     ('lines',lines,(16/255,18/255,35/255,.85),5),
                                     ('lines',lines,(210/255,186/255,1,.95),2)):
        if vertices:
            if width:line_widths[len(batches)]=width
            batches.append((kind,np.asarray(vertices,dtype=np.float32),np.tile(rgba,(len(vertices),1)).astype(np.float32)))
    return dict(batches=batches,native=None,line_widths=line_widths)
