"""Touch and encoder station picker over Home's RF canvas."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import re
import time
import unicodedata
from dataclasses import dataclass, replace
import offline_schedules
from smart_seek_waterfall import PreviewLeveler


@dataclass(frozen=True)
class BroadcastMatch:
    name: str
    country: str
    transmitter: str = ''
    power_kw: str = ''
    language: str = ''
    schedule: str = ''
    frequency_khz: float = None
    old_schedule: bool = False


def schedule_matches(rows, is_active):
    """Keep distinct broadcasters/countries instead of hiding ambiguity."""
    matches = []
    seen = set()
    for row in rows:
        times = re.findall(r'\b(?:[01]\d|2[0-4]):?[0-5]\d\b', row.get('time', ''))
        times = ['0000' if value in ('2400', '24:00') else value for value in times]
        if len(times) < 2 or not is_active(times[0], times[1]):
            continue
        name = str(row.get('station') or '').strip()
        country = str(row.get('country') or '').strip()
        try:
            listed_frequency = float(row['frequency_khz'])
        except (KeyError,ValueError,TypeError):
            listed_frequency = None
        key = name.casefold(), country.casefold(), listed_frequency
        if name and key not in seen:
            matches.append(BroadcastMatch(name, country,
                transmitter=str(row.get('transmitter') or '').strip(),
                power_kw=str(row.get('power_kw') or '').strip(),
                language=str(row.get('language') or '').strip(),
                schedule=str(row.get('time') or '').strip(), frequency_khz=listed_frequency,
                old_schedule=bool(row.get('schedule_stale'))))
            seen.add(key)
    return tuple(matches)


def short_station_name(name):
    for word, short in ((r'\bInternational\b', 'Intl'),
                        (r'\bRadio\b', 'R.'), (r'\bVoice of\b', 'Vo.')):
        name = re.sub(word, short, name, flags=re.I)
    return name


def station_matches_query(matches, query):
    def normalize(text):
        return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold())
                       if not unicodedata.combining(c))
    words = normalize(query).split()
    return any(all(word in normalize(match.name+' '+match.country) for word in words)
               for match in matches or ())


def station_frequency(measured, matches):
    """Display a scheduled channel without losing the received carrier."""
    listed = {m.frequency_khz for m in (matches or ()) if m.frequency_khz is not None}
    if len(listed) == 1:
        frequency = next(iter(listed))
        if abs(frequency-measured) <= 2.5:
            return frequency,False
    if not listed:
        channel = offline_schedules.shortwave_channel(measured)
        if channel is not None:
            return channel,abs(channel-measured) > .001
    return measured,False


def frequency_label(frequency):
    return f'{frequency:,.3f}'.rstrip('0').rstrip('.')+' kHz'


def candidate_playing(candidate, frequency):
    return min(abs(candidate.frequency_khz-frequency),abs(candidate.tuning_khz-frequency)) < .5


def candidate_slots(candidate, frequency, waterfall=False):
    return (4 if waterfall else 2) if candidate_playing(candidate, frequency) else 1


def wrap_station_title(text, measure, width, max_lines=2):
    """Use word boundaries before resorting to an ellipsis in a tall card."""
    words = str(text).split()
    lines = []
    while words and len(lines) < max_lines:
        line = words.pop(0)
        while words and measure(line+' '+words[0]) <= width:
            line += ' '+words.pop(0)
        if len(lines) == max_lines-1 and words:
            line += ' '+' '.join(words)
            words = []
        if measure(line) > width:
            while line and measure(line+'…') > width:
                line = line[:-1]
            line = line.rstrip()+'…'
        lines.append(line)
    return tuple(lines)


def station_detail_lines(match):
    location = match.country or 'Country not listed'
    if match.transmitter and match.transmitter.casefold() != match.country.casefold():
        location += ' · '+match.transmitter
    power = match.power_kw
    if power.casefold() in ('', '-', '?', '0', '0.0', '0 kw'):
        power = 'Power not listed'
    elif re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', power):
        power = 'Power: '+power+' kW'
    else:
        power = 'Power: '+power
    if match.language:
        power += ' · '+match.language
    return location, power, ('UTC '+match.schedule if match.schedule else 'Schedule not listed')


class SmartSeekView:
    PAGE_SIZE = 9
    BAND_TOP = 76
    LIST_TOP = BAND_TOP+100

    def __init__(self, ui, state, long_scan=None):
        self.ui, self.state = ui, state
        self.actions = []
        self.matches = {}
        self.names_at = {}
        self.pending = {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='seek-names')
        self.press_action = None
        self.first_visible = 0
        self.scroll_y = 0.0
        self.manual_scroll = False
        self._row_order = ()
        self._row_positions = ()
        self.drag_origin = None
        self.drag_scroll = False
        self.row_height = 64
        self.visible_count = self.PAGE_SIZE
        self.name_generation = None
        self.lookup_targets = {}
        self.research_frequency = None
        self.research_future = None
        self.research_rows = None
        self.research_error = False
        self.research_offset = 0
        self.waterfall_texture = None
        self.waterfall_generation = None
        self.waterfall_style = None
        self.waterfall_leveler = None
        self.tool_preview = None
        self.search_query = ''
        self.search_text = ''
        self.search_keyboard = False
        self.keyboard_mode = 'lower'
        self.search_selection = None
        self.long_view = None
        if long_scan is not None:
            from long_scan_view import LongScanView
            self.long_view = LongScanView(ui,long_scan,lambda:state.snapshot()[0])

    @property
    def keyboard_open(self):
        return self.search_keyboard or bool(self.long_view and self.long_view.open and self.long_view.keyboard)

    @property
    def open(self):
        opened = self.state.smart_seek_snapshot()['open']
        if not opened and self.long_view:
            self.long_view.close()
        return opened

    def close(self, selected=None):
        if self.long_view:
            self.long_view.close()
        self.tool_preview = None
        self.search_keyboard = False
        self.search_query = ''
        self.search_selection = None
        self.state.close_smart_seek(selected=selected)
        self.press_action = None
        self.drag_origin = None
        self.drag_scroll = False
        self.scroll_y = 0.0
        self.first_visible = 0
        self.manual_scroll = False
        self._row_order = ()
        self._row_positions = ()
        self.close_research()

    def close_research(self):
        if self.research_future:
            self.research_future.cancel()
        self.research_frequency = None
        self.research_future = None
        self.research_rows = None
        self.research_offset = 0

    def research(self, frequency):
        self.close_research()
        candidate = next((item for item in self.state.smart_seek_snapshot()['candidates']
                          if item.frequency_khz == frequency),None)
        if candidate is not None:
            frequency = candidate.tuning_khz
        self.research_frequency = frequency
        self.research_error = False
        self.research_future = self.executor.submit(self.ui.research_shortwave_frequency, frequency)

    def shutdown(self):
        self.close()
        if self.long_view:
            self.long_view.shutdown()
        if self.waterfall_texture is not None:
            self.waterfall_texture.close()
        for future in self.pending.values():
            future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def move(self, delta):
        if self.long_view and self.long_view.open:
            self.long_view.move(delta)
            return
        if self.tool_preview is not None or self.search_keyboard:
            return
        if self.research_frequency is not None:
            self.scroll_research(delta)
            return
        self.manual_scroll = False
        if self.search_query:
            rows = self.display_snapshot(self.state.smart_seek_snapshot())['candidates']
            if rows:
                index = next((i for i,c in enumerate(rows) if c.frequency_khz == self.search_selection),0)
                self.search_selection = rows[max(0,min(len(rows)-1,index+int(delta)))].frequency_khz
            return
        self.state.move_smart_seek(delta)

    def back(self):
        if self.long_view and self.long_view.open:
            self.long_view.back()
        elif self.search_keyboard:
            self.search_keyboard = False
            self.press_action = None
        elif self.tool_preview is not None:
            self.tool_preview = None
            self.actions = []
        elif self.research_frequency is not None:
            self.close_research()
        else:
            self.close()

    def swipe(self, start_y, end_y):
        if self.long_view and self.long_view.open:
            self.long_view.pressed = None
            return
        action,self.press_action = self.press_action,None
        if self.tool_preview is not None or self.search_keyboard:
            return
        if self.research_frequency is not None:
            self.scroll_research(round((start_y-end_y)/96))
            return
        if action and action[0] in ('band','close'):
            return
        if abs(end_y-start_y) >= 12:
            self._set_scroll_y(self.scroll_y+start_y-end_y)

    def row_layout(self, candidates, playing_khz, waterfall=False):
        gap = 4
        card_height = (self.ui.LOGICAL_H-self.LIST_TOP-12-gap*(self.PAGE_SIZE-1))/self.PAGE_SIZE
        positions = [0.0]
        for candidate in candidates:
            positions.append(positions[-1]+card_height*candidate_slots(candidate,playing_khz,waterfall)+gap)
        total = max(0,positions[-1]-gap)
        return positions,total,card_height

    def _set_scroll_y(self, value, snapshot=None):
        snapshot = self.display_snapshot(self.state.smart_seek_snapshot()) if snapshot is None else snapshot
        candidates = snapshot['candidates']
        positions,total,_ = self.row_layout(candidates,snapshot['playing_khz'],snapshot.get('waterfall',False))
        viewport = self.ui.LOGICAL_H-12-self.LIST_TOP
        self.scroll_y = max(0.0,min(max(0,total-viewport),float(value)))
        self.manual_scroll = True
        first = 0
        while first+1 < len(candidates) and positions[first+1] <= self.scroll_y:
            first += 1
        self.first_visible = first

    def scroll_rows(self, delta):
        self._scroll_to(self.first_visible+delta)

    def _scroll_to(self, first):
        snapshot = self.display_snapshot(self.state.smart_seek_snapshot())
        candidates = snapshot['candidates']
        positions,_,_ = self.row_layout(candidates,snapshot['playing_khz'],snapshot.get('waterfall',False))
        index = max(0,min(len(candidates),int(first)))
        self._set_scroll_y(positions[index],snapshot)

    def selected(self):
        if self.long_view and self.long_view.open:
            return None
        if self.research_frequency is not None or self.tool_preview is not None or self.search_keyboard:
            return None
        return self.display_snapshot(self.state.smart_seek_snapshot())['selected']

    def action_at(self, x, y):
        if self.long_view and self.long_view.open:
            return self.long_view.action_at(x,y)
        if self.search_keyboard:
            key = self.ui.touch_keyboard_action_at(x,y,self.keyboard_mode)
            return ('search_key',key) if key else None
        return next((action for box, action in reversed(self.actions) if self.ui.contains(box, x, y)), None)

    def press(self, x, y):
        if self.long_view and self.long_view.open:
            self.long_view.press(x,y)
            return
        self.press_action = self.action_at(x,y)
        in_list = (self.research_frequency is None and self.tool_preview is None and not self.search_keyboard
                   and self.LIST_TOP <= y <= self.ui.LOGICAL_H-12)
        self.drag_origin = (x,y,self.scroll_y) if in_list else None
        self.drag_scroll = False

    def back_box(self):
        return (self.ui.LOGICAL_W-246, 8, self.ui.LOGICAL_W-10, 66)

    def drag(self, x, y):
        if self.long_view and self.long_view.open:
            return False
        if self.drag_origin:
            start_x,start_y,offset = self.drag_origin
            dx,dy = x-start_x,y-start_y
            if self.drag_scroll or (abs(dy)>=12 and abs(dy)>abs(dx)*1.1):
                self.drag_scroll = True
                self.press_action = None
                self._set_scroll_y(offset-dy)
                return True
        return False

    def release(self, x, y):
        if self.long_view and self.long_view.open:
            self.long_view.release(x,y)
            return None
        if self.drag(x, y):
            self.press_action = None
            self.drag_origin = None
            self.drag_scroll = False
            return None
        action, self.press_action = self.press_action, None
        self.drag_origin = None
        if action is None or action != self.action_at(x, y):
            return None
        kind, value = action
        if kind == 'close':
            self.close()
        elif kind == 'tune':
            self.manual_scroll = False
            if self.search_query:
                self.search_selection = value
            return value
        elif kind == 'move':
            self.scroll_rows(value*self.visible_count)
        elif kind == 'refresh':
            self.state.start_smart_seek(refresh=True)
        elif kind == 'band':
            self.set_query('')
            self.state.start_smart_seek(band_label=value)
            self.first_visible = 0
            self.scroll_y = 0.0
            self.manual_scroll = False
            self._row_order = ()
            self._row_positions = ()
        elif kind == 'research':
            if self.state.smart_seek_snapshot().get('waterfall'):
                self.state.toggle_seek_waterfall()
            self.research(value)
        elif kind == 'waterfall':
            self.manual_scroll = False
            self.state.toggle_seek_waterfall()
        elif kind == 'research_back':
            self.close_research()
        elif kind == 'research_retry':
            self.research(self.research_frequency)
        elif kind == 'research_move':
            self.scroll_research(value*6)
        elif kind == 'tool_preview':
            self.tool_preview = value
            self.actions = []
        elif kind == 'tool_close':
            self.tool_preview = None
            self.actions = []
        elif kind == 'search':
            self.search_text = self.search_query
            self.search_keyboard = True
            self.keyboard_mode = 'lower'
            self.actions = []
        elif kind == 'search_clear':
            self.set_query('')
        elif kind == 'search_key':
            self.search_key(value)
        elif kind == 'long_setup' and self.long_view:
            self.long_view.show()
        return None

    def set_query(self, query):
        self.search_query = query.strip()[:80]
        self.search_selection = None
        self.first_visible,self.scroll_y,self.manual_scroll = 0,0.0,False
        self._row_order,self._row_positions = (),()
        self.actions = []

    def search_key(self, key):
        if key == 'CANCEL':
            self.search_keyboard = False
        elif key == 'SAVE':
            self.set_query(self.search_text)
            self.search_keyboard = False
        elif key in ('MODE','CAPS'):
            self.keyboard_mode = self.ui.touch_keyboard_next_mode(self.keyboard_mode,key)
        elif key == 'CLEAR':
            self.search_text = ''
        elif key == 'BACK':
            self.search_text = self.search_text[:-1]
        elif key == 'SPACE':
            self.search_text = (self.search_text+' ')[:80]
        elif key and len(key) == 1 and key.isprintable():
            self.search_text = (self.search_text+key)[:80]

    def keyboard_event(self, event):
        if self.long_view and self.long_view.open:
            self.long_view.keyboard_event(event)
            return
        pygame = self.ui.pygame
        if event.key == pygame.K_ESCAPE:
            self.search_key('CANCEL')
        elif event.key in (pygame.K_RETURN,pygame.K_KP_ENTER):
            self.search_key('SAVE')
        elif event.key == pygame.K_BACKSPACE:
            self.search_key('BACK')
        else:
            for character in getattr(event,'unicode',''):
                self.search_key('SPACE' if character == ' ' else character)

    def display_snapshot(self, snapshot):
        if not self.search_query:
            return snapshot
        entries = [item for item in snapshot.get('catalogue',())
                   if station_matches_query(self.matches.get(item['candidate'].frequency_khz),self.search_query)]
        candidates = tuple(item['candidate'] for item in entries)
        if self.search_selection not in {c.frequency_khz for c in candidates}:
            self.search_selection = candidates[0].frequency_khz if candidates else None
        return dict(snapshot,candidates=candidates,selected=self.search_selection,
                    stale=tuple(item['candidate'].frequency_khz for item in entries if item['stale']),
                    signal_status={item['candidate'].frequency_khz:item['status'] for item in entries},
                    candidate_bands={item['candidate'].frequency_khz:item['band'] for item in entries})

    def scroll_research(self, delta):
        self.research_offset = max(0,min(max(0,len(self.research_rows or [])-6),
                                        self.research_offset+delta))

    def _names_for_page(self, candidates):
        # All lookups are local. Re-evaluate on database changes and UTC
        # minute boundaries, without keeping an expired programme on screen.
        generation = (offline_schedules.store.status()[0], int(time.time()//60))
        if generation != self.name_generation:
            if self.name_generation is not None:
                self.matches.clear()
                self.names_at.clear()
                for future in self.pending.values():
                    future.cancel()
                self.pending.clear()
            self.name_generation = generation
        for candidate in candidates:
            key,target = candidate.frequency_khz,candidate.tuning_khz
            if self.lookup_targets.get(key,target) != target:
                self.matches.pop(key,None)
                self.names_at.pop(key,None)
                old = self.pending.pop(key,None)
                if old:
                    old.cancel()
            self.lookup_targets[key] = target
        for frequency, future in list(self.pending.items()):
            if future.done():
                try:
                    _frequency, rows, _error = future.result()
                except Exception:
                    rows = []
                self.matches[frequency] = schedule_matches(rows, self.ui._frequency_identity_schedule_active)
                self.state.note_smart_seek_identity(frequency,bool(self.matches[frequency]),
                    tuple(m.frequency_khz for m in self.matches[frequency] if m.frequency_khz is not None))
                self.names_at[frequency] = time.monotonic()
                del self.pending[frequency]
        for candidate in candidates:
            frequency = candidate.frequency_khz
            if time.monotonic()-self.names_at.get(frequency, time.monotonic()) >= 300:
                self.matches.pop(frequency, None)
            if frequency not in self.matches and frequency not in self.pending and len(self.pending) < 2:
                self.pending[frequency] = self.executor.submit(self.ui.lookup_smart_seek_frequency, candidate.tuning_khz)
            if frequency in self.matches:
                matches = self.matches[frequency]
                self.state.note_smart_seek_identity(frequency,bool(matches),
                    tuple(m.frequency_khz for m in matches if m.frequency_khz is not None))

    def visible_rows(self, candidates, selected, playing_khz, waterfall=False):
        """Keep the selected row fully visible, including a four-slot waterfall."""
        if not candidates:
            self.first_visible = 0
            self._row_order = ()
            self._row_positions = ()
            return ()
        positions,_,_ = self.row_layout(candidates,playing_khz,waterfall)
        order = tuple(candidate.frequency_khz for candidate in candidates)
        if self._row_order and order != self._row_order and (self.manual_scroll or self.first_visible):
            old_index = min(self.first_visible,len(self._row_order)-1)
            anchor = self._row_order[old_index]
            if anchor in order:
                new_index = order.index(anchor)
                shift = positions[new_index]-self._row_positions[old_index]
                self.scroll_y += shift
                self.first_visible = new_index
                if self.drag_origin is not None:
                    px,py,offset = self.drag_origin
                    self.drag_origin = (px,py,offset+shift)
        self._row_order,self._row_positions = order,positions
        if self.manual_scroll:
            self._set_scroll_y(self.scroll_y,dict(candidates=candidates,playing_khz=playing_khz,waterfall=waterfall))
            first = self.first_visible
            end = first
            limit = self.scroll_y+self.ui.LOGICAL_H-12-self.LIST_TOP
            while end < len(candidates) and positions[end] < limit:
                end += 1
            return candidates[first:end]
        selected_index = next((i for i, item in enumerate(candidates) if item.frequency_khz == selected), 0)
        first = min(self.first_visible, len(candidates)-1, selected_index)

        def end_at(start):
            used, end = 0, start
            while end < len(candidates):
                slots = candidate_slots(candidates[end], playing_khz, waterfall)
                if used+slots > self.PAGE_SIZE:
                    break
                used += slots
                end += 1
            return end

        end = end_at(first)
        while selected_index >= end:
            first += 1
            end = end_at(first)
        self.first_visible = first
        self.scroll_y = positions[first]
        return candidates[first:end]

    @contextmanager
    def list_clip(self):
        ui = self.ui
        points = [ui.logical_to_native(x,y) for x,y in
                  ((20,self.LIST_TOP),(ui.LOGICAL_W-20,self.LIST_TOP),
                   (20,ui.LOGICAL_H-12),(ui.LOGICAL_W-20,ui.LOGICAL_H-12))]
        left,right = int(min(p[0] for p in points)),int(max(p[0] for p in points))
        top,bottom = int(min(p[1] for p in points)),int(max(p[1] for p in points))
        enabled = bool(ui.GL.glIsEnabled(ui.GL.GL_SCISSOR_TEST))
        previous = tuple(int(v) for v in ui.GL.glGetIntegerv(ui.GL.GL_SCISSOR_BOX)) if enabled else None
        press = ui.UI_PRESS_POINT
        if self.drag_scroll:
            ui.set_ui_press_point()
        ui.GL.glEnable(ui.GL.GL_SCISSOR_TEST)
        ui.GL.glScissor(left,ui.NATIVE_H-bottom,right-left,bottom-top)
        try:
            yield
        finally:
            if enabled:
                ui.GL.glScissor(*previous)
            else:
                ui.GL.glDisable(ui.GL.GL_SCISSOR_TEST)
            ui.set_ui_press_point(*press) if press is not None else ui.set_ui_press_point()

    def draw_waterfall(self, cache, box, ink):
        ui = self.ui
        generation, rows, center, span, updated = self.state.take_seek_waterfall()
        if generation != self.waterfall_generation:
            if self.waterfall_texture is not None:
                self.waterfall_texture.close()
            self.waterfall_texture = ui.MiniWaterfallTexture(width=512, height=192)
            self.waterfall_generation = generation
            self.waterfall_style = None
        floor, ceiling, _speed, automatic, palette, _revision = self.state.waterfall_snapshot()
        style = palette, automatic
        if style != self.waterfall_style:
            self.waterfall_leveler = PreviewLeveler()
            self.waterfall_mapper = ui.waterfall_mapper(palette)
            self.waterfall_style = style
        for samples in rows:
            low, high = self.waterfall_leveler.levels_for(samples) if automatic else (floor, ceiling)
            image = ui.kiwi.waterfall_line(samples, self.waterfall_mapper, low, high, width=512)
            self.waterfall_texture.push_rgba(image.convert('RGBA').tobytes())
        x0, y0, x1, y1 = box
        ui.draw_logical_rect(x0, y0, x1, y1, (4, 12, 18, 255))
        self.waterfall_texture.draw(x0, y0, x1, y1-18, visible_fraction=1)
        fresh = updated is not None and time.monotonic()-updated < 2
        label = 'LIVE' if fresh else 'Waiting for waterfall…'
        ink(x0+6, y0+9, label, 14, (101, 223, 194), max_width=x1-x0-12)
        marker = (x0+x1)/2
        ui.draw_logical_line(marker, y0, marker, y1-18, (255, 209, 94), 1)
        # The marker is the received tuning frequency, not a rounded schedule channel.
        tick = 10 if span > 60 else 5
        for frequency in range(int((center-span/2)//tick)*tick, int(center+span/2)+1, tick):
            px = x0+(frequency-center+span/2)/span*(x1-x0)
            if x0+23 < px < x1-23 and abs(px-marker) > 43:
                ink(px-18, y1-8, str(frequency), 12, (146, 166, 179))
        ink(marker-37, y1-8, f'{center:.1f} kHz', 12, (255, 209, 94))

    def draw(self, cache):
        ui = self.ui
        snapshot = self.state.smart_seek_snapshot()
        if not snapshot['open']:
            return
        if self.long_view and self.long_view.open:
            self.long_view.draw(cache)
            return
        width, bottom = ui.LOGICAL_W, ui.LOGICAL_H
        self.actions = []
        if self.search_keyboard:
            ui.draw_touch_keyboard(cache,'Search scanned stations','Station name or country · all scanned bands',
                                   self.search_text,self.keyboard_mode,submit='Search',
                                   placeholder='e.g. Romania',rail_title='SMART SCAN')
            return
        ui.draw_logical_rect(0, 0, width, bottom, (0, 0, 0, 255))
        dim_row = False

        def ink(x, y, text, size=20, color=(205, 221, 229), max_width=None, bold=None):
            if dim_row:
                color = tuple(round(channel*.5) for channel in color[:3])
            weight = size >= 22 if bold is None else bool(bold)
            if max_width:
                text = ui.fit_station_text(cache, text, max_width, size, weight, False, family='Liberation Sans')
            ui.draw_text(cache, x, y, text, color, size, weight, False, 'lm', family='Liberation Sans')

        def button(box, label, action, active=False):
            style = ui.APP_UI_STYLE.button
            ui.draw_styled_text_button(cache,box,label,active=active,style=style)
            if action == ('tool_preview','Record'):
                cx,cy = (box[0]+box[2])/2,(box[1]+box[3])/2
                ui.draw_logical_circle(cx,cy+16,6,(235,55,65,255))
            self.actions.append((box, action))

        if self.research_frequency is not None:
            self.draw_research(cache, ink, button)
            return
        title = (10,8,250,66)
        if self.long_view:
            style = ui.APP_UI_STYLE.button
            style = replace(style,palette=replace(style.palette,surface=(0,0,0,0),border=(0,0,0,0)))
            ui.draw_styled_button_frame(title,style=style)
            self.actions.append((title,('long_setup',None)))
        ink(20, 31, 'SMART SCAN', 26, (101, 223, 194))
        waterfall = snapshot.get('waterfall', False)
        back = self.back_box()
        button(back, 'BACK', ('close', None))
        button((270,8,890,66),'Search: '+self.search_query if self.search_query else 'Search stations',('search',None))
        if self.search_query:
            button((902,8,1018,66),'Clear',('search_clear',None))
        catalogue = tuple(item['candidate'] for item in snapshot.get('catalogue',()))
        index_candidates = tuple({c.frequency_khz:c for c in snapshot['candidates']+catalogue}.values())
        self._names_for_page(index_candidates)
        snapshot = self.display_snapshot(snapshot)
        count = len(snapshot['candidates'])
        self.draw_band_activity(cache, snapshot)
        candidates = snapshot['candidates']
        visible = self.visible_rows(candidates, snapshot['selected'], snapshot['playing_khz'], waterfall)
        self.visible_count = max(1, len(visible))
        gap = 4
        card_width = width-40
        card_height = (bottom-self.LIST_TOP-12-gap*(self.PAGE_SIZE-1))/self.PAGE_SIZE
        self.row_height = card_height+gap
        positions,total_height,_ = self.row_layout(candidates,snapshot['playing_khz'],waterfall)
        row_y = self.LIST_TOP+positions[self.first_visible]-self.scroll_y
        row_action_start = len(self.actions)
        with self.list_clip():
            for index, candidate in enumerate(visible):
                dim_row = candidate.frequency_khz in snapshot['stale']
                x = 20
                y = row_y
                playing = candidate_playing(candidate,snapshot['playing_khz'])
                preview = playing and waterfall
                meta_left = 184
                scope_left = card_width*.55-(240-meta_left)
                style = ui.APP_UI_STYLE.button
                tool_width = style.height
                tool_left = x+8
                info_width = card_width-meta_left-8-tool_width-style.gap
                details_height = card_height*2 if playing else card_height
                row_height = card_height*candidate_slots(candidate, snapshot['playing_khz'], waterfall)
                box = (x, y, x+card_width, y+row_height)
                row_y += row_height+gap
                selected = candidate.frequency_khz == snapshot['selected']
                ui.draw_styled_button_frame(box, active=selected,
                                            pressed=not self.drag_scroll and self.press_action==('tune',candidate.frequency_khz)
                                            and ui.ui_button_pressed(box))
                ui.draw_logical_rect(x+2,y+2,x+meta_left-8,y+row_height-2,(0,0,0,255))
                self.actions.append((box, ('tune', candidate.frequency_khz)))
                matches = self.matches.get(candidate.frequency_khz)
                displayed_frequency, approximate = station_frequency(candidate.tuning_khz,matches)
                ink(x+12, y+20, ('≈ ' if approximate else '')+frequency_label(displayed_frequency), 22,
                    (101, 223, 194) if playing else (205, 221, 229))
                if playing:
                    centered = abs(candidate.tuning_khz-snapshot['playing_khz']) < .5
                    status = 'PLAYING' if centered else 'Tap to center'
                    if self.search_query:
                        status += ' · '+snapshot['candidate_bands'][candidate.frequency_khz]
                    ink(x+76,y+44,status,14,(101,223,194),max_width=meta_left-80)
                else:
                    status = snapshot['signal_status'].get(candidate.frequency_khz,'')
                    status = 'Rechecking…' if dim_row else 'AM' if status=='AM signal' else status
                    if self.search_query:
                        band = snapshot['candidate_bands'][candidate.frequency_khz]
                        status = band+(' · '+status if status else '')
                    ink(x+76,y+44,status,14,(146,166,179),max_width=meta_left-80)
                displayed_matches = (matches or ())[:2 if playing else 4]
                for match_index, match in enumerate(displayed_matches):
                    if preview:
                        match_x = x+meta_left
                        column_width = scope_left-meta_left-12
                        top = y+match_index*row_height/len(displayed_matches)
                        font = cache.font(28,bold=False,family='Liberation Sans')
                        title = wrap_station_title(match.name,lambda text:font.size(text)[0],column_width-86)
                        ui.draw_country_flag(match.country,match_x,top+2,60,40,
                                             alpha=.4 if dim_row else 1)
                        if match.old_schedule:
                            ink(match_x-14,top+22,'*',18,(210,181,119))
                        for line,text in enumerate(title):
                            ink(match_x+76,top+22+line*28,text,28,bold=False)
                        details = station_detail_lines(match)
                        if len(displayed_matches)>1:
                            details = (details[0],details[1].removeprefix('Power: ')+' · '+details[2])
                        detail_top = 52 if len(title)==1 else 82
                        for line,text in enumerate(details):
                            ink(match_x,top+detail_top+line*22,text,18,(166,190,202),
                                max_width=column_width-12)
                        continue
                    column, row = match_index % 2, match_index // 2
                    column_width = info_width/(2 if len(matches) > 1 else 1)
                    match_x = x+meta_left+column*column_width
                    crowded = not playing and len(matches) > 2
                    match_y = y+(15+row*26 if crowded else 22)
                    flag_width, flag_height = (52, 30) if crowded else (60, 40)
                    if match.old_schedule:
                        ink(match_x-14, match_y, '*', 18, (210, 181, 119))
                    ui.draw_country_flag(match.country, match_x, match_y-flag_height/2,
                                         flag_width, flag_height, alpha=.4 if dim_row else 1)
                    name = match.name if len(matches) == 1 else short_station_name(match.name)
                    ink(match_x+flag_width+16, match_y, name, 24 if crowded else 28,
                        max_width=column_width-flag_width-26, bold=False)
                    if playing:
                        details = station_detail_lines(match)
                        for line, text in enumerate(details):
                            ink(match_x, y+52+line*22, text, 18, (166, 190, 202),
                                max_width=column_width-12)
                if playing and matches and len(matches) > 2:
                    ink(x+meta_left+190, y+details_height-10, f'+{len(matches)-2} matches', 14, (146, 166, 179), max_width=175)
                if playing and abs(displayed_frequency-candidate.tuning_khz) > .001:
                    ink(x+meta_left+(200 if not matches else 0),y+details_height-10,
                        'RF '+frequency_label(candidate.tuning_khz),12,(146,166,179),max_width=175)
                if not matches:
                    classification = snapshot['signal_status'].get(candidate.frequency_khz,'')
                    label = classification if classification in ('Carrier only','Unconfirmed') else 'Unknown'
                    ink(x+meta_left, y+22, 'Checking…' if matches is None else label, 28,
                        (146, 166, 179), bold=False)
                    if playing:
                        ink(x+meta_left, y+53, 'Schedule and transmitter details unavailable.', 18,
                            (146, 166, 179), max_width=(scope_left-meta_left-12 if preview else info_width-12))
                    if matches is not None:
                        button((x+meta_left,y+68,x+meta_left+165,y+124) if playing else
                               (width-192, y, width-20, y+card_height), 'RESEARCH',
                               ('research',candidate.frequency_khz))
                if preview:
                    self.draw_waterfall(cache, (x+scope_left, y+4, x+card_width-8, y+row_height-4), ink)
                if playing:
                    button((x+card_width-8-tool_width,y+8,x+card_width-8,y+8+style.height),
                           'Close' if waterfall else 'Scope',('waterfall',None),waterfall)
                    tools = (('Text',('tool_preview','Transcribe')),
                             ('REC',('tool_preview','Record')))
                    for tool,(caption,action) in enumerate(tools):
                        tx = tool_left+tool*(tool_width+style.gap)
                        button((tx,y+61,tx+tool_width,y+61+style.height),caption,action,
                               False)
                strength = max(1, min(5, round(candidate.prominence/8)))
                for bar in range(5):
                    height = 6+bar*3
                    ui.draw_logical_rect(x+12+bar*10, y+49-height,
                                         x+19+bar*10, y+49,
                                         ((45, 78, 68, 255) if dim_row else (71, 204, 164, 255)) if bar < strength else (41, 55, 63, 255))
        clipped = []
        for box,action in self.actions[row_action_start:]:
            hit = (max(20,box[0]),max(self.LIST_TOP,box[1]),
                   min(width-20,box[2]),min(bottom-12,box[3]))
            if hit[2]>hit[0] and hit[3]>hit[1]:
                clipped.append((hit,action))
        self.actions[row_action_start:] = clipped
        dim_row = False
        if not candidates:
            message = ('Matching station names…' if self.pending else 'No matching stations in the scanned bands.') if self.search_query else ('Checking AM modulation…' if snapshot['active'] else 'No stations detected yet.')
            ink(32,self.LIST_TOP+80,message,24)
        viewport = bottom-12-self.LIST_TOP
        if total_height > viewport:
            thumb_height = viewport*viewport/total_height
            top = self.LIST_TOP+(viewport-thumb_height)*self.scroll_y/(total_height-viewport)
            ui.draw_logical_rect(width-12,top,width-7,top+thumb_height,(101,223,194,255))
        if self.tool_preview is not None:
            self.draw_tool_preview(cache, ink, button)

    def draw_tool_preview(self, cache, ink, button):
        ui = self.ui
        self.actions = []
        ui.draw_logical_rect(0,0,ui.LOGICAL_W,ui.LOGICAL_H,(0,0,0,210))
        left,top = (ui.LOGICAL_W-680)/2,(ui.LOGICAL_H-280)/2
        right,bottom = left+680,top+280
        ui.draw_styled_button_frame((left,top,right,bottom))
        label = 'Text' if self.tool_preview == 'Transcribe' else 'REC'
        ink(left+28,top+40,label+' · Preview',26,(101,223,194))
        message = ('Transcription controls will appear here.' if self.tool_preview == 'Transcribe'
                   else 'Recording controls will appear here.')
        ink(left+28,top+100,message,22,bold=False)
        ink(left+28,top+139,'Interface preview only. Listening stays unchanged.',20,(146,166,179))
        style = ui.APP_UI_STYLE.button
        button((right-28-style.height,bottom-24-style.height,right-28,bottom-24),
               'Close',('tool_close',None))

    def draw_band_activity(self, cache, snapshot):
        """Direct band selection with a 90 px chart, 40% shorter than the banner."""
        ui = self.ui
        bands = snapshot['bands']
        if not bands:
            return
        left, right = 20, ui.LOGICAL_W-20
        top, baseline, bottom = self.BAND_TOP, self.BAND_TOP+84, self.BAND_TOP+90
        cell = (right-left)/len(bands)
        for index, label in enumerate(bands):
            x0, x1 = left+index*cell, left+(index+1)*cell
            selected = label == snapshot['label']
            scanning = snapshot.get('scanning_band') == label and snapshot['active']
            box = (x0+1, top, x1-1, bottom)
            visual = ui.draw_styled_button_frame(box, active=selected)
            self.actions.append((box, ('band', label)))
            color = visual.text if selected else (141,178,196)
            if scanning:
                progress = max(0,min(1,(snapshot['completed']+snapshot['window_progress'])
                                      /max(1,snapshot['total'])))
                ui.draw_logical_rect(box[0], top-6, box[2], top-4, (49,70,81,255))
                ui.draw_logical_rect(box[0], top-6,
                                     box[0]+max(2,(box[2]-box[0])*progress), top-4, (*color[:3],255))
            ui.draw_text(cache, (x0+x1)/2, top+14, label.replace(' ', ''), visual.text,
                         20, False, False, 'cm', family=ui.APP_UI_STYLE.button.font_family)
            signals = snapshot.get('band_signals', {}).get(label)
            ui.draw_text(cache, (x0+x1)/2, top+35,
                         '—' if signals is None else str(len(signals)), visual.text,
                         14, False, False, 'cm', family=ui.APP_UI_STYLE.button.font_family)
            if signals is None:
                continue
            count = len(signals)
            spacing = (cell-12)/max(1,count)
            thickness = min(2, spacing*.65)
            for station, candidate in enumerate(signals):
                x = x0+6+(station+.5)*spacing
                height = .7*(4+max(0,min(1,(candidate.prominence-6)/44))*36)
                ui.draw_logical_rect(x-thickness/2, baseline-height,
                                     x+thickness/2, baseline, (*color[:3],255))

    def draw_research(self, cache, ink, button):
        ui = self.ui
        self.actions = []
        ui.draw_logical_rect(0,0,ui.LOGICAL_W,ui.LOGICAL_H,(0,0,0,255))
        future = self.research_future
        if future and future.done():
            try:
                _frequency,self.research_rows,error = future.result()
                self.research_error = bool(error)
            except Exception:
                self.research_rows,self.research_error = [],True
            self.research_future = None
        ink(20,30,'POSSIBLE STATIONS',28,(101,223,194))
        ink(20,66,f'{self.research_frequency:,.3f} kHz · online schedule suggestions',22)
        ink(20,94,'Listening stays unchanged · suggestions are not confirmed identities',18,(146,166,179))
        rows = self.research_rows
        if rows is None:
            ink(28,166,'Searching online schedules…',28)
        elif not rows:
            ink(28,166,'Search unavailable.' if self.research_error else 'No online schedule matches found.',26)
            ink(28,210,'Try again later; you can still listen to this frequency.',20,(146,166,179))
        else:
            for index,row in enumerate(rows[self.research_offset:self.research_offset+6]):
                y = 112+index*96
                box = (20,y,ui.LOGICAL_W-20,y+90)
                ui.draw_styled_button_frame(box)
                ui.draw_country_flag(row.get('country',''),32,y+8,42,28)
                ink(86,y+23,short_station_name(row.get('station','Unknown')),26,max_width=860,bold=False)
                ink(ui.LOGICAL_W-290,y+23,f"{row['frequency_khz']:,.3f} kHz",22)
                match = BroadcastMatch(row.get('station',''),row.get('country',''),
                    row.get('transmitter',''),row.get('power_kw',''),row.get('language',''),row.get('time',''))
                location,power,schedule = station_detail_lines(match)
                ink(32,y+52,location+' · '+power,19,(166,190,202),max_width=ui.LOGICAL_W-64)
                ink(32,y+77,schedule+' · '+row.get('source','Online schedule'),18,
                    (146,166,179),max_width=ui.LOGICAL_W-64)
        button(self.back_box(),'BACK',('research_back',None))
        if rows is not None:
            button((self.ui.LOGICAL_W-494,8,self.ui.LOGICAL_W-258,66),'SEARCH AGAIN',('research_retry',None))
