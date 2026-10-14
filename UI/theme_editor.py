"""Touch-first state and hit targets for the two-column theme editor."""

import time

from smeter_styles import METER_STYLES

from theme_system import (BUILTIN_THEME_IDS, COLOR_NAMES, DEFAULT_THEME_ID,
                          TEXT_SCALE_MIN, TEXT_SCALE_MAX,
                          color_hex, is_builtin_theme_id, new_theme)


COLOR_GROUPS = (
    ("BASE", ("background", "sidebar", "section_surface", "section_border", "divider", "top_instrument_band", "sidebar_rule", "focus")),
    ("TEXT", ("text", "secondary_text", "section_heading", "sidebar_title", "frequency", "focus_text", "untested_text")),
    ("BUTTON", ("surface", "border", "active_surface", "active_border", "selected_surface",
                "selected_border", "pressed_surface", "pressed_border")),
    ("STATES", ("ready", "waiting", "danger", "danger_border", "untested")),
    ("RADIO", ("meter_on", "meter_hot", "meter_off", "notice")),
    ("BAND", ("passband_fill", "passband_border", "passband_center",
              "home_passband_fill", "home_passband_border", "home_passband_center")),
    ("SLIDERS", ("slider_track", "slider_fill", "slider_thumb", "slider_marker")),
    ("FOOTER", ("footer_background", "footer_primary", "footer_live")),
    ("S-METER", ("smeter_scale", "smeter_hot", "smeter_rail", "smeter_tick", "smeter_minor",
                 "smeter_active", "smeter_dbm", "smeter_marker", "smeter_peak")),
    ("SPECTRUM", ("spectrum_field", "spectrum_grid", "spectrum_axis", "spectrum_tick",
                  "spectrum_label", "spectrum_peak_fill", "spectrum_peak_line",
                  "spectrum_fill", "spectrum_line")),
    ("WATERFALL", ("waterfall_low", "waterfall_high", "waterfall_ruler_background",
                   "waterfall_ruler_minor", "waterfall_ruler_major", "waterfall_ruler_label")),
)
NAME_KEYS = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") + ("SPACE", "DEL", "CLEAR", "DONE")
HEX_KEYS = tuple("0123456789ABCDEF")


def contains(box, x, y):
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def theme_screen_boxes(editor):
    """Return exactly the boxes used by both paint and touch dispatch."""
    rail_left, rail_right = 1034, 1270
    editor_left, editor_right = 536, 1000
    boxes = {"back": (rail_left, 728, rail_right, 792)}
    if editor.mode == "browse":
        boxes.update({
            "new": (rail_left, 104, rail_right, 168),
            "meters": (rail_left, 176, rail_right, 240),
            "previous": (editor_left, 676, 764, 732),
            "next": (772, 676, editor_right, 732),
        })
        for index in range(7):
            top = 100 + index * 76
            boxes[f"theme:{index}"] = (editor_left, top, editor_left + 220, top + 64)
            boxes[f"edit:{index}"] = (editor_left + 232, top, editor_left + 342, top + 64)
            boxes[f"delete:{index}"] = (editor_left + 354, top, editor_right, top + 64)
    else:
        for index, name in enumerate(("STYLE", "UNITS", "COLORS", "NAME", "SIDEBAR", "METERS")):
            boxes[f"section:{name}"] = (rail_left, 104 + index * 72, rail_right, 168 + index * 72)
        boxes["save"] = (rail_left, 656, rail_right, 720)
        if editor.section == "STYLE":
            for index, name in enumerate(("straight", "rounded")):
                boxes[f"option:{name}"] = (editor_left + index * 236, 126,
                                            editor_left + 228 + index * 236, 198)
        elif editor.section == "METERS":
            boxes["meter_previous"] = (editor_left, 676, 764, 732)
            boxes["meter_next"] = (772, 676, editor_right, 732)
            styles = list(METER_STYLES)[editor.meter_page * 6:editor.meter_page * 6 + 6]
            for index, identifier in enumerate(styles):
                left = editor_left + index % 2 * 236
                top = 100 + index // 2 * 188
                boxes[f"meter:{identifier}"] = (left, top, left + 228, top + 176)
        elif editor.section == "SIDEBAR":
            for index, name in enumerate(("left", "right")):
                boxes[f"option:{name}"] = (editor_left + index * 236, 126,
                                            editor_left + 228 + index * 236, 198)
        elif editor.section == "UNITS":
            for index, name in enumerate(("imperial", "metric")):
                boxes[f"option:{name}"] = (editor_left + index * 236, 126,
                                            editor_left + 228 + index * 236, 198)
            boxes["text:smaller"] = (editor_left, 330, editor_left + 228, 394)
            boxes["text:larger"] = (editor_left + 236, 330, editor_right, 394)
            boxes["text:reset"] = (editor_left, 408, editor_right, 472)
        elif editor.section == "COLORS":
            if editor.color_key:
                for index, key in enumerate(HEX_KEYS):
                    boxes[f"hex:{key}"] = (
                        editor_left + index % 4 * 118, 256 + index // 4 * 62,
                        editor_left + 110 + index % 4 * 118, 310 + index // 4 * 62,
                    )
                boxes["hex:BACK"] = (editor_left, 524, editor_left + 228, 580)
                boxes["hex:CLEAR"] = (editor_left + 236, 524, editor_right, 580)
                boxes["hex:APPLY"] = (editor_left, 592, editor_left + 228, 648)
                boxes["hex:CANCEL"] = (editor_left + 236, 592, editor_right, 648)
                for index in range(4):
                    boxes[f"swatch:{index}"] = (editor_left + index * 118, 174,
                                                editor_left + 110 + index * 118, 230)
            else:
                for index in range(len(COLOR_GROUPS)):
                    column, row = index % 4, index // 4
                    boxes[f"group:{index}"] = (editor_left + column * 118, 110 + row * 46,
                                                editor_left + 110 + column * 118, 148 + row * 46)
                keys = COLOR_GROUPS[editor.color_group][1]
                for index, _key in enumerate(keys):
                    boxes[f"color:{index}"] = (editor_left, 252 + index * 52,
                                                editor_right, 298 + index * 52)
        elif editor.section == "NAME":
            for index, key in enumerate(NAME_KEYS):
                boxes[f"name:{key}"] = (
                    editor_left + index % 4 * 118, 144 + index // 4 * 56,
                    editor_left + 110 + index % 4 * 118, 194 + index // 4 * 56,
                )
    return boxes


class ThemeEditor:
    def __init__(self, library, notice_duration=2.5):
        self.library = library
        self.notice_duration = notice_duration
        self.open = False
        self.mode = "browse"
        self.selected_id = library.active_id
        self.page = 0
        self.meter_page = 0
        self.draft = None
        self.section = "STYLE"
        self.color_group = 0
        self.color_key = None
        self.hex_value = ""
        self.hex_pristine = False
        self.color_original = None
        self.confirm_delete_id = None
        self.notice = ""
        self.notice_action = ""
        self.notice_detail = ""
        self.notice_until = 0.0

    @property
    def themes(self):
        return [*(self.library.get(identifier) for identifier in BUILTIN_THEME_IDS),
                *self.library.themes]

    @property
    def selected(self):
        return self.library.get(self.selected_id) or self.library.get(DEFAULT_THEME_ID)

    @property
    def preview(self):
        return self.draft if self.mode == "edit" else self.selected

    def notify(self, action, detail=""):
        self.notice_action = str(action).upper()
        self.notice_detail = str(detail).upper()
        self.notice = f"{self.notice_detail} {self.notice_action}".strip()
        self.notice_until = time.monotonic() + self.notice_duration

    def begin(self, theme=None):
        self.draft = new_theme(source=theme) if theme is None else {
            **theme, "colors": {key: list(value) for key, value in theme["colors"].items()},
        }
        self.mode = "edit"
        self.meter_page = 0
        self.section = "STYLE"
        self.color_key = None
        self.color_original = None
        self.confirm_delete_id = None
        self.notice = ""
        self.notice_until = 0.0

    def cancel_color_edit(self):
        if self.color_key and self.color_original is not None:
            self.draft["colors"][self.color_key] = self.color_original
        self.color_key = None
        self.color_original = None

    def preview_hex_color(self):
        if len(self.hex_value) not in (6, 8):
            return False
        try:
            parsed = list(bytes.fromhex(self.hex_value))
        except ValueError:
            return False
        if len(parsed) == 3:
            parsed += self.color_original[3:]
        self.draft["colors"][self.color_key] = parsed
        return True

    def back(self):
        if self.color_key:
            self.cancel_color_edit()
        elif self.mode == "edit":
            self.mode = "browse"
            self.draft = None
        else:
            self.confirm_delete_id = None
            self.open = False

    def tap(self, x, y):
        boxes = theme_screen_boxes(self)
        action = next((key for key, box in boxes.items() if contains(box, x, y)), None)
        if action is None:
            return
        if action == "back":
            self.back()
            return
        if self.mode == "browse":
            if action.startswith(("theme:", "edit:", "delete:")):
                index = self.page * 7 + int(action.split(":")[1])
                if index < len(self.themes):
                    item = self.themes[index]
                    identifier = item["id"]
                    if action.startswith("theme:"):
                        try:
                            self.library.activate(identifier)
                        except OSError as error:
                            self.notify("ERROR", error)
                        else:
                            self.selected_id = identifier
                            self.notify("APPLIED", item["name"])
                            self.confirm_delete_id = None
                    elif action.startswith("edit:"):
                        self.confirm_delete_id = None
                        self.begin(new_theme(source=item) if is_builtin_theme_id(identifier) else item)
                    elif is_builtin_theme_id(identifier):
                        self.confirm_delete_id = None
                        self.notify("LOCKED", "BUILT-IN THEME")
                    elif self.confirm_delete_id == identifier:
                        try:
                            self.library.delete(identifier)
                        except OSError as error:
                            self.notify("ERROR", error)
                        else:
                            self.selected_id = self.library.active_id
                            self.page = min(self.page, (len(self.themes) - 1) // 7)
                            self.notify("DELETED", item["name"])
                        self.confirm_delete_id = None
                    else:
                        self.confirm_delete_id = identifier
                        self.notify("CONFIRM", f"DELETE {item['name']}")
            elif action == "meters":
                self.begin(new_theme(source=self.selected) if is_builtin_theme_id(self.selected_id) else self.selected)
                self.section = "METERS"
            elif action == "new":
                self.begin()
            elif action == "previous":
                self.confirm_delete_id = None
                self.page = max(0, self.page - 1)
            elif action == "next":
                self.confirm_delete_id = None
                self.page = min((len(self.themes) - 1) // 7, self.page + 1)
            return
        if action.startswith("section:"):
            self.cancel_color_edit()
            self.section = action.split(":")[1]
        elif action == "meter_previous":
            self.meter_page = max(0, self.meter_page - 1)
        elif action == "meter_next":
            self.meter_page = min((len(METER_STYLES) - 1) // 6, self.meter_page + 1)
        elif action == "save":
            if self.color_key:
                if not self.preview_hex_color():
                    self.notify("ERROR", "ENTER 6 OR 8 HEX DIGITS")
                    return
                self.color_key = None
                self.color_original = None
            try:
                self.library.upsert(self.draft)
            except (ValueError, OSError) as error:
                self.notify("ERROR", error)
            else:
                self.selected_id = self.draft["id"]
                self.mode = "browse"
                self.draft = None
                self.page = (len(self.themes) - 1) // 7
                self.notify("APPLIED", self.selected["name"])
        elif action.startswith("meter:"):
            self.draft["smeter_style"] = action.split(":")[1]
        elif action.startswith("option:"):
            value = action.split(":")[1]
            if value in ("rounded", "straight"):
                self.draft["radius"] = 8 if value == "rounded" else 0
            elif value in ("left", "right"):
                self.draft["sidebar"] = value
            else:
                self.draft["units"] = value
        elif action.startswith("text:"):
            choice = action.split(":")[1]
            current = self.draft["text_scale_percent"]
            self.draft["text_scale_percent"] = (
                100 if choice == "reset" else
                max(TEXT_SCALE_MIN, current - 5) if choice == "smaller"
                else min(TEXT_SCALE_MAX, current + 5)
            )
        elif action.startswith("group:"):
            self.color_group = int(action.split(":")[1])
        elif action.startswith("color:"):
            index = int(action.split(":")[1])
            self.color_key = COLOR_GROUPS[self.color_group][1][index]
            self.color_original = list(self.draft["colors"][self.color_key])
            self.hex_value = color_hex(self.draft["colors"][self.color_key])[1:]
            self.hex_pristine = True
        elif action.startswith("swatch:"):
            swatches = ((255, 255, 255), (0, 0, 0), (160, 160, 160), (115, 255, 177))
            base = self.draft["colors"][self.color_key]
            self.hex_value = color_hex((*swatches[int(action.split(":")[1])], *base[3:]))[1:]
            self.hex_pristine = True
            self.preview_hex_color()
        elif action.startswith("hex:"):
            value = action.split(":")[1]
            if value == "BACK":
                self.hex_value = self.hex_value[:-1]
                self.hex_pristine = False
            elif value == "CLEAR":
                self.hex_value = ""
                self.hex_pristine = False
            elif value == "CANCEL":
                self.cancel_color_edit()
            elif value == "APPLY":
                if self.preview_hex_color():
                    self.color_key = None
                    self.color_original = None
                else:
                    self.notify("ERROR", "ENTER 6 OR 8 HEX DIGITS")
            elif self.hex_pristine:
                self.hex_value = value
                self.hex_pristine = False
            elif len(self.hex_value) < 8:
                self.hex_value += value
            if self.color_key and value not in ("CANCEL", "APPLY"):
                self.preview_hex_color()
        elif action.startswith("name:"):
            value = action.split(":")[1]
            if value == "DEL":
                self.draft["name"] = self.draft["name"][:-1]
            elif value == "CLEAR":
                self.draft["name"] = ""
            elif value == "SPACE":
                self.draft["name"] += " " if len(self.draft["name"]) < 32 else ""
            elif value == "DONE":
                self.section = "STYLE"
            elif len(self.draft["name"]) < 32:
                self.draft["name"] += value
