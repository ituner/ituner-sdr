"""Touch and encoder station picker over Home's RF canvas."""
from concurrent.futures import ThreadPoolExecutor
import re
import time
from dataclasses import dataclass, replace
import offline_schedules
import ui_chrome


@dataclass(frozen=True)
class BroadcastMatch:
    name: str
    country: str
    transmitter: str = ''
    power_kw: str = ''
    language: str = ''
    schedule: str = ''
    frequency_khz: float = None


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
                schedule=str(row.get('time') or '').strip(), frequency_khz=listed_frequency))
            seen.add(key)
    return tuple(matches)


def short_station_name(name):
    for word, short in ((r'\bInternational\b', 'Intl'),
                        (r'\bRadio\b', 'R.'), (r'\bVoice of\b', 'Vo.')):
        name = re.sub(word, short, name, flags=re.I)
    return name


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
    PAGE_SIZE = 10

    def __init__(self, ui, state):
        self.ui, self.state = ui, state
        self.actions = []
        self.matches = {}
        self.names_at = {}
        self.pending = {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='seek-names')
        self.press_action = None
        self.first_visible = 0
        self.band_menu = False
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

    @property
    def open(self):
        return self.state.smart_seek_snapshot()['open']

    def close(self, selected=None):
        self.state.close_smart_seek(selected=selected)
        self.press_action = None
        self.band_menu = False
        self.drag_origin = None
        self.drag_scroll = False
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
        for future in self.pending.values():
            future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def move(self, delta):
        if self.research_frequency is not None:
            self.scroll_research(delta)
            return
        self.state.move_smart_seek(delta)

    def back(self):
        if self.research_frequency is not None:
            self.close_research()
        else:
            self.close()

    def swipe(self, start_y, end_y):
        self.press_action = None
        if self.research_frequency is not None:
            self.scroll_research(round((start_y-end_y)/96))
            return
        if not self.band_menu and abs(end_y-start_y) >= 48:
            self.scroll_rows(round((start_y-end_y)/self.row_height))

    def scroll_rows(self, delta):
        self._scroll_to(self.first_visible+delta)

    def _scroll_to(self, first):
        snapshot = self.state.smart_seek_snapshot()
        candidates = snapshot['candidates']
        if not candidates:
            return
        last, slots = len(candidates), 0
        while last > 0:
            size = 2 if candidate_playing(candidates[last-1],snapshot['playing_khz']) else 1
            if slots+size > self.PAGE_SIZE:
                break
            slots += size
            last -= 1
        first = max(0, min(last, int(first)))
        current = next((i for i,p in enumerate(candidates) if p.frequency_khz == snapshot['selected']), 0)
        self.state.move_smart_seek(first-current)
        self.first_visible = first

    def selected(self):
        return None if self.research_frequency is not None else self.state.smart_seek_snapshot()['selected']

    def action_at(self, x, y):
        return next((action for box, action in reversed(self.actions) if self.ui.contains(box, x, y)), None)

    def press(self, x, y):
        # Save the action rather than hit-testing new discoveries on release.
        self.press_action = self.action_at(x, y)
        self.drag_origin = (y, self.first_visible) if self.press_action and self.press_action[0] == 'tune' else None
        self.drag_scroll = False
        self.drag(x, y)

    def signal_slider_box(self):
        bottom = self.ui.LOGICAL_H
        return (20, bottom-92, 332, bottom-30)

    def drag(self, x, y):
        if self.press_action == ('signal', None):
            fraction = max(0, min(1, (x-32)/(320-32)))
            self.state.set_smart_seek_sensitivity(round(100*(1-fraction)))
            return True
        if self.drag_origin and not self.band_menu:
            start, first = self.drag_origin
            if self.drag_scroll or abs(y-start) >= 16:
                self.drag_scroll = True
                self._scroll_to(first+round((start-y)/self.row_height))
                return True
        return False

    def release(self, x, y):
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
            return value
        elif kind == 'move':
            self.scroll_rows(value*self.visible_count)
        elif kind == 'refresh':
            self.state.start_smart_seek(refresh=True)
        elif kind == 'bands':
            self.band_menu = not self.band_menu
        elif kind == 'band':
            self.state.start_smart_seek(band_label=value)
            self.first_visible = 0
            self.band_menu = False
        elif kind == 'research':
            self.research(value)
        elif kind == 'research_back':
            self.close_research()
        elif kind == 'research_retry':
            self.research(self.research_frequency)
        elif kind == 'research_move':
            self.scroll_research(value*6)
        return None

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
                self.pending[frequency] = self.executor.submit(self.ui.lookup_shortwave_frequency, candidate.tuning_khz)
            if frequency in self.matches:
                matches = self.matches[frequency]
                self.state.note_smart_seek_identity(frequency,bool(matches),
                    tuple(m.frequency_khz for m in matches if m.frequency_khz is not None))

    def visible_rows(self, candidates, selected, playing_khz):
        """Keep row heights fixed; the listening row consumes two slots."""
        if not candidates:
            self.first_visible = 0
            return ()
        selected_index = next((i for i, item in enumerate(candidates) if item.frequency_khz == selected), 0)
        first = min(self.first_visible, len(candidates)-1, selected_index)

        def end_at(start):
            used, end = 0, start
            while end < len(candidates):
                slots = 2 if candidate_playing(candidates[end],playing_khz) else 1
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
        return candidates[first:end]

    def draw(self, cache):
        ui = self.ui
        snapshot = self.state.smart_seek_snapshot()
        if not snapshot['open']:
            return
        width, bottom = ui.LOGICAL_W, ui.LOGICAL_H
        self.actions = []
        ui.draw_logical_rect(0, 0, width, bottom, (0, 0, 0, 255))
        dim_row = False

        def ink(x, y, text, size=20, color=(205, 221, 229), max_width=None):
            if dim_row:
                color = tuple(round(channel*.5) for channel in color[:3])
            if max_width:
                text = ui.fit_station_text(cache, text, max_width, size, size >= 22, False, family='Liberation Sans')
            ui.draw_text(cache, x, y, text, color, size, size >= 22, False, 'lm', family='Liberation Sans')

        def button(box, label, action, active=False):
            if action[0] in ('move','research','research_move','research_retry'):
                visual = ui.draw_styled_button_frame(box, active=active)
                ui.draw_text(cache, (box[0]+box[2])/2, (box[1]+box[3])/2,
                             label.title(), visual.text, 18, False, False, 'cm',
                             family='Liberation Sans')
                self.actions.append((box, action))
                return
            # Shared rail buttons default to 13 px labels. This full-screen
            # touch workspace needs an explicit larger shared button style.
            style = replace(ui.APP_UI_STYLE.button, label_size=22)
            ui.draw_styled_text_button(cache, box, label, style=style, active=active)
            self.actions.append((box, action))

        if self.research_frequency is not None:
            self.draw_research(cache, ink, button)
            return
        ink(20, 31, 'SMART SEEK', 26, (101, 223, 194))
        button((width-330, 16, width-150, 74), 'BAND: '+snapshot['label'], ('bands', None), self.band_menu)
        back = ui_chrome.RAIL_BACK_BOX
        button(back, 'BACK', ('close', None))
        count = len(snapshot['candidates'])
        confirmed = sum(candidate.frequency_khz not in snapshot['stale'] for candidate in snapshot['candidates'])
        status = f"{snapshot['label']} · {confirmed} signals"
        if confirmed < count:
            status += f' · {count-confirmed} rechecking'
        status += (' · surveying other bands…' if snapshot['phase']=='spectrum' else
                   ' · checking '+str(snapshot['scanning_band'])+'…' if snapshot['phase']=='background' else
                   ' · surveying band…' if snapshot['phase']=='overview' else
                   ' · checking uncertain signal…' if snapshot['phase']=='review' else
                   ' · scanning…' if snapshot['active'] else
                   ' · watching this band…' if snapshot['continuous'] else ' · ready to listen')
        if snapshot['skipped']:
            status += ' · some areas could not be checked'
        ink(20, 59, status, 18, max_width=width-350)
        ink(20, 80, 'Tap to listen · swipe to scroll · names are schedule matches', 18, (146, 166, 179))
        ui.draw_logical_rect(20, 92, width-20, 96, (35, 48, 56, 255))
        progress = (snapshot['completed']+snapshot['window_progress'])/max(1, snapshot['total'])
        ui.draw_logical_rect(20, 92, 20+(width-40)*progress, 96, (68, 202, 168, 255))
        candidates = snapshot['candidates']
        visible = self.visible_rows(candidates, snapshot['selected'], snapshot['playing_khz'])
        self.visible_count = max(1, len(visible))
        self._names_for_page(candidates)
        gap = 4
        card_width = width-40
        card_height = (bottom-100-104-gap*(self.PAGE_SIZE-1))/self.PAGE_SIZE
        self.row_height = card_height+gap
        row_y = 100
        for index, candidate in enumerate(visible):
            dim_row = candidate.frequency_khz in snapshot['stale']
            x = 20
            y = row_y
            playing = candidate_playing(candidate,snapshot['playing_khz'])
            row_height = card_height*(2 if playing else 1)
            box = (x, y, x+card_width, y+row_height)
            row_y += row_height+gap
            selected = candidate.frequency_khz == snapshot['selected']
            ui.draw_styled_button_frame(box, active=selected)
            self.actions.append((box, ('tune', candidate.frequency_khz)))
            matches = self.matches.get(candidate.frequency_khz)
            displayed_frequency, approximate = station_frequency(candidate.tuning_khz,matches)
            ink(x+12, y+20, ('≈ ' if approximate else '')+frequency_label(displayed_frequency), 22,
                (101, 223, 194) if playing else (205, 221, 229))
            if playing:
                centered = abs(candidate.tuning_khz-snapshot['playing_khz']) < .5
                ink(x+76, y+44, 'PLAYING' if centered else 'Tap to center', 14, (101, 223, 194))
            else:
                ink(x+76,y+44,'Rechecking…' if dim_row else snapshot['signal_status'].get(candidate.frequency_khz,''),14,(146,166,179),max_width=120)
            displayed_matches = (matches or ())[:2 if playing else 4]
            for match_index, match in enumerate(displayed_matches):
                column, row = match_index % 2, match_index // 2
                column_width = (card_width-208)/(2 if len(matches) > 1 else 1)
                match_x = x+200+column*column_width
                crowded = not playing and len(matches) > 2
                match_y = y+(20 if playing else 15+row*26 if crowded else card_height/2)
                flag_width, flag_height = (36, 24) if crowded else (42, 28)
                ui.draw_country_flag(match.country, match_x, match_y-flag_height/2,
                                     flag_width, flag_height, alpha=.4 if dim_row else 1)
                name = match.name if len(matches) == 1 else short_station_name(match.name)
                ink(match_x+flag_width+10, match_y, name, 24 if crowded else 28,
                    max_width=column_width-flag_width-20)
                if playing:
                    for line, text in enumerate(station_detail_lines(match)):
                        ink(match_x, y+49+line*26, text, 18, (166, 190, 202),
                            max_width=column_width-12)
            if playing and matches and len(matches) > 2:
                ink(x+12, y+81, f'+{len(matches)-2} matches', 16, (146, 166, 179), max_width=175)
            if playing and abs(displayed_frequency-candidate.tuning_khz) > .001:
                ink(x+12,y+103,'RF '+frequency_label(candidate.tuning_khz),14,
                    (146,166,179),max_width=175)
            if not matches:
                classification = snapshot['signal_status'].get(candidate.frequency_khz,'')
                label = classification if classification in ('Carrier only','Unconfirmed') else 'Unknown'
                ink(x+200, y+card_height/2, 'Checking…' if matches is None else label, 28,
                    (146, 166, 179))
                if playing:
                    ink(x+200, y+76, 'Schedule and transmitter details unavailable.', 18,
                        (146, 166, 179), max_width=card_width-220)
                if matches is not None:
                    button((width-192, y, width-20, y+card_height), 'RESEARCH',
                           ('research',candidate.frequency_khz))
            strength = max(1, min(5, round(candidate.prominence/8)))
            for bar in range(5):
                height = 6+bar*3
                ui.draw_logical_rect(x+12+bar*10, y+49-height,
                                     x+19+bar*10, y+49,
                                     ((45, 78, 68, 255) if dim_row else (71, 204, 164, 255)) if bar < strength else (41, 55, 63, 255))
        dim_row = False
        if not candidates:
            ink(32, 180, 'Checking AM modulation…' if snapshot['active'] else 'No stations meet the minimum signal.', 24)
            ink(32, 222, 'Move Minimum signal toward Weak to include more stations.', 20)
        y = bottom-80
        slider_y = y-12
        ink(20, slider_y+9, 'Minimum signal', 18)
        thumb_x = 32+288*(1-snapshot['sensitivity']/100)
        ui.draw_logical_line(32, slider_y+32, 320, slider_y+32, (53, 74, 84), 4)
        ui.draw_logical_line(32, slider_y+32, thumb_x, slider_y+32, (101, 223, 194), 4)
        ui.draw_logical_circle(thumb_x, slider_y+32, 9, (208, 242, 237, 255), segments=24)
        ink(20, slider_y+54, 'Weak', 16, (146, 166, 179))
        ink(280, slider_y+54, 'Strong', 16, (146, 166, 179))
        self.actions.append((self.signal_slider_box(), ('signal', None)))
        button((344, y, 474, y+58), 'REFRESH', ('refresh', None))
        button((486, y, 744, y+58), 'SCROLL UP', ('move', -1))
        button((756, y, 1014, y+58), 'SCROLL DOWN', ('move', 1))
        ui_chrome.draw_status_clock(ui, cache, y=789)
        database_status = offline_schedules.store.status()[1]
        database_label = ('Updating station names…' if 'updating' in database_status else
                          'Station names unavailable' if 'unavailable' in database_status else
                          'Offline station names')
        ink(344, 789, database_label, 16, (146,166,179), max_width=670)
        if count > len(visible):
            track = bottom-104-100
            top = 100+track*self.first_visible/count
            ui.draw_logical_rect(width-12, top, width-7,
                                 top+track*len(visible)/count, (101, 223, 194, 255))
        if self.band_menu:
            self.actions = [a for a in self.actions if a[1][0] in ('close', 'bands')]
            ui.draw_logical_rect(12, 100, width-12, bottom-104, (8, 16, 22, 255))
            ink(28, 127, 'CHOOSE A BAND · previous finds are dimmed until checked again', 20,
                max_width=width-56)
            cell_width = (width-56)/4
            for index, label in enumerate(snapshot['bands']):
                x = 24+(index % 4)*cell_width
                row_y = 150+(index//4)*70
                found = snapshot['band_counts'].get(label)
                box = (x, row_y, x+cell_width-8, row_y+58)
                button(box, label, ('band', label),
                       label == snapshot['label'])
                indicator = '('+('—' if found is None else str(found))+')'
                ui.draw_text(cache, box[2]-10, row_y+14, indicator,
                             (146,166,179),16,False,False,'rm',
                             family=ui.APP_UI_STYLE.button.font_family)
            ink(28,450,'Counts kept for 1 hour · — not checked recently',18,(146,166,179))
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
                ink(86,y+23,short_station_name(row.get('station','Unknown')),26,max_width=860)
                ink(ui.LOGICAL_W-290,y+23,f"{row['frequency_khz']:,.3f} kHz",22)
                match = BroadcastMatch(row.get('station',''),row.get('country',''),
                    row.get('transmitter',''),row.get('power_kw',''),row.get('language',''),row.get('time',''))
                location,power,schedule = station_detail_lines(match)
                ink(32,y+52,location+' · '+power,19,(166,190,202),max_width=ui.LOGICAL_W-64)
                ink(32,y+77,schedule+' · '+row.get('source','Online schedule'),18,
                    (146,166,179),max_width=ui.LOGICAL_W-64)
        button(ui_chrome.RAIL_BACK_BOX,'BACK',('research_back',None))
        if rows is not None:
            button((344,720,548,778),'SEARCH AGAIN',('research_retry',None))
        if rows and len(rows)>6:
            button((560,720,780,778),'SCROLL UP',('research_move',-1))
            button((792,720,1014,778),'SCROLL DOWN',('research_move',1))
        ui_chrome.draw_status_clock(ui,cache,y=789)
        if self.research_error and rows:
            ink(344,789,'Some schedule sources could not be reached.',16,(146,166,179))
