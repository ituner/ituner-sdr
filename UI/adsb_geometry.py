"""Small camera-support meshes, computed once rather than on every gesture."""
import numpy as np


def enu_positions(rows,site,origin):
    """Rotate a whole history in NumPy rather than running WGS84 trig per row."""
    values=np.asarray([(r[2],r[3],r[4]*.3048) for r in rows],dtype=np.float64)
    latitude=np.deg2rad(values[:,0]);longitude=np.deg2rad(values[:,1]);height=values[:,2]
    sine=np.sin(latitude);cosine=np.cos(latitude);n=6378137/np.sqrt(1-6.6943799901413165e-3*sine*sine)
    x=(n+height)*cosine*np.cos(longitude)-origin[0];y=(n+height)*cosine*np.sin(longitude)-origin[1];z=(n*(1-6.6943799901413165e-3)+height)*sine-origin[2]
    p,l=np.deg2rad([site['lat'],site['lon']]);sp,cp,sl,cl=np.sin(p),np.cos(p),np.sin(l),np.cos(l)
    return np.column_stack((-sl*x+cl*y,-sp*cl*x-sp*sl*y+cp*z,cp*cl*x+cp*sl*y+sp*z)).tolist()


def camera_hull(vertices):
    points=np.asarray(vertices,dtype=np.float32).reshape(-1,3)
    if len(points)<=2048:return points
    try:
        from scipy.spatial import ConvexHull, QhullError
        try:return points[ConvexHull(points).vertices]
        except QhullError:pass
    except ImportError:pass
    # Conservative eight-corner fallback still contains every received position.
    low=points.min(axis=0);high=points.max(axis=0)
    return np.asarray([(x,y,z) for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])],dtype=np.float32)
