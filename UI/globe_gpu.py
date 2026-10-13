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


class MotionDetail:
    """Hide HD overlays during fast motion, with hysteresis to prevent flicker."""
    def __init__(self):
        self.previous = None
        self.reduced = False
        self.last_fast = -math.inf

    def update(self, yaw, pitch, radius, now, interactive):
        previous = self.previous
        self.previous = (yaw, pitch, radius, now)
        if not interactive or previous is None or not 0 < now - previous[3] < 0.25:
            self.reduced = False
            self.last_fast = -math.inf
            return False
        old_yaw, old_pitch, old_radius, old_time = previous
        # Wrap longitude so crossing the dateline is not a sudden full turn.
        dyaw = (yaw - old_yaw + math.pi) % math.tau - math.pi
        distance = max(radius, old_radius) * math.hypot(
            dyaw * math.cos((pitch + old_pitch) / 2), pitch - old_pitch)
        speed = max(distance, abs(radius - old_radius)) / (now - old_time)
        if speed >= (120 if self.reduced else 180):
            self.reduced = True
            self.last_fast = now
        elif now - self.last_fast >= 0.18:
            self.reduced = False
        return self.reduced


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


def border_data(paths):
    """Build disconnected line segments once; never join separate islands/rings."""
    data = array('f')
    seen = set()
    for path in paths:
        previous = None
        for lat, lon in path:
            lat, lon = math.radians(lat), math.radians(lon)
            point = (math.cos(lat)*math.sin(lon), math.sin(lat), math.cos(lat)*math.cos(lon))
            if previous is not None:
                # Shared national boundaries must not become twice as bright.
                edge = tuple(sorted((tuple(round(v, 7) for v in previous),
                                     tuple(round(v, 7) for v in point))))
                if edge[0] != edge[1] and edge not in seen:
                    seen.add(edge)
                    data.extend(previous)
                    data.extend(point)
            previous = point
    return data


class GlobeBorders:
    def __init__(self, paths):
        # CPU geometry is prepared during UI startup, not on the first swipe.
        self.data = border_data(paths)
        self.buffer = None

    def draw(self, matrix, color):
        if not self.data:
            return
        GL.glPushAttrib(GL.GL_ENABLE_BIT | GL.GL_CURRENT_BIT | GL.GL_TRANSFORM_BIT
                        | GL.GL_LINE_BIT | GL.GL_COLOR_BUFFER_BIT)
        GL.glPushClientAttrib(GL.GL_CLIENT_VERTEX_ARRAY_BIT)
        GL.glPushMatrix()
        try:
            if self.buffer is None:
                self.buffer = GL.glGenBuffers(1)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.buffer)
                payload = self.data.tobytes()
                GL.glBufferData(GL.GL_ARRAY_BUFFER, len(payload), payload, GL.GL_STATIC_DRAW)
            else:
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.buffer)
            GL.glDisable(GL.GL_TEXTURE_2D)
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glEnable(GL.GL_LINE_SMOOTH)
            GL.glLineWidth(1.0)
            GL.glColor4f(*(v/255 for v in color))
            GL.glClipPlane(GL.GL_CLIP_PLANE0, (0.0, 0.0, 1.0, 0.0))
            GL.glEnable(GL.GL_CLIP_PLANE0)
            GL.glMultMatrixf(matrix)
            GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)
            GL.glDisableClientState(GL.GL_COLOR_ARRAY)
            GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
            GL.glVertexPointer(3, GL.GL_FLOAT, 0, ctypes.c_void_p(0))
            GL.glDrawArrays(GL.GL_LINES, 0, len(self.data)//3)
        finally:
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
            GL.glPopMatrix()
            GL.glPopClientAttrib()
            GL.glPopAttrib()


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
