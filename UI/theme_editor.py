"""Touch-first Theme Library and live full-screen editor state."""

import colorsys
from copy import deepcopy
import math
import time

from theme_colors import recolor_family, shade_grid, transparency_percent, with_transparency
from theme_system import (BUILTIN_THEME_IDS, COLOR_NAMES, DEFAULT_THEME_ID,
                          TEXT_SCALE_MIN, TEXT_SCALE_MAX, apply_theme,
                          is_builtin_theme_id, new_theme)


# Every persisted palette key belongs to exactly one visible family.
COLOR_GROUPS = (
    ("SURFACES", ("background", "sidebar", "section_surface", "section_border",
                  "divider", "top_instrument_band", "sidebar_rule", "focus")),
    ("TEXT", ("text", "secondary_text", "section_heading", "sidebar_title",
              "frequency", "focus_text", "untested_text")),
    ("BUTTONS", ("surface", "border", "active_surface", "active_border",
                 "selected_surface", "selected_border", "pressed_surface", "pressed_border")),
    ("STATES", ("ready", "waiting", "danger", "danger_border", "untested", "notice")),
    ("S-METER", ("meter_on", "meter_hot", "meter_off", "smeter_scale", "smeter_hot",
                  "smeter_rail", "smeter_tick", "smeter_minor", "smeter_active",
                  "smeter_dbm", "smeter_marker", "smeter_peak")),
    ("PASSBAND", ("passband_fill", "passband_border", "passband_center",
                  "home_passband_fill", "home_passband_border", "home_passband_center")),
    ("SLIDERS", ("slider_track", "slider_fill", "slider_thumb", "slider_marker")),
    ("FOOTER", ("footer_background", "footer_primary", "footer_live")),
    ("SPECTRUM", ("spectrum_field", "spectrum_grid", "spectrum_axis", "spectrum_tick",
                  "spectrum_label", "spectrum_peak_fill", "spectrum_peak_line",
                  "spectrum_fill", "spectrum_line")),
    ("WATERFALL", ("waterfall_low", "waterfall_high", "waterfall_ruler_background",
                   "waterfall_ruler_minor", "waterfall_ruler_major", "waterfall_ruler_label")),
)
assert set(COLOR_NAMES) == {key for _family, keys in COLOR_GROUPS for key in keys}
NAME_KEYS = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") + ("SPACE", "DEL", "CLEAR", "DONE")
NUMBER_KEYS = tuple("123456789") + ("CLEAR", "0", "DEL", "CANCEL", "DONE")
HEX_KEYS = tuple("0123456789ABCDEF") + ("DEL", "CLEAR", "CANCEL", "APPLY")
BACK_BOX = (1034, 728, 1270, 792)
SAVED_CARDS_PER_PAGE = 8
EDITOR_PREVIEW_BOX = (24, 160, 820, 708)
EDITOR_INSPECTOR_BOX = (836, 96, 1256, 728)


def contains(box, x, y):
    return box[0] <= x < box[2] and box[1] <= y < box[3]


def _keypad_boxes(prefix, keys, *, columns, x0, y0, width, height, gap=8):
    boxes = {}
    cell_w = (width - (columns - 1) * gap) / columns
    for index, key in enumerate(keys):
        col, row = index % columns, index // columns
        left, top = x0 + col * (cell_w + gap), y0 + row * (height + gap)
        boxes[f"{prefix}:{key}"] = (left, top, left + cell_w, top + height)
    return boxes


def theme_screen_boxes(editor, *, ignore_overlay=False):
    """The single source of visual and touch geometry."""
    if editor.confirm_back and not ignore_overlay:
        return {
            "leave_save": (210, 430, 482, 494),
            "leave_discard": (504, 430, 776, 494),
            "leave_keep": (798, 430, 1070, 494),
        }
    if editor.confirm_delete_id and not ignore_overlay:
        return {
            "delete_confirm": (430, 430, 618, 494),
            "delete_cancel": (646, 430, 834, 494),
        }

    boxes = {"back": BACK_BOX}
    if editor.mode == "browse":
        boxes["new"] = (1034, 24, 1270, 88)
        for slot in range(len(BUILTIN_THEME_IDS) + SAVED_CARDS_PER_PAGE):
            item = editor.card_item(slot)
            if item is None:
                continue
            col, row = slot % 4, slot // 4
            x0 = 24 + col * 312
            y0 = 128 if row == 0 else 324 + (row - 1) * 164
            boxes[f"theme:{slot}"] = (x0, y0, x0 + 296, y0 + 148)
            if slot < len(BUILTIN_THEME_IDS):
                boxes[f"edit:{slot}"] = (x0 + 152, y0 + 88, x0 + 280, y0 + 136)
            else:
                boxes[f"edit:{slot}"] = (x0 + 88, y0 + 88, x0 + 184, y0 + 136)
                boxes[f"delete:{slot}"] = (x0 + 192, y0 + 88, x0 + 280, y0 + 136)
        boxes["previous"] = (24, 728, 260, 792)
        boxes["next"] = (268, 728, 504, 792)
        return boxes

    if editor.name_open and not ignore_overlay:
        boxes.update(_keypad_boxes("name", NAME_KEYS, columns=10,
                                   x0=160, y0=228, width=960, height=60))
        return boxes
    if editor.alpha_open and not ignore_overlay:
        boxes.update(_keypad_boxes("alpha", NUMBER_KEYS, columns=3,
                                   x0=440, y0=220, width=400, height=64))
        boxes["alpha:CANCEL"] = (440, 508, 636, 572)
        boxes["alpha:DONE"] = (644, 508, 840, 572)
        return boxes
    if editor.hex_open and not ignore_overlay:
        boxes.update(_keypad_boxes("hex", HEX_KEYS, columns=4,
                                   x0=344, y0=204, width=592, height=64))
        return boxes
    if editor.family_picker and not ignore_overlay:
        for index, (name, _keys) in enumerate(COLOR_GROUPS):
            col, row = index % 3, index // 3
            x0, y0 = (440 if row == 3 else 32 + col * 408), 232 + row * 80
            boxes[f"family:{index}"] = (x0, y0, x0 + 392, y0 + 64)
        boxes["family_cancel"] = (450, 576, 830, 640)
        return boxes

    boxes["theme_name"] = (24, 16, 412, 80)
    boxes["panel:colors"] = (424, 16, 552, 80)
    boxes["panel:layout"] = (560, 16, 688, 80)
    boxes["panel:text"] = (696, 16, 824, 80)
    boxes["panel:advanced"] = (832, 16, 1000, 80)
    boxes["save"] = (1034, 16, 1270, 80)
    for index, scene in enumerate(("home", "browse", "popups")):
        left = 24 + index * 136
        boxes[f"scene:{scene}"] = (left, 96, left + 128, 144)

    if editor.panel in ("colors", "advanced"):
        boxes["family_open"] = (848, 96, 1256, 152)
        keys = editor.family_keys
        for slot in range(4):
            index = editor.part_page * 4 + slot
            if index >= len(keys):
                continue
            col, row = slot % 2, slot // 2
            x0, y0 = 848 + col * 208, 160 + row * 64
            boxes[f"part:{index}"] = (x0, y0, x0 + 200, y0 + 56)
        boxes["part_previous"] = (848, 288, 980, 332)
        boxes["part_next"] = (988, 288, 1120, 332)
        if editor.panel == "advanced":
            boxes["hex_open"] = (1128, 288, 1256, 332)
        boxes["hue"] = (848, 344, 1256, 392)
        for index in range(16):
            col, row = index % 4, index // 4
            x0, y0 = 848 + col * 104, 400 + row * 52
            boxes[f"shade:{index}"] = (x0, y0, x0 + 96, y0 + 44)
        if len(editor.current_color) == 4:
            boxes["alpha_open"] = (848, 608, 1256, 656)
        boxes["apply_family"] = (848, 664, 1256, 712)
    elif editor.panel == "layout":
        for index, name in enumerate(("straight", "rounded")):
            x0 = 848 + index * 208
            boxes[f"option:{name}"] = (x0, 178, x0 + 200, 242)
        for index, name in enumerate(("left", "right")):
            x0 = 848 + index * 208
            boxes[f"option:{name}"] = (x0, 338, x0 + 200, 402)
        for index, name in enumerate(("imperial", "metric")):
            x0 = 848 + index * 208
            boxes[f"option:{name}"] = (x0, 498, x0 + 200, 562)
    elif editor.panel == "text":
        boxes["text:smaller"] = (848, 208, 1048, 272)
        boxes["text:larger"] = (1056, 208, 1256, 272)
        boxes["text:reset"] = (848, 288, 1256, 352)

    preview = EDITOR_PREVIEW_BOX
    rail = ((24, 192) if editor.draft["sidebar"] == "left" else (652, 820))
    main = ((192, 820) if editor.draft["sidebar"] == "left" else (24, 652))
    if editor.scene == "home":
        boxes["preview:frequency"] = (rail[0], 178, rail[1], 252)
        boxes["preview:meter"] = (rail[0], 258, rail[1], 345)
        boxes["preview:buttons"] = (rail[0], 360, rail[1], 526)
        boxes["preview:passband"] = (main[0] + 8, 315, main[1] - 8, 630)
        boxes["preview:footer"] = (main[0] + 8, 640, main[1] - 8, 698)
    elif editor.scene == "browse":
        boxes["preview:browse_categories"] = (rail[0], 210, rail[1], 500)
        boxes["preview:browse_text"] = (main[0] + 20, 180, main[1] - 20, 215)
        boxes["preview:browse_rows"] = (main[0] + 20, 220, main[1] - 20, 600)
    else:
        boxes["preview:notice"] = (main[0] + 24, 195, main[1] - 24, 266)
        boxes["preview:popup_text"] = (main[0] + 40, 350, main[1] - 40, 410)
        boxes["preview:popup"] = (main[0] + 24, 300, main[1] - 24, 520)
    return boxes


class ThemeEditor:
    def __init__(self, library, notice_duration=2.5):
        self.library = library
        self.notice_duration = notice_duration
        self.open = False
        self.mode = "browse"
        self.selected_id = library.active_id
        self.page = 0
        self.draft = None
        self.baseline = None
        self.entry_theme = None
        self.scene = "home"
        self.panel = "colors"
        self.color_group = 0
        self.part_page = 0
        self.color_key = COLOR_GROUPS[0][1][0]
        self.hue = 0.0
        self.shade_index = 10
        self.name_open = False
        self.alpha_open = False
        self.alpha_value = ""
        self.alpha_pristine = False
        self.alpha_original = None
        self.hex_open = False
        self.hex_value = ""
        self.hex_pristine = False
        self.family_picker = False
        self.confirm_back = False
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

    @property
    def dirty(self):
        return self.mode == "edit" and self.draft != self.baseline

    @property
    def family_keys(self):
        return COLOR_GROUPS[self.color_group][1]

    @property
    def current_color(self):
        return self.draft["colors"][self.color_key] if self.draft else self.selected["colors"][self.color_key]

    @property
    def page_count(self):
        return max(1, math.ceil(len(self.library.themes) / SAVED_CARDS_PER_PAGE))

    @property
    def can_previous(self):
        return self.page > 0

    @property
    def can_next(self):
        return self.page < self.page_count - 1

    def card_item(self, slot):
        if slot < len(BUILTIN_THEME_IDS):
            return self.library.get(BUILTIN_THEME_IDS[slot])
        index = self.page * SAVED_CARDS_PER_PAGE + slot - len(BUILTIN_THEME_IDS)
        return self.library.themes[index] if index < len(self.library.themes) else None

    def notify(self, action, detail=""):
        self.notice_action = str(action).upper()
        self.notice_detail = str(detail).upper()
        self.notice = f"{self.notice_detail} {self.notice_action}".strip()
        self.notice_until = time.monotonic() + self.notice_duration

    def _sync_hue(self):
        r, g, b = (value / 255.0 for value in self.current_color[:3])
        self.hue = colorsys.rgb_to_hls(r, g, b)[0]

    def begin(self, theme=None):
        self.entry_theme = deepcopy(self.library.get(self.library.active_id))
        if theme is None:
            self.draft = new_theme(source=self.entry_theme)
        elif is_builtin_theme_id(theme["id"]):
            self.draft = new_theme(source=theme)
        else:
            self.draft = deepcopy(theme)
        self.baseline = deepcopy(self.draft)
        self.mode = "edit"
        self.scene = "home"
        self.panel = "colors"
        self.color_group = 0
        self.part_page = 0
        self.color_key = self.family_keys[0]
        self._sync_hue()
        self.name_open = self.alpha_open = self.hex_open = self.family_picker = False
        self.confirm_back = False
        self.confirm_delete_id = None
        apply_theme(self.draft)

    def _apply_draft(self):
        # The name keypad may temporarily leave the draft blank. Appearance
        # still previews live while save validation owns the final name.
        if self.draft["name"].strip():
            apply_theme(self.draft)
        else:
            apply_theme({**self.draft, "name": self.baseline["name"]})

    def _leave_edit(self, restore):
        if restore:
            apply_theme(self.entry_theme)
        self.mode = "browse"
        self.draft = self.baseline = self.entry_theme = None
        self.name_open = self.alpha_open = self.hex_open = self.family_picker = False
        self.confirm_back = False

    def back(self):
        if self.mode == "browse":
            self.confirm_delete_id = None
            self.open = False
        elif self.dirty:
            self.confirm_back = True
        else:
            self._leave_edit(restore=True)

    def save(self):
        try:
            self.library.upsert(self.draft)
        except (ValueError, OSError) as error:
            self.notify("ERROR", error)
            return False
        self.selected_id = self.draft["id"]
        name = self.draft["name"]
        self._leave_edit(restore=False)
        self.page = max(0, (len(self.library.themes) - 1) // SAVED_CARDS_PER_PAGE)
        self.notify("SAVED", name)
        return True

    def set_color(self, rgb):
        original = self.current_color
        next_color = [*rgb, *original[3:]]
        if next_color != original:
            self.draft["colors"][self.color_key] = next_color
            self._apply_draft()

    def set_hue(self, x):
        box = theme_screen_boxes(self)["hue"]
        self.hue = max(0.0, min(1.0, (x - box[0]) / (box[2] - box[0])))
        self.set_color(shade_grid(self.hue)[self.shade_index])

    def drag(self, x, y):
        if self.mode != "edit" or self.panel not in ("colors", "advanced"):
            return
        if self.confirm_back or self.name_open or self.alpha_open or self.hex_open or self.family_picker:
            return
        self.set_hue(x)

    def _choose_family(self, index):
        self.color_group = index
        self.part_page = 0
        self.color_key = self.family_keys[0]
        self.family_picker = False
        self._sync_hue()

    def _alpha_key(self, value):
        if value == "CANCEL":
            if self.alpha_original != self.current_color:
                self.draft["colors"][self.color_key] = self.alpha_original
                self._apply_draft()
            self.alpha_open = False
            self.alpha_original = None
            return
        if value == "DONE":
            if self.alpha_value and 0 <= int(self.alpha_value) <= 100:
                self.alpha_open = False
                self.alpha_original = None
            else:
                self.notify("ERROR", "ENTER 0 TO 100")
            return
        if value == "DEL":
            self.alpha_value = self.alpha_value[:-1]
        elif value == "CLEAR":
            self.alpha_value = ""
        elif self.alpha_pristine:
            self.alpha_value = value
        elif len(self.alpha_value) < 3:
            self.alpha_value += value
        self.alpha_pristine = False
        if self.alpha_value:
            percent = int(self.alpha_value)
            if 0 <= percent <= 100:
                next_color = with_transparency(self.current_color, percent)
                if next_color != self.current_color:
                    self.draft["colors"][self.color_key] = next_color
                    self._apply_draft()

    def _hex_key(self, value):
        if value == "CANCEL":
            self.hex_open = False
            return
        if value == "APPLY":
            expected = len(self.current_color) * 2
            if len(self.hex_value) != expected:
                self.notify("ERROR", f"ENTER {expected} HEX DIGITS")
                return
            try:
                parsed = list(bytes.fromhex(self.hex_value))
            except ValueError:
                self.notify("ERROR", "INVALID HEX COLOR")
                return
            self.draft["colors"][self.color_key] = parsed
            self._apply_draft()
            self.hex_open = False
            self._sync_hue()
            return
        if value == "DEL":
            self.hex_value = self.hex_value[:-1]
        elif value == "CLEAR":
            self.hex_value = ""
        elif self.hex_pristine:
            self.hex_value = value
        elif len(self.hex_value) < len(self.current_color) * 2:
            self.hex_value += value
        self.hex_pristine = False

    def _name_key(self, value):
        if value == "DONE":
            self.name_open = False
        elif value == "DEL":
            self.draft["name"] = self.draft["name"][:-1]
        elif value == "CLEAR":
            self.draft["name"] = ""
        elif value == "SPACE":
            if len(self.draft["name"]) < 32:
                self.draft["name"] += " "
        elif len(self.draft["name"]) < 32:
            self.draft["name"] += value

    def tap(self, x, y):
        boxes = theme_screen_boxes(self)
        action = next((name for name, box in boxes.items() if contains(box, x, y)), None)
        if self.mode == "browse" and action and action.startswith("theme:"):
            slot = action.split(":")[1]
            action = next((name for name in (f"edit:{slot}", f"delete:{slot}")
                           if name in boxes and contains(boxes[name], x, y)), action)
        if action is None:
            return
        if self.confirm_back:
            if action == "leave_save":
                self.save()
            elif action == "leave_discard":
                self._leave_edit(restore=True)
            elif action == "leave_keep":
                self.confirm_back = False
            return
        if self.confirm_delete_id:
            if action == "delete_confirm":
                item = self.library.get(self.confirm_delete_id)
                try:
                    self.library.delete(self.confirm_delete_id)
                except (ValueError, OSError) as error:
                    self.notify("ERROR", error)
                else:
                    self.selected_id = self.library.active_id
                    self.page = min(self.page, self.page_count - 1)
                    self.notify("DELETED", item["name"])
                self.confirm_delete_id = None
            elif action == "delete_cancel":
                self.confirm_delete_id = None
            return
        if action == "back":
            self.back()
            return
        if self.mode == "browse":
            if action in ("previous", "next"):
                if (action == "previous" and self.can_previous) or (action == "next" and self.can_next):
                    self.page += -1 if action == "previous" else 1
            elif action == "new":
                self.begin()
            elif action.startswith(("theme:", "edit:", "delete:")):
                verb, slot_text = action.split(":")
                item = self.card_item(int(slot_text))
                if item is None:
                    return
                if verb == "theme":
                    try:
                        self.library.activate(item["id"])
                    except (ValueError, OSError) as error:
                        self.notify("ERROR", error)
                    else:
                        self.selected_id = item["id"]
                        self.notify("APPLIED", item["name"])
                elif verb == "edit":
                    self.begin(item)
                else:
                    self.confirm_delete_id = item["id"]
            return

        if self.name_open:
            if action.startswith("name:"):
                self._name_key(action.split(":")[1])
            return
        if self.alpha_open:
            if action.startswith("alpha:"):
                self._alpha_key(action.split(":")[1])
            return
        if self.hex_open:
            if action.startswith("hex:"):
                self._hex_key(action.split(":")[1])
            return
        if self.family_picker:
            if action.startswith("family:"):
                self._choose_family(int(action.split(":")[1]))
            elif action == "family_cancel":
                self.family_picker = False
            return

        if action == "save":
            self.save()
        elif action == "theme_name":
            self.name_open = True
        elif action.startswith("panel:"):
            self.panel = action.split(":")[1]
        elif action.startswith("scene:"):
            self.scene = action.split(":")[1]
        elif action == "family_open":
            self.family_picker = True
        elif action.startswith("family:"):
            self._choose_family(int(action.split(":")[1]))
        elif action.startswith("part:"):
            self.color_key = self.family_keys[int(action.split(":")[1])]
            self._sync_hue()
        elif action == "part_previous":
            self.part_page = max(0, self.part_page - 1)
        elif action == "part_next":
            self.part_page = min((len(self.family_keys) - 1) // 4, self.part_page + 1)
        elif action == "hue":
            self.set_hue(x)
        elif action.startswith("shade:"):
            self.shade_index = int(action.split(":")[1])
            self.set_color(shade_grid(self.hue)[self.shade_index])
        elif action == "alpha_open":
            self.alpha_value = str(transparency_percent(self.current_color))
            self.alpha_pristine = True
            self.alpha_original = list(self.current_color)
            self.alpha_open = True
        elif action == "apply_family":
            updated = recolor_family(self.draft["colors"], self.family_keys, self.hue)
            if updated != self.draft["colors"]:
                self.draft["colors"] = updated
                self._apply_draft()
        elif action == "hex_open":
            self.hex_value = "".join(f"{value:02X}" for value in self.current_color)
            self.hex_pristine = True
            self.hex_open = True
        elif action.startswith("option:"):
            value = action.split(":")[1]
            if value in ("rounded", "straight"):
                self.draft["radius"] = 8 if value == "rounded" else 0
            elif value in ("left", "right"):
                self.draft["sidebar"] = value
            else:
                self.draft["units"] = value
            self._apply_draft()
        elif action.startswith("text:"):
            value = action.split(":")[1]
            current = self.draft["text_scale_percent"]
            self.draft["text_scale_percent"] = (
                100 if value == "reset"
                else max(TEXT_SCALE_MIN, current - 5) if value == "smaller"
                else min(TEXT_SCALE_MAX, current + 5)
            )
            self._apply_draft()
        elif action.startswith("preview:"):
            family = {"frequency": 1, "meter": 4, "buttons": 2,
                      "passband": 5, "footer": 7, "browse_categories": 2,
                      "browse_text": 1, "browse_rows": 0, "notice": 3,
                      "popup_text": 1, "popup": 0}[action.split(":")[1]]
            self._choose_family(family)
            self.panel = "colors"
