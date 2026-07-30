#!/usr/bin/env python3
import argparse
import math
import mmap
import struct
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
WATERFALL = ROOT / "assets" / "waterfall-texture.png"
SYS = Path("/sys/class/graphics/fb0")
FB = Path("/dev/fb0")
LW, LH = 960, 320
ACTIVE_H = 400
TOP_H = 66
RULER_H = 24
DEFAULT_FREQ_KHZ = 7032.5
DEFAULT_SPAN_KHZ = 64.0
RULER_MAJOR_STEPS_HZ = (
    100,
    200,
    500,
    1_000,
    2_000,
    5_000,
    10_000,
    20_000,
    50_000,
    100_000,
    200_000,
    500_000,
    1_000_000,
)


def format_freq(freq_khz):
    hz = int(round(freq_khz * 1000))
    mhz = hz // 1_000_000
    khz = (hz // 1000) % 1000
    rem_hz = hz % 1000
    return f"{mhz}.{khz:03d}.{rem_hz:03d}"


@lru_cache(maxsize=64)
def font(size, bold=False, mono=False):
    names = []
    if mono:
        names = [
            "JetBrainsMono-Bold.ttf" if bold else "JetBrainsMono-Regular.ttf",
            "Menlo.ttc",
            "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf",
        ]
    else:
        names = [
            "Avenir Next.ttc",
            "Helvetica.ttc",
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        ]

    bases = (
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/local/share/fonts"),
    )
    for base in bases:
        for name in names:
            path = base / name
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size)
                except OSError:
                    continue
    return ImageFont.load_default()


def text_box(draw, xy, text, fill, size=12, bold=False, mono=False, anchor=None):
    draw.text(xy, text, fill=fill, font=font(size, bold=bold, mono=mono), anchor=anchor)


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def glow_line(img, points, fill, width=2, blur=5):
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line(points, fill=fill, width=width + 3)
    glow = glow.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(glow)
    ImageDraw.Draw(img).line(points, fill=fill, width=width)


def prepare_waterfall():
    src = Image.open(WATERFALL).convert("RGB")
    return ImageOps.fit(src, (LW, LH - TOP_H), method=Image.Resampling.LANCZOS, centering=(0.52, 0.42)).convert("RGBA")


def draw_button(draw, box, label, active=False):
    fill = (15, 22, 31, 235) if not active else (16, 61, 54, 255)
    outline = (52, 67, 80, 255) if not active else (62, 246, 185, 255)
    text = (170, 184, 199, 255) if not active else (215, 255, 243, 255)
    rounded(draw, box, 6, fill, outline, 1)
    text_box(draw, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), label, text, 14, True, anchor="mm")


def draw_slider(draw, x, y, w, value):
    rounded(draw, (x, y, x + w, y + 9), 4, (25, 32, 42, 255), (50, 63, 76, 255), 1)
    fill_w = int((w - 4) * value)
    rounded(draw, (x + 2, y + 2, x + 2 + fill_w, y + 7), 3, (66, 237, 174, 255))
    knob_x = x + 2 + fill_w
    draw.ellipse((knob_x - 5, y - 3, knob_x + 5, y + 12), fill=(237, 255, 248, 255), outline=(52, 237, 174, 255), width=1)


def draw_top_panel(img, freq_khz=DEFAULT_FREQ_KHZ, smeter_dbm=-45.0):
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, LW, TOP_H), fill=(5, 9, 14, 252))

    text_box(draw, (16, 18), "KIWI SDR", (235, 245, 250, 255), 20, True)
    draw.ellipse((111, 12, 124, 25), fill=(79, 255, 145, 255))
    text_box(draw, (16, 45), "RX-02  40m", (104, 229, 188, 255), 13, True, mono=True)

    modes = (
        ("SSB", 150, 18, True),
        ("DIG", 150, 47, False),
    )
    for label, x, y, active in modes:
        rounded(
            draw,
            (x - 8, y - 15, x + 48, y + 7),
            5,
            (18, 72, 62, 255) if active else (18, 26, 35, 245),
        )
        text_box(
            draw,
            (x, y),
            label,
            (226, 255, 246, 255) if active else (157, 174, 188, 255),
            15,
            True,
            mono=True,
            anchor="lm",
        )

    text_box(draw, (248, 39), format_freq(freq_khz), (242, 249, 252, 255), 47, True, mono=True, anchor="lm")

    text_box(draw, (560, 20), "STEP", (128, 143, 156, 255), 11, True)
    text_box(draw, (560, 50), "100 Hz", (226, 236, 244, 255), 18, True, mono=True, anchor="lm")

    meter_x0 = 654
    bar_w = 8
    bar_gap = 3
    segment_count = 24
    meter_x1 = meter_x0 + segment_count * bar_w + (segment_count - 1) * bar_gap
    green = (222, 255, 228, 255)
    red = (255, 32, 48, 255)
    rail = (220, 238, 232, 255)
    gray_tick = (65, 75, 70, 255)
    blue = (0, 95, 255, 255)

    scale_marks = (
        ("S", -121, green, 14),
        ("1", -121, green, 14),
        ("3", -109, green, 14),
        ("5", -97, green, 14),
        ("7", -85, green, 14),
        ("9", -73, green, 14),
        ("+20", -53, red, 13),
        ("+40", -33, red, 13),
        ("+60", -13, red, 13),
    )

    def dbx(dbm):
        return meter_x0 + round((meter_x1 - meter_x0) * ((dbm + 121) / 108))

    labels = (
        ("S", dbx(-121) - 30, green, 14),
        ("1", dbx(-121), green, 14),
        ("3", dbx(-109), green, 14),
        ("5", dbx(-97), green, 14),
        ("7", dbx(-85), green, 14),
        ("9", dbx(-73), green, 14),
        ("+20", dbx(-53), red, 13),
        ("+40", dbx(-33), red, 13),
        ("+60", dbx(-13) - 8, red, 13),
    )
    for text, x, color, size in labels:
        text_box(draw, (x, 17), text, color, size, True, mono=True, anchor="mm")

    # KiwiSDR/HF S-meter scale: S9=-73 dBm, 6 dB per S-unit below,
    # then dB-over-S9 above. Only major ticks are shown.
    top_rail_y = 30
    for text, dbm, color, _size in scale_marks:
        if text == "S":
            continue
        x = dbx(dbm)
        draw.line((x, top_rail_y, x, top_rail_y + 6), fill=color if color == red else rail, width=1)

    # Active level: the fill bars sit below the scale ticks and align to the
    # same 24-segment math.
    active_bars = max(0, min(segment_count, int(round((smeter_dbm + 121) / 108 * segment_count))))
    bar_y0, bar_y1 = 41, 53
    for i in range(active_bars):
        x = meter_x0 + i * (bar_w + bar_gap)
        bar_mid_dbm = -121 + 108 * ((i + 0.5) / segment_count)
        fill = red if bar_mid_dbm >= -73 else blue
        draw.rectangle((x, bar_y0, x + bar_w, bar_y1), fill=fill)

    rail_y = 55
    draw.line((meter_x0, rail_y, meter_x1, rail_y), fill=rail, width=1)


def ruler_major_step_hz(span_khz):
    target_px = 150
    wanted_hz = max(1, int(round(span_khz * 1000 * target_px / LW)))
    for step in RULER_MAJOR_STEPS_HZ:
        if step >= wanted_hz:
            return step
    return RULER_MAJOR_STEPS_HZ[-1]


def format_ruler_label(hz, major_step_hz):
    decimals = 4 if major_step_hz < 1_000 else 3
    return f"{hz / 1_000_000:.{decimals}f}"


def draw_ruler(draw, center_khz=DEFAULT_FREQ_KHZ, span_khz=DEFAULT_SPAN_KHZ):
    y0 = TOP_H
    draw.rectangle((0, y0, LW, y0 + RULER_H), fill=(10, 15, 21, 185))
    span_hz = max(1, int(round(span_khz * 1000)))
    center_hz = int(round(center_khz * 1000))
    start_hz = center_hz - span_hz // 2
    end_hz = center_hz + span_hz // 2
    hz_per_px = span_hz / LW

    major_step_hz = ruler_major_step_hz(span_khz)
    minor_step_hz = max(50, major_step_hz // 5)
    minor_start_hz = int(math.ceil(start_hz / minor_step_hz) * minor_step_hz)
    major_start_hz = int(math.ceil(start_hz / major_step_hz) * major_step_hz)

    tick_color = (196, 210, 216, 255)
    minor_color = (142, 158, 166, 215)
    label_color = (231, 240, 244, 255)
    tick_top = y0 + 2

    hz = minor_start_hz
    while hz <= end_hz:
        if hz % major_step_hz:
            x = int(round((hz - start_hz) / hz_per_px))
            if 0 <= x < LW:
                draw.line((x, tick_top, x, tick_top + 3), fill=minor_color, width=1)
        hz += minor_step_hz

    label_font = font(15, bold=True, mono=True)
    last_label_right = -999
    hz = major_start_hz
    while hz <= end_hz:
        x = int(round((hz - start_hz) / hz_per_px))
        if 0 <= x < LW:
            draw.line((x, tick_top, x, tick_top + 6), fill=tick_color, width=2)
            label = format_ruler_label(hz, major_step_hz)
            bbox = draw.textbbox((x, y0 + 18), label, font=label_font, anchor="mm")
            if bbox[0] >= 0 and bbox[2] <= LW and bbox[0] > last_label_right + 10:
                draw.text((x, y0 + 18), label, fill=label_color, font=label_font, anchor="mm")
                last_label_right = bbox[2]
        hz += major_step_hz


def draw_spectrum_overlay(img):
    draw = ImageDraw.Draw(img)
    tags = [
        (58, "FT8"), (181, "AM"), (356, "FAX"), (715, "BC"), (844, "DATA")
    ]
    for x, label in tags:
        y = TOP_H + RULER_H + 16
        draw.line((x, TOP_H + RULER_H, x, y - 3), fill=(154, 178, 187, 180), width=1)
        text_box(draw, (x, y), label, (225, 238, 243, 255), 11, True, mono=True, anchor="mm")


def draw_lower_hud(draw):
    y0 = 292
    draw.rectangle((0, y0, LW, LH), fill=(4, 8, 12, 208))

    text_box(draw, (18, 298), "AGC FAST", (229, 236, 239, 255), 16, True)
    text_box(draw, (126, 298), "SQL -92", (110, 222, 239, 255), 16, True, mono=True)

    text_box(draw, (258, 298), "BW 2.4 k    REC 00:12    IQ 96k", (118, 218, 229, 255), 16, True, mono=True)
    text_box(draw, (730, 298), "DECODER", (229, 236, 239, 255), 16, True)
    text_box(draw, (838, 298), "NO SYNC", (255, 178, 105, 255), 16, True, mono=True)


def render(freq_khz=DEFAULT_FREQ_KHZ, span_khz=DEFAULT_SPAN_KHZ, smeter_dbm=-45.0, waterfall=None):
    img = Image.new("RGBA", (LW, LH), (4, 7, 11, 255))
    wf = waterfall.convert("RGBA") if waterfall is not None else prepare_waterfall()
    if wf.size != (LW, LH - TOP_H):
        wf = ImageOps.fit(wf, (LW, LH - TOP_H), method=Image.Resampling.LANCZOS)
    img.alpha_composite(wf, (0, TOP_H))
    draw = ImageDraw.Draw(img)

    # Darken waterfall slightly so the overlays stay legible on the small LCD.
    shade = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle((0, TOP_H, LW, LH), fill=(0, 0, 0, 22))
    img.alpha_composite(shade)
    draw_top_panel(img, freq_khz=freq_khz, smeter_dbm=smeter_dbm)
    draw_ruler(draw, center_khz=freq_khz, span_khz=span_khz)
    draw_spectrum_overlay(img)
    draw_lower_hud(draw)
    return img.convert("RGB")


def to_framebuffer_400x960(logical):
    active = Image.new("RGB", (LW, ACTIVE_H), (0, 0, 0))
    active.paste(logical, (0, ACTIVE_H - LH))
    return active.rotate(90, expand=True)


def to_framebuffer_320x960(logical):
    return logical.rotate(90, expand=True)


def write_fb(logical):
    w, h = map(int, (SYS / "virtual_size").read_text().strip().split(","))
    bpp = int((SYS / "bits_per_pixel").read_text())
    stride = int((SYS / "stride").read_text())
    if bpp != 32:
        raise SystemExit(f"expected 32bpp framebuffer, got {w}x{h}x{bpp}")
    if (w, h) == (400, 960):
        native = to_framebuffer_400x960(logical)
    elif (w, h) == (320, 960):
        native = to_framebuffer_320x960(logical)
    else:
        raise SystemExit(f"unsupported framebuffer size {w}x{h}; expected 400x960 or 320x960")

    raw = bytearray(stride * h)
    px = native.load()
    for y in range(h):
        row = y * stride
        for x in range(w):
            r, g, b = px[x, y]
            raw[row + x * 4:row + x * 4 + 4] = struct.pack("<BBBB", b, g, r, 0)

    with FB.open("r+b") as fh:
        mm = mmap.mmap(fh.fileno(), len(raw))
        mm[:] = raw
        mm.flush()
        mm.close()
    print(f"wrote SDR mockup to /dev/fb0 {w}x{h}, stride={stride}")


def main():
    parser = argparse.ArgumentParser(description="Render a 960x320 SDR frontend mockup for the YX45011A display.")
    parser.add_argument("--png", type=Path, default=ROOT / "renders" / "sdr-frontend-960x320.png")
    parser.add_argument("--fb-png", type=Path, default=ROOT / "renders" / "sdr-frontend-fb-400x960.png")
    parser.add_argument("--fb", action="store_true", help="Write directly to /dev/fb0 on the Raspberry Pi.")
    parser.add_argument("--freq-khz", type=float, default=DEFAULT_FREQ_KHZ)
    parser.add_argument("--span-khz", type=float, default=DEFAULT_SPAN_KHZ)
    parser.add_argument("--smeter-dbm", type=float, default=-45.0)
    args = parser.parse_args()

    logical = render(freq_khz=args.freq_khz, span_khz=args.span_khz, smeter_dbm=args.smeter_dbm)
    args.png.parent.mkdir(parents=True, exist_ok=True)
    logical.save(args.png)
    to_framebuffer_400x960(logical).save(args.fb_png)
    print(f"preview: {args.png} {logical.size}")
    print(f"framebuffer: {args.fb_png} {(400, 960)}")
    if args.fb:
        write_fb(logical)


if __name__ == "__main__":
    main()
