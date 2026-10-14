"""Calibrated vector faces, original Flexible skins, and shared needle geometry.

Drawing callbacks keep geometry independent of OpenGL. Original skin images
and their calibration points have provenance in assets/smeters/flexible/SOURCE.md.
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class MeterStyle:
    name: str
    kind: str
    height: int
    face: tuple
    ink: tuple
    metal: tuple
    needle: tuple
    start: float = -55
    sweep: float = 110
    skin: str = ""
    scales: tuple = ("S",)


METER_STYLES = {
    "flex_dx": MeterStyle("FLEX · DX101", "skin", 160, (0, 0, 0), (216, 225, 248), (62, 69, 78), (255, 48, 35), skin="flex_dx", scales=("S", "ARTWORK")),
    "flex_icom": MeterStyle("FLEX · ICOM", "skin", 160, (0, 0, 0), (228, 235, 239), (50, 60, 65), (255, 255, 255), skin="flex_icom", scales=("S", "ARTWORK")),
    "flex_orange": MeterStyle("FLEX · ORANGE", "skin", 160, (255, 154, 0), (28, 17, 8), (140, 82, 16), (255, 48, 35), skin="flex_orange", scales=("S", "ARTWORK")),
    "triple_black": MeterStyle("OBSIDIAN · RF LAB", "triple", 190, (10, 17, 22), (211, 230, 230), (60, 72, 80), (255, 82, 53), -31, 62, scales=("S", "dBm", "µV")),
    "triple_amber": MeterStyle("AMBER · RF LAB", "triple", 190, (27, 18, 10), (255, 191, 85), (117, 89, 43), (255, 224, 159), -31, 62, scales=("S", "dBm", "µV")),
    "triple_copper": MeterStyle("COPPER · RF LAB", "triple", 190, (183, 81, 20), (35, 23, 13), (95, 58, 32), (39, 23, 14), -31, 62, scales=("S", "dBm", "µV")),
    "flex_dark": MeterStyle("FLEX · DARK", "skin", 160, (12, 30, 39), (222, 235, 237), (55, 75, 86), (255, 48, 35), skin="flex_dark", scales=("S", "ARTWORK")),
    "flex_neon": MeterStyle("FLEX · NEON", "skin", 160, (0, 0, 0), (72, 214, 255), (53, 74, 94), (57, 255, 20), skin="flex_neon"),
    "led": MeterStyle("LED BAR", "led", 80, (8, 13, 17), (203, 226, 232), (48, 57, 64), (96, 221, 249)),
    "linear": MeterStyle("SLIDING POINTER", "linear", 80, (13, 20, 25), (204, 225, 230), (58, 69, 77), (255, 188, 79)),
    "classic": MeterStyle("CLASSIC IVORY", "radial", 160, (232, 223, 198), (45, 43, 38), (89, 92, 86), (155, 39, 28)),
    "precision": MeterStyle("PRECISION DARK", "radial", 160, (13, 22, 28), (212, 228, 229), (62, 77, 86), (255, 174, 61)),
    "aviation": MeterStyle("AVIATION BLACK", "round", 210, (10, 14, 15), (220, 231, 210), (56, 63, 66), (235, 239, 219), -130, 260),
    "heritage": MeterStyle("AVIATION BRASS", "round", 210, (26, 25, 19), (236, 217, 165), (137, 113, 67), (255, 237, 187), -130, 260),
}
DEFAULT_METER_STYLE = "led"
SCALE_LABELS = ((-121, "1"), (-109, "3"), (-97, "5"), (-85, "7"),
                (-73, "9"), (-53, "+20"), (-33, "+40"))
SKIN_ASSET_DIR = Path(__file__).parent / "assets" / "smeters" / "flexible"
SKIN_CALIBRATION = json.loads((SKIN_ASSET_DIR / "calibration.json").read_text(encoding="utf-8"))


def dbm_to_microvolts(dbm):
    """RMS voltage across a 50-ohm receiver input, derived from measured dBm."""
    if not isinstance(dbm, (int, float)) or not math.isfinite(dbm):
        return None
    return math.sqrt(.001 * 50) * 10 ** (max(-300, min(100, dbm)) / 20) * 1e6


def voltage_label(dbm):
    voltage = dbm_to_microvolts(dbm)
    if voltage is None:
        return "— µV"
    return f"{voltage / 1000:.2f} mV" if voltage >= 1000 else f"{float(f'{voltage:.2g}'):g} µV"


def s_label(dbm):
    if not isinstance(dbm, (int, float)) or not math.isfinite(dbm):
        return "S—"
    return f"S{max(0, min(9, round((dbm + 127) / 6)))}" if dbm <= -73 else f"S9+{round(dbm + 73)}"


def skin_tip(style_id, dbm):
    """Interpolate the skin author's S0..S9,+10..+60 calibration points."""
    skin = SKIN_CALIBRATION[style_id]
    levels, points = skin["dbm"], skin["points"]
    value = dbm if isinstance(dbm, (int, float)) and math.isfinite(dbm) else levels[0]
    if value <= levels[0]:
        return tuple(points[0])
    for index in range(1, len(levels)):
        if value <= levels[index]:
            fraction = (value - levels[index - 1]) / (levels[index] - levels[index - 1])
            return tuple(a + (b - a) * fraction for a, b in zip(points[index - 1], points[index]))
    return tuple(points[-1])


def skin_image_box(style_id, box):
    """Use the full face width and whole pixels, retaining its aspect ratio."""
    x0, y0, x1, y1 = box
    width, height = SKIN_CALIBRATION[style_id]["size"]
    body_height = max(1, round((y1 - y0) * .86))
    scale = min((x1 - x0) / width, body_height / height)
    face_width, face_height = max(1, round(width * scale)), max(1, round(height * scale))
    left = round(x0 + (x1 - x0 - face_width) / 2)
    top = round(y0 + (body_height - face_height) / 2)
    return left, top, left + face_width, top + face_height


def skin_needle_segment(style_id, box, dbm):
    skin = SKIN_CALIBRATION[style_id]
    left, top, right, bottom = skin_image_box(style_id, box)
    scale_x = (right - left) / skin["size"][0]
    scale_y = (bottom - top) / skin["size"][1]
    px, py = skin["pivot"]
    tx, ty = skin_tip(style_id, dbm)
    # Conceal the pivot beneath the bitmap, ending before the RF readouts.
    # The original calibration tip retains its exact position on the artwork.
    clip_y = min(skin["size"][1], (box[1] + (box[3] - box[1]) * .80 - top) / scale_y)
    clip_y = max(ty, clip_y)
    if py > clip_y:
        fraction = (clip_y - ty) / (py - ty)
        px, py = tx + (px - tx) * fraction, clip_y
    return (left + px * scale_x, top + py * scale_y,
            left + tx * scale_x, top + ty * scale_y)


def draw_triple_meter(style_id, box, dbm, peak_dbm, *, rect, line, circle, text,
                      face=True, dynamic=True):
    """A layered three-scale RF instrument; its static face can be cached."""
    style = METER_STYLES[style_id]
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    unit = min(w / 236, h / 190)
    def xy(x, y):
        return x0 + x * w / 236, y0 + y * h / 190
    def stroke(a, b, color, width=1):
        line(*xy(*a), *xy(*b), color, max(.7, width * unit))
    def fill(a, b, color):
        rect(*xy(*a), *xy(*b), color)
    def label(x, y, content, color=None, size=10, anchor="cm"):
        text(*xy(x, y), content, color or style.ink, max(6, round(size * unit)), anchor)
    pivot = (118, 230)
    def point(db, radius):
        return needle_point(style, db, pivot, radius)
    secondary = (130, 198, 210) if style_id == "triple_black" else (
        (204, 149, 77) if style_id == "triple_amber" else (74, 32, 13))
    voltage_ink = (127, 203, 156) if style_id == "triple_black" else secondary
    hot = (255, 92, 61) if style_id != "triple_copper" else (98, 20, 12)
    if face:
        fill((0, 0), (236, 190), (9, 12, 15))
        # Brushed metal bezel and illuminated face use continuous shading,
        # baked once into a supersampled texture in the production renderer.
        for row in range(190):
            shine = .58 + .36 * math.exp(-((row - 16) / 50) ** 2)
            color = tuple(round(c * shine) for c in style.metal)
            fill((2, row + 2), (234, min(188, row + 3)), color)
        for row in range(6, 185):
            glow = .86 + .27 * math.exp(-((row - 70) / 75) ** 2)
            color = tuple(min(255, round(c * glow)) for c in style.face)
            fill((7, row), (229, row + 1), color)
        stroke((8, 7), (228, 7), tuple(min(255, c + 23) for c in style.metal))
        label(16, 16, "RF", size=10, anchor="lm")
        label(220, 16, "50 Ω", color=secondary, size=9, anchor="rm")
        for radius, ink in ((190, style.ink), (151, secondary), (111, voltage_ink)):
            previous = None
            for index in range(101):
                angle = math.radians(style.start + style.sweep * index / 100)
                p = (pivot[0] + math.sin(angle) * radius, pivot[1] - math.cos(angle) * radius)
                if previous:
                    stroke(previous, p, hot if radius == 190 and index / 100 > meter_fraction(-73) else ink, 1.1)
                previous = p
            for db in (*range(-121, -72, 3), *range(-68, -32, 5)):
                major = db in (-121, -109, -97, -85, -73, -53, -33)
                stroke(point(db, radius), point(db, radius - (7 if major else 3.5)), ink, 1.1 if major else .6)
        for db, content in SCALE_LABELS:
            label(*point(db, 202), content, color=hot if db > -73 else style.ink, size=11)
        for db in (-120, -100, -80, -60, -40):
            label(*point(db, 163), str(db), color=secondary, size=9)
        for db in (-121, -109, -97, -85, -73, -53, -33):
            voltage = dbm_to_microvolts(db)
            content = f"{voltage / 1000:.0f}k" if voltage >= 1000 else f"{float(f'{voltage:.2g}'):g}"
            label(*point(db, 124), content, color=voltage_ink, size=8)
        # Compact units key keeps each coloured scale explicit.
        label(24, 83, "S", size=9)
        label(31, 118, "dBm", color=secondary, size=8)
        label(48, 143, "µV", color=voltage_ink, size=8)
        fill((12, 154), (224, 182), tuple(max(0, c - 4) for c in style.face))
        stroke((12, 153), (224, 153), style.metal, .8)
        for x, content, color in ((42, "S / dB", style.ink), (118, "dBm", secondary), (194, "µV RMS", voltage_ink)):
            label(x, 161, content, color=color, size=8)
        for xx in (4.5, 231.5):
            for yy in (4.5, 185.5):
                circle(*xy(xx, yy), 1.5 * unit, style.metal)
    if dynamic:
        value = dbm if isinstance(dbm, (int, float)) and math.isfinite(dbm) else -121
        tip = point(value, 183)
        # The concealed pivot sits beneath all three concentric scales.
        fraction = (147 - tip[1]) / (pivot[1] - tip[1])
        stem = (tip[0] + (pivot[0] - tip[0]) * fraction, 147)
        stroke((stem[0] + .8, stem[1]), (tip[0] + .8, tip[1]), (0, 0, 0, 100), 2)
        stroke(stem, tip, style.needle, 1.2)
        if isinstance(peak_dbm, (int, float)) and math.isfinite(peak_dbm) and peak_dbm > value + .75:
            stroke(point(peak_dbm, 184), point(peak_dbm, 194), hot, 1.5)
        missing = dbm_to_microvolts(dbm) is None
        label(42, 173, s_label(dbm), size=10)
        label(118, 173, "—" if missing else f"{dbm:.0f}", color=secondary, size=11)
        label(194, 173, "—" if missing else f"{float(f'{dbm_to_microvolts(dbm):.3g}'):g}", color=voltage_ink, size=10)


def normalize_meter_style(value):
    return value if isinstance(value, str) and value in METER_STYLES else DEFAULT_METER_STYLE


def meter_fraction(dbm):
    """Match the receiver's 36-segment scale: S1=-121, S9=-73 dBm."""
    if not isinstance(dbm, (int, float)) or not math.isfinite(dbm):
        return 0.0
    dbm = max(-121.0, min(-33.0, dbm))
    if dbm <= -73:
        segments = (dbm + 121) / 48 * 22
    elif dbm <= -53:
        segments = 22 + (dbm + 73) / 20 * 6
    else:
        segments = 28 + (dbm + 53) / 20 * 8
    return segments / 36


def needle_point(style, dbm, pivot, radius):
    """Face geometry and signal calibration determine the needle endpoint."""
    angle = math.radians(style.start + style.sweep * meter_fraction(dbm))
    return pivot[0] + math.sin(angle) * radius, pivot[1] - math.cos(angle) * radius


def draw_meter(style_id, box, dbm, peak_dbm, *, rect, line, circle, text, palette):
    style = METER_STYLES[normalize_meter_style(style_id)]
    if style.kind == "triple":
        return draw_triple_meter(style_id, box, dbm, peak_dbm,
                                 rect=rect, line=line, circle=circle, text=text)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if style.kind in ("radial", "round"):
        # Preserve each physical housing's proportions in wide preview slots.
        face_width = min(w, h * 236 / style.height)
        face_height = min(h, w * style.height / 236)
        x0 += (w - face_width) / 2
        y0 += (h - face_height) / 2
        w, h = face_width, face_height
        x1, y1 = x0 + w, y0 + h
        box = (x0, y0, x1, y1)
    unit = min(w / 236, h / style.height)
    missing = not isinstance(dbm, (int, float)) or not math.isfinite(dbm)
    value = -121 if missing else dbm
    hot = (191, 51, 40) if style_id == "classic" else (244, 104, 89)
    ink = style.ink
    # Compact instruments follow the theme; physical analog faces retain their
    # material colours, like a radio's cream dial or a cockpit's black gauge.
    if style.kind in ("led", "linear"):
        ink = tuple(palette["smeter_scale"][:3])
    def label(x, y, content, size=12, color=None, anchor="cm"):
        text(x, y, content, color or ink, max(7, round(size * unit)), anchor)
    def frame(bounds, color):
        a, b, c, d = bounds
        rect(a, b, c, d, color)
        line(a, b, c, b, (155, 163, 160), max(1, unit))
        line(a, d, c, d, (18, 23, 26), max(1, unit))
    frame(box, style.metal)
    inset = max(2, 5 * unit)
    rect(x0 + inset / 2, y0 + inset / 2, x1 - inset / 2, y1 - inset / 2,
         tuple(round(channel * .64) for channel in style.metal))
    rect(x0 + inset, y0 + inset, x1 - inset, y1 - inset, style.face)
    level = meter_fraction(value)
    readout = "— dBm" if missing else f"{value:.0f} dBm"

    if style.kind in ("led", "linear"):
        label(x0 + 10 * unit, y0 + h * .17, "S-METER", 12, anchor="lm")
        label(x1 - 10 * unit, y0 + h * .17, readout, 12, palette["smeter_dbm"], "rm")
        a, b, cy = x0 + 14 * unit, x1 - 14 * unit, y0 + h * .55
        if style.kind == "led":
            for index in range(36):
                left = a + (b - a) * index / 36
                color = palette["meter_on"] if index < 28 else palette["meter_hot"]
                rect(left + unit, cy - h * .15, left + (b - a) / 36 - unit,
                     cy + h * .15, color if index + .5 <= level * 36 else palette["meter_off"])
        else:
            line(a, cy, b, cy, palette["smeter_rail"], max(2, 3 * unit))
            for index in range(37):
                xx = a + (b - a) * index / 36
                length = h * (.16 if index % 2 == 0 else .08)
                line(xx, cy - length, xx, cy + length, ink, max(1, unit))
            xx = a + (b - a) * level
            line(xx, cy - h * .26, xx, cy + h * .22, style.needle, max(2, 3 * unit))
            line(xx - 4 * unit, cy - h * .26, xx + 4 * unit, cy - h * .26, style.needle, max(2, 3 * unit))
        if peak_dbm is not None and math.isfinite(peak_dbm) and peak_dbm > value + .75:
            xx = a + (b - a) * meter_fraction(peak_dbm)
            line(xx, cy - h * .18, xx, cy + h * .18, palette["smeter_peak"], max(1, unit))
        for db, content in SCALE_LABELS:
            label(a + (b - a) * meter_fraction(db), y0 + h * .86,
                  "S" + content if content == "1" else content, 10,
                  palette["smeter_hot"] if db > -73 else ink)
        return

    if style.kind == "round":
        pivot = ((x0 + x1) / 2, y0 + h * .49)
        radius = min(w * .40, h * .43)
        circle(*pivot, radius + 7 * unit, (7, 9, 10))
        circle(*pivot, radius + 4 * unit, style.metal, outline=True, width=max(1, 2 * unit))
        circle(*pivot, radius, style.face)
        for xx in (x0 + 12 * unit, x1 - 12 * unit):
            for yy in (y0 + 12 * unit, y1 - 12 * unit):
                circle(xx, yy, 3 * unit, (157, 164, 157))
                line(xx - 2 * unit, yy + unit, xx + 2 * unit, yy - unit, (32, 37, 38), max(1, unit))
        label(pivot[0], pivot[1] + radius * .43, "SIGNAL", 11)
        label(pivot[0], pivot[1] + radius * .63, "S / dB", 9)
        label(pivot[0], y1 - h * .065, readout, 13)
    else:
        pivot = ((x0 + x1) / 2, y0 + h * .88)
        radius = min(w * .53, h * .72)
        label(pivot[0], y0 + h * .10, "SIGNAL STRENGTH", 10)
        label(x0 + w * .13, y0 + h * .82, "S / dB", 10)
        label(x1 - w * .04, y0 + h * .82, readout, 12, anchor="rm")
    # A shared angular scale and needle use exactly the same calibrated map.
    previous = None
    for index in range(73):
        angle = math.radians(style.start + style.sweep * index / 72)
        point = (pivot[0] + math.sin(angle) * radius, pivot[1] - math.cos(angle) * radius)
        if previous:
            line(*previous, *point, hot if index / 72 > meter_fraction(-73) else ink, max(1, unit))
        previous = point
    for db in (*range(-121, -72, 6), -63, -53, -43, -33):
        tip = needle_point(style, db, pivot, radius)
        base = needle_point(style, db, pivot, radius * .90)
        line(*base, *tip, hot if db > -73 else ink, max(1, 1.5 * unit))
    for db, content in SCALE_LABELS:
        xx, yy = needle_point(style, db, pivot, radius * .76)
        label(xx, yy, content, 12, hot if db > -73 else ink)
    if peak_dbm is not None and math.isfinite(peak_dbm) and peak_dbm > value + .75:
        line(*needle_point(style, peak_dbm, pivot, radius * .92),
             *needle_point(style, peak_dbm, pivot, radius * 1.02), hot, max(1, 2 * unit))
    tip = needle_point(style, value, pivot, radius * .91)
    # Restrained offset shadow gives the pointer depth without hiding the scale.
    line(pivot[0] + unit, pivot[1] + unit, tip[0] + unit, tip[1] + unit,
         (0, 0, 0, 80), max(2, 3 * unit))
    line(*pivot, *tip, style.needle, max(1.5, 2 * unit))
    circle(*pivot, 5 * unit, style.metal)
    circle(*pivot, 2 * unit, style.needle)
