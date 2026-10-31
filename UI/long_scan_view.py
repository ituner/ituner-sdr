"""Hidden Long Scan setup and a separate, time-based activity viewer."""
from concurrent.futures import ThreadPoolExecutor
from array import array
import ctypes
from urllib.parse import urlsplit
import time

from long_scan import HOURS
import offline_schedules


class LongScanView:
    def __init__(self, ui, controller, listening_receiver):
        self.ui,self.controller,self.listening_receiver = ui,controller,listening_receiver
        self.open = False
        self.page = 'setup'
        self.keyboard = False
        self.entry = ''
        self.mode = 'lower'
        self.error = ''
        self.actions = []
        self.pressed = None
        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix='long-scan-history')
        self.future = None
        self.future_key = None
        self.history = None
        self.history_key = None
        self.selection = ''
        self.trace_key = None
        self.trace_vertices = None
        self.trace_colors = None

    def show(self):
        self.open,self.page,self.keyboard = True,'setup',False
        if not self.controller.snapshot()['receiver']:
            try:
                self.controller.configure(receiver=self.listening_receiver())
            except (ValueError,OSError) as error:
                self.error = str(error)

    def close(self):
        self.open,self.keyboard,self.pressed = False,False,None

    def shutdown(self):
        self.close()
        self.executor.shutdown(wait=False,cancel_futures=True)

    def back(self):
        if self.keyboard:
            self.keyboard = False
        elif self.page == 'history':
            self.page = 'setup'
        else:
            self.close()

    def action_at(self, x, y):
        if self.keyboard:
            key = self.ui.touch_keyboard_action_at(x,y,self.mode)
            return ('key',key) if key else None
        return next((action for box,action in reversed(self.actions) if self.ui.contains(box,x,y)),None)

    def press(self, x, y):
        self.pressed = self.action_at(x,y)

    def release(self, x, y):
        action,self.pressed = self.pressed,None
        if action and action == self.action_at(x,y):
            self.action(action[0],(x,y) if action[0] == 'inspect' else action[1])

    def key(self, key):
        if key == 'CANCEL':
            self.keyboard = False
        elif key == 'SAVE':
            try:
                self.controller.configure(receiver=self.entry)
                self.keyboard,self.error = False,''
            except (ValueError,OSError) as error:
                self.error = str(error)
        elif key in ('MODE','CAPS'):
            self.mode = self.ui.touch_keyboard_next_mode(self.mode,key)
        elif key == 'CLEAR':
            self.entry = ''
        elif key == 'BACK':
            self.entry = self.entry[:-1]
        elif key == 'SPACE':
            self.entry = (self.entry+' ')[:250]
        elif key and len(key) == 1 and key.isprintable():
            self.entry = (self.entry+key)[:250]

    def keyboard_event(self, event):
        pygame = self.ui.pygame
        if event.key == pygame.K_ESCAPE:
            self.key('CANCEL')
        elif event.key in (pygame.K_RETURN,pygame.K_KP_ENTER):
            self.key('SAVE')
        elif event.key == pygame.K_BACKSPACE:
            self.key('BACK')
        else:
            for character in getattr(event,'unicode',''):
                self.key('SPACE' if character == ' ' else character)

    def action(self, kind, value):
        try:
            self.error = ''
            if kind == 'back':
                self.back()
            elif kind == 'key':
                self.key(value)
            elif kind == 'receiver':
                state = self.controller.snapshot()
                if state['running']:
                    self.error = 'Stop Long Scan before changing its receiver.'
                else:
                    self.entry,self.keyboard,self.mode = state['receiver'],True,'lower'
            elif kind == 'current':
                self.controller.configure(receiver=self.listening_receiver())
            elif kind == 'toggle':
                if self.controller.snapshot()['running']:
                    self.controller.stop()
                else:
                    self.controller.start()
            elif kind == 'view':
                self.page = 'history'
            elif kind == 'hours':
                self.controller.configure(hours=value)
            elif kind == 'inspect':
                self.inspect(*value)
        except (ValueError,OSError) as error:
            self.error = str(error)

    def move(self, delta):
        if self.page == 'history' and not self.keyboard:
            hours = self.controller.snapshot()['hours']
            self.action('hours',HOURS[max(0,min(len(HOURS)-1,HOURS.index(hours)+int(delta)))])

    def _history(self, state):
        key = state['receiver'],state['hours'],int(time.time()//20)
        if self.history_key and key[:2] != self.history_key[:2]:
            self.history = None
            self.selection = ''
        if self.future and self.future.done():
            try:
                result = self.future.result()
                if self.future_key[:2] == key[:2]:
                    self.history = result
            except Exception:
                self.error = 'Activity history is temporarily unavailable.'
            self.future = None
        if key != self.history_key and self.future is None and self.controller.history:
            self.history_key = key
            self.future_key = key
            self.future = self.executor.submit(self.controller.history.read,state['receiver'],state['hours'],state['period'])
        return self.history

    def inspect(self, x, y):
        if not self.history:
            return
        left,top,right,bottom = self.plot_box()
        bands = self.controller.bands
        index = max(0,min(len(bands)-1,int((x-left)/(right-left)*len(bands))))
        low,high,band = bands[index]
        frequency = low+(x-left-(right-left)/len(bands)*index)/((right-left)/len(bands))*(high-low)
        nearby = [(abs(f-frequency),f) for label,f in self.history['tracks'] if label == band]
        if not nearby:
            self.selection = band+' · no detected station at this position'
            return
        distance,frequency = min(nearby)
        if distance > (high-low)*8/((right-left)/len(bands)):
            self.selection = band+' · no detected station at this position'
            return
        timestamp = self.history['end']-(y-top)/(bottom-top)*(self.history['end']-self.history['start'])
        _,rows,_ = offline_schedules.lookup(frequency,timestamp,tolerance=2.5,allow_old_season=True)
        names = list(dict.fromkeys((row.get('station') or 'Unknown')+
                                   (' · '+row['country'] if row.get('country') else '') for row in rows))
        self.selection = f'{frequency:,.1f} kHz · '+('Possible: '+' / '.join(names[:2]) if names else 'Unknown')

    def plot_box(self):
        return 78,174,self.ui.LOGICAL_W-20,self.ui.LOGICAL_H-64

    def draw_activity(self, history, running, palette):
        """Cache the long history as one colored line batch, not thousands of draw calls."""
        ui = self.ui
        left,top,right,bottom = self.plot_box()
        key = (id(history),running,tuple(palette.ready),tuple(palette.secondary_text),
               self.plot_box(),ui.logical_to_native(0,0),ui.logical_to_native(1,1))
        if key != self.trace_key:
            vertices,colors = array('f'),array('f')
            duration = history['end']-history['start']
            cell = (right-left)/len(self.controller.bands)
            mapping = {band:(index,low,high) for index,(low,high,band) in enumerate(self.controller.bands)}
            def ypos(stamp):
                return max(top,min(bottom,top+(history['end']-stamp)/duration*(bottom-top)))
            def line(x0,y0,x1,y1,color):
                vertices.extend(ui.logical_to_native(x0,y0))
                vertices.extend(ui.logical_to_native(x1,y1))
                rgba = tuple(value/255 for value in color)
                colors.extend(rgba);colors.extend(rgba)
            def trace(start,end,band,frequency,strength,provisional=False,point=False):
                if band not in mapping or end < history['start']:
                    return
                index,low,high = mapping[band]
                x = left+index*cell+max(0,min(1,(frequency-low)/(high-low)))*cell
                alpha = round((70+150*max(0,min(1,(strength-6)/40)))*(.4 if provisional else 1))
                y0,y1 = ypos(start),ypos(end)
                if point:
                    y0 = max(top,min(bottom-2,y0-1))
                    y1 = y0+2
                line(x,y0,x,y1,(*palette.ready[:3],alpha))
            for segment in history['segments']:
                trace(*segment)
            if running:
                for segment in history['tails']:
                    trace(*segment,provisional=True)
            for stamp,band,frequency,strength in history['points']:
                trace(stamp,stamp,band,frequency,strength,point=True)
            for stamp,band in history['gaps']:
                if band == '*':
                    line(left,ypos(stamp),right,ypos(stamp),(*palette.secondary_text[:3],55))
            self.trace_vertices,self.trace_colors = vertices,colors
            self.trace_key = key
        if not self.trace_vertices:
            return
        gl = ui.GL
        vertex_pointer = (ctypes.c_float*len(self.trace_vertices)).from_buffer(self.trace_vertices)
        color_pointer = (ctypes.c_float*len(self.trace_colors)).from_buffer(self.trace_colors)
        previous = int(gl.glGetIntegerv(gl.GL_ARRAY_BUFFER_BINDING))
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,0)
        gl.glDisable(gl.GL_TEXTURE_2D)
        gl.glEnableClientState(gl.GL_VERTEX_ARRAY)
        gl.glEnableClientState(gl.GL_COLOR_ARRAY)
        try:
            gl.glVertexPointer(2,gl.GL_FLOAT,0,vertex_pointer)
            gl.glColorPointer(4,gl.GL_FLOAT,0,color_pointer)
            gl.glLineWidth(1.5)
            gl.glDrawArrays(gl.GL_LINES,0,len(self.trace_vertices)//2)
        finally:
            gl.glDisableClientState(gl.GL_COLOR_ARRAY)
            gl.glDisableClientState(gl.GL_VERTEX_ARRAY)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER,previous)
            gl.glEnable(gl.GL_TEXTURE_2D)

    def draw(self, cache):
        ui = self.ui
        state = self.controller.snapshot()
        palette = ui.APP_UI_STYLE.palette
        self.actions = []
        if self.keyboard:
            ui.draw_touch_keyboard(cache,'Long Scan receiver','KiwiSDR receiver address',self.entry,self.mode,
                                   submit='Save',error=self.error,placeholder='http://receiver:8073',rail_title='SMART SCAN')
            return
        ui.draw_logical_rect(0,0,ui.LOGICAL_W,ui.LOGICAL_H,palette.background)
        def ink(x,y,text,size=20,color=None,width=None):
            if width:
                text = ui.fit_station_text(cache,text,width,size,False,False,family=ui.APP_UI_STYLE.button.font_family)
            ui.draw_text(cache,x,y,text,color or palette.text,size,False,False,'lm',family=ui.APP_UI_STYLE.button.font_family)
        def button(box,label,action,active=False):
            ui.draw_styled_text_button(cache,box,label,active=active)
            self.actions.append((box,action))
        ink(20,31,'LONG SCAN'+(' · EXPERIMENTAL' if self.page == 'setup' else ''),24,palette.section_heading)
        button((ui.LOGICAL_W-246,8,ui.LOGICAL_W-10,66),'Back',('back',None))
        if self.page == 'setup':
            ink(32,107,'Dedicated scanning receiver',20,palette.secondary_text)
            ink(32,146,state['receiver'] or 'Choose a receiver',24,width=ui.LOGICAL_W-64)
            button((32,174,326,238),'Use listening receiver',('current',None))
            button((338,174,610,238),'Change receiver',('receiver',None))
            ink(32,278,state['status'],24,palette.ready if state['running'] else palette.secondary_text)
            ink(32,310,state['detail'],20,width=ui.LOGICAL_W-64)
            button((32,344,268,408),'Stop Long Scan' if state['running'] else 'Start Long Scan',('toggle',None),state['running'])
            button((280,344,516,408),'View history',('view',None))
            ink(32,441,'History window',20,palette.secondary_text)
            for index,hours in enumerate(HOURS):
                x = 32+index*130
                button((x,458,x+118,522),f'{hours} hour'+('s' if hours != 1 else ''),('hours',hours),state['hours']==hours)
            ink(32,566,'Uses an additional receiver channel. Your listening session stays separate.',20,width=ui.LOGICAL_W-64)
            ink(32,603,'Targets ten full checks per hour; a slow receiver may take longer.',18,palette.secondary_text)
            ink(32,638,'History is saved on this device. Long Scan keeps running when this window closes.',18,palette.secondary_text)
            if self.error:
                ink(32,686,self.error,20,palette.waiting,width=ui.LOGICAL_W-64)
            return
        for index,hours in enumerate(HOURS):
            x = 20+index*124
            button((x,76,x+114,140),f'{hours} h',('hours',hours),state['hours']==hours)
        host = urlsplit(state['receiver']).hostname or 'No receiver selected'
        history = self._history(state)
        ink(530,95,host,18,palette.secondary_text,width=ui.LOGICAL_W-550)
        status = state['status']+(' · '+state['band'] if state['band'] else '')
        if history:
            status += f" · {len(history['tracks'])} frequencies"
        ink(530,124,status,18,palette.secondary_text,width=ui.LOGICAL_W-550)
        left,top,right,bottom = self.plot_box()
        cell = (right-left)/len(self.controller.bands)
        for index,(_low,_high,label) in enumerate(self.controller.bands):
            x = left+index*cell
            ui.draw_text(cache,x+cell/2,top-15,label.replace(' ',''),palette.text,18,False,False,'cm',family=ui.APP_UI_STYLE.button.font_family)
            ui.draw_logical_line(x,top,x,bottom,palette.divider,1)
        if history:
            duration = history['end']-history['start']
            def ypos(stamp):
                return max(top,min(bottom,top+(history['end']-stamp)/duration*(bottom-top)))
            for step in range(7):
                stamp = history['end']-duration*step/6
                y = ypos(stamp)
                ink(8,y,time.strftime('%H:%M',time.gmtime(stamp)),14,palette.secondary_text)
                ui.draw_logical_line(left,y,right,y,palette.divider,1)
            self.draw_activity(history,state['running'],palette)
            if not history['points']:
                ink(left+24,top+60,'No detections in this history window yet.',22,palette.secondary_text)
        else:
            ink(left+24,top+60,'Loading saved activity…',22,palette.secondary_text)
        self.actions.append(((left,top,right,bottom),('inspect',None)))
        ink(20,ui.LOGICAL_H-38,self.selection or 'UTC · Bright traces: measured signals. Dim tails: awaiting another check.',16,palette.secondary_text,width=ui.LOGICAL_W-40)
