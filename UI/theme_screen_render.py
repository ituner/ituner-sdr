"""Full-canvas Theme Library and visual editor rendering.

The main UI module supplies its established OpenGL drawing helpers. Geometry
always comes from theme_editor.theme_screen_boxes.
"""

import colorsys
from types import SimpleNamespace

from theme_colors import transparency_percent
from theme_editor import (BACK_BOX, COLOR_GROUPS, METER_CARDS_PER_PAGE,
                          SAVED_CARDS_PER_PAGE, GUIDED_CATEGORIES,
                          theme_screen_boxes)
from smeter_styles import METER_STYLES
import theme_system
from ui_style import ButtonStyle, UIPalette


def _text(ui, cache, x, y, value, color, size=14, anchor="lm", bold=True):
    ui.draw_text(cache, x, y, str(value), color, size, bold, False, anchor,
                 family=ui.APP_UI_STYLE.button.font_family)


def _button(ui, cache, box, label, active=False, danger=False):
    ui.draw_styled_text_button(cache, box, label, active=active, danger=danger)


def _frame(ui, box, fill, border, radius=8):
    ui.draw_logical_rounded_rect(*box, radius, fill, border)


def _swatch(ui, box, color, border):
    if len(color) == 4 and color[3] < 255:
        x0, y0, x1, y1 = box
        step = 12
        for row, y in enumerate(range(int(y0), int(y1), step)):
            for col, x in enumerate(range(int(x0), int(x1), step)):
                check = (156, 156, 156, 255) if (row + col) % 2 else (52, 52, 52, 255)
                ui.draw_logical_rect(x, y, min(x + step, x1), min(y + step, y1), check)
    _frame(ui, box, color, border, 4)


def _draw_library(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    _text(ui, cache, 24, 46, "THEMES", palette.text, 26)
    _text(ui, cache, 24, 78, "TOUCH A THEME TO APPLY IT", palette.secondary_text, 14)
    _button(ui, cache, boxes["meters"], "S-METERS")
    _button(ui, cache, boxes["new"], "NEW THEME")
    _text(ui, cache, 24, 112, "BUILT-IN", palette.section_heading, 14)
    _text(ui, cache, 24, 308, "SAVED THEMES", palette.section_heading, 14)
    for slot in range(len(theme_system.BUILTIN_THEME_IDS) + SAVED_CARDS_PER_PAGE):
        item = editor.card_item(slot)
        if item is None:
            continue
        box = boxes[f"theme:{slot}"]
        colors = item["colors"]
        card_palette = UIPalette(**{key: tuple(value) for key, value in colors.items()})
        card_style = ButtonStyle(card_palette, radius=item["radius"],
                                 label_size=round(13 * item["text_scale_percent"] / 100))
        active = item["id"] == editor.library.active_id
        _frame(ui, box, colors["active_surface"] if active else colors["section_surface"],
               colors["active_border"] if active else colors["section_border"],
               item["radius"])
        name = item["name"].upper()
        name_size = round(19 * item["text_scale_percent"] / 100)
        if callable(getattr(cache, "texture", None)):
            name = ui.fit_station_text(cache, name, box[2] - box[0] - 32,
                                       name_size, bold=True,
                                       family=card_style.font_family)
        elif len(name) > 21:
            name = name[:20] + "…"
        _text(ui, cache, box[0] + 16, box[1] + 30, name, colors["text"], name_size)
        _text(ui, cache, box[0] + 16, box[1] + 58,
              "ACTIVE" if active else ("ROUNDED CORNERS" if item["radius"] else "STRAIGHT CORNERS"),
              colors["ready"] if active else colors["secondary_text"],
              round(12 * item["text_scale_percent"] / 100))
        ui.draw_styled_text_button(cache, boxes[f"edit:{slot}"],
                                   "CUSTOMIZE" if slot < len(theme_system.BUILTIN_THEME_IDS) else "EDIT",
                                   style=card_style)
        if slot >= len(theme_system.BUILTIN_THEME_IDS):
            ui.draw_styled_text_button(cache, boxes[f"delete:{slot}"], "DELETE",
                                       style=card_style)
    for action, label, enabled in (("previous", "PREV", editor.can_previous),
                                   ("next", "NEXT", editor.can_next)):
        if enabled:
            _button(ui, cache, boxes[action], label)
        else:
            _frame(ui, boxes[action], palette.surface, palette.border,
                   ui.APP_UI_STYLE.button.radius)
            _text(ui, cache, (boxes[action][0] + boxes[action][2]) / 2,
                  (boxes[action][1] + boxes[action][3]) / 2,
                  label, palette.secondary_text, 13, "cm")
    _text(ui, cache, 528, 760, f"{editor.page + 1} / {editor.page_count}",
          palette.secondary_text, 13, "lm")


def _draw_overlay(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    ui.draw_logical_rect(0, 0, 1280, 800, (0, 0, 0, 188))
    if editor.confirm_back:
        panel = (160, 270, 1120, 550)
        title = "SAVE CHANGES?"
        subtitle = "YOUR THEME HAS UNSAVED CHANGES"
        actions = (("leave_save", "SAVE & LEAVE"), ("leave_discard", "DISCARD & LEAVE"),
                   ("leave_keep", "KEEP EDITING"))
    elif editor.confirm_delete_id:
        panel = (160, 270, 1120, 550)
        item = editor.library.get(editor.confirm_delete_id)
        title = "DELETE THEME?"
        subtitle = item["name"].upper() if item else ""
        actions = (("delete_confirm", "DELETE"), ("delete_cancel", "CANCEL"))
    elif editor.name_open:
        panel = (120, 96, 1160, 636)
        title = "NAME THEME"
        subtitle = editor.draft["name"] or "ENTER A NAME"
        actions = tuple((name, name.split(":")[1]) for name in boxes if name.startswith("name:"))
    elif editor.alpha_open:
        panel = (120, 96, 1160, 636)
        title = "TRANSPARENCY  0–100%"
        subtitle = editor.alpha_value or "0"
        actions = tuple((name, name.split(":")[1]) for name in boxes if name.startswith("alpha:"))
    elif editor.hex_open:
        panel = (120, 96, 1160, 636)
        title = "EXACT COLOR"
        subtitle = "#" + editor.hex_value
        actions = tuple((name, name.split(":")[1]) for name in boxes if name.startswith("hex:"))
    _frame(ui, panel, palette.section_surface, palette.section_border, 8)
    title_y = 334 if editor.confirm_back or editor.confirm_delete_id else 148
    subtitle_y = 382 if editor.confirm_back or editor.confirm_delete_id else 194
    _text(ui, cache, 640, title_y, title, palette.text, 26, "cm")
    _text(ui, cache, 640, subtitle_y, subtitle, palette.secondary_text, 17, "cm")
    for action, label in actions:
        if action in boxes:
            _button(ui, cache, boxes[action], label, danger=action in ("leave_discard", "delete_confirm"))


def draw_theme_screen(text_cache, editor, ui):
    """Paint exactly the state represented by ThemeEditor's hit geometry."""
    if editor.mode == "edit":
        return draw_guided_theme_editor(text_cache, editor, ui)
    palette = ui.APP_UI_STYLE.palette
    ui.draw_logical_rect(0, 0, 1280, 800, palette.background)
    overlay = (editor.confirm_back or editor.confirm_delete_id or editor.name_open
               or editor.alpha_open or editor.hex_open)
    base_boxes = theme_screen_boxes(editor, ignore_overlay=True)
    if editor.mode == "browse":
        _draw_library(ui, text_cache, editor, base_boxes)
    if overlay:
        _draw_overlay(ui, text_cache, editor, theme_screen_boxes(editor))
    _button(ui, text_cache, BACK_BOX, "BACK")


GUIDED_CHROME_BUTTON_STYLE = ButtonStyle(UIPalette())


class _GuidedChromeUI:
    """Keep editor controls legible while the real app previews any draft."""

    def __init__(self, ui):
        self._ui = ui
        self.APP_UI_STYLE = SimpleNamespace(palette=GUIDED_CHROME_BUTTON_STYLE.palette,
                                            button=GUIDED_CHROME_BUTTON_STYLE)

    def __getattr__(self, name):
        return getattr(self._ui, name)

    def draw_styled_text_button(self, cache, box, label, **kwargs):
        kwargs["style"] = self.APP_UI_STYLE.button
        return self._ui.draw_styled_text_button(cache, box, label, **kwargs)


_FAMILY_DESCRIPTIONS = {
    "SURFACES": "App background, sidebar and panels",
    "FOOTER": "Footer background and status text",
    "TEXT": "Labels, headings and frequency text",
    "BUTTONS": "Normal, active, selected and pressed buttons",
    "STATES": "Ready, waiting, notices and alerts",
    "S-METER": "Meter bars, scales, ticks and markers",
    "PASSBAND": "Passband fill, edges and center lines",
    "SLIDERS": "Slider track, fill, thumb and marker",
    "SPECTRUM": "Spectrum field, grid, labels and traces",
    "WATERFALL": "Waterfall colors, ruler and labels",
}


def _draw_guided_picker(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    label = editor.color_key.replace("_", " ").upper() if editor.fine_tune else editor.selected_family
    _text(ui, cache, 440, 366, label, palette.text, 20)
    _swatch(ui, (1176, 344, 1256, 384), editor.current_color, palette.border)
    hue_box, tone_box = boxes["hue"], boxes["tone"]
    for index in range(96):
        left = hue_box[0] + index * (hue_box[2] - hue_box[0]) / 96
        right = hue_box[0] + (index + 1) * (hue_box[2] - hue_box[0]) / 96
        rgb = tuple(round(value * 255) for value in colorsys.hls_to_rgb(index / 96, 0.5, 1.0))
        ui.draw_logical_rect(left, hue_box[1], right, hue_box[3], rgb)
    for row in range(24):
        top = tone_box[1] + row * (tone_box[3] - tone_box[1]) / 24
        bottom = tone_box[1] + (row + 1) * (tone_box[3] - tone_box[1]) / 24
        for col in range(64):
            left = tone_box[0] + col * (tone_box[2] - tone_box[0]) / 64
            right = tone_box[0] + (col + 1) * (tone_box[2] - tone_box[0]) / 64
            rgb = tuple(round(value * 255) for value in colorsys.hls_to_rgb(
                editor.hue % 1.0, 1 - row / 23, col / 63))
            ui.draw_logical_rect(left, top, right, bottom, rgb)
    hx = hue_box[0] + editor.hue * (hue_box[2] - hue_box[0])
    tx = tone_box[0] + editor.strength * (tone_box[2] - tone_box[0])
    ty = tone_box[1] + (1 - editor.lightness) * (tone_box[3] - tone_box[1])
    # A dark outline and white center stay visible on every picker color.
    for color, width in (((0, 0, 0), 5), ((255, 255, 255), 2)):
        ui.draw_logical_line(hx, hue_box[1], hx, hue_box[3], color, width)
        ui.draw_logical_line(tx - 8, ty, tx + 8, ty, color, width)
        ui.draw_logical_line(tx, ty - 8, tx, ty + 8, color, width)
    _text(ui, cache, 440, 464, "LIGHTER ↑", palette.secondary_text, 12)
    _text(ui, cache, 440, 664, "NEUTRAL", palette.secondary_text, 12)
    _text(ui, cache, 1256, 664, "COLOR STRENGTH →", palette.secondary_text, 12, "rm")
    _button(ui, cache, boxes["reset_category"], "RESET CATEGORY")
    if editor.fine_tune:
        _button(ui, cache, boxes["fine_tune_close"], "DONE FINE TUNING")
        _button(ui, cache, boxes["hex_open"], "EXACT HEX COLOR")
        if "alpha_open" in boxes:
            _button(ui, cache, boxes["alpha_open"],
                    f"TRANSPARENCY  {transparency_percent(editor.current_color)}%")
    else:
        _button(ui, cache, boxes["fine_tune"], "FINE TUNE")


def _guided_nav_button(ui, cache, box, label, enabled):
    if enabled:
        _button(ui, cache, box, label)
    else:
        palette = ui.APP_UI_STYLE.palette
        _frame(ui, box, palette.surface, palette.border)
        _text(ui, cache, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
              label, palette.secondary_text, 13, "cm")


def _draw_guided_layout(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    theme = editor.draft
    for title, top in (("BUTTON CORNERS", 156), ("SIDEBAR POSITION", 292),
                       ("DISTANCE & TEMPERATURE", 428), ("ALL APP TEXT", 564)):
        _text(ui, cache, 24, top + 32, title, palette.section_heading, 17)
    active = {"rounded" if theme["radius"] else "straight", theme["sidebar"], theme["units"]}
    for name in ("straight", "rounded", "left", "right", "original", "imperial", "metric"):
        _button(ui, cache, boxes[f"option:{name}"], name.upper(), name in active)
    percent = theme["text_scale_percent"]
    _text(ui, cache, 24, 624, f"{percent}%", palette.text, 26)
    _guided_nav_button(ui, cache, boxes["text:smaller"], "SMALLER",
                       percent > theme_system.TEXT_SCALE_MIN)
    _guided_nav_button(ui, cache, boxes["text:larger"], "LARGER",
                       percent < theme_system.TEXT_SCALE_MAX)
    _button(ui, cache, boxes["text:reset"], "RESET TO 100%")
    _button(ui, cache, boxes["reset_category"], "RESET CATEGORY")
    _text(ui, cache, 440, 664, "80% – 120%  •  5% STEPS", palette.secondary_text, 14)


def _draw_guided_meter_card(ui, cache, editor, box, identifier, selected=False, chooser=False):
    palette = ui.APP_UI_STYLE.palette
    _frame(ui, box, palette.active_surface if selected else palette.surface,
           palette.active_border if selected else palette.border)
    label = METER_STYLES[identifier].name.upper()
    _text(ui, cache, box[0] + 12, box[1] + 18, label, palette.text, 13)
    if chooser:
        _text(ui, cache, box[2] - 12, box[3] - 12, "CHANGE FACE", palette.secondary_text, 11, "rm")
    ui.draw_selected_smeter(
        cache, (box[0] + 8, box[1] + 34, box[2] - 8, box[3] - (28 if chooser else 8)),
        -85, None, theme=editor.draft, style_id=identifier,
    )


def _draw_guided_meter_gallery(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    _text(ui, cache, 24, 44, "S-METER FACES", palette.text, 26)
    _text(ui, cache, 24, 80, "TOUCH A FACE TO USE IT  •  SWIPE FOR MORE", palette.secondary_text, 14)
    for action, box in boxes.items():
        if action.startswith("meter:"):
            identifier = action.split(":", 1)[1]
            _draw_guided_meter_card(ui, cache, editor, box, identifier,
                                   selected=identifier == editor.draft["smeter_style"])
    _guided_nav_button(ui, cache, boxes["meter_previous"], "PREV", editor.can_meter_previous)
    _guided_nav_button(ui, cache, boxes["meter_next"], "NEXT", editor.can_meter_next)
    _button(ui, cache, boxes["meter_close"], "CLOSE")
    pages = (len(METER_STYLES) + METER_CARDS_PER_PAGE - 1) // METER_CARDS_PER_PAGE
    _text(ui, cache, 640, 680, f"{editor.meter_page + 1} / {pages}", palette.secondary_text, 14, "cm")


def draw_guided_theme_editor(cache, editor, ui):
    """Draw one category with the same geometry used by guided touch input."""
    if editor.mode == "browse":
        draw_theme_screen(cache, editor, ui)
        return
    ui = _GuidedChromeUI(ui)
    palette = ui.APP_UI_STYLE.palette
    boxes = theme_screen_boxes(editor, ignore_overlay=True)
    if editor.view_app:
        _button(ui, cache, boxes["return_to_editor"], "RETURN TO EDITOR")
        return
    ui.draw_logical_rect(0, 0, 1280, 800, palette.background)
    if editor.meter_gallery_open and not (editor.confirm_back or editor.confirm_delete_id
                                          or editor.name_open or editor.alpha_open
                                          or editor.hex_open):
        _draw_guided_meter_gallery(ui, cache, editor, theme_screen_boxes(editor))
        return
    _text(ui, cache, 24, 44, editor.draft["name"], palette.text, 26)
    _text(ui, cache, 24, 80, GUIDED_CATEGORIES[editor.category_index][0].upper(),
          palette.section_heading, 18)
    _text(ui, cache, 1256, 44, f"CATEGORY {editor.category_index + 1} / 6",
          palette.secondary_text, 15, "rm")
    if editor.dirty:
        _text(ui, cache, 1256, 80, "UNSAVED", palette.notice, 12, "rm")
    for action, box in boxes.items():
        if action.startswith(("family:", "key:")):
            name = action.split(":", 1)[1]
            is_family = action.startswith("family:")
            key = dict(COLOR_GROUPS)[name][0] if is_family else name
            selected = name == (editor.selected_family if is_family else editor.color_key)
            _frame(ui, box, palette.active_surface if selected else palette.surface,
                   palette.active_border if selected else palette.border)
            _swatch(ui, (box[0] + 16, box[1] + 12, box[0] + 72, box[3] - 12),
                    editor.draft["colors"][key], palette.border)
            _text(ui, cache, box[0] + 92, box[1] + 24,
                  name.replace("_", " ").upper(), palette.text, 17)
            if is_family:
                _text(ui, cache, box[0] + 92, box[1] + 48,
                      _FAMILY_DESCRIPTIONS[name], palette.secondary_text, 13)
    if editor.category_index == 5:
        _draw_guided_layout(ui, cache, editor, boxes)
    elif editor.selected_family:
        _draw_guided_picker(ui, cache, editor, boxes)
    if "meter_gallery" in boxes:
        _draw_guided_meter_card(ui, cache, editor, boxes["meter_gallery"],
                               editor.draft["smeter_style"], chooser=True)
    if editor.fine_tune:
        for action, label in (("key_previous", "PREV KEYS"), ("key_next", "NEXT KEYS")):
            _button(ui, cache, boxes[action], label)
    for action, label, enabled in (("previous", "PREV", editor.can_previous),
                                   ("next", "NEXT", editor.can_next)):
        _guided_nav_button(ui, cache, boxes[action], label, enabled)
    _button(ui, cache, boxes["view_app"], "VIEW APP")
    _button(ui, cache, boxes["back"], "BACK")
    if (editor.confirm_back or editor.confirm_delete_id or editor.name_open
            or editor.alpha_open or editor.hex_open):
        _draw_overlay(ui, cache, editor, theme_screen_boxes(editor))
