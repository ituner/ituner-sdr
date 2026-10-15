"""Touch-first Theme Library and live full-screen editor state."""

import colorsys
from copy import deepcopy
import math
import time

from theme_colors import recolor_family_shades, transparency_percent, with_transparency
from smeter_styles import METER_STYLES
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
GUIDED_CATEGORIES = (
    ("Surfaces", ("SURFACES", "FOOTER")),
    ("Text", ("TEXT",)),
    ("Buttons & states", ("BUTTONS", "STATES")),
    ("S-meter & passband", ("S-METER", "PASSBAND", "SLIDERS")),
    ("Spectrum & waterfall", ("SPECTRUM", "WATERFALL")),
    ("Layout & sizing", ()),
)
NAME_KEYS = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") + ("SPACE", "DEL", "CLEAR", "DONE")
NUMBER_KEYS = tuple("123456789") + ("CLEAR", "0", "DEL", "CANCEL", "DONE")
HEX_KEYS = tuple("0123456789ABCDEF") + ("DEL", "CLEAR", "CANCEL", "APPLY")
BACK_BOX = (1034, 728, 1270, 792)
SAVED_CARDS_PER_PAGE = 8
METER_CARDS_PER_PAGE = 6


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


def _library_overlay_boxes(editor, *, ignore_overlay=False):
    """Library cards and shared keypads/confirmation geometry."""
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
        boxes["meters"] = (790, 24, 1026, 88)
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
    return boxes


def theme_screen_boxes(editor, *, ignore_overlay=False):
    """Shared touch/drawing geometry for the guided editor and its overlays."""
    if editor.mode == "browse":
        return _library_overlay_boxes(editor, ignore_overlay=ignore_overlay)
    if not ignore_overlay and (editor.confirm_back or editor.confirm_delete_id
                               or editor.name_open or editor.alpha_open
                               or editor.hex_open):
        return _library_overlay_boxes(editor)
    if editor.view_app:
        return {"return_to_editor": (522, 728, 758, 792)}
    if editor.meter_gallery_open and not ignore_overlay:
        boxes = {"meter_previous": (24, 648, 260, 712),
                 "meter_next": (268, 648, 504, 712),
                 "meter_close": (1020, 648, 1256, 712)}
        first = editor.meter_page * METER_CARDS_PER_PAGE
        for slot, identifier in enumerate(list(METER_STYLES)[first:first + METER_CARDS_PER_PAGE]):
            left = 24 + (slot % 3) * 416
            top = 120 + (slot // 3) * 264
            boxes[f"meter:{identifier}"] = (left, top, left + 400, top + 248)
        return boxes
    boxes = {
        "back": BACK_BOX,
        "theme_name": (24, 16, 748, 80),
        "previous": (24, 728, 260, 792),
        "next": (268, 728, 504, 792),
        "view_app": (512, 728, 748, 792),
        "reset_category": (24, 648, 400, 712),
    }
    if editor.category_index == 5:
        for top, names in ((156, ("straight", "rounded")),
                           (292, ("left", "right")),
                           (428, ("original", "imperial", "metric"))):
            for index, name in enumerate(names):
                left = 440 + index * 272
                boxes[f"option:{name}"] = (left, top, left + 264, top + 64)
        for index, name in enumerate(("smaller", "larger", "reset")):
            left = 440 + index * 272
            boxes[f"text:{name}"] = (left, 564, left + 264, 628)
        return boxes
    if editor.selected_family:
        boxes.update({"hue": (440, 400, 1256, 448),
                      "tone": (440, 476, 1256, 644)})
    if editor.fine_tune:
        for key in editor.family_keys[editor.part_page * 3:editor.part_page * 3 + 3]:
            row = editor.family_keys.index(key) % 3
            top = 120 + row * 72
            boxes[f"key:{key}"] = (24, top, 1256, top + 64)
        boxes.update({"key_previous": (24, 344, 204, 400),
                      "key_next": (212, 344, 392, 400),
                      "fine_tune_close": (24, 416, 400, 480),
                      "hex_open": (24, 488, 400, 552)})
        if len(editor.current_color) == 4:
            boxes["alpha_open"] = (24, 560, 400, 624)
    else:
        for row, family in enumerate(editor.visible_family_rows):
            top = 120 + row * 72
            boxes[f"family:{family}"] = (24, top, 1256, top + 64)
        if editor.selected_family:
            boxes["fine_tune"] = (24, 416, 400, 480)
        if editor.category_index == 3:
            boxes["fine_tune"] = (24, 344, 400, 408)
            boxes["meter_gallery"] = (24, 416, 400, 640)
    return boxes


class ThemeEditor:
    """Theme Library, guided editing, and the live unsaved draft."""

    def __init__(self, library, notice_duration=2.5):
        self.library = library
        self.notice_duration = notice_duration
        self.open = False
        self.mode = "browse"
        self.selected_id = library.active_id
        self.page = 0
        self.meter_page = 0
        self.draft = None
        self.baseline = None
        self.entry_theme = None
        self.color_group = 0
        self.part_page = 0
        self.color_key = COLOR_GROUPS[0][1][0]
        self.hue = 0.0
        self.name_open = False
        self.alpha_open = False
        self.alpha_value = ""
        self.alpha_pristine = False
        self.alpha_original = None
        self.hex_open = False
        self.hex_value = ""
        self.hex_pristine = False
        self.confirm_back = False
        self.confirm_delete_id = None
        self.notice = ""
        self.notice_action = ""
        self.notice_detail = ""
        self.notice_until = 0.0
        self.category_index = 0
        self.selected_family = "SURFACES"
        self.view_app = False
        self.fine_tune = False
        self.meter_gallery_open = False
        self.family_source = None
        self.lightness = 0.5
        self.strength = 0.0

    @property
    def themes(self):
        return [*(self.library.get(identifier) for identifier in BUILTIN_THEME_IDS),
                *self.library.themes]

    @property
    def selected(self):
        return self.library.get(self.selected_id) or self.library.get(DEFAULT_THEME_ID)

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
        return self.category_index > 0 if self.mode == "edit" else self.page > 0

    @property
    def can_next(self):
        return (self.category_index < len(GUIDED_CATEGORIES) - 1
                if self.mode == "edit" else self.page < self.page_count - 1)

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
        self.meter_page = 0
        self.color_group = 0
        self.part_page = 0
        self.color_key = self.family_keys[0]
        self._sync_hue()
        self.name_open = self.alpha_open = self.hex_open = False
        self.confirm_back = False
        self.confirm_delete_id = None
        apply_theme(self.draft)
        self.category_index = 0
        self.selected_family = "SURFACES"
        self.view_app = False
        self.fine_tune = False
        self.meter_gallery_open = False
        self._choose_family(0)

    def _apply_draft(self):
        # The name keypad may temporarily leave the draft blank. Appearance
        # still applies live while save validation owns the final name.
        if self.draft["name"].strip():
            apply_theme(self.draft)
        else:
            apply_theme({**self.draft, "name": self.baseline["name"]})

    def _leave_edit(self, restore):
        if restore:
            apply_theme(self.entry_theme)
        self.mode = "browse"
        self.draft = self.baseline = self.entry_theme = None
        self.name_open = self.alpha_open = self.hex_open = False
        self.confirm_back = False
        self.view_app = False
        self.fine_tune = False
        self.meter_gallery_open = False
        self.family_source = None

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

    def _choose_family(self, index):
        self.color_group = index
        self.part_page = 0
        self.color_key = self.family_keys[0]
        self._sync_hue()
        self.selected_family = COLOR_GROUPS[index][0]
        self.fine_tune = False
        self._snapshot_family()

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
            if parsed != self.current_color:
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

    def _tap_library_or_overlay(self, x, y):
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
            elif action == "meters":
                self.begin(self.selected)
                self._select_category(3)
                self._open_meter_gallery()
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

    @property
    def category_families(self):
        return GUIDED_CATEGORIES[self.category_index][1]

    @property
    def visible_family_rows(self):
        return self.category_families[:3]

    @property
    def can_meter_previous(self):
        return self.meter_page > 0

    @property
    def can_meter_next(self):
        return self.meter_page < (len(METER_STYLES) - 1) // METER_CARDS_PER_PAGE

    def _page_meters(self, direction):
        self.meter_page = max(0, min((len(METER_STYLES) - 1) // METER_CARDS_PER_PAGE,
                                     self.meter_page + direction))

    def _open_meter_gallery(self):
        self.meter_page = list(METER_STYLES).index(self.draft["smeter_style"]) // METER_CARDS_PER_PAGE
        self.meter_gallery_open = True

    def swipe(self, start_x, start_y, x, y):
        """Page a gallery gesture without treating it as a face selection."""
        if (not self.meter_gallery_open or self.view_app or self.mode != "edit"
                or self.confirm_back or self.name_open or self.alpha_open or self.hex_open):
            return False
        if abs(x - start_x) < 60 or abs(x - start_x) <= abs(y - start_y):
            return False
        self._page_meters(1 if x < start_x else -1)
        return True

    def _select_category(self, index):
        self.category_index = max(0, min(len(GUIDED_CATEGORIES) - 1, index))
        self.fine_tune = False
        self.meter_gallery_open = False
        self.selected_family = self.category_families[0] if self.category_families else None
        if self.selected_family is not None:
            self._choose_family(next(index for index, (name, _keys) in enumerate(COLOR_GROUPS)
                                     if name == self.selected_family))

    def _snapshot_family(self):
        self.family_source = deepcopy(self.draft["colors"])
        self._sync_picker()

    def _sync_picker(self):
        self._sync_hue()
        _hue, self.lightness, self.strength = colorsys.rgb_to_hls(
            *(channel / 255 for channel in self.current_color[:3]))
        if not self.fine_tune:
            self.lightness = sum(colorsys.rgb_to_hls(
                *(channel / 255 for channel in self.draft["colors"][key][:3]))[1]
                for key in self.family_keys) / len(self.family_keys)

    def drag(self, control, x, y):
        if (self.mode != "edit" or self.view_app or self.selected_family is None
                or self.confirm_back or self.confirm_delete_id or self.name_open
                or self.alpha_open or self.hex_open
                or self.meter_gallery_open or control not in ("hue", "tone")):
            return
        box = theme_screen_boxes(self)[control]
        if control == "hue":
            self.hue = max(0.0, min(1.0, (x - box[0]) / (box[2] - box[0])))
        else:
            self.strength = max(0.0, min(1.0, (x - box[0]) / (box[2] - box[0])))
            self.lightness = 1.0 - max(0.0, min(1.0, (y - box[1]) / (box[3] - box[1])))
        if self.fine_tune:
            self.set_color([round(channel * 255) for channel in colorsys.hls_to_rgb(
                self.hue % 1.0, self.lightness, self.strength)])
        else:
            updated = recolor_family_shades(self.family_source, self.family_keys,
                                           self.hue, self.lightness, self.strength)
            # A snapshot supplies stable shade relationships, while unrelated
            # families retain any changes made since that snapshot was taken.
            if any(updated[key] != self.draft["colors"][key] for key in self.family_keys):
                for key in self.family_keys:
                    self.draft["colors"][key] = updated[key]
                self._apply_draft()

    def reset_category(self):
        keys = [key for family in self.category_families for key in dict(COLOR_GROUPS)[family]]
        settings = {3: ("smeter_style",),
                    5: ("radius", "sidebar", "units", "text_scale_percent")}.get(self.category_index, ())
        changed = (any(self.draft["colors"][key] != self.baseline["colors"][key] for key in keys)
                   or any(self.draft[key] != self.baseline[key] for key in settings))
        for key in keys:
            self.draft["colors"][key] = list(self.baseline["colors"][key])
        for key in settings:
            self.draft[key] = self.baseline[key]
        if self.selected_family:
            self._snapshot_family()
        if changed:
            self._apply_draft()

    def tap(self, x, y):
        if self.mode == "browse":
            self._tap_library_or_overlay(x, y)
            return
        if (self.confirm_back or self.confirm_delete_id or self.name_open
                or self.alpha_open or self.hex_open):
            self._tap_library_or_overlay(x, y)
            if self.mode == "edit" and not (self.name_open or self.alpha_open or self.hex_open):
                self._sync_picker()
            return
        boxes = theme_screen_boxes(self)
        action = next((name for name, box in boxes.items() if contains(box, x, y)), None)
        if action == "meter_gallery":
            self._open_meter_gallery()
        elif action == "meter_close":
            self.meter_gallery_open = False
        elif action == "meter_previous":
            self._page_meters(-1)
        elif action == "meter_next":
            self._page_meters(1)
        elif action and action.startswith("meter:"):
            choice = action.split(":", 1)[1]
            if choice in METER_STYLES and self.draft["smeter_style"] != choice:
                self.draft["smeter_style"] = choice
                self._apply_draft()
            self.meter_gallery_open = False
        elif action and action.startswith("option:"):
            choice = action.split(":", 1)[1]
            options = {"straight": ("radius", 0), "rounded": ("radius", 8),
                       "left": ("sidebar", "left"), "right": ("sidebar", "right"),
                       "original": ("units", "original"), "imperial": ("units", "imperial"),
                       "metric": ("units", "metric")}
            if choice in options:
                key, value = options[choice]
                if self.draft[key] != value:
                    self.draft[key] = value
                    self._apply_draft()
        elif action and action.startswith("text:"):
            choice = action.split(":", 1)[1]
            current = self.draft["text_scale_percent"]
            values = {"smaller": max(TEXT_SCALE_MIN, current - 5),
                      "larger": min(TEXT_SCALE_MAX, current + 5), "reset": 100}
            if choice in values and current != values[choice]:
                self.draft["text_scale_percent"] = values[choice]
                self._apply_draft()
        elif action == "previous":
            if self.can_previous:
                self._select_category(self.category_index - 1)
        elif action == "next":
            if self.can_next:
                self._select_category(self.category_index + 1)
        elif action == "view_app":
            self.view_app = True
        elif action == "return_to_editor":
            self.view_app = False
        elif action == "back":
            self.back()
        elif action == "theme_name":
            self.name_open = True
        elif action and action.startswith("family:"):
            family = action.split(":", 1)[1]
            self._choose_family(next(index for index, (name, _keys) in enumerate(COLOR_GROUPS)
                                     if name == family))
        elif action in ("hue", "tone"):
            self.drag(action, x, y)
        elif action == "fine_tune":
            self.fine_tune = True
            self.part_page = 0
            self._sync_picker()
        elif action == "fine_tune_close":
            self.fine_tune = False
            self._snapshot_family()
        elif action and action.startswith("key:"):
            self.color_key = action.split(":", 1)[1]
            self._sync_picker()
        elif action == "key_previous":
            self.part_page = max(0, self.part_page - 1)
        elif action == "key_next":
            self.part_page = min((len(self.family_keys) - 1) // 3, self.part_page + 1)
        elif action == "alpha_open":
            self.alpha_value = str(transparency_percent(self.current_color))
            self.alpha_pristine = True
            self.alpha_original = list(self.current_color)
            self.alpha_open = True
        elif action == "hex_open":
            self.hex_value = "".join(f"{value:02X}" for value in self.current_color)
            self.hex_pristine = True
            self.hex_open = True
        elif action == "reset_category":
            self.reset_category()
