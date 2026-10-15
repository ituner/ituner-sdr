"""Retain the real Home framebuffer on the GPU for the appearance picker."""


class LiveHomeFrame:
    def __init__(self, ui):
        self.ui = ui
        gl = ui.GL
        self.texture = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, ui.NATIVE_W, ui.NATIVE_H,
                        0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)

    def capture(self):
        ui, gl = self.ui, self.ui.GL
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, 0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glCopyTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, 0, 0, ui.NATIVE_W, ui.NATIVE_H)

    def draw(self, box):
        ui, gl = self.ui, self.ui.GL
        x0, y0, x1, y1 = box
        gl.glEnable(gl.GL_TEXTURE_2D)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glDisable(gl.GL_BLEND)
        gl.glColor4f(1, 1, 1, 1)
        gl.glBegin(gl.GL_QUADS)
        for sx, sy, dx, dy in ((0, 0, x0, y0), (1280, 0, x1, y0),
                               (1280, 800, x1, y1), (0, 800, x0, y1)):
            nx, ny = ui.logical_to_native(sx, sy)
            gl.glTexCoord2f(nx / ui.NATIVE_W, 1 - ny / ui.NATIVE_H)
            gl.glVertex2f(*ui.logical_to_native(dx, dy))
        gl.glEnd()
        gl.glEnable(gl.GL_BLEND)

    def close(self):
        self.ui.GL.glDeleteTextures([self.texture])
