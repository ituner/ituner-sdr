#!/usr/bin/env python3
"""Build the native portrait buffer used as a landscape CM5 boot splash."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets/boot-splash/ituner-sdr-native.png"
FONT = ROOT / "assets/fonts/oxanium/Oxanium.ttf"


def centered(draw, y, text, font, fill, width=1280):
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (box[2] - box[0])) / 2, y), text, font=font, fill=fill)


def main():
    canvas = Image.new("RGB", (1280, 800), "#000000")
    draw = ImageDraw.Draw(canvas)
    title = ImageFont.truetype(str(FONT), 104)
    subtitle = ImageFont.truetype(str(FONT), 25)
    status = ImageFont.truetype(str(FONT), 18)

    cyan = "#00E5FF"
    white = "#F4F7F8"
    secondary = "#737A7D"
    divider = "#202629"

    draw.line((388, 306, 892, 306), fill=divider, width=2)
    draw.line((498, 306, 546, 306), fill=cyan, width=3)
    draw.line((734, 306, 782, 306), fill=cyan, width=3)
    centered(draw, 326, "iTUNER SDR", title, white)
    centered(draw, 455, "SOFTWARE DEFINED RADIO", subtitle, secondary)
    draw.rectangle((548, 515, 732, 517), fill=divider)
    draw.rectangle((548, 515, 610, 517), fill=cyan)
    centered(draw, 546, "STARTING", status, secondary)

    # The CM5 panel is physically landscape but exposes an 800x1280 native
    # mode. The renderer maps its 1280x800 logical canvas counter-clockwise.
    native = canvas.transpose(Image.Transpose.ROTATE_90)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    native.save(OUTPUT, optimize=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
