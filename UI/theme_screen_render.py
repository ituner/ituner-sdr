"""Full-canvas Theme Library and visual editor rendering.

The main UI module supplies its established OpenGL drawing helpers. Geometry
always comes from theme_editor.theme_screen_boxes.
"""

import colorsys

from theme_colors import shade_grid, transparency_percent
from theme_editor import (BACK_BOX, COLOR_GROUPS, EDITOR_INSPECTOR_BOX,
                          EDITOR_PREVIEW_BOX, theme_screen_boxes)
import theme_system


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
    _button(ui, cache, boxes["new"], "NEW THEME")
    _text(ui, cache, 24, 112, "BUILT-IN", palette.section_heading, 14)
    _text(ui, cache, 24, 308, "SAVED THEMES", palette.section_heading, 14)
    for slot in range(9):
        item = editor.card_item(slot)
        if item is None:
            continue
        box = boxes[f"theme:{slot}"]
        colors = item["colors"]
        active = item["id"] == editor.library.active_id
        _frame(ui, box, palette.active_surface if active else palette.section_surface,
               palette.active_border if active else palette.section_border,
               item["radius"])
        name = item["name"].upper()
        if len(name) > 24:
            name = name[:23] + "…"
        _text(ui, cache, box[0] + 16, box[1] + 30, name, palette.text, 19)
        _text(ui, cache, box[0] + 16, box[1] + 58,
              "ACTIVE" if active else ("ROUNDED" if item["radius"] else "STRAIGHT"),
              palette.ready if active else palette.secondary_text, 12)
        for index, key in enumerate(("background", "surface", "frequency", "ready", "passband_fill")):
            x0 = box[0] + 16 + index * 42
            _swatch(ui, (x0, box[1] + 76, x0 + 34, box[1] + 108),
                    colors[key], palette.border)
        _button(ui, cache, boxes[f"edit:{slot}"],
                "CUSTOMIZE" if slot < 3 else "EDIT")
        if slot >= 3:
            _button(ui, cache, boxes[f"delete:{slot}"], "DELETE")
    _button(ui, cache, boxes["previous"], "PREV")
    _button(ui, cache, boxes["next"], "NEXT")
    _text(ui, cache, 1130, 682, f"{editor.page + 1} / {editor.page_count}",
          palette.secondary_text, 13, "cm")


def _draw_preview(ui, cache, editor):
    theme = editor.preview
    colors = theme["colors"]
    x0, y0, x1, y1 = EDITOR_PREVIEW_BOX
    _frame(ui, EDITOR_PREVIEW_BOX, colors["background"], colors["section_border"], 4)
    rail_width = 168
    rail = ((x0, y0, x0 + rail_width, y1) if theme["sidebar"] == "left"
            else (x1 - rail_width, y0, x1, y1))
    main = ((x0 + rail_width, y0, x1, y1) if theme["sidebar"] == "left"
            else (x0, y0, x1 - rail_width, y1))
    ui.draw_logical_rect(*rail, colors["sidebar"])
    ui.draw_logical_line(rail[2] if theme["sidebar"] == "left" else rail[0],
                         y0, rail[2] if theme["sidebar"] == "left" else rail[0],
                         y1, colors["section_border"], 1)
    if editor.scene == "home":
        _draw_preview_home(ui, cache, theme, rail, main)
    elif editor.scene == "browse":
        _draw_preview_browse(ui, cache, theme, rail, main)
    else:
        _draw_preview_popups(ui, cache, theme, rail, main)


def _draw_preview_home(ui, cache, theme, rail, main):
    colors = theme["colors"]
    rx = (rail[0] + rail[2]) / 2
    _text(ui, cache, rx, 205, "1.088.900", colors["frequency"], 28, "cm")
    _text(ui, cache, rx, 240, "MW  AM", colors["secondary_text"], 13, "cm")
    _text(ui, cache, rail[0] + 12, 275, "S-METER", colors["section_heading"], 13)
    for index in range(24):
        x = rail[0] + 12 + index * 6
        ui.draw_logical_rect(x, 291, x + 4, 311,
                             colors["meter_on"] if index < 13 else colors["meter_off"])
    _text(ui, cache, rail[0] + 12, 330, "S1  S3  S5  S7  S9", colors["smeter_scale"], 11)
    labels = (("NORMAL", "surface", "border"), ("ACTIVE", "active_surface", "active_border"),
              ("SELECTED", "selected_surface", "selected_border"),
              ("PRESSED", "pressed_surface", "pressed_border"))
    for index, (label, fill_key, border_key) in enumerate(labels):
        bx = rail[0] + 10 + (index % 2) * 78
        by = 374 + (index // 2) * 72
        box = (bx, by, bx + 70, by + 64)
        _frame(ui, box, colors[fill_key], colors[border_key], theme["radius"])
        _text(ui, cache, bx + 35, by + 25, label, colors["text"], 10, "cm")
        _text(ui, cache, bx + 35, by + 43, "TEXT", colors["secondary_text"], 10, "cm")
    mx0, my0, mx1, my1 = main
    ui.draw_logical_rect(mx0 + 8, 178, mx1 - 8, 315, colors["spectrum_field"])
    for row in range(1, 4):
        yy = 178 + row * 34
        ui.draw_logical_line(mx0 + 8, yy, mx1 - 8, yy, colors["spectrum_grid"], 1)
    for index in range(56):
        xx = mx0 + 8 + index * (mx1 - mx0 - 16) / 55
        peak = 22 + (index * 17 % 39)
        ui.draw_logical_line(xx, 315, xx, 315 - peak,
                             colors["spectrum_line"], 1)
    ui.draw_logical_rect(mx0 + 8, 315, mx1 - 8, 630, colors["waterfall_low"])
    for index in range(22):
        xx = mx0 + 10 + index * (mx1 - mx0 - 20) / 21
        ui.draw_logical_line(xx, 315, xx, 630,
                             colors["waterfall_high"] if index % 6 == 0 else colors["waterfall_low"], 2)
    cx = (mx0 + mx1) / 2
    ui.draw_logical_rect(cx - 34, 178, cx + 34, 630, colors["passband_fill"])
    ui.draw_logical_line(cx - 34, 178, cx - 34, 630, colors["passband_border"], 1)
    ui.draw_logical_line(cx + 34, 178, cx + 34, 630, colors["passband_border"], 1)
    ui.draw_logical_rect(mx0 + 8, 640, mx1 - 8, 698, colors["footer_background"])
    _text(ui, cache, mx0 + 20, 661, "RECEIVER  •  BRACKNELL", colors["footer_primary"], 12)
    _text(ui, cache, mx0 + 20, 686, "BUFFER  Q7/T6   05:32 UTC", colors["footer_live"], 12)
    _text(ui, cache, mx1 - 20, 686,
          theme_system.display_distance(100, theme) + "   "
          + theme_system.display_temperature(40, theme),
          colors["footer_primary"], 12, "rm")


def _draw_preview_browse(ui, cache, theme, rail, main):
    colors = theme["colors"]
    _text(ui, cache, rail[0] + 12, 198, "RECEIVERS", colors["sidebar_title"], 15)
    for index, label in enumerate(("ALL", "KIWI", "OPENWEBRX", "FM-DX")):
        box = (rail[0] + 10, 220 + index * 72, rail[2] - 10, 276 + index * 72)
        _frame(ui, box, colors["active_surface"] if index == 0 else colors["surface"],
               colors["active_border"] if index == 0 else colors["border"], theme["radius"])
        _text(ui, cache, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, label,
              colors["text"], 12, "cm")
    _text(ui, cache, main[0] + 20, 196, "BROWSE RECEIVERS", colors["section_heading"], 17)
    for index, name in enumerate(("KIWI BRACKNELL", "SDR ENGLAND", "OPENWEBRX NORTH", "KIWI EAST")):
        box = (main[0] + 20, 220 + index * 94, main[2] - 20, 302 + index * 94)
        _frame(ui, box, colors["selected_surface"] if index == 1 else colors["section_surface"],
               colors["selected_border"] if index == 1 else colors["section_border"], theme["radius"])
        _text(ui, cache, box[0] + 16, box[1] + 28, name, colors["text"], 15)
        _text(ui, cache, box[0] + 16, box[1] + 57, "RECEIVER DETAILS  •  3 USERS",
              colors["secondary_text"], 12)


def _draw_preview_popups(ui, cache, theme, rail, main):
    colors = theme["colors"]
    _text(ui, cache, rail[0] + 12, 198, "CAPTIONS", colors["sidebar_title"], 15)
    notice = (main[0] + 24, 195, main[2] - 24, 266)
    ui.draw_logical_rect(*notice, colors["section_surface"])
    ui.draw_logical_line(notice[0], notice[1], notice[2], notice[1], colors["notice"], 2)
    _text(ui, cache, notice[0] + 16, 229, "ZOOM  24x", colors["notice"], 22)
    popup = (main[0] + 24, 300, main[2] - 24, 520)
    _frame(ui, popup, colors["section_surface"], colors["section_border"], theme["radius"])
    _text(ui, cache, popup[0] + 20, 333, "LIVE TRANSCRIPTION", colors["section_heading"], 16)
    _text(ui, cache, popup[0] + 20, 389, "Sample speech appears here.", colors["text"], 18)
    _text(ui, cache, popup[0] + 20, 448, "WAITING FOR SPEECH", colors["secondary_text"], 13)
    _text(ui, cache, popup[2] - 20, 494, "CLOSE", colors["text"], 13, "rm")


def _draw_color_inspector(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    family, keys = COLOR_GROUPS[editor.color_group]
    _button(ui, cache, boxes["family_open"], f"{family}  •  {len(keys)} PARTS  •  CHANGE")
    for slot in range(4):
        index = editor.part_page * 4 + slot
        name = f"part:{index}"
        if name in boxes:
            _button(ui, cache, boxes[name], keys[index].replace("_", " ").upper(),
                    active=keys[index] == editor.color_key)
    _button(ui, cache, boxes["part_previous"], "PREV")
    _button(ui, cache, boxes["part_next"], "NEXT")
    if "hex_open" in boxes:
        _button(ui, cache, boxes["hex_open"], "HEX")
    else:
        _swatch(ui, (1128, 288, 1184, 332),
                editor.baseline["colors"][editor.color_key], palette.border)
        _swatch(ui, (1192, 288, 1256, 332), editor.current_color, palette.border)
    color = editor.current_color
    _text(ui, cache, 848, 340, editor.color_key.replace("_", " ").upper(),
          palette.section_heading, 13)
    _text(ui, cache, 1256, 340, theme_system.color_hex(color),
          palette.secondary_text, 12, "rm")
    hue_box = boxes["hue"]
    strips = 48
    strip_w = (hue_box[2] - hue_box[0]) / strips
    for index in range(strips):
        hue = index / strips
        rgb = colorsys.hls_to_rgb(hue, 0.5, 1.0)
        fill = tuple(round(value * 255) for value in rgb)
        x = hue_box[0] + index * strip_w
        ui.draw_logical_rect(x, hue_box[1], x + strip_w + 1, hue_box[3], fill)
    marker_x = hue_box[0] + editor.hue * (hue_box[2] - hue_box[0])
    ui.draw_logical_line(marker_x, hue_box[1], marker_x, hue_box[3], palette.text, 3)
    for index, rgb in enumerate(shade_grid(editor.hue)):
        box = boxes[f"shade:{index}"]
        _swatch(ui, box, (*rgb, *color[3:]), palette.text if index == editor.shade_index else palette.border)
    if "alpha_open" in boxes:
        _button(ui, cache, boxes["alpha_open"],
                f"TRANSPARENCY   {transparency_percent(color)}%")
    else:
        _text(ui, cache, 848, 632, "OPAQUE COLOR", palette.secondary_text, 13)
    _button(ui, cache, boxes["apply_family"], f"APPLY MATCHING SHADES  •  {family}")


def _draw_layout_inspector(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    theme = editor.preview
    for title, y in (("BUTTON CORNERS", 142), ("SIDEBAR POSITION", 302),
                     ("DISTANCE & TEMPERATURE", 462)):
        _text(ui, cache, 848, y, title, palette.section_heading, 14)
    for name in ("straight", "rounded", "left", "right", "imperial", "metric"):
        active = (name == ("rounded" if theme["radius"] else "straight")
                  or name == theme["sidebar"] or name == theme["units"])
        _button(ui, cache, boxes[f"option:{name}"], name.upper(), active)


def _draw_text_inspector(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    _text(ui, cache, 848, 150, "ALL APP TEXT", palette.section_heading, 15)
    _text(ui, cache, 1052, 182, f"{editor.preview['text_scale_percent']}%",
          palette.text, 32, "cm")
    _button(ui, cache, boxes["text:smaller"], "SMALLER")
    _button(ui, cache, boxes["text:larger"], "LARGER")
    _button(ui, cache, boxes["text:reset"], "RESET TO 100%")
    _text(ui, cache, 848, 394, "80% – 120%", palette.secondary_text, 13)


def _draw_editor(ui, cache, editor, boxes):
    palette = ui.APP_UI_STYLE.palette
    _button(ui, cache, boxes["theme_name"], editor.draft["name"].upper() + "  EDIT")
    for panel in ("colors", "layout", "text", "advanced"):
        _button(ui, cache, boxes[f"panel:{panel}"], panel.upper(), editor.panel == panel)
    _button(ui, cache, boxes["save"], "SAVE THEME")
    if editor.dirty:
        _text(ui, cache, 24, 92, "UNSAVED", palette.notice, 12)
    for scene in ("home", "browse", "popups"):
        _button(ui, cache, boxes[f"scene:{scene}"], scene.upper(), editor.scene == scene)
    _draw_preview(ui, cache, editor)
    ui.draw_logical_line(EDITOR_INSPECTOR_BOX[0] - 10, 96,
                         EDITOR_INSPECTOR_BOX[0] - 10, 708, palette.divider, 1)
    if editor.panel in ("colors", "advanced"):
        _draw_color_inspector(ui, cache, editor, boxes)
    elif editor.panel == "layout":
        _draw_layout_inspector(ui, cache, editor, boxes)
    else:
        _draw_text_inspector(ui, cache, editor, boxes)


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
    else:
        panel = (16, 96, 1264, 660)
        title = "SELECT COLOR FAMILY"
        subtitle = "CHANGES APPLY TO THE SELECTED FAMILY"
        actions = tuple((f"family:{index}", name) for index, (name, _keys) in enumerate(COLOR_GROUPS))
        actions += (("family_cancel", "CANCEL"),)
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
    palette = ui.APP_UI_STYLE.palette
    ui.draw_logical_rect(0, 0, 1280, 800, palette.background)
    overlay = (editor.confirm_back or editor.confirm_delete_id or editor.name_open
               or editor.alpha_open or editor.hex_open or editor.family_picker)
    base_boxes = theme_screen_boxes(editor, ignore_overlay=True)
    if editor.mode == "browse":
        _draw_library(ui, text_cache, editor, base_boxes)
    else:
        _draw_editor(ui, text_cache, editor, base_boxes)
    if overlay:
        _draw_overlay(ui, text_cache, editor, theme_screen_boxes(editor))
    _button(ui, text_cache, BACK_BOX, "BACK")
