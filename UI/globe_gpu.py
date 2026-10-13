"""Cached GPU geometry for the compatibility-OpenGL globe renderer.

No network or UI dependencies. Geometry and sunlight colors are uploaded once;
view rotation and clipping happen on the GPU. New tile uploads are managed by
caller so dragging never waits for JPEG decoding.
"""
from array import array
from collections import OrderedDict
import ctypes
import math
from OpenGL import GL


def view_matrix(yaw, pitch, radius, center, native_point):
    """Column-major world-sphere -> native display transform.

World axes: x=cos(lat)*sin(lon), y=sin(lat), z=cos(lat)*cos(lon).
The orthographic projection keeps front-facing depth positive.
"""
    sy, cy = math.sin(yaw), math.cos(yaw)
    sp, cp = math.sin(pitch), math.cos(pitch)
    cx, ly = center
    nx, ny = native_point(cx, ly)
    xx, xy = native_point(cx + 1, ly)
    yx, yy = native_point(cx, ly + 1)
    dx, dy = (xx - nx, xy - ny), (yx - nx, yy - ny)
    right = (cy, 0.0, -sy)
    up = (-sp * sy, cp, -sp * cy)
    depth = (cp * sy, sp, cp * cy)
    matrix = []
    for i in range(3):
        matrix.extend((radius * (dx[0] * right[i] - dy[0] * up[i]),
                       radius * (dx[1] * right[i] - dy[1] * up[i]),
                       0.5 * depth[i], 0.0))
    matrix.extend((nx, ny, 0.0, 1.0))
    return matrix


def mesh_data(bounds, columns, rows, sun_lon, sun_lat):
    """Interleaved XYZ / UV / RGBA; one continuous mesh per image."""
    west, south, east, north = bounds
    ss, cs = math.sin(sun_lat), math.cos(sun_lat)
    grid = []
    for row in range(rows + 1):
        v = row / rows
        latitude = north + (south - north) * v
        lat = math.radians(latitude)
        sl, cl = math.sin(lat), math.cos(lat)
        points = []
        for col in range(columns + 1):
            u = col / columns
            lon = math.radians(west + (east - west) * u)
            illumination = sl * ss + cl * cs * math.cos(lon - sun_lon)
            light = min(1.0, max(0.0, (illumination + 0.16) / 0.34))
            light = light * light * (3.0 - 2.0 * light)
            twilight = math.exp(-((illumination - 0.025) / 0.115) ** 2)
            points.append((cl * math.sin(lon), sl, cl * math.cos(lon), u, v,
                           0.16 + 0.84 * light + 0.15 * twilight,
                           0.22 + 0.78 * light + 0.06 * twilight,
                           0.41 + 0.59 * light, 1.0))
        grid.append(points)
    data = array('f')
    for row in range(rows):
        for col in range(columns):
            for vertex in (grid[row][col], grid[row][col + 1],
                           grid[row + 1][col + 1], grid[row + 1][col]):
                data.extend(vertex)
    return data


class GlobeMeshes:
    def __init__(self, limit=32):
        self.limit = limit
        self.cache = OrderedDict()

    def draw(self, key, texture, bounds, columns, rows, matrix, sun, now, interactive):
        entry = self.cache.get(key)
        # Recolor at most once per minute, only when stationary. Rotating never
        # recalculates lighting or rebuilds a warmed mesh.
        if entry is None or (not interactive and now - entry[2] >= 60.0):
            data = mesh_data(bounds, columns, rows, *sun)
            buffer = entry[0] if entry else GL.glGenBuffers(1)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buffer)
            payload = data.tobytes()
            try:
                GL.glBufferData(GL.GL_ARRAY_BUFFER, len(payload), payload, GL.GL_STATIC_DRAW)
            finally:
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            entry = (buffer, len(data) // 9, now)
            self.cache[key] = entry
        self.cache.move_to_end(key)
        while len(self.cache) > self.limit:
            _, old = self.cache.popitem(last=False)
            GL.glDeleteBuffers(1, [old[0]])
        # Preserve fixed-function state for the rest of the SDR interface.
        GL.glPushAttrib(GL.GL_ENABLE_BIT | GL.GL_CURRENT_BIT | GL.GL_TRANSFORM_BIT)
        GL.glPushClientAttrib(GL.GL_CLIENT_VERTEX_ARRAY_BIT)
        GL.glPushMatrix()
        try:
            GL.glEnable(GL.GL_TEXTURE_2D)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
            # Define the front hemisphere in view space, before world rotation.
            GL.glClipPlane(GL.GL_CLIP_PLANE0, (0.0, 0.0, 1.0, 0.0))
            GL.glEnable(GL.GL_CLIP_PLANE0)
            GL.glMultMatrixf(matrix)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, entry[0])
            GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
            GL.glEnableClientState(GL.GL_TEXTURE_COORD_ARRAY)
            GL.glEnableClientState(GL.GL_COLOR_ARRAY)
            GL.glVertexPointer(3, GL.GL_FLOAT, 36, ctypes.c_void_p(0))
            GL.glTexCoordPointer(2, GL.GL_FLOAT, 36, ctypes.c_void_p(12))
            GL.glColorPointer(4, GL.GL_FLOAT, 36, ctypes.c_void_p(20))
            GL.glDrawArrays(GL.GL_QUADS, 0, entry[1])
        finally:
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            GL.glPopMatrix()
            GL.glPopClientAttrib()
            GL.glPopAttrib()
