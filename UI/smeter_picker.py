"""Immediate Home meter selection without leaving the live waterfall."""
from smeter_styles import METER_STYLES


class SMeterPicker:
    per_page = 6

    def __init__(self, library):
        self.library = library
        self.open = False
        self.page = 0
        self.error = ""

    @property
    def ids(self):
        return tuple(METER_STYLES)

    @property
    def page_count(self):
        return (len(self.ids) + self.per_page - 1) // self.per_page

    def show(self):
        self.page = self.ids.index(self.library.smeter_style) // self.per_page
        self.error = ""
        self.open = True

    def boxes(self, width=1024):
        left, right, top, bottom = 24, width - 24, 150, 742
        boxes = {
            "panel": (left, top, right, bottom),
            "close": (right - 136, top + 12, right - 16, top + 68),
            "previous": (left + 16, bottom - 72, left + 184, bottom - 16),
            "next": (right - 184, bottom - 72, right - 16, bottom - 16),
        }
        gap = 12
        card_width = (right - left - 32 - 2 * gap) / 3
        for index, identifier in enumerate(self.ids[self.page * 6:(self.page + 1) * 6]):
            x = left + 16 + index % 3 * (card_width + gap)
            y = top + 84 + index // 3 * 192
            boxes["meter:" + identifier] = (x, y, x + card_width, y + 180)
        return boxes

    def action_at(self, x, y, width=1024):
        for action, (a, b, c, d) in self.boxes(width).items():
            if action != "panel" and a <= x <= c and b <= y <= d:
                return action
        return "dismiss" if not self._inside(self.boxes(width)["panel"], x, y) else None

    @staticmethod
    def _inside(box, x, y):
        return box[0] <= x <= box[2] and box[1] <= y <= box[3]

    def tap(self, x, y, width=1024, *, started_at=None):
        action = self.action_at(x, y, width)
        if started_at is not None and action != self.action_at(*started_at, width):
            return
        if action in ("close", "dismiss"):
            self.open = False
        elif action == "previous":
            self.page = max(0, self.page - 1)
        elif action == "next":
            self.page = min(self.page_count - 1, self.page + 1)
        elif action and action.startswith("meter:"):
            try:
                self.library.set_smeter_style(action.split(":", 1)[1])
            except OSError:
                self.error = "Could not save. Try again."
            else:
                self.open = False

    def draw(self, ui, cache):
        width = ui.rf_canvas_width()
        boxes = self.boxes(width)
        palette = ui.APP_UI_STYLE.palette
        ui.draw_logical_rect(0, 0, width, ui.LOGICAL_H, (0, 0, 0, 105))
        ui.draw_logical_rounded_rect(*boxes["panel"], ui.APP_UI_STYLE.button.radius,
                                     palette.background, palette.border, 1)
        ui.draw_text(cache, 40, 188, "CHOOSE S-METER", palette.text, 24, True, False, "lm")
        ui.draw_styled_text_button(cache, boxes["close"], "CLOSE")
        selected = self.library.smeter_style
        for action, box in boxes.items():
            if not action.startswith("meter:"):
                continue
            identifier = action.split(":", 1)[1]
            style = METER_STYLES[identifier]
            ui.draw_styled_button_frame(box, active=identifier == selected)
            cx = (box[0] + box[2]) / 2
            title, _, author = style.name.partition(" · ")
            label_box = (box[0] + 8, box[1], box[2] - 8, box[1] + 34)
            title = ui.button_label_for_box(cache, title, label_box, size=20)
            ui.draw_text(cache, cx, box[1] + 22, title,
                         palette.focus if identifier == selected else palette.text,
                         20, True, False, "cm")
            if author:
                ui.draw_text(cache, cx, box[1] + 44, author, palette.secondary_text,
                             14, True, False, "cm")
            height = min(112, (box[2] - box[0] - 24) * style.height / 236)
            meter_width = height * 236 / style.height
            y = box[1] + 58 + (112 - height) / 2
            ui.draw_selected_smeter(cache, (cx - meter_width / 2, y,
                                          cx + meter_width / 2, y + height),
                                    -85, -73, style_id=identifier)
        for action, enabled in (("previous", self.page > 0),
                                ("next", self.page + 1 < self.page_count)):
            if enabled:
                ui.draw_styled_text_button(cache, boxes[action], action.upper())
        ui.draw_text(cache, width / 2, 698,
                     self.error or f"{self.page + 1} / {self.page_count} · Tap to apply",
                     palette.secondary_text, 20, True, False, "cm")
