"""Hidden Long Scan setup and a separate, time-based activity viewer."""
from concurrent.futures import ThreadPoolExecutor
from array import array
import ctypes
import math
from itertools import chain
import threading
from urllib.parse import urlsplit
import time

from long_scan import HOURS
import offline_schedules
from long_scan_search import search_history


class LongScanView:
    MAX_ZOOM = 64.0
    def __init__(self, ui, controller, listening_receiver):
        self.ui,self.controller,self.listening_receiver = ui,controller,listening_receiver
        self.open = False
        self.page = 'setup'
        self.keyboard = False
        self.entry = ''
        self.mode = 'lower'
        self.keyboard_target = 'receiver'
        self.search_query = ''
        self.search_future = None
        self.search_key = None
        self.search_result = None
        self.search_cancel = None
        self.search_error = ''
        self.error = ''
        self.actions = []
        self.pressed = None
        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix='long-scan-history')
        self.future = None
        self.future_key = None
        self.history = None
        self.history_key = None
        self.selection = ''
        self.info_card = None
        self.trace_key = None
        self.trace_vertices = None
        self.trace_colors = None
        self.zoom = 1.0
        self.offset = 0.0
        self.drag_origin = None
        self.dragged = False
        self.pinched = False
        self.pinch_origin = None

    def show(self):
        self.open,self.page,self.keyboard = True,'setup',False
        self.info_card = None
        if not self.controller.snapshot()['receiver']:
            try:
                self.controller.configure(receiver=self.listening_receiver())
            except (ValueError,OSError) as error:
                self.error = str(error)

    def close(self):
        self.open,self.keyboard,self.pressed = False,False,None
        self.drag_origin = self.pinch_origin = None
        self.cancel_search()

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
        self.drag_origin = (x,y,self.offset) if self.pressed == ('inspect',None) else None
        self.dragged = self.pinched = False
        self.pinch_origin = None

    def world_at(self, x):
        left,_,right,_ = self.plot_box()
        return self.offset+(x-left)/((right-left)*self.zoom)

    def screen_at(self, world):
        left,_,right,_ = self.plot_box()
        return left+(world-self.offset)*self.zoom*(right-left)

    def set_window(self, zoom, offset):
        self.zoom = max(1.0,min(self.MAX_ZOOM,zoom))
        self.offset = max(0.0,min(1.0-1.0/self.zoom,offset))

    def zoom_at(self, factor, x):
        if factor <= 0 or not math.isfinite(factor):
            return
        self.info_card = None
        anchor = self.world_at(x)
        left,_,right,_ = self.plot_box()
        zoom = max(1.0,min(self.MAX_ZOOM,self.zoom*factor))
        self.set_window(zoom,anchor-(x-left)/(right-left)/zoom)

    def drag(self, x, y, points=None):
        if self.page != 'history' or self.keyboard or not self.drag_origin:
            return False
        if points is None:
            return self.dragged  # Release must not apply a stale first-finger position.
        if len(points) >= 2:
            self.dragged = self.pinched = True
            self.info_card = None
            self.pressed = None
            a,b = points[:2]
            distance = max(1.0,math.hypot(b[0]-a[0],b[1]-a[1]))
            midpoint = (a[0]+b[0])/2
            if self.pinch_origin is None:
                self.pinch_origin = distance,self.zoom,self.world_at(midpoint)
            else:
                original,zoom,anchor = self.pinch_origin
                left,_,right,_ = self.plot_box()
                zoom = max(1.0,min(self.MAX_ZOOM,zoom*distance/original))
                self.set_window(zoom,anchor-(midpoint-left)/(right-left)/zoom)
            return True
        if self.pinched:
            return True  # Do not pan or inspect when one finger of a pinch lifts.
        start_x,start_y,offset = self.drag_origin
        if self.dragged or max(abs(x-start_x),abs(y-start_y)) >= 10:
            self.dragged = True
            self.info_card = None
            self.pressed = None
            left,_,right,_ = self.plot_box()
            self.set_window(self.zoom,offset-(x-start_x)/(right-left)/self.zoom)
            return True
        return False

    def release(self, x, y):
        action,self.pressed = self.pressed,None
        dragged,self.dragged = self.dragged,False
        self.drag_origin = self.pinch_origin = None
        self.pinched = False
        if dragged:
            return
        if action and action == self.action_at(x,y):
            self.action(action[0],(x,y) if action[0] in ('inspect','navigate') else action[1])

    def key(self, key):
        if key == 'CANCEL':
            self.keyboard = False
        elif key == 'SAVE':
            if self.keyboard_target == 'search':
                self.set_query(self.entry)
                self.keyboard,self.error = False,''
                return
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
            self.entry = (self.entry+' ')[:80 if self.keyboard_target == 'search' else 250]
        elif key and len(key) == 1 and key.isprintable():
            self.entry = (self.entry+key)[:80 if self.keyboard_target == 'search' else 250]

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
                    self.keyboard_target = 'receiver'
                    self.entry,self.keyboard,self.mode = state['receiver'],True,'lower'
            elif kind == 'search':
                self.keyboard_target = 'search'
                self.entry,self.keyboard,self.mode = self.search_query,True,'lower'
            elif kind == 'clear_search':
                self.set_query('')
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
                self.info_card = None
                self.controller.configure(hours=value)
            elif kind == 'zoom':
                left,_,right,_ = self.plot_box()
                self.zoom_at(value,(left+right)/2)
            elif kind == 'fit':
                self.info_card = None
                self.set_window(1,0)
            elif kind == 'dismiss_info':
                self.info_card = None
            elif kind == 'navigate':
                self.info_card = None
                left,_,right,_ = self.plot_box()
                self.set_window(self.zoom,(value[0]-left)/(right-left)-.5/self.zoom)
            elif kind == 'inspect':
                self.inspect(*value)
        except (ValueError,OSError) as error:
            self.error = str(error)

    def move(self, delta):
        if self.page == 'history' and not self.keyboard:
            hours = self.controller.snapshot()['hours']
            self.action('hours',HOURS[max(0,min(len(HOURS)-1,HOURS.index(hours)+int(delta)))])

    def cancel_search(self):
        if self.search_cancel:
            self.search_cancel.set()
        if self.search_future:
            self.search_future.cancel()
        self.search_future = self.search_cancel = self.search_key = None
        self.search_result = None

    def set_query(self, query):
        self.cancel_search()
        self.search_query = ' '.join(query.split())[:80]
        self.search_error = ''
        self.info_card = None
        self.selection = ''
        if self.search_query:
            self.set_window(1,0)

    def poll_search(self, history):
        if not self.search_query or history is None:
            self.cancel_search()
            return
        key = id(history),self.search_query,offline_schedules.store.generation
        if self.search_future and self.search_future.done():
            if key == self.search_key:
                try:
                    self.search_result = self.search_future.result()
                    self.search_error = ''
                except Exception:
                    self.search_error = 'History search is temporarily unavailable.'
            self.search_future = None
        if key != self.search_key:
            previous = self.search_result
            self.cancel_search()
            self.search_result = previous
            self.search_error = ''
            self.search_key = key
            self.search_cancel = threading.Event()
            self.search_future = self.executor.submit(search_history,history,self.search_query,None,self.search_cancel)

    def _history(self, state):
        key = state['receiver'],state['hours'],int(time.time()//20)
        if self.history_key and key[:2] != self.history_key[:2]:
            self.history = None
            self.selection = ''
            self.info_card = None
            self.cancel_search()
            if key[0] != self.history_key[0]:
                self.set_window(1,0)
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
        world = max(0,min(1,self.world_at(x)))
        index = max(0,min(len(bands)-1,int(world*len(bands))))
        low,high,band = bands[index]
        timestamp = self.history['end']-(y-top)/(bottom-top)*(self.history['end']-self.history['start'])
        duration = max(1,self.history['end']-self.history['start'])
        points = ((stamp,stamp,label,frequency,strength)
                  for stamp,label,frequency,strength in self.history.get('points',()))
        tails = self.history.get('tails',()) if self.controller.snapshot()['running'] else ()
        nearest = None
        for start,end,label,frequency,_strength in chain(self.history.get('segments',()),tails,points):
            if label != band or end < self.history['start']:
                continue
            u = (index+max(0,min(1,(frequency-low)/(high-low))))/len(bands)
            dx = self.screen_at(u)-x
            first = max(top,min(bottom,top+(self.history['end']-end)/duration*(bottom-top)))
            last = max(top,min(bottom,top+(self.history['end']-start)/duration*(bottom-top)))
            dy = max(0,first-y,y-last)
            distance = dx*dx+dy*dy
            if distance <= 18*18 and (nearest is None or distance < nearest[0]):
                nearest = distance,frequency,max(start,min(end,timestamp))
        if nearest is None:
            clock = time.strftime('%d %b %H:%M UTC',time.gmtime(timestamp))
            self.selection = f'{band} · {low:,.0f}–{high:,.0f} kHz · {clock} · No measured trace here'
            self.info_card = dict(band=band,range=(low,high),stamp=timestamp,frequency=None,names=[])
            return
        _,frequency,timestamp = nearest
        _,rows,_ = offline_schedules.lookup(frequency,timestamp,tolerance=2.5,allow_old_season=True)
        names = list(dict.fromkeys((row.get('station') or 'Unknown')+
                                   (' · '+row['country'] if row.get('country') else '') for row in rows))
        clock = time.strftime('%d %b %H:%M UTC',time.gmtime(timestamp))
        self.selection = f'{band} · {frequency:,.1f} kHz · {clock} · '+('Possible: '+' / '.join(names[:2]) if names else 'Unknown')
        self.info_card = dict(band=band,range=(low,high),stamp=timestamp,frequency=frequency,names=names)

    def draw_info_card(self, cache, palette):
        if not self.info_card:
            return
        ui = self.ui
        info = self.info_card
        left,top,right,bottom = self.plot_box()
        selected_y = None
        if info['frequency'] is not None and self.history:
            index = next(i for i,b in enumerate(self.controller.bands) if b[2] == info['band'])
            low,high = info['range']
            u = (index+(info['frequency']-low)/(high-low))/len(self.controller.bands)
            x = self.screen_at(u)
            y = top+(self.history['end']-info['stamp'])/max(1,self.history['end']-self.history['start'])*(bottom-top)
            selected_y = y
            if left+8 <= x <= right-8 and top+8 <= y <= bottom-8:
                ui.draw_logical_circle(x,y,8,palette.ready,segments=24,outline=True,width=2)
        x1,y1 = right-12,bottom-12
        if selected_y is not None and selected_y>(top+bottom)/2:
            y1 = top+202
        x0,y0 = max(left+12,x1-720),y1-190
        ui.draw_logical_rect(x0,y0,x1,y1,(*palette.background[:3],248))
        ui.draw_section_divider(x0,y0,x1)
        ui.draw_section_divider(x0,y1,x1)
        close = x1-112,y0+8,x1-8,y0+64
        ui.draw_styled_text_button(cache,close,'Close')
        def ink(x,y,text,size=22,secondary=False,width=None):
            if width:
                text = ui.fit_station_text(cache,text,width,size,False,False,family=ui.APP_UI_STYLE.button.font_family)
            ui.draw_text(cache,x,y,text,palette.secondary_text if secondary else palette.text,
                         size,False,False,'lm',family=ui.APP_UI_STYLE.button.font_family)
        frequency = f"{info['frequency']:,.1f} kHz" if info['frequency'] is not None else f'{info["range"][0]:,.0f}–{info["range"][1]:,.0f} kHz'
        ink(x0+20,y0+30,info['band']+' · '+frequency,24,width=x1-x0-150)
        ink(x0+20,y0+67,time.strftime('%d %b %H:%M UTC',time.gmtime(info['stamp'])),18,True)
        if info['frequency'] is None:
            ink(x0+20,y0+111,'No measured trace at this position.',22,width=x1-x0-40)
            ink(x0+20,y0+150,'Blank areas can be unobserved.',18,True,width=x1-x0-40)
        elif not info['names']:
            ink(x0+20,y0+111,'Unknown broadcaster',22)
            ink(x0+20,y0+150,'Measured signal · No matching schedule entry',18,True,width=x1-x0-40)
        else:
            ink(x0+20,y0+106,'Possible: '+info['names'][0],22,width=x1-x0-40)
            if len(info['names'])>1:
                ink(x0+20,y0+148,info['names'][1],20,width=x1-x0-40)
        self.actions.append(((x0,y0,x1,y1),('info',None)))
        self.actions.append((close,('dismiss_info',None)))

    def plot_box(self):
        return 20,198,self.ui.LOGICAL_W-20,self.ui.LOGICAL_H-120

    def frequency_ticks(self):
        """A local kHz ruler for each equal-width band, not a false linear span."""
        left,_,right,_ = self.plot_box()
        count = len(self.controller.bands)
        ticks = []
        previous = left-1000
        for index,(low,high,band) in enumerate(self.controller.bands):
            u0,u1 = max(index/count,self.offset),min((index+1)/count,self.offset+1/self.zoom)
            if u1<=u0:
                continue
            first = low+(u0*count-index)*(high-low)
            last = low+(u1*count-index)*(high-low)
            desired = (high-low)*count/((right-left)*self.zoom)*130
            base = 10**math.floor(math.log10(max(.001,desired)))
            step = next(mult*base for mult in (1,2,5,10) if mult*base>=desired)
            value = math.ceil(first/step)*step
            while value<=last+step*.001:
                x = self.screen_at((index+(value-low)/(high-low))/count)
                if left+48<=x<=right-48 and x-previous>=110:
                    ticks.append((x,value,step,band))
                    previous = x
                value += step
        return ticks

    def draw_frequency_ruler(self, cache, palette):
        ui = self.ui
        left,_,right,bottom = self.plot_box()
        ui.draw_logical_line(left,bottom+7,right,bottom+7,palette.divider,1)
        ticks = self.frequency_ticks()
        for x,frequency,step,_band in ticks:
            ui.draw_logical_line(x,bottom+5,x,bottom+11,palette.secondary_text,1)
            decimals = max(0,-int(math.floor(math.log10(step))))
            label = f'{frequency:,.{decimals}f}'
            ui.draw_text(cache,x,bottom+25,label,palette.secondary_text,16,False,False,'cm',family=ui.APP_UI_STYLE.button.font_family)
        ui.draw_text(cache,right,bottom+25,'kHz',palette.secondary_text,14,False,False,'rm',family=ui.APP_UI_STYLE.button.font_family)

    def draw_activity(self, history, running, palette):
        """Cache the long history as one colored line batch, not thousands of draw calls."""
        ui = self.ui
        left,top,right,bottom = self.plot_box()
        key = (id(history),running,tuple(palette.ready),self.plot_box(),self.search_query,
               id(self.search_result),tuple(palette.waiting),tuple(palette.secondary_text))
        if key != self.trace_key:
            vertices,colors = array('f'),array('f')
            duration = history['end']-history['start']
            mapping = {band:(index,low,high) for index,(low,high,band) in enumerate(self.controller.bands)}
            def ypos(stamp):
                return max(0,min(1,(history['end']-stamp)/max(1,duration)))
            def line(x0,y0,x1,y1,color):
                vertices.extend((x0,y0))
                vertices.extend((x1,y1))
                rgba = tuple(value/255 for value in color)
                colors.extend(rgba);colors.extend(rgba)
            def trace(start,end,band,frequency,strength,provisional=False,point=False,highlight=False):
                if band not in mapping or end < history['start']:
                    return
                index,low,high = mapping[band]
                x = (index+max(0,min(1,(frequency-low)/(high-low))))/len(mapping)
                alpha = round((70+150*max(0,min(1,(strength-6)/40)))*(.4 if provisional else 1))
                color = palette.ready
                if self.search_query:
                    color = palette.waiting if highlight else palette.secondary_text
                    alpha = max(70 if provisional else 180,alpha) if highlight else 24
                y0,y1 = ypos(start),ypos(end)
                if point:
                    height = 2/(bottom-top)
                    y0 = max(0,min(1-height,y0-height/2))
                    y1 = y0+height
                line(x,y0,x,y1,(*color[:3],alpha))
            for segment in history['segments']:
                trace(*segment)
            if running:
                for segment in history['tails']:
                    trace(*segment,provisional=True)
            for stamp,band,frequency,strength in history['points']:
                trace(stamp,stamp,band,frequency,strength,point=True)
            if self.search_query and self.search_result:
                for segment in self.search_result['segments']:
                    trace(*segment,highlight=True)
                if running:
                    for segment in self.search_result['tails']:
                        trace(*segment,provisional=True,highlight=True)
                for stamp,band,frequency,strength in self.search_result['points']:
                    trace(stamp,stamp,band,frequency,strength,point=True,highlight=True)
            self.trace_vertices,self.trace_colors = vertices,colors
            self.trace_key = key
        if not self.trace_vertices:
            return
        gl = ui.GL
        vertex_pointer = (ctypes.c_float*len(self.trace_vertices)).from_buffer(self.trace_vertices)
        color_pointer = (ctypes.c_float*len(self.trace_colors)).from_buffer(self.trace_colors)
        previous = int(gl.glGetIntegerv(gl.GL_ARRAY_BUFFER_BINDING))
        mode = int(gl.glGetIntegerv(gl.GL_MATRIX_MODE))
        scissor = bool(gl.glIsEnabled(gl.GL_SCISSOR_TEST))
        scissor_box = tuple(int(v) for v in gl.glGetIntegerv(gl.GL_SCISSOR_BOX))
        corners = [ui.logical_to_native(x,y) for x in (left,right) for y in (top,bottom)]
        nx0,ny0 = min(x for x,y in corners),min(y for x,y in corners)
        nx1,ny1 = max(x for x,y in corners),max(y for x,y in corners)
        gl.glEnable(gl.GL_SCISSOR_TEST)
        gl.glScissor(round(nx0),round(ui.NATIVE_H-ny1),round(nx1-nx0),round(ny1-ny0))
        # Transform a cached normalized batch: pinch/pan never rebuilds history.
        origin_x = left-self.offset*self.zoom*(right-left)
        ox,oy = ui.logical_to_native(origin_x,top)
        xx,xy = ui.logical_to_native(origin_x+self.zoom*(right-left),top)
        yx,yy = ui.logical_to_native(origin_x,bottom)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        gl.glMultMatrixf((xx-ox,xy-oy,0,0,yx-ox,yy-oy,0,0,0,0,1,0,ox,oy,0,1))
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
            gl.glPopMatrix()
            gl.glMatrixMode(mode)
            gl.glScissor(*scissor_box)
            if not scissor:
                gl.glDisable(gl.GL_SCISSOR_TEST)

    def draw(self, cache):
        ui = self.ui
        state = self.controller.snapshot()
        timing = state.get('timing')
        timing_label = ''
        if timing:
            timing_label = f"{timing['views_per_second']:.2f} views/s"
            if timing['first_row_ms'] is not None:
                timing_label += f" · first row {timing['first_row_ms']:.0f} ms"
        palette = ui.APP_UI_STYLE.palette
        self.actions = []
        if self.keyboard:
            searching = self.keyboard_target == 'search'
            ui.draw_touch_keyboard(cache,'Long Scan history search' if searching else 'Long Scan receiver',
                                   'Station name or country' if searching else 'KiwiSDR receiver address',self.entry,self.mode,
                                   submit='Find' if searching else 'Save',error=self.error,
                                   placeholder='Romania or Radio Romania International' if searching else 'http://receiver:8073',rail_title='SMART SCAN')
            return
        ui.draw_logical_rect(0,0,ui.LOGICAL_W,ui.LOGICAL_H,palette.background)
        def ink(x,y,text,size=20,color=None,width=None):
            if width:
                text = ui.fit_station_text(cache,text,width,size,False,False,family=ui.APP_UI_STYLE.button.font_family)
            ui.draw_text(cache,x,y,text,color or palette.text,size,False,False,'lm',family=ui.APP_UI_STYLE.button.font_family)
        def button(box,label,action,active=False):
            ui.draw_styled_text_button(cache,box,label,active=active)
            self.actions.append((box,action))
        def selection_button(box,label,action,selected):
            ui.draw_selection_button(cache,box,label,selected)
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
                selection_button((x,458,x+118,522),f'{hours} hour'+('s' if hours != 1 else ''),('hours',hours),state['hours']==hours)
            ink(32,566,'Uses an additional receiver channel. Your listening session stays separate.',20,width=ui.LOGICAL_W-64)
            ink(32,603,timing_label or 'Targets ten full checks per hour; a slow receiver may take longer.',18,palette.secondary_text)
            ink(32,638,'History is saved on this device. Long Scan keeps running when this window closes.',18,palette.secondary_text)
            if self.error:
                ink(32,686,self.error,20,palette.waiting,width=ui.LOGICAL_W-64)
            return
        search_right = ui.LOGICAL_W-(382 if self.search_query else 256)
        search_label = 'Search: '+self.search_query if self.search_query else 'Search station or country'
        search_label = ui.fit_station_text(cache,search_label,search_right-340,20,False,False,family=ui.APP_UI_STYLE.button.font_family)
        button((320,8,search_right,66),search_label,('search',None))
        if self.search_query:
            button((ui.LOGICAL_W-372,8,ui.LOGICAL_W-256,66),'Clear',('clear_search',None))
        for index,hours in enumerate(HOURS):
            x = 20+index*124
            selection_button((x,76,x+114,140),f'{hours} h',('hours',hours),state['hours']==hours)
        button((ui.LOGICAL_W-282,76,ui.LOGICAL_W-226,132),'−',('zoom',1/1.5))
        button((ui.LOGICAL_W-216,76,ui.LOGICAL_W-160,132),'+',('zoom',1.5))
        button((ui.LOGICAL_W-150,76,ui.LOGICAL_W-20,132),'Fit bands',('fit',None))
        host = urlsplit(state['receiver']).hostname or 'No receiver selected'
        history = self._history(state)
        self.poll_search(history)
        ink(530,97,host,18,palette.secondary_text,width=ui.LOGICAL_W-830)
        status = state['status']+(' · '+state['band'] if state['band'] else '')
        if history:
            status += f" · {len(history['tracks'])} frequencies"
        if timing_label:
            status += ' · '+timing_label
        if self.search_query:
            if self.search_error:
                status = self.search_error
            elif self.search_result is None:
                status = 'Searching recorded signals…'
            elif not self.search_result['database_available']:
                status = 'Offline station database unavailable'
            else:
                status = f"Possible matches: {self.search_query} · {self.search_result['matched_traces']} traces · {len(self.search_result['bands'])} bands"
        ink(20,159,status,18,palette.secondary_text,width=ui.LOGICAL_W-200)
        ui.draw_text(cache,ui.LOGICAL_W-20,159,f'{self.zoom:.1f}×',palette.secondary_text,18,False,False,'rm',family=ui.APP_UI_STYLE.button.font_family)
        left,top,right,bottom = self.plot_box()
        count = len(self.controller.bands)
        for index,(_low,_high,label) in enumerate(self.controller.bands):
            x0,x1 = max(left,self.screen_at(index/count)),min(right,self.screen_at((index+1)/count))
            if x1<=x0:
                continue
            if index%2:
                ui.draw_logical_rect(x0,top,x1,bottom,(*palette.divider[:3],18))
        if history:
            self.draw_activity(history,state['running'],palette)
            ink(left+8,top+20,time.strftime('%d %b %H:%M UTC',time.gmtime(history['end'])),16,palette.secondary_text)
            ink(left+8,bottom-14,time.strftime('%d %b %H:%M UTC',time.gmtime(history['start'])),16,palette.secondary_text)
            if not history['points']:
                ink(left+24,top+60,'No detections in this history window yet.',22,palette.secondary_text)
            elif self.search_query and self.search_result and self.search_result['database_available'] and not self.search_result['matched_traces']:
                ink(left+24,top+60,'No matching observed signals in this time window.',22,palette.secondary_text)
        else:
            ink(left+24,top+60,'Loading saved activity…',22,palette.secondary_text)
        for index,(_low,_high,label) in enumerate(self.controller.bands):
            x0,x1 = max(left,self.screen_at(index/count)),min(right,self.screen_at((index+1)/count))
            if x1-x0>=36:
                matched = self.search_result and label in self.search_result['bands']
                ui.draw_text(cache,(x0+x1)/2,top-13,label.replace(' ',''),palette.waiting if matched else palette.text,18,False,False,'cm',family=ui.APP_UI_STYLE.button.font_family)
        self.actions.append(((left,top,right,bottom),('inspect',None)))
        self.draw_frequency_ruler(cache,palette)
        # A quiet overview keeps the zoomed window's position legible without ticks.
        nav_top,nav_bottom = ui.LOGICAL_H-78,ui.LOGICAL_H-64
        for index in range(count):
            x0 = left+(right-left)*index/count
            x1 = left+(right-left)*(index+1)/count-2
            matched = self.search_result and self.controller.bands[index][2] in self.search_result['bands']
            color = palette.waiting if matched else palette.divider
            ui.draw_logical_rect(x0,nav_top,x1,nav_bottom,(*color[:3],150 if matched else 90))
        ui.draw_logical_rect(left+self.offset*(right-left),nav_top,
                            left+(self.offset+1/self.zoom)*(right-left),nav_bottom,
                            (*palette.ready[:3],50 if self.search_query else 150))
        self.actions.append(((left,nav_top-10,right,nav_bottom+10),('navigate',None)))
        ink(20,ui.LOGICAL_H-30,self.selection or 'Pinch to zoom · Drag to pan · Tap a trace for details · Blank areas may be unobserved.',16,palette.secondary_text,width=ui.LOGICAL_W-40)
        self.draw_info_card(cache,palette)
