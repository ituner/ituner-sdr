"""A stable gallery beside a faithful preview; one action applies and exits."""
import colorsys

import theme_system
from smeter_styles import METER_STYLES
from theme_colors import shade_grid, transparency_percent
from theme_editor import (APPLY_BOX, BACK_BOX, COLOR_GROUPS, METER_FILTERS,
                          PREVIEW_BOX, FULLSCREEN_BOX, CONTINUE_BOX, FULLSCREEN_SAVE_BOX,
                          CARDS_PER_PAGE, METER_CARDS_PER_PAGE, theme_screen_boxes)

def _palette(ui):
    return ui.APP_UI_STYLE.palette


def _text(ui, cache, x, y, value, color=None, size=14, anchor="lm", width=None):
    value = str(value)
    color = _palette(ui).text if color is None else color
    # Gallery controls remain legible and stationary while preview text changes.
    scale = theme_system.runtime_theme["text_scale_percent"] / 100
    chosen = max(1, round(size / scale))
    if isinstance(cache, ui.TextCache) and width:
        while chosen > max(1, round(8 / scale)):
            if cache.font(chosen, bold=True, family="Liberation Sans").size(value)[0] <= width:
                break
            chosen -= 1
    ui.draw_text(cache, x, y, value, color, chosen, True, False, anchor, family="Liberation Sans")


def _button(ui, cache, box, label, *, active=False, primary=False, enabled=True, danger=False):
    style = ui.APP_UI_STYLE.button
    visual = style.resolve(
        active=active or primary,
        pressed=ui.ui_button_pressed(box),
        danger=danger,
    )
    color = visual.text if enabled else _palette(ui).untested_text
    ui.draw_logical_rounded_rect(
        *box, style.radius, visual.fill, visual.border, visual.border_width,
    )
    _text(ui, cache, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
          label, color, 14, "cm", box[2] - box[0] - 20)


def _preview(ui, cache, editor, box=PREVIEW_BOX):
    """Show the whole actual Home framebuffer, including the selected meter."""
    if editor.live_frame is not None:
        editor.live_frame.draw(box)
    else:
        ui.draw_logical_rect(*box, _palette(ui).background)
        _text(ui, cache, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
              "Waiting for live Home preview…", _palette(ui).secondary_text, 16, "cm")


def _pages(ui, cache, boxes, prefix, page, count):
    _button(ui, cache, boxes[prefix + "_previous"], "PREVIOUS", enabled=page > 0)
    _button(ui, cache, boxes[prefix + "_next"], "NEXT", enabled=page + 1 < count)
    _text(ui, cache, 1000, 660, f"{page + 1} / {count}", _palette(ui).secondary_text, 14, "cm")


def _gallery(ui, cache, editor, boxes):
    if editor.tab == "themes":
        palette = _palette(ui)
        _text(ui, cache, 736, 122, "CHOOSE A THEME", palette.secondary_text, 13)
        items = editor.themes[editor.page * CARDS_PER_PAGE:(editor.page + 1) * CARDS_PER_PAGE]
        for item in items:
            box = boxes["theme:" + item["id"]]
            active = item["id"] == editor.selected_id
            colors = item["colors"]
            ui.draw_logical_rounded_rect(
                *box, ui.APP_UI_STYLE.button.radius, colors["background"],
                palette.focus if active else palette.border, 2 if active else 1,
            )
            _text(ui, cache, box[0] + 12, box[1] + 24, item["name"], colors["text"], 17, width=208)
            _text(ui, cache, box[0] + 12, box[1] + 52,
                  "Selected" if active else "Tap to preview", colors["secondary_text"], 13, width=208)
            if active:
                ui.draw_logical_circle(box[2] - 16, box[1] + 16, 3, palette.focus)
        _pages(ui, cache, boxes, "theme", editor.page, editor.page_count)
    else:
        for name, label in METER_FILTERS:
            _button(ui, cache, boxes["filter:" + name], label, active=editor.meter_filter == name)
        for identifier in editor.meter_ids[editor.meter_page * METER_CARDS_PER_PAGE:(editor.meter_page + 1) * METER_CARDS_PER_PAGE]:
            box = boxes["meter:" + identifier]
            style = METER_STYLES[identifier]
            active = identifier == editor.preview["smeter_style"]
            name, separator, author = style.name.partition(" · ")
            cx = (box[0] + box[2]) / 2
            palette = _palette(ui)
            _text(ui, cache, cx, box[1] + 14, name, palette.focus if active else palette.text, 13, "cm", 228)
            if separator:
                _text(ui, cache, cx, box[1] + 30, author, palette.secondary_text, 11, "cm", 228)
            if active:
                ui.draw_logical_circle(box[0] + 5, box[1] + 14, 3, palette.focus)
            width = min(236, (box[3] - box[1] - 42) * 236 / style.height)
            height = width * style.height / 236
            y = box[1] + 42
            ui.draw_selected_smeter(cache, (cx - width / 2, y, cx + width / 2, y + height),
                                    -85, -73, theme=editor.preview, style_id=identifier)
        _pages(ui, cache, boxes, "meter", editor.meter_page, editor.meter_page_count)


def _customize(ui, cache, editor, boxes):
    theme = editor.preview
    palette = _palette(ui)
    if editor.colors_open:
        _button(ui, cache, boxes["appearance"], "APPEARANCE")
        _text(ui, cache, 1256, 138, "EDIT COLORS", palette.secondary_text, 14, "rm")
        _button(ui, cache, boxes["group_previous"], "‹")
        _button(ui, cache, boxes["group_next"], "›")
        _text(ui, cache, 996, 212, COLOR_GROUPS[editor.color_group][0], palette.text, 20, "cm")
        for name, box in boxes.items():
            if name.startswith("part:"):
                key = editor.family_keys[int(name.split(":")[1])]
                _button(ui, cache, box, key.replace("_", " ").upper(), active=key == editor.color_key)
        count = (len(editor.family_keys) + 3) // 4
        _button(ui, cache, boxes["part_previous"], "PREVIOUS", enabled=editor.part_page > 0)
        _button(ui, cache, boxes["part_next"], "NEXT", enabled=editor.part_page + 1 < count)
        _text(ui, cache, 996, 418, f"{editor.part_page + 1} / {count}", palette.secondary_text, 13, "cm")
        _text(ui, cache, 736, 454, "HUE", palette.secondary_text, 12)
        hue = boxes["hue"]
        for index in range(96):
            x = hue[0] + index * (hue[2] - hue[0]) / 96
            rgb = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(index / 96, 1, 1))
            ui.draw_logical_rect(x, hue[1], x + (hue[2] - hue[0]) / 96 + 1, hue[3], rgb)
        for name, box in boxes.items():
            if name.startswith("shade:"):
                color = shade_grid(editor.hue)[int(name.split(":")[1])]
                ui.draw_logical_rounded_rect(*box, ui.APP_UI_STYLE.button.radius, color, palette.border)
        _button(ui, cache, boxes["hex_open"], "#" + "".join(f"{v:02X}" for v in editor.current_color[:3]))
        if "alpha_open" in boxes:
            _button(ui, cache, boxes["alpha_open"], f"TRANSPARENCY {transparency_percent(editor.current_color)}%")
        return
    _text(ui, cache, 736, 126, "NAME  ·  OPTIONAL", palette.secondary_text, 14)
    _button(ui, cache, boxes["theme_name"], theme["name"] + "  ·  RENAME")
    for row, label in enumerate(("SIDEBAR", "CORNERS", "TEXT SIZE", "UNITS")):
        _text(ui, cache, 736, 276 + row * 72, label, palette.secondary_text, 14)
    selected = {theme["sidebar"], "rounded" if theme["radius"] else "straight", theme["units"]}
    labels = {"straight": "SQUARE", "original": "ORIGINAL"}
    for name, box in boxes.items():
        if name.startswith("option:"):
            value = name.split(":")[1]
            _button(ui, cache, box, labels.get(value, value.upper()), active=value in selected)
    _button(ui, cache, boxes["text:smaller"], "−")
    _button(ui, cache, boxes["text:reset"], f"{theme['text_scale_percent']}%  ·  RESET")
    _button(ui, cache, boxes["text:larger"], "+")
    _button(ui, cache, boxes["colors"], "EDIT COLORS")
    _button(ui, cache, boxes["copy"], "MAKE A COPY")
    if "delete" in boxes:
        _button(ui, cache, boxes["delete"], "DELETE THEME", danger=True)


def _overlay(ui, cache, editor):
    palette = _palette(ui)
    ui.draw_logical_rect(0, 0, 1280, 800, (0, 0, 0, 215))
    ui.draw_logical_rounded_rect(
        64, 140, 1216, 680, ui.APP_UI_STYLE.button.radius,
        palette.surface, palette.border,
    )
    boxes = theme_screen_boxes(editor)
    if editor.overlay == "delete":
        _text(ui, cache, 640, 300, "DELETE THIS THEME?", palette.text, 26, "cm")
        _text(ui, cache, 640, 350, editor.draft["name"], palette.secondary_text, 20, "cm", 1000)
        _button(ui, cache, boxes["delete_cancel"], "KEEP THEME")
        _button(ui, cache, boxes["delete_confirm"], "DELETE", danger=True)
    else:
        title = {"name": "THEME NAME", "hex": "EXACT COLOR", "alpha": "TRANSPARENCY · 0–100%"}[editor.overlay]
        _text(ui, cache, 640, 174, title, palette.secondary_text, 16, "cm")
        _text(ui, cache, 640, 216, editor.buffer or "…", palette.text, 24, "cm", 1060)
        for name, box in boxes.items():
            label = name.split(":", 1)[1]
            _button(ui, cache, box, label, primary=label in ("APPLY", "DONE"))
        if editor.error:
            _text(ui, cache, 640, 654, editor.error, palette.danger_border, 14, "cm", 1060)


def draw_theme_screen(cache, editor, ui):
    palette = _palette(ui)
    if editor.fullscreen:
        _preview(ui, cache, editor, (0, 0, 1280, 800))
        if editor.fullscreen_controls:
            ui.draw_logical_rounded_rect(
                320, 706, 960, 796, ui.APP_UI_STYLE.button.radius,
                palette.background, palette.border,
            )
            _button(ui, cache, CONTINUE_BOX, "CONTINUE CHOOSING")
            _button(ui, cache, FULLSCREEN_SAVE_BOX, "SAVE & HOME", primary=True)
            _text(ui, cache, 640, 692, "Tap elsewhere to hide or show these controls", palette.text, 13, "cm")
        if editor.error:
            ui.draw_logical_rect(24, 620, 1256, 680, palette.background)
            _text(ui, cache, 640, 650, editor.error, palette.danger_border, 16, "cm", 1200)
        return
    boxes = theme_screen_boxes(editor, ignore_overlay=True)
    ui.draw_logical_rect(0, 0, 1280, 800, palette.background)
    _text(ui, cache, 24, 42, "DISPLAY APPEARANCE", palette.text, 25)
    _text(ui, cache, 24, 78, "Choose a look. Preview your complete Home screen.", palette.secondary_text, 15)
    for tab, label in (("themes", "THEMES"), ("meters", "S-METERS"), ("customize", "CUSTOMIZE")):
        _button(ui, cache, boxes[f"tab:{tab}"], label, active=editor.tab == tab)
    _text(ui, cache, 24, 124, "LIVE HOME PREVIEW", palette.focus, 14)
    _text(ui, cache, 704, 124, "Not saved yet" if editor.dirty else "Current settings", palette.secondary_text, 13, "rm")
    _preview(ui, cache, editor)
    _text(ui, cache, 24, 606, editor.preview["name"] + "  ·  " + METER_STYLES[editor.preview["smeter_style"]].name,
          palette.text, 15, width=680)
    _button(ui, cache, FULLSCREEN_BOX, "FULL-SCREEN PREVIEW")
    ui.draw_logical_line(720, 112, 720, 714, palette.divider, 1)
    if editor.tab in ("themes", "meters"):
        _gallery(ui, cache, editor, boxes)
    else:
        _customize(ui, cache, editor, boxes)
    _button(ui, cache, BACK_BOX, "CANCEL")
    _button(ui, cache, APPLY_BOX, "SAVE & HOME", primary=True)
    _text(ui, cache, 222, 760, editor.error or "Preview freely. Nothing is saved until Save & Home.",
          palette.danger_border if editor.error else palette.secondary_text, 14, width=740)
    if editor.overlay:
        _overlay(ui, cache, editor)
