"""A stable gallery beside a faithful preview; one action applies and exits."""
import colorsys
import math
import time

import theme_system
from theme_preview import home_capture, frontend_preview
from smeter_styles import METER_STYLES
from theme_colors import shade_grid, transparency_percent
from theme_editor import (APPLY_BOX, BACK_BOX, COLOR_GROUPS, METER_FILTERS,
                          PREVIEW_BOX, theme_screen_boxes)

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


def _home(ui, cache, theme, box):
    """Use the real meter renderer, palette, sidebar and text proportions."""
    x0, y0, x1, y1 = box
    sx, sy = (x1 - x0) / 1280, (y1 - y0) / 800
    def b(a, c, d, e):
        return x0 + a * sx, y0 + c * sy, x0 + d * sx, y0 + e * sy
    colors = theme["colors"]
    capture, _image = home_capture()
    def rect(bounds, color):ui.draw_logical_rect(*b(*bounds), color)
    def line(a, c, d, e, color, width=1):ui.draw_logical_line(*b(a, c, d, e), color, width)
    def text(x, y, value, color, size=20, anchor="cm", width=None):
        _text(ui, cache, x0 + x * sx, y0 + y * sy, value, color,
              max(7, size * sx * theme["text_scale_percent"] / 100), anchor,
              width * sx if width else None)
    left = theme["sidebar"] == "left"
    rail = (0, 256) if left else (1024, 1280)
    screen = (256, 1280) if left else (0, 1024)
    rx = (rail[0] + rail[1]) / 2
    rect((0, 0, 1280, 800), colors["background"])
    rect((rail[0], 0, rail[1], 800), colors["sidebar"])
    text(rx, 55, capture["frequency_label"], colors["frequency"], 38, width=240)
    text(rx, 97, capture["band_mode"], colors["secondary_text"], 19, width=240)
    meter = METER_STYLES[theme["smeter_style"]]
    mh = meter.height
    ui.draw_selected_smeter(cache, b(rail[0] + 10, 120, rail[1] - 10, 120 + mh),
                            capture["signal_dbm"], None, theme=theme, style_id=theme["smeter_style"])
    # Preserve Home's actual instrument order and compact/tall-meter spacing.
    mode_y = 120 + mh + 18
    for index, caption in enumerate(("AM", "SAM", "DRM", "LSB", "USB", "CW", "FM", "IQ")):
        bx, by = rail[0] + 10 + (index % 4) * 60, mode_y + (index // 4) * 40
        ui.draw_logical_rounded_rect(*b(bx, by, bx + 56, by + 32), theme["radius"] * sx,
                                     colors["surface"], colors["border"])
        text(bx + 28, by + 16, caption, colors["text"], 17)
    if mh == 80:
        text(rail[0] + 14, 318, "BANDPASS", colors["section_heading"], 16, "lm")
        text(rail[1] - 14, 318, capture["bandwidth_label"], colors["text"], 17, "rm")
        rect((rail[0] + 90, 337, rail[1] - 90, 372), colors["home_passband_fill"])
        line(rail[0] + 24, 372, rail[1] - 24, 372, colors["home_passband_border"])
        line(rx, 333, rx, 374, colors["home_passband_center"])
    volume_y = max(408, mode_y + 84)
    text(rail[0] + 14, volume_y, "VOLUME", colors["secondary_text"], 17, "lm")
    text(rail[1] - 14, volume_y, str(capture["volume_percent"]) + "%", colors["text"], 17, "rm")
    fill_end = rail[0] + 60 + (rail[1] - rail[0] - 80) * capture["volume_percent"] / 100
    rect((rail[0] + 60, volume_y + 31, rail[1] - 20, volume_y + 38), colors["slider_track"])
    rect((rail[0] + 60, volume_y + 31, fill_end, volume_y + 38), colors["slider_fill"])
    rect((fill_end - 5, volume_y + 25, fill_end + 5, volume_y + 44), colors["slider_thumb"])
    for index, (kind, caption) in enumerate(ui.MENU_ITEMS):
        bx, by = rail[0] + 10 + (index % 2) * 122, 488 + (index // 2) * 78
        bounds = b(bx, by, bx + 114, by + 70)
        ui.draw_logical_rounded_rect(*bounds, theme["radius"] * sx,
                                     colors["surface"], colors["border"])
        text(bx + 57, by + 27, caption, colors["text"], 19, width=106)
        text(bx + 57, by + 52, ui.menu_subtitle(kind), colors["secondary_text"], 15, width=106)
    a, z = screen
    _captured_frontend(ui, cache, theme, b(a, 0, z, 800))


def _preview(ui, cache, editor):
    theme = editor.preview
    _text(ui, cache, 24, 122, "PREVIEW" if editor.dirty else "CURRENT LOOK", ACCENT, 14)
    _text(ui, cache, 628, 122, "Not applied yet" if editor.dirty else "Saved settings", MUTED, 13, "rm")
    if editor.tab == "meters":
        style = METER_STYLES[theme["smeter_style"]]
        _text(ui, cache, 326, 186, style.name, TEXT, 22, "cm", 580)
        w = min(556, 334 * 236 / style.height)
        h = w * style.height / 236
        y = 260 + (290 - h) / 2
        ui.draw_selected_smeter(cache, (326 - w / 2, y, 326 + w / 2, y + h),
                                -89 + 25 * math.sin(time.monotonic() * .7), -63,
                                theme=theme, style_id=theme["smeter_style"])
        _text(ui, cache, 326, 600, "Meter choice is separate from your theme", MUTED, 15, "cm", 570)
        _text(ui, cache, 326, 630, "Choose any meter to preview it here.", MUTED, 14, "cm")
    else:
        _home(ui, cache, theme, PREVIEW_BOX)
        _text(ui, cache, 24, 584, theme["name"], TEXT, 24, width=600)
        _text(ui, cache, 24, 619, "S-meter: " + METER_STYLES[theme["smeter_style"]].name,
              MUTED, 14, width=600)
        _text(ui, cache, 24, 656, "Your captured SDR screen with this theme.", MUTED, 13)


def _pages(ui, cache, boxes, prefix, page, count):
    _button(ui, cache, boxes[prefix + "_previous"], "PREVIOUS", enabled=page > 0)
    _button(ui, cache, boxes[prefix + "_next"], "NEXT", enabled=page + 1 < count)
    _text(ui, cache, 958, 684, f"{page + 1} / {count}", MUTED, 14, "cm")


def _gallery(ui, cache, editor, boxes):
    if editor.tab == "themes":
        _text(ui, cache, 660, 122, "CHOOSE A THEME", MUTED, 14)
        items = editor.themes[editor.page * 6:editor.page * 6 + 6]
        for item in items:
            box = boxes["theme:" + item["id"]]
            active = item["id"] == editor.selected_id
            colors = item["colors"]
            ui.draw_logical_rounded_rect(*box, 8, colors["background"], ACCENT if active else BORDER)
            _text(ui, cache, box[0] + 20, box[1] + 54, item["name"], colors["text"], 22, width=252)
            _text(ui, cache, box[0] + 20, box[1] + 100,
                  "Selected" if active else "Tap to preview", colors["secondary_text"], 14, width=252)
            if active:
                ui.draw_logical_circle(box[2] - 16, box[1] + 18, 3, ACCENT)
        _pages(ui, cache, boxes, "theme", editor.page, editor.page_count)
    else:
        _text(ui, cache, 660, 122, "CHOOSE AN S-METER", MUTED, 14)
        for name, label in METER_FILTERS:
            _button(ui, cache, boxes["filter:" + name], label, active=editor.meter_filter == name)
        for identifier in editor.meter_ids[editor.meter_page * 6:editor.meter_page * 6 + 6]:
            box = boxes["meter:" + identifier]
            active = identifier == editor.draft["smeter_style"]
            # Retain the user's borderless faces and callsign attribution.
            ui.draw_logical_rect(*box, BG)
            _text(ui, cache, (box[0] + box[2]) / 2, box[1] + 16, METER_STYLES[identifier].name,
                  ACCENT if active else TEXT, 12, "cm", box[2] - box[0] - 28)
            if active:
                ui.draw_logical_circle(box[0] + 7, box[1] + 16, 3, ACCENT)
            style = METER_STYLES[identifier]
            available_h = box[3] - box[1] - 34
            width = min(box[2] - box[0], available_h * 236 / style.height)
            height = width * style.height / 236
            x = (box[0] + box[2] - width) / 2
            y = box[1] + 34
            ui.draw_selected_smeter(cache, (x, y, x + width, y + height), -85, -73,
                                    theme=editor.preview, style_id=identifier)
        _pages(ui, cache, boxes, "meter", editor.meter_page, editor.meter_page_count)


def _customize(ui, cache, editor, boxes):
    theme = editor.preview
    if editor.colors_open:
        _button(ui, cache, boxes["appearance"], "APPEARANCE")
        _text(ui, cache, 1256, 138, "EDIT COLORS", MUTED, 14, "rm")
        _button(ui, cache, boxes["group_previous"], "‹")
        _button(ui, cache, boxes["group_next"], "›")
        _text(ui, cache, 958, 212, COLOR_GROUPS[editor.color_group][0], TEXT, 20, "cm")
        for name, box in boxes.items():
            if name.startswith("part:"):
                key = editor.family_keys[int(name.split(":")[1])]
                _button(ui, cache, box, key.replace("_", " ").upper(), active=key == editor.color_key)
        count = (len(editor.family_keys) + 3) // 4
        _button(ui, cache, boxes["part_previous"], "PREVIOUS", enabled=editor.part_page > 0)
        _button(ui, cache, boxes["part_next"], "NEXT", enabled=editor.part_page + 1 < count)
        _text(ui, cache, 958, 418, f"{editor.part_page + 1} / {count}", MUTED, 13, "cm")
        _text(ui, cache, 660, 454, "HUE", MUTED, 12)
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
    _text(ui, cache, 660, 126, "NAME  ·  OPTIONAL", MUTED, 14)
    _button(ui, cache, boxes["theme_name"], theme["name"] + "  ·  RENAME")
    for row, label in enumerate(("SIDEBAR", "CORNERS", "TEXT SIZE", "UNITS")):
        _text(ui, cache, 660, 276 + row * 72, label, MUTED, 14)
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
    _text(ui, cache, 24, 42, "THEMES", TEXT, 28)
    _text(ui, cache, 24, 76, "Choose. Preview. Apply.", MUTED, 15)
    for tab, label in (("themes", "THEMES"), ("meters", "S-METERS"), ("customize", "CUSTOMIZE")):
        _button(ui, cache, boxes[f"tab:{tab}"], label, active=editor.tab == tab)
    ui.draw_logical_line(644, 112, 644, 704, BORDER, 1)
    _preview(ui, cache, editor)
    if editor.tab in ("themes", "meters"):
        _gallery(ui, cache, editor, boxes)
    else:
        _customize(ui, cache, editor, boxes)
    ui.draw_logical_line(24, 718, 1256, 718, BORDER, 1)
    _button(ui, cache, BACK_BOX, "CANCEL")
    _button(ui, cache, APPLY_BOX, "APPLY & HOME", primary=True)
    summary = editor.error or ("Nothing changes until you apply." if not editor.dirty else "Preview ready · apply to save and return Home.")
    _text(ui, cache, 222, 760, summary, ERROR if editor.error else MUTED, 14, width=740)
    if editor.overlay:
        _overlay(ui, cache, editor)
