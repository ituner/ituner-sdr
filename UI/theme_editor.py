"""Draft-only preset customization over the complete, live HOME framebuffer."""
from copy import deepcopy
import colorsys
from theme_fonts import FONT_STYLES
from theme_colors import saturate_rgb, apply_muted_text_colors
import math

from theme_system import (BUILTIN_THEMES, BUILTIN_THEME_IDS, DEFAULT_THEME, COLOR_NAMES, TEXT_SCALE_MIN,
                          TEXT_SCALE_MAX, is_builtin_theme_id)

COLOR_GROUPS = (
    ("BASE", ("background", "sidebar", "sidebar_header", "section_surface", "section_border", "divider", "top_instrument_band", "sidebar_rule", "focus")),
    ("TEXT", ("text", "secondary_text", "section_heading", "sidebar_title", "frequency", "focus_text", "untested_text")),
    ("BUTTON", ("surface", "border", "active_surface", "active_border", "selected_surface", "selected_border", "pressed_surface", "pressed_border")),
    ("STATES", ("ready", "waiting", "danger", "danger_border", "untested", "notice")),
    ("RADIO", ("meter_on", "meter_hot", "meter_off")),
    ("BAND", ("passband_fill", "passband_border", "passband_center", "home_passband_fill", "home_passband_border", "home_passband_center")),
    ("SLIDERS", ("slider_track", "slider_fill", "slider_thumb", "slider_marker")),
    ("FOOTER", ("footer_background", "footer_primary", "footer_live")),
    ("S-METER", ("smeter_scale", "smeter_hot", "smeter_rail", "smeter_tick", "smeter_minor", "smeter_active", "smeter_dbm", "smeter_marker", "smeter_peak")),
    ("SPECTRUM", ("spectrum_field", "spectrum_grid", "spectrum_axis", "spectrum_tick", "spectrum_label", "spectrum_peak_fill", "spectrum_peak_line", "spectrum_fill", "spectrum_line")),
    ("WATERFALL", ("waterfall_low", "waterfall_high", "waterfall_ruler_background", "waterfall_ruler_minor", "waterfall_ruler_major", "waterfall_ruler_label")),
)
assert set(COLOR_NAMES) == {key for _, keys in COLOR_GROUPS for key in keys}

CARDS_PER_PAGE = 4
ACCENTS = (("original", "Original", None), ("mint", "Mint", (114, 235, 174)),
           ("cyan", "Cyan", (87, 212, 235)), ("amber", "Amber", (255, 194, 92)),
           ("white", "White", (235, 235, 235)))
ACCENT_ROLES = ("focus", "focus_text", "frequency", "slider_fill", "active_border",
                "selected_border", "pressed_border", "pressed_surface",
                "passband_fill", "passband_border", "passband_center",
                "home_passband_fill", "home_passband_border", "home_passband_center")
FULL_HOME_BOX = (0, 0, 1280, 800)
COLOR_STRIP_HEIGHT = 24*.8
INTENSITY_LIMITS = {'color_intensity': (50, 150), 'border_intensity': (25, 200), 'saturation': (0,200)}
BORDER_BACKGROUNDS = {'border': 'surface', 'active_border': 'active_surface',
    'selected_border': 'selected_surface', 'pressed_border': 'pressed_surface',
    'section_border': 'section_surface', 'divider': 'background', 'sidebar_rule': 'sidebar'}
STATUS_COLORS = ('ready', 'waiting', 'danger', 'danger_border', 'notice', 'untested')
TEXT_ROLES = ('text', 'secondary_text', 'section_heading', 'sidebar_title', 'untested_text', 'footer_primary')


def rainbow_rgb(position):
    return [round(v*255) for v in colorsys.hsv_to_rgb(max(0,min(1,position)),1,1)]


def contains(box, x, y):
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def luminance(rgb):
    channels = [v / 255 for v in rgb[:3]]
    channels = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(channels, (.2126, .7152, .0722)))


def contrast(first, second):
    lo, hi = sorted((luminance(first), luminance(second)))
    return (hi + .05) / (lo + .05)


def accent_colors(base, identifier):
    """Coordinated interface/passband accents; spectrum and status colors stay separate."""
    colors = base['colors']
    rgb = next(rgb for key, _name, rgb in ACCENTS if key == identifier)
    if rgb is None:
        return {key: deepcopy(colors[key]) for key in ACCENT_ROLES}
    result = {}
    for key in ACCENT_ROLES:
        if key == 'focus_text':
            continue
        background = colors['sidebar'] if key == 'frequency' else colors['background']
        chosen = rgb
        # Pale accents need a darker variant on light interface presets.
        if key != 'pressed_surface' and contrast(chosen, background) < 4.5:
            chosen = tuple(round(v * .3) for v in rgb)
        result[key] = [*chosen, *colors[key][3:]]
    focus = result['focus']
    result['focus_text'] = list(max(((0, 0, 0), (255, 255, 255)), key=lambda c: contrast(c, focus)))
    return result


def inspector_box(editor):
    offset = 256 if editor.entry_theme['sidebar'] == 'left' else 0
    return (16 + offset, 224, 1008 + offset, 718)


def theme_screen_boxes(editor, *, ignore_overlay=False):
    """Physical-screen rectangles shared by drawing and touch; never double-mirrored."""
    dx = inspector_box(editor)[0] - 16
    if editor.overlay == 'colors':
        boxes = {'color:cancel':(652,634,812,698), 'color:save':(828,634,988,698)}
        for field,x in (('accent',36),('text',524)):
            boxes.update({f'color:{field}:black':(x,344,x+44,388),
                          f'color:{field}:white':(x+56,344,x+100,388),
                          f'color:{field}:rainbow':(x+120,344,x+464,388)})
        boxes.update({'color_intensity': (36,480,500,524),
                      'border_intensity': (524,480,988,524),
                      'saturation': (36,568,988,612)})
        return {key:(a+dx,b,c+dx,d) for key,(a,b,c,d) in boxes.items()}
    if editor.fullscreen:
        if not editor.fullscreen_controls:
            return {'show': (756 + dx, 642, 992 + dx, 706)}
        boxes = {'hide': (828, 240, 988, 304), 'reset': (36, 634, 196, 698),
                 'choose': (212, 634, 372, 698), 'back': (652, 634, 812, 698),
                 'save': (828, 634, 988, 698), 'text:smaller': (396, 344, 460, 408),
                 'text:reset': (468, 344, 564, 408), 'text:larger': (572, 344, 636, 408),
                 'option:straight': (732, 344, 846, 408),
                 'option:rounded': (854, 344, 968, 408)}
        boxes.update({'colors:accent':(36,344,188,408), 'colors:text':(204,344,356,408)})
        for i,(identifier,_name) in enumerate(FONT_STYLES):
            x = 36+i*176
            boxes['font:'+identifier] = (x,508,x+160,572)
        return {key: (a + dx, b, c + dx, d) for key, (a,b,c,d) in boxes.items()}
    boxes = {'back': (828, 634, 988, 698),
             'theme_previous': (36, 634, 204, 698),
             'theme_next': (220, 634, 388, 698)}
    items = editor.themes[editor.page * CARDS_PER_PAGE:(editor.page + 1) * CARDS_PER_PAGE]
    for i, item in enumerate(items):
        x, y = 36 + i % 2 * 484, 328 + i // 2 * 140
        boxes['theme:' + item['id']] = (x, y, x + 468, y + 124)
    return {key: (a + dx, b, c + dx, d) for key, (a,b,c,d) in boxes.items()}


class ThemeEditor:
    def __init__(self, library, notice_duration=2.5):
        self.library = library
        self.notice_duration = notice_duration
        self.live_frame = None
        self.open = False
        self.fullscreen = False
        self.fullscreen_controls = True
        self.overlay = None
        self.notice_until = 0
        self.notice_action = self.notice_detail = self.error = self.status = ''
        self.exit_surface = 'home'
        self.mode = 'browse'
        self.page = 0
        self.selected_id = library.active_id
        self.entry_theme = deepcopy(library.get(library.active_id))
        self.draft = deepcopy(self.entry_theme)
        self._drafts = {}

    @property
    def themes(self):
        return [self.library.get(key) for key in
                (*BUILTIN_THEME_IDS, *(item['id'] for item in self.library.themes))]

    @property
    def page_count(self):
        return max(1, math.ceil(len(self.themes) / CARDS_PER_PAGE))

    @property
    def preview(self):
        return self.draft

    @property
    def dirty(self):
        return self.draft != self.entry_theme

    def _keep_operational_settings(self, theme):
        for key in ('sidebar', 'units', 'smeter_style'):
            theme[key] = deepcopy(self.entry_theme[key])
        # Derive status colors from an unchanged source too, so Saturation
        # never becomes baked into the next session's Reset baseline.
        status_base = (DEFAULT_THEME['colors'] if is_builtin_theme_id(theme['id']) else
                       theme.get('customization_base',{}).get('colors',self.entry_theme['colors']))
        for key, color in status_base.items():
            if key in STATUS_COLORS:
                theme['colors'][key] = deepcopy(color)
        identifier = theme['id']
        theme['waterfall_style'] = identifier if is_builtin_theme_id(identifier) else 'custom'
        return theme

    @property
    def baseline(self):
        theme = BUILTIN_THEMES.get(self.selected_id) or self.library.get(self.selected_id)
        theme = deepcopy(theme)
        if not is_builtin_theme_id(self.selected_id):
            base = deepcopy(theme.get('customization_base', {
                key: theme[key] for key in ('colors','radius','text_scale_percent','font_style')}))
            theme.update(base)
            theme['customization_base'] = base
        theme.pop('accent_rgb',None)
        theme.pop('text_rgb',None)
        if not is_builtin_theme_id(self.selected_id):
            theme['font_style'] = theme.get('customization_base',{}).get('font_style','current')
        theme.update(accent_id='original', color_intensity_percent=100, border_intensity_percent=25,
                     saturation_percent=100)
        return self._keep_operational_settings(theme)

    @property
    def accent_id(self):
        if self.draft.get('accent_id') in {key for key,_name,_rgb in ACCENTS}:
            return self.draft['accent_id']
        for key, _name, _rgb in ACCENTS:
            if all(self.draft['colors'][role] == color
                   for role, color in accent_colors(self.baseline, key).items()):
                return key
        return 'original'

    def chosen_color(self, field):
        """Return the actual choice, independent of brightness and saturation."""
        if field+'_rgb' in self.draft:
            return list(self.draft[field+'_rgb'])
        if field == 'accent':
            rgb = next(rgb for key,_name,rgb in ACCENTS if key == self.accent_id)
            if rgb is not None:
                return list(rgb)
        role = 'focus' if field == 'accent' else 'text'
        return list(self.baseline['colors'][role][:3])

    def _rebuild_colors(self):
        """Derive every adjustment from a stable base, never from rounded output."""
        accent = self.accent_id
        base = self.baseline
        colors = deepcopy(base['colors'])
        colors.update(accent_colors(base, accent))
        if 'accent_rgb' in self.draft:
            rgb = self.draft['accent_rgb']
            for key in ACCENT_ROLES:
                if key != 'focus_text':
                    colors[key] = [*rgb,*colors[key][3:]]
            colors['focus_text'] = list(max(((0,0,0),(255,255,255)),key=lambda c:contrast(c,rgb)))
        if 'text_rgb' in self.draft:
            for key in TEXT_ROLES:
                colors[key] = [*self.draft['text_rgb'],*colors[key][3:]]
        original = deepcopy(colors)
        intensity = self.draft.get('color_intensity_percent',100)
        borders = self.draft.get('border_intensity_percent',25)
        for key,color in original.items():
            # Waterfall pixels receive brightness after their color mapping,
            # so their endpoints must not be multiplied a second time here.
            if key not in BORDER_BACKGROUNDS and key not in (*STATUS_COLORS,'waterfall_low','waterfall_high'):
                colors[key] = [*(min(255,round(v*intensity/100)) for v in color[:3]),*color[3:]]
        if intensity != 100:
            for key,background in (('text','background'),('secondary_text','background'),
                    ('section_heading','section_surface'),('sidebar_title','sidebar_header'),
                    ('frequency','sidebar'),('focus_text','focus'),('footer_primary','footer_background'),
                    ('footer_live','footer_background'),('spectrum_label','spectrum_field')):
                # Text follows brightness directly, including preset text.
                # The color editor keeps its own controls readable separately.
                if key in TEXT_ROLES:
                    continue
                target = min(4.5,contrast(original[key],original[background]))
                if contrast(colors[key],colors[background]) < target:
                    endpoint = max(((0,0,0),(255,255,255)),key=lambda c: contrast(c,colors[background]))
                    for step in range(1,101):
                        candidate = [round(v+(end-v)*step/100) for v,end in zip(colors[key][:3],endpoint)]
                        if contrast(candidate,colors[background]) >= target:
                            colors[key] = [*candidate,*colors[key][3:]]
                            break
            # Shared pressed buttons use black lettering. Keep their fill
            # readable even when the rest of the appearance is dimmed.
            if contrast((0,0,0),colors['pressed_surface']) < 4.5:
                for step in range(1,101):
                    candidate = [round(v+(255-v)*step/100) for v in colors['pressed_surface'][:3]]
                    if contrast((0,0,0),candidate) >= 4.5:
                        colors['pressed_surface'] = [*candidate,*colors['pressed_surface'][3:]]
                        break
        for key,background in BORDER_BACKGROUNDS.items():
            colors[key] = [*(max(0,min(255,round(bg+(v-bg)*borders/100)))
                for v,bg in zip(original[key][:3],original[background][:3])),*original[key][3:]]
        saturation = self.draft.get('saturation_percent',100)
        for key,color in colors.items():
            # Waterfall endpoints stay raw: pixels are saturated after mapping.
            if key not in ('waterfall_low','waterfall_high'):
                colors[key] = saturate_rgb(color,saturation)
        apply_muted_text_colors(colors)
        self.draft.update(colors=colors,accent_id=accent,color_intensity_percent=intensity,
                          border_intensity_percent=borders,saturation_percent=saturation)
        if 'customization_base' in base:
            self.draft['customization_base'] = deepcopy(base['customization_base'])

    def _set_intensity(self, field, amount):
        low,high = INTENSITY_LIMITS[field]
        self.draft[field+'_percent'] = max(low,min(high,round(amount/5)*5))
        self._rebuild_colors()

    def _intensity_at_x(self, field, x):
        a,_b,c,_d = theme_screen_boxes(self)[field]
        low,high = INTENSITY_LIMITS[field]
        self._set_intensity(field,low+max(0,min(1,(x-a-4)/max(1,c-a-8)))*(high-low))

    def show(self):
        self.entry_theme = deepcopy(self.library.get(self.library.active_id))
        self.draft = deepcopy(self.entry_theme)
        self.selected_id = self.entry_theme['id']
        self._drafts = {}
        self.open, self.mode = True, 'preview'
        self.fullscreen, self.fullscreen_controls = False, True
        self.page = next(i // CARDS_PER_PAGE for i, theme in enumerate(self.themes)
                         if theme['id'] == self.selected_id)
        self.error = self.status = ''
        self.overlay = None

    def select_theme(self, identifier):
        theme = self.library.get(identifier)
        if theme is None:
            return
        self._drafts[self.selected_id] = deepcopy(self.draft)
        self.selected_id = identifier
        self.draft = self._keep_operational_settings(deepcopy(self._drafts.get(identifier, theme)))
        self._rebuild_colors()
        self.fullscreen = self.fullscreen_controls = True
        self.overlay = None
        self.error = self.status = ''

    def reset_theme(self):
        self.draft = self.baseline
        self._rebuild_colors()
        self.error = ''
        self.status = 'Original theme restored'

    def cancel(self):
        self.draft = deepcopy(self.entry_theme)
        self._drafts = {}
        self.open = False
        self.mode = 'browse'
        self.error = self.status = ''
        self.exit_surface = 'home'

    def back(self):
        if self.fullscreen:
            self._drafts[self.selected_id] = deepcopy(self.draft)
            self.fullscreen = False
            self.error = ''
        else:
            self.cancel()

    def save(self):
        try:
            if is_builtin_theme_id(self.selected_id):
                self.library.customize_builtin(self.draft)
            else:
                self.library.upsert(self.draft)
        except (OSError, ValueError) as error:
            self.error = str(error)
            self.fullscreen_controls = True
            return False
        self.selected_id = self.library.active_id
        self.entry_theme = deepcopy(self.library.get(self.selected_id))
        self.draft = deepcopy(self.entry_theme)
        self.open, self.mode = False, 'browse'
        self.exit_surface = 'home'
        self.error = ''
        return True

    def drag(self, x, y, *, started_at=None):
        if not (self.open and self.fullscreen and self.fullscreen_controls):
            return
        origin = started_at or (x,y)
        if self.overlay == 'colors':
            for field in ('accent','text'):
                key = f'color:{field}:rainbow'
                if contains(theme_screen_boxes(self)[key],*origin):
                    self._rainbow_at_x(field,x)
                    return
            for field in INTENSITY_LIMITS:
                if contains(theme_screen_boxes(self)[field],*origin):
                    self._intensity_at_x(field,x)
                    return
            return

    def _rainbow_at_x(self, field, x):
        a,_,c,_ = theme_screen_boxes(self)[f'color:{field}:rainbow']
        self.draft[field+'_rgb'] = rainbow_rgb((x-a)/max(1,c-a))
        self._rebuild_colors()

    def choose_accent(self, identifier):
        self.draft.pop('accent_rgb',None)
        self.draft['accent_id'] = identifier
        self._rebuild_colors()

    def tap(self, x, y):
        if not self.open:
            return
        action = next((key for key, box in theme_screen_boxes(self).items() if contains(box, x, y)), None)
        if action is None:
            return
        if action == 'theme_previous' and self.page == 0:
            return
        if action == 'theme_next' and self.page + 1 >= self.page_count:
            return
        self.error = self.status = ''
        if action.startswith('colors:'):
            self._color_entry = deepcopy(self.draft)
            self.overlay = 'colors'
        elif action == 'color:save':
            self.overlay = None
        elif action == 'color:cancel':
            self.draft = self._color_entry
            self.overlay = None
        elif action.startswith('color:'):
            _,field,choice = action.split(':')
            if choice == 'rainbow':
                self._rainbow_at_x(field,x)
            else:
                self.draft[field+'_rgb'] = [0,0,0] if choice == 'black' else [255,255,255]
                self._rebuild_colors()
        elif action == 'back':
            self.cancel()
        elif action == 'choose':
            self.back()
        elif action == 'save':
            self.save()
        elif action == 'reset':
            self.reset_theme()
        elif action in ('hide', 'show'):
            self.fullscreen_controls = action == 'show'
        elif action.startswith('theme:'):
            self.select_theme(action.split(':', 1)[1])
        elif action == 'theme_previous':
            self.page = max(0, self.page - 1)
        elif action == 'theme_next':
            self.page = min(self.page_count - 1, self.page + 1)
        elif action.startswith('accent:'):
            self.choose_accent(action.split(':',1)[1])
        elif action in INTENSITY_LIMITS:
            self._intensity_at_x(action,x)
        elif action.split(':',1)[0] in INTENSITY_LIMITS:
            field,step = action.split(':',1)
            self._set_intensity(field,self.draft.get(field+'_percent',100)+(-5 if step=='smaller' else 5))
        elif action.startswith('option:'):
            self.draft['radius'] = 8 if action.endswith('rounded') else 0
        elif action.startswith('text:'):
            self.draft['text_scale_percent'] = (100 if action == 'text:reset' else
                max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX,
                    self.draft['text_scale_percent'] + (-5 if action == 'text:smaller' else 5))))
        elif action.startswith('font:'):
            self.draft['font_style'] = action.split(':',1)[1]
