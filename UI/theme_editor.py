"""One preview session for choosing a theme, meter and optional customizations."""
from copy import deepcopy
import colorsys
import math
import time

from smeter_styles import METER_STYLES
from theme_colors import shade_grid, transparency_percent, with_transparency
from theme_system import (BUILTIN_THEME_IDS, COLOR_NAMES, DEFAULT_THEME_ID,
                          TEXT_SCALE_MIN, TEXT_SCALE_MAX, is_builtin_theme_id,
                          normalize_theme, theme_appearance)

COLOR_GROUPS = (
    ("BASE", ("background", "sidebar", "section_surface", "section_border", "divider", "top_instrument_band", "sidebar_rule", "focus")),
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
NAME_KEYS = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") + ("SPACE", "DEL", "CLEAR", "CANCEL", "DONE")
HEX_KEYS = tuple("0123456789ABCDEF") + ("DEL", "CLEAR", "CANCEL", "APPLY")
NUMBER_KEYS = tuple("123456789") + ("CLEAR", "0", "DEL", "CANCEL", "DONE")
CARDS_PER_PAGE = 4
METER_CARDS_PER_PAGE = 1
METER_FILTERS = (("all", "ALL"), ("digital", "LED / SLIDER"), ("analog", "ANALOG"), ("eye", "MAGIC EYE"))
BACK_BOX = (1034, 750, 1270, 794)
APPLY_BOX = (1034, 696, 1270, 742)
PREVIEW_BOX = (0, 0, 1024, 800)


def contains(box, x, y):
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def theme_screen_boxes(editor, *, ignore_overlay=False):
    """Paint and touch use the same non-overlapping targets."""
    if editor.overlay and not ignore_overlay:
        if editor.overlay == "delete":
            return {"delete_cancel": (360, 446, 624, 510), "delete_confirm": (648, 446, 912, 510)}
        prefix, keys, columns = ("name", NAME_KEYS, 10) if editor.overlay == "name" else (
            ("hex", HEX_KEYS, 4) if editor.overlay == "hex" else ("alpha", NUMBER_KEYS, 3))
        width = 1080 if prefix == "name" else 584
        left = (1280 - width) / 2
        cell = (width - (columns - 1) * 8) / columns
        return {f"{prefix}:{key}": (left + (index % columns) * (cell + 8), 252 + (index // columns) * 68,
                                      left + (index % columns) * (cell + 8) + cell, 312 + (index // columns) * 68)
                for index, key in enumerate(keys)}
    boxes = {"back": BACK_BOX, "save": APPLY_BOX}
    boxes.update({"tab:themes": (1034, 52, 1148, 102),
                  "tab:meters": (1156, 52, 1270, 102),
                  "tab:customize": (1034, 112, 1270, 156)})
    if editor.tab in ("themes", "meters"):
        items = editor.themes if editor.tab == "themes" else editor.meter_ids
        page = editor.page if editor.tab == "themes" else editor.meter_page
        count = CARDS_PER_PAGE if editor.tab == "themes" else METER_CARDS_PER_PAGE
        for slot, item in enumerate(items[page * count:page * count + count]):
            identifier = item["id"] if editor.tab == "themes" else item
            y = 202 + slot * 98 if editor.tab == "themes" else 332
            boxes[f"{'theme' if editor.tab == 'themes' else 'meter'}:{identifier}"] = (1034, y, 1270, y + (88 if editor.tab == "themes" else 258))
        prefix = "theme" if editor.tab == "themes" else "meter"
        boxes[f"{prefix}_previous"] = (1034, 606, 1148, 658)
        boxes[f"{prefix}_next"] = (1156, 606, 1270, 658)
        if editor.tab == "meters":
            for index, (name, _label) in enumerate(METER_FILTERS):
                x, y = 1034 + (index % 2) * 122, 214 + (index // 2) * 54
                boxes[f"filter:{name}"] = (x, y, x + 114, y + 46)
    elif editor.colors_open:
        boxes.update({"appearance": (660, 112, 856, 164),
                      "group_previous": (660, 184, 724, 240), "group_next": (1192, 184, 1256, 240),
                      "part_previous": (660, 396, 852, 440), "part_next": (1064, 396, 1256, 440),
                      "hue": (660, 472, 1256, 520),
                      "hex_open": (660, 656, 952, 712)})
        keys = editor.family_keys
        for slot in range(4):
            index = editor.part_page * 4 + slot
            if index < len(keys):
                x, y = 660 + (slot % 2) * 304, 260 + (slot // 2) * 64
                boxes[f"part:{index}"] = (x, y, x + 292, y + 56)
        for index in range(16):
            x, y = 660 + (index % 8) * 76, 540 + (index // 8) * 52
            boxes[f"shade:{index}"] = (x, y, x + 64, y + 44)
        if len(editor.current_color) == 4:
            boxes["alpha_open"] = (964, 656, 1256, 712)
    else:
        boxes["theme_name"] = (660, 156, 1256, 220)
        for row, options in enumerate((("left", "right"), ("straight", "rounded"))):
            for index, value in enumerate(options):
                boxes[f"option:{value}"] = (852 + index * 204, 248 + row * 72, 1048 + index * 204, 304 + row * 72)
        boxes.update({"text:smaller": (852, 392, 944, 448), "text:larger": (1160, 392, 1256, 448),
                      "text:reset": (952, 392, 1152, 448), "colors": (660, 548, 1256, 608),
                      "copy": (660, 636, 952, 700)})
        for index, value in enumerate(("original", "metric", "imperial")):
            boxes[f"option:{value}"] = (852 + index * 136, 464, 980 + index * 136, 520)
        if not is_builtin_theme_id(editor.selected_id) and editor.library.get(editor.selected_id):
            boxes["delete"] = (964, 636, 1256, 700)
    if editor.tab == "customize":
        for name, box in tuple(boxes.items()):
            if name not in ("back", "save") and not name.startswith("tab:"):
                boxes[name] = (box[0] - 256, box[1], box[2] - 256, box[3])
    return boxes


class ThemeEditor:
    def __init__(self, library, notice_duration=2.5):
        self.library = library
        self.notice_duration = notice_duration
        self.open = False
        self.mode = "browse"
        self.tab = "themes"
        self.section = "THEMES"
        self.page = self.meter_page = 0
        self.meter_filter = "all"
        self.colors_open = False
        self.color_group = self.part_page = 0
        self.color_key = COLOR_GROUPS[0][1][0]
        self.overlay = None
        self.buffer = ""
        self.pristine = True
        self.error = self.status = ""
        self.notice = self.notice_action = self.notice_detail = ""
        self.notice_until = 0
        self.exit_surface = "home"
        self.selected_id = library.active_id
        self.entry_theme = deepcopy(library.get(library.active_id))
        self.draft = deepcopy(self.entry_theme)

    @property
    def themes(self):
        return [self.library.get(key) for key in
                (*BUILTIN_THEME_IDS, *(item["id"] for item in self.library.themes))]

    @property
    def selected(self):
        return self.library.get(self.selected_id) or self.entry_theme

    @property
    def preview(self):
        return self.draft

    @property
    def dirty(self):
        return self.draft != self.entry_theme

    @property
    def family_keys(self):
        return COLOR_GROUPS[self.color_group][1]

    @property
    def current_color(self):
        return self.draft["colors"][self.color_key]

    @property
    def meter_ids(self):
        return [key for key, style in METER_STYLES.items() if self.meter_filter == "all"
                or self.meter_filter == "digital" and style.kind in ("led", "linear")
                or self.meter_filter == "analog" and style.kind in ("skin", "triple", "radial", "round")
                or self.meter_filter == "eye" and style.kind == "eye"]

    @property
    def page_count(self):
        return max(1, math.ceil(len(self.themes) / CARDS_PER_PAGE))

    @property
    def meter_page_count(self):
        return max(1, math.ceil(len(self.meter_ids) / METER_CARDS_PER_PAGE))

    def show(self, tab="themes"):
        self.entry_theme = deepcopy(self.library.get(self.library.active_id))
        self.draft = deepcopy(self.entry_theme)
        self.selected_id = self.entry_theme["id"]
        self.open, self.mode = True, "preview"
        self.tab, self.section = tab, tab.upper()
        self.meter_filter = "all"
        self.page = next(index // CARDS_PER_PAGE for index, item in enumerate(self.themes) if item["id"] == self.selected_id)
        self.meter_page = list(METER_STYLES).index(self.draft["smeter_style"]) // METER_CARDS_PER_PAGE
        self.overlay = None
        self.colors_open = False
        self.error = self.status = ""
        self.notice_until = 0

    def begin(self, theme=None):
        self.show("customize")
        self.draft = (self.library.new_theme(source=theme or self.entry_theme)
                      if theme is None or is_builtin_theme_id(theme["id"]) else deepcopy(theme))
        self.selected_id = self.draft["id"]

    def notify(self, action, detail=""):
        self.notice_action, self.notice_detail = str(action).upper(), str(detail)
        self.notice = f"{detail} {action}".strip()
        self.notice_until = 0  # Inline feedback leaves the preview visible.
        if action.upper() == "ERROR":
            self.error = str(detail)
        else:
            self.status = str(detail)

    def back(self):
        if self.overlay:
            self.overlay = None
        else:
            self.open = False
            self.exit_surface = "home"
            self.draft = deepcopy(self.entry_theme)
            self.colors_open = False
            self.error = ""

    def select_theme(self, identifier):
        item = self.library.get(identifier)
        if item is None:
            return
        meter = self.draft["smeter_style"]
        self.selected_id = identifier
        self.draft = deepcopy(item)
        self.draft["smeter_style"] = meter
        self.error = ""

    def save(self):
        try:
            normalized = normalize_theme(self.draft, allow_default=is_builtin_theme_id(self.draft["id"]))
            existing = self.library.get(normalized["id"])
            meter = normalized["smeter_style"]
            if existing is not None and theme_appearance(existing) == theme_appearance(normalized):
                self.library.activate(normalized["id"], smeter_style=meter)
            else:
                if is_builtin_theme_id(normalized["id"]):
                    copy = self.library.new_theme(source=normalized, name=existing["name"] + " Custom")
                    if normalized["name"] != existing["name"]:
                        copy["name"] = normalized["name"]
                    normalized = copy
                self.library.upsert(normalized, smeter_style=meter)
        except (OSError, ValueError) as error:
            self.notify("ERROR", error)
            return False
        self.selected_id = self.library.active_id
        self.draft = deepcopy(self.library.get(self.selected_id))
        self.entry_theme = deepcopy(self.draft)
        self.error = ""
        self.open = False
        self.mode = "browse"
        self.exit_surface = "home"
        return True

    def _sync_hue(self):
        self.hue = colorsys.rgb_to_hsv(*(value / 255 for value in self.current_color[:3]))[0]

    def set_hue(self, x):
        box = theme_screen_boxes(self).get("hue")
        if box:
            self.hue = max(0, min(1, (x - box[0]) / (box[2] - box[0])))
            self.draft["colors"][self.color_key] = [*shade_grid(self.hue)[10], *self.current_color[3:]]

    def drag(self, x, y):
        if self.open and self.colors_open and not self.overlay:
            self.set_hue(x)

    def _key(self, value):
        if value == "CANCEL":
            self.overlay = None
            self.error = ""
            return
        if value in ("DONE", "APPLY"):
            try:
                if self.overlay == "name":
                    if not self.buffer.strip() or len(self.buffer.strip()) > 32:
                        raise ValueError("Enter a name of 1–32 characters")
                    self.draft["name"] = self.buffer.strip()
                elif self.overlay == "hex":
                    if len(self.buffer) not in (6, 8):
                        raise ValueError("Enter 6 or 8 hex digits")
                    rgb = list(bytes.fromhex(self.buffer))
                    self.draft["colors"][self.color_key] = rgb + self.current_color[3:] if len(rgb) == 3 else rgb[:len(self.current_color)]
                else:
                    self.draft["colors"][self.color_key] = with_transparency(self.current_color, int(self.buffer))
            except ValueError as error:
                self.error = str(error)
                return
            self.overlay = None
            self.error = ""
            return
        if value == "CLEAR":
            self.buffer = ""
        elif value == "DEL":
            self.buffer = self.buffer[:-1]
        else:
            if self.pristine:
                self.buffer = ""
            limit = 32 if self.overlay == "name" else 8 if self.overlay == "hex" else 3
            self.buffer = (self.buffer + (" " if value == "SPACE" else value))[:limit]
        self.pristine = False

    def tap(self, x, y):
        action = next((name for name, box in theme_screen_boxes(self).items() if contains(box, x, y)), None)
        if action is None:
            return
        if self.overlay:
            if self.overlay == "delete":
                if action == "delete_confirm":
                    try:
                        self.library.delete(self.selected_id)
                    except (ValueError, OSError) as error:
                        self.notify("ERROR", error)
                    else:
                        self.show()
                else:
                    self.overlay = None
            else:
                self._key(action.split(":", 1)[1])
            return
        self.error = ""
        if action == "back":
            self.back()
        elif action == "save":
            self.save()
        elif action.startswith("tab:"):
            self.tab = action.split(":")[1]
            self.section = self.tab.upper()
            self.colors_open = False
            if self.tab == "meters" and self.draft["smeter_style"] in self.meter_ids:
                self.meter_page = self.meter_ids.index(self.draft["smeter_style"]) // METER_CARDS_PER_PAGE
        elif action.startswith("theme:"):
            self.select_theme(action.split(":", 1)[1])
        elif action.startswith("meter:"):
            self.draft["smeter_style"] = action.split(":", 1)[1]
        elif action.startswith("filter:"):
            self.meter_filter = action.split(":")[1]
            self.meter_page = (self.meter_ids.index(self.draft["smeter_style"])
                               if self.draft["smeter_style"] in self.meter_ids else 0)
            self.draft["smeter_style"] = self.meter_ids[self.meter_page]
        elif action in ("theme_previous", "theme_next"):
            self.page = max(0, min(self.page_count - 1, self.page + (-1 if action.endswith("previous") else 1)))
        elif action in ("meter_previous", "meter_next"):
            self.meter_page = max(0, min(self.meter_page_count - 1, self.meter_page + (-1 if action.endswith("previous") else 1)))
            self.draft["smeter_style"] = self.meter_ids[self.meter_page]
        elif action == "theme_name":
            self.overlay, self.buffer, self.pristine = "name", self.draft["name"], True
        elif action == "copy":
            self.draft = self.library.new_theme(source=self.draft, name=self.draft["name"][:24] + " Copy")
            self.selected_id = self.draft["id"]
            self.status = "Copy ready to preview"
        elif action == "delete":
            self.overlay = "delete"
        elif action == "colors":
            self.colors_open = True
            self._sync_hue()
        elif action == "appearance":
            self.colors_open = False
        elif action in ("group_previous", "group_next"):
            self.color_group = (self.color_group + (-1 if action.endswith("previous") else 1)) % len(COLOR_GROUPS)
            self.color_key, self.part_page = self.family_keys[0], 0
            self._sync_hue()
        elif action.startswith("part:"):
            self.color_key = self.family_keys[int(action.split(":")[1])]
            self._sync_hue()
        elif action in ("part_previous", "part_next"):
            self.part_page = max(0, min((len(self.family_keys) - 1) // 4, self.part_page + (-1 if action.endswith("previous") else 1)))
        elif action == "hue":
            self.set_hue(x)
        elif action.startswith("shade:"):
            self.draft["colors"][self.color_key] = [*shade_grid(self.hue)[int(action.split(":")[1])], *self.current_color[3:]]
        elif action == "hex_open":
            self.overlay, self.buffer, self.pristine = "hex", "".join(f"{v:02X}" for v in self.current_color), True
        elif action == "alpha_open":
            self.overlay, self.buffer, self.pristine = "alpha", str(transparency_percent(self.current_color)), True
        elif action.startswith("option:"):
            value = action.split(":")[1]
            if value in ("left", "right"):
                self.draft["sidebar"] = value
            elif value in ("straight", "rounded"):
                self.draft["radius"] = 0 if value == "straight" else 8
            else:
                self.draft["units"] = value
        elif action.startswith("text:"):
            action = action.split(":")[1]
            self.draft["text_scale_percent"] = (100 if action == "reset" else max(TEXT_SCALE_MIN, min(TEXT_SCALE_MAX,
                self.draft["text_scale_percent"] + (-5 if action == "smaller" else 5))))
