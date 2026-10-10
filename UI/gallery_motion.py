"""Finger-following gallery paging using two GPU-cached frames, no pixel readback."""
import time


class GalleryMotion:
    def __init__(self, workspace, mode, clock=time.monotonic):
        self.workspace=workspace;self.mode=mode;self.clock=clock
        self.bounds={'sstv':(0,80,1280,720),'hell':(0,80,1280,720),
                     'qrss':(0,72,1280,800),'cw':(0,150,1280,790)}[mode]
        self.height=self.bounds[3]-self.bounds[1]
        self.down=False;self.active=False;self.offset=0.;self.velocity=0.
        self.direction=0;self.animation=None;self.textures=[];self.old_state=None;self.target_state=None
        self.draw_original=workspace.draw;self.swipe_original=workspace.swipe
        self.close_original=workspace.close
        workspace.draw=self.draw;workspace.swipe=self.release
        workspace.drag_begin=self.begin;workspace.drag_move=self.move;workspace.close=self.close

    def state(self):
        return {k:getattr(self.workspace,k) for k in ('page','saved_view','visible_strips','history_open') if hasattr(self.workspace,k)}

    def restore(self,state):
        for key,value in state.items():setattr(self.workspace,key,value)

    def eligible(self,x,y):
        w=self.workspace
        if getattr(getattr(w,'log_search_view',None),'open',False):return False
        if not w.open or w.add_open or w.decoders_open or w.enlarged:return False
        if getattr(w,'field',None) is not None or getattr(w,'reporting',None) is not None:return False
        x0,y0,x1,y1=self.bounds
        return x0<=x<=x1 and y0<=y<=y1

    def begin(self,x,y):
        # A second gesture starts from the completed destination, not a half page.
        if self.animation:self.finish()
        self.down=self.eligible(x,y);self.active=False;self.offset=0;self.direction=0
        self.sx,self.sy=x,y;self.last_y=y;self.last_t=self.clock();self.velocity=0
        self.old_state=None;self.target_state=None

    def move(self,sx,sy,x,y):
        if not self.down:return
        dx,dy=x-self.sx,y-self.sy
        if not self.active:
            if abs(dy)<12 or abs(dy)<abs(dx)*1.5:return
            self.active=True;self.old_state=self.state()
        now=self.clock();dt=max(.001,now-self.last_t)
        instant=(y-self.last_y)/dt
        self.velocity=.5*self.velocity+.5*instant
        self.last_t,self.last_y=now,y
        direction=1 if dy<0 else -1
        if direction!=self.direction:
            self.direction=direction;self.target_state=None
        self.offset=max(-self.height*.95,min(self.height*.95,dy))

    def prepare(self):
        if self.target_state is not None:return
        self.restore(self.old_state)
        # Reuse each decoder's existing live/saved and page boundary rules.
        self.swipe_original(self.sx,self.sy,self.sx,self.sy-self.direction*100)
        self.target_state=self.state();self.restore(self.old_state)
        self.needs_capture=True

    def release(self,sx,sy,x,y):
        if not self.down:return self.swipe_original(sx,sy,x,y)
        if self.last_y!=y:self.move(sx,sy,x,y)
        self.down=False
        # Only consume gestures that actually started vertical paging. CW
        # horizontal tuning (and ordinary taps) belongs to the workspace.
        if not self.active:return self.swipe_original(sx,sy,x,y)
        self.prepare()
        changed=self.has_target()
        recent=self.clock()-self.last_t<.12
        flick=recent and abs(y-self.sy)>=24 and self.velocity*self.direction < -500
        commit=changed and (abs(y-self.sy)>=60 or flick)
        self.commit=commit
        start=self.display_offset()
        self.animation=(self.clock(),start,-self.direction*self.height if commit else 0.)
        return True

    def has_target(self):
        return any(self.target_state.get(k)!=v for k,v in self.old_state.items() if k!='visible_strips')

    def display_offset(self):
        return self.offset if self.has_target() else self.offset*.22

    def finish(self):
        if self.animation and self.commit:self.restore(self.target_state)
        self.animation=None;self.active=False;self.offset=0;self.old_state=None;self.target_state=None

    def capture(self,index):
        ui=self.workspace.ui;gl=ui.GL
        while len(self.textures)<=index:self.textures.append(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D,self.textures[index])
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_MIN_FILTER,gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D,gl.GL_TEXTURE_MAG_FILTER,gl.GL_LINEAR)
        gl.glCopyTexImage2D(gl.GL_TEXTURE_2D,0,gl.GL_RGBA,0,0,ui.NATIVE_W,ui.NATIVE_H,0)

    def paint(self,index,dy=0,content=False):
        ui=self.workspace.ui;gl=ui.GL
        ax,ay=ui.logical_to_native(0,0);bx,by=ui.logical_to_native(0,dy)
        dx,dy=bx-ax,by-ay
        gl.glEnable(gl.GL_TEXTURE_2D);gl.glBindTexture(gl.GL_TEXTURE_2D,self.textures[index]);gl.glColor4f(1,1,1,1)
        x0,y0,x1,y1=0,0,ui.NATIVE_W,ui.NATIVE_H
        if content:
            a,b,c,d=self.bounds
            corners=[ui.logical_to_native(x,y) for x,y in ((a,b),(c,b),(c,d),(a,d))]
            xs,ys=zip(*corners);x0,y0,x1,y1=min(xs),min(ys),max(xs),max(ys)
        gl.glBegin(gl.GL_QUADS)
        for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1)):
            u,v=x/ui.NATIVE_W,1-y/ui.NATIVE_H
            gl.glTexCoord2f(u,v);gl.glVertex2f(x+dx,y+dy)
        gl.glEnd()

    def draw(self,cache,*args):
        if not self.active:return self.draw_original(cache,*args)
        self.prepare()
        ui=self.workspace.ui;gl=ui.GL
        if self.needs_capture:
            actions=self.workspace.actions
            try:
                self.restore(self.old_state);self.draw_original(cache,*args);self.capture(0)
                self.restore(self.target_state);self.draw_original(cache,*args);self.capture(1)
            finally:
                self.restore(self.old_state);self.workspace.actions=actions
            self.needs_capture=False
        offset=self.display_offset()
        if self.animation:
            started,first,last=self.animation;t=min(1.,(self.clock()-started)/.22)
            offset=first+(last-first)*(1-(1-t)**3)
            if t>=1:
                self.finish();return self.draw_original(cache,*args)
        self.paint(0)  # Fixed controls remain outside the clipped content area.
        x0,y0,x1,y1=self.bounds
        corners=[ui.logical_to_native(x,y) for x,y in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))]
        xs,ys=zip(*corners)
        gl.glPushAttrib(gl.GL_SCISSOR_BIT)
        try:
            gl.glEnable(gl.GL_SCISSOR_TEST)
            gl.glScissor(int(min(xs)),int(ui.NATIVE_H-max(ys)),int(max(xs)-min(xs)),int(max(ys)-min(ys)))
            ui.draw_logical_rect(*self.bounds,(7,18,25,255))
            self.paint(0,offset,content=True)
            if self.has_target():self.paint(1,offset+self.direction*self.height,content=True)
        finally:gl.glPopAttrib()

    def close(self):
        if self.textures:self.workspace.ui.GL.glDeleteTextures(self.textures)
        self.close_original()
