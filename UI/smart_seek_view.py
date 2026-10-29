"""Touch and encoder station picker over Home's RF canvas."""
from concurrent.futures import ThreadPoolExecutor
import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class BroadcastMatch:
    name: str
    country: str
    transmitter: str = ''
    power_kw: str = ''
    language: str = ''
    schedule: str = ''


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
        key = name.casefold(), country.casefold()
        if name and key not in seen:
            matches.append(BroadcastMatch(name, country,
                transmitter=str(row.get('transmitter') or '').strip(),
                power_kw=str(row.get('power_kw') or '').strip(),
                language=str(row.get('language') or '').strip(),
                schedule=str(row.get('time') or '').strip()))
            seen.add(key)
    return tuple(matches)


def short_station_name(name):
    for word, short in ((r'\bInternational\b', 'Intl'),
                        (r'\bRadio\b', 'R.'), (r'\bVoice of\b', 'Vo.')):
        name = re.sub(word, short, name, flags=re.I)
    return name


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
    PAGE_SIZE = 8

    def __init__(self, ui, state):
        self.ui, self.state = ui, state
        self.actions = []
        self.matches = {}
        self.names_at = {}
        self.pending = {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='seek-names')
        self.press_action = None
        self.first_visible = 0

    @property
    def open(self):
        return self.state.smart_seek_snapshot()['open']

    def close(self, selected=None):
        self.state.close_smart_seek(selected=selected)
        self.press_action = None

    def shutdown(self):
        self.close()
        for future in self.pending.values():
            future.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def move(self, delta):
        self.state.move_smart_seek(delta)

    def swipe(self, start_y, end_y):
        self.press_action = None
        if abs(end_y-start_y) >= 48:
            self.move(self.PAGE_SIZE if end_y < start_y else -self.PAGE_SIZE)

    def selected(self):
        return self.state.smart_seek_snapshot()['selected']

    def action_at(self, x, y):
        return next((action for box, action in self.actions if self.ui.contains(box, x, y)), None)

    def press(self, x, y):
        # Save the action rather than hit-testing new discoveries on release.
        self.press_action = self.action_at(x, y)
        self.drag(x, y)

    def signal_slider_box(self):
        bottom = self.ui.LOGICAL_H-self.ui.BOTTOM_STATUS_H
        return (20, bottom-72, 332, bottom-14)

    def drag(self, x, y):
        if self.press_action == ('signal', None):
            fraction = max(0, min(1, (x-32)/(320-32)))
            self.state.set_smart_seek_sensitivity(round(100*(1-fraction)))
            return True
        return False

    def release(self, x, y):
        if self.drag(x, y):
            self.press_action = None
            return None
        action, self.press_action = self.press_action, None
        if action is None or action != self.action_at(x, y):
            return None
        kind, value = action
        if kind == 'close':
            self.close()
        elif kind == 'tune':
            return value
        elif kind == 'move':
            self.move(value)
        elif kind == 'refresh':
            self.state.start_smart_seek(refresh=True)
        return None

    def _names_for_page(self, candidates):
        # Only visible cards are looked up, with at most two jobs in flight.
        # Schedule failures leave fully usable Unknown frequency cards.
        for frequency, future in list(self.pending.items()):
            if future.done():
                try:
                    _frequency, rows, _error = future.result()
                except Exception:
                    rows = []
                self.matches[frequency] = schedule_matches(rows, self.ui._frequency_identity_schedule_active)
                self.names_at[frequency] = time.monotonic()
                del self.pending[frequency]
        for candidate in candidates:
            frequency = candidate.frequency_khz
            if time.monotonic()-self.names_at.get(frequency, time.monotonic()) >= 300:
                self.matches.pop(frequency, None)
            if frequency not in self.matches and frequency not in self.pending and len(self.pending) < 2:
                self.pending[frequency] = self.executor.submit(self.ui.lookup_shortwave_frequency, frequency)

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
                slots = 2 if abs(candidates[end].frequency_khz-playing_khz) < .5 else 1
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
        width, bottom = ui.rf_canvas_width(), ui.LOGICAL_H-ui.BOTTOM_STATUS_H
        self.actions = []
        ui.draw_logical_rect(0, 0, width, bottom, (0, 0, 0, 255))

        def ink(x, y, text, size=20, color=(205, 221, 229), max_width=None):
            if max_width:
                text = ui.fit_station_text(cache, text, max_width, size, size >= 22, False, family='Liberation Sans')
            ui.draw_text(cache, x, y, text, color, size, size >= 22, False, 'lm', family='Liberation Sans')

        def button(box, label, action, active=False):
            ui.draw_styled_text_button(cache, box, label, size=20, active=active)
            self.actions.append((box, action))

        ink(20, 31, 'FINDING STATIONS…' if snapshot['active'] else 'SMART SEEK', 26, (101, 223, 194))
        button((width-138, 16, width-18, 74), 'CLOSE', ('close', None))
        count = len(snapshot['candidates'])
        status = f"{snapshot['label']} · {count} stations · {snapshot['completed']}/{snapshot['total']} windows"
        if snapshot['cached']:
            age = int(snapshot['age_seconds'])
            age_label = f'{age}s' if age < 60 else f'{age//60}m'
            status = f"{snapshot['label']} · {count} stations · saved {age_label} ago"
            if snapshot['completed'] < snapshot['total']:
                status += ' · partial survey'
        if snapshot['skipped']:
            status += ' · incomplete coverage'
        ink(20, 67, status, max_width=width-180)
        ink(20, 94, 'Tap to listen · swipe for more · names are schedule matches', 18, (146, 166, 179))
        ui.draw_logical_rect(20, 108, width-20, 112, (35, 48, 56, 255))
        progress = snapshot['completed']/max(1, snapshot['total'])
        ui.draw_logical_rect(20, 108, 20+(width-40)*progress, 112, (68, 202, 168, 255))
        candidates = snapshot['candidates']
        visible = self.visible_rows(candidates, snapshot['selected'], snapshot['playing_khz'])
        self._names_for_page(visible)
        gap = 4
        card_width = width-40
        card_height = (bottom-118-88-gap*(self.PAGE_SIZE-1))/self.PAGE_SIZE
        row_y = 118
        for index, candidate in enumerate(visible):
            x = 20
            y = row_y
            playing = abs(candidate.frequency_khz-snapshot['playing_khz']) < .5
            row_height = card_height*(2 if playing else 1)
            box = (x, y, x+card_width, y+row_height)
            row_y += row_height+gap
            selected = candidate.frequency_khz == snapshot['selected']
            ui.draw_styled_button_frame(box, active=selected)
            self.actions.append((box, ('tune', candidate.frequency_khz)))
            ink(x+12, y+20, f'{candidate.frequency_khz:,.3f} kHz', 22,
                (101, 223, 194) if playing else (205, 221, 229))
            if playing:
                ink(x+76, y+44, 'PLAYING', 15, (101, 223, 194))
            matches = self.matches.get(candidate.frequency_khz)
            displayed_matches = (matches or ())[:2 if playing else 4]
            for match_index, match in enumerate(displayed_matches):
                column, row = match_index % 2, match_index // 2
                column_width = (card_width-208)/2
                match_x = x+200+column*column_width
                match_y = y+(20 if playing else 17+row*26 if len(matches) > 2 else card_height/2)
                ui.draw_country_flag(match.country, match_x, match_y-10, 30, 20)
                ink(match_x+38, match_y, short_station_name(match.name), 20,
                    max_width=column_width-46)
                if playing:
                    for line, text in enumerate(station_detail_lines(match)):
                        ink(match_x, y+49+line*26, text, 18, (166, 190, 202),
                            max_width=column_width-12)
            if playing and matches and len(matches) > 2:
                ink(x+12, y+81, f'+{len(matches)-2} matches', 16, (146, 166, 179), max_width=175)
            if not matches:
                ink(x+200, y+card_height/2, 'Checking…' if matches is None else 'Unknown', 20,
                    (146, 166, 179))
                if playing:
                    ink(x+200, y+76, 'Schedule and transmitter details unavailable.', 18,
                        (146, 166, 179), max_width=card_width-220)
            strength = max(1, min(5, round(candidate.prominence/8)))
            for bar in range(5):
                height = 6+bar*3
                ui.draw_logical_rect(x+12+bar*10, y+49-height,
                                     x+19+bar*10, y+49,
                                     (71, 204, 164, 255) if bar < strength else (41, 55, 63, 255))
        if not candidates:
            ink(32, 180, 'Checking AM modulation…' if snapshot['active'] else 'No stations meet the minimum signal.', 24)
            ink(32, 222, 'Move Minimum signal toward Weak to include more stations.', 20)
        y = bottom-72
        ink(20, y+9, 'Minimum signal', 18)
        thumb_x = 32+288*(1-snapshot['sensitivity']/100)
        ui.draw_logical_line(32, y+32, 320, y+32, (53, 74, 84), 4)
        ui.draw_logical_line(32, y+32, thumb_x, y+32, (101, 223, 194), 4)
        ui.draw_logical_circle(thumb_x, y+32, 9, (208, 242, 237, 255), segments=24)
        ink(20, y+54, 'Weak', 16, (146, 166, 179))
        ink(280, y+54, 'Strong', 16, (146, 166, 179))
        self.actions.append((self.signal_slider_box(), ('signal', None)))
        button((344, y, 474, y+58), 'REFRESH', ('refresh', None))
        button((486, y, 550, y+58), '↑', ('move', -self.PAGE_SIZE))
        first = self.first_visible+1 if visible else 0
        ink(561, y+29, f'{first}–{self.first_visible+len(visible)}/{count}', 18)
        button((640, y, 704, y+58), '↓', ('move', self.PAGE_SIZE))
