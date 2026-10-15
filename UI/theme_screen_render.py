"""A stable gallery beside a faithful preview; one action applies and exits."""
import colorsys
import math
import time

import theme_system
from theme_preview import home_capture, frontend_preview
from smeter_styles import METER_STYLES
from theme_colors import shade_grid, transparency_percent
from theme_editor import (APPLY_BOX, BACK_BOX, COLOR_GROUPS, METER_FILTERS,
                          PREVIEW_BOX, CARDS_PER_PAGE, METER_CARDS_PER_PAGE, theme_screen_boxes)

BG = (12, 17, 22)
SURFACE = (21, 29, 36)
BORDER = (48, 64, 75)
TEXT = (231, 238, 243)
MUTED = (150, 168, 180)
ACCENT = (88, 229, 176)
SELECTED = (22, 61, 48)
ERROR = (255, 163, 137)


def _text(ui, cache, x, y, value, color=TEXT, size=14, anchor="lm", width=None):
    value = str(value)
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
    fill = (43, 193, 137) if primary else SELECTED if active else SURFACE
    border = ACCENT if active or primary else BORDER
    color = (5, 25, 19) if primary else ACCENT if active else TEXT if enabled else (91, 111, 124)
    if danger:
        color = ERROR
    ui.draw_logical_rounded_rect(*box, 8, fill, border)
    _text(ui, cache, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
          label, color, 14, "cm", box[2] - box[0] - 20)


def _captured_frontend(ui, cache, theme, box):
    """Resize the real captured frontend once per candidate appearance."""
    if not isinstance(cache, ui.TextCache):
        ui.draw_logical_rect(*box, theme['colors']['background'])
        return
    metadata, _image = home_capture()
    size = (max(1, round(box[2] - box[0])), max(1, round(box[3] - box[1])))
    key = ('theme-home-capture-v1', metadata['sha256'], theme['id'], size,
           tuple((key, tuple(value)) for key, value in sorted(theme['colors'].items())))
    cached = cache._cached_texture(('surface', key))
    if cached is None:
        artwork = frontend_preview(theme, ui.themed_waterfall_pixels)
        artwork = artwork.resize(size, ui.PILImage.Resampling.LANCZOS)
        surface = ui.pygame.image.fromstring(artwork.tobytes(), size, 'RGBA')
        cached = cache.surface_texture(key, surface)
    ui.draw_textured_quad(cached[0], *box, 0, 0, 1, 1)


def _preview(ui, cache, editor):
    """The SDR scene occupies its native Home viewport, without a second meter."""
    _captured_frontend(ui, cache, editor.preview, PREVIEW_BOX)


def _pages(ui, cache, boxes, prefix, page, count):
    _button(ui, cache, boxes[prefix + "_previous"], "PREVIOUS", enabled=page > 0)
    _button(ui, cache, boxes[prefix + "_next"], "NEXT", enabled=page + 1 < count)
    _text(ui, cache, 1152, 677, f"{page + 1} / {count}", MUTED, 14, "cm")


def _gallery(ui, cache, editor, boxes):
    if editor.tab == "themes":
        _text(ui, cache, 1034, 182, "CHOOSE A THEME", MUTED, 13)
        items = editor.themes[editor.page * CARDS_PER_PAGE:(editor.page + 1) * CARDS_PER_PAGE]
        for item in items:
            box = boxes["theme:" + item["id"]]
            active = item["id"] == editor.selected_id
            colors = item["colors"]
            ui.draw_logical_rounded_rect(*box, 8, colors["background"], ACCENT if active else BORDER)
            _text(ui, cache, box[0] + 12, box[1] + 30, item["name"], colors["text"], 19, width=208)
            _text(ui, cache, box[0] + 12, box[1] + 62,
                  "Selected" if active else "Tap to preview", colors["secondary_text"], 13, width=208)
            if active:
                ui.draw_logical_circle(box[2] - 16, box[1] + 18, 3, ACCENT)
        _pages(ui, cache, boxes, "theme", editor.page, editor.page_count)
    else:
        _text(ui, cache, 1034, 182, "PREVIEW AN S-METER", MUTED, 13)
        for name, label in METER_FILTERS:
            _button(ui, cache, boxes["filter:" + name], label, active=editor.meter_filter == name)
        for identifier in editor.meter_ids[editor.meter_page * METER_CARDS_PER_PAGE:(editor.meter_page + 1) * METER_CARDS_PER_PAGE]:
            box = boxes["meter:" + identifier]
            style = METER_STYLES[identifier]
            name, separator, author = style.name.partition(" · ")
            _text(ui, cache, 1152, box[1] + 16, name, ACCENT, 16, "cm", 232)
            if separator:
                _text(ui, cache, 1152, box[1] + 34, author, MUTED, 12, "cm", 232)
            # Exactly the same 236-pixel width and height as Home's meter.
            y = box[1] + 44
            ui.draw_selected_smeter(cache, (1034, y, 1270, y + style.height),
                                    -89 + 25 * math.sin(time.monotonic() * .7), -63,
                                    theme=editor.preview, style_id=identifier)
        _pages(ui, cache, boxes, "meter", editor.meter_page, editor.meter_page_count)


def _customize(ui, cache, editor, boxes):
    theme = editor.preview
    if editor.colors_open:
        _button(ui, cache, boxes["appearance"], "APPEARANCE")
        _text(ui, cache, 1000, 138, "EDIT COLORS", MUTED, 14, "rm")
        _button(ui, cache, boxes["group_previous"], "‹")
        _button(ui, cache, boxes["group_next"], "›")
        _text(ui, cache, 702, 212, COLOR_GROUPS[editor.color_group][0], TEXT, 20, "cm")
        for name, box in boxes.items():
            if name.startswith("part:"):
                key = editor.family_keys[int(name.split(":")[1])]
                _button(ui, cache, box, key.replace("_", " ").upper(), active=key == editor.color_key)
        count = (len(editor.family_keys) + 3) // 4
        _button(ui, cache, boxes["part_previous"], "PREVIOUS", enabled=editor.part_page > 0)
        _button(ui, cache, boxes["part_next"], "NEXT", enabled=editor.part_page + 1 < count)
        _text(ui, cache, 702, 418, f"{editor.part_page + 1} / {count}", MUTED, 13, "cm")
        _text(ui, cache, 404, 454, "HUE", MUTED, 12)
        hue = boxes["hue"]
        for index in range(96):
            x = hue[0] + index * (hue[2] - hue[0]) / 96
            rgb = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(index / 96, 1, 1))
            ui.draw_logical_rect(x, hue[1], x + (hue[2] - hue[0]) / 96 + 1, hue[3], rgb)
        for name, box in boxes.items():
            if name.startswith("shade:"):
                color = shade_grid(editor.hue)[int(name.split(":")[1])]
                ui.draw_logical_rounded_rect(*box, 4, color, BORDER)
        _button(ui, cache, boxes["hex_open"], "#" + "".join(f"{v:02X}" for v in editor.current_color[:3]))
        if "alpha_open" in boxes:
            _button(ui, cache, boxes["alpha_open"], f"TRANSPARENCY {transparency_percent(editor.current_color)}%")
        return
    _text(ui, cache, 404, 126, "NAME  ·  OPTIONAL", MUTED, 14)
    _button(ui, cache, boxes["theme_name"], theme["name"] + "  ·  RENAME")
    for row, label in enumerate(("SIDEBAR", "CORNERS", "TEXT SIZE", "UNITS")):
        _text(ui, cache, 404, 276 + row * 72, label, MUTED, 14)
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
    ui.draw_logical_rect(0, 0, 1280, 800, (0, 0, 0, 215))
    ui.draw_logical_rounded_rect(64, 140, 1216, 680, 12, SURFACE, BORDER)
    boxes = theme_screen_boxes(editor)
    if editor.overlay == "delete":
        _text(ui, cache, 640, 300, "DELETE THIS THEME?", TEXT, 26, "cm")
        _text(ui, cache, 640, 350, editor.draft["name"], MUTED, 20, "cm", 1000)
        _button(ui, cache, boxes["delete_cancel"], "KEEP THEME")
        _button(ui, cache, boxes["delete_confirm"], "DELETE", danger=True)
    else:
        title = {"name": "THEME NAME", "hex": "EXACT COLOR", "alpha": "TRANSPARENCY · 0–100%"}[editor.overlay]
        _text(ui, cache, 640, 174, title, MUTED, 16, "cm")
        _text(ui, cache, 640, 216, editor.buffer or "…", TEXT, 24, "cm", 1060)
        for name, box in boxes.items():
            label = name.split(":", 1)[1]
            _button(ui, cache, box, label, primary=label in ("APPLY", "DONE"))
        if editor.error:
            _text(ui, cache, 640, 654, editor.error, ERROR, 14, "cm", 1060)


def draw_theme_screen(cache, editor, ui):
    boxes = theme_screen_boxes(editor, ignore_overlay=True)
    ui.draw_logical_rect(0, 0, 1280, 800, BG)
    _preview(ui, cache, editor)
    ui.draw_logical_rect(1024, 0, 1280, 800, BG)
    ui.draw_logical_line(1024, 0, 1024, 800, BORDER, 1)
    _text(ui, cache, 1034, 26, "DISPLAY LOOK", TEXT, 18)
    for tab, label in (("themes", "THEMES"), ("meters", "S-METERS"), ("customize", "CUSTOMIZE")):
        _button(ui, cache, boxes[f"tab:{tab}"], label, active=editor.tab == tab)
    if editor.tab in ("themes", "meters"):
        _gallery(ui, cache, editor, boxes)
    else:
        ui.draw_logical_rounded_rect(384, 104, 1012, 712, 8, BG, BORDER)
        _customize(ui, cache, editor, boxes)
        _text(ui, cache, 1152, 202, editor.preview["name"], ACCENT, 18, "cm", 228)
        style = METER_STYLES[editor.preview["smeter_style"]]
        ui.draw_selected_smeter(cache, (1034, 240, 1270, 240 + style.height), -85, -73,
                                theme=editor.preview, style_id=editor.preview["smeter_style"])
        _text(ui, cache, 1152, 560, "Preview only", MUTED, 14, "cm")
        _text(ui, cache, 1152, 584, "Apply when ready", MUTED, 14, "cm")
    _button(ui, cache, BACK_BOX, "CANCEL")
    _button(ui, cache, APPLY_BOX, "APPLY & HOME", primary=True)
    if editor.error:
        ui.draw_logical_rounded_rect(24, 710, 1000, 784, 8, BG, ERROR)
        _text(ui, cache, 40, 747, editor.error, ERROR, 16, width=944)
    if editor.overlay:
        _overlay(ui, cache, editor)
