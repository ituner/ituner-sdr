#!/usr/bin/env python3
"""Build the landscape preview and native portrait CM5 boot splash."""

from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets/boot-splash/ituner-sdr-native.png"
PREVIEW = ROOT / "assets/boot-splash/ituner-sdr-preview.png"
LOGO = ROOT / "assets/boot-splash/ituner-logo-color.svg"
LOGO_WIDTH = 350


def main():
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise SystemExit('VERSION must contain a major.minor.patch version, for example 0.1.0')
    renderer = shutil.which("rsvg-convert")
    if renderer is None:
        raise SystemExit("Install librsvg (rsvg-convert) to render the SVG logo.")
    # Specifying only width preserves the SVG's original aspect ratio.
    rendered = subprocess.check_output([renderer, "--width", str(LOGO_WIDTH), str(LOGO)])
    logo = Image.open(BytesIO(rendered)).convert("RGBA")
    canvas = Image.new("RGB", (1280, 800), "#000000")
    canvas.paste(logo, ((canvas.width - logo.width) // 2,
                        (canvas.height - logo.height) // 2), logo)

    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype(str(ROOT / 'assets/fonts/oxanium/Oxanium.ttf'), 18)
    draw.text((canvas.width / 2, (canvas.height + logo.height) // 2 + 20),
              'v' + version, font=font, fill='#C0C0C0', anchor='mt')

    # The landscape CM5 panel exposes an 800x1280 native portrait buffer.
    native = canvas.transpose(Image.Transpose.ROTATE_90)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngInfo()
    metadata.add_text('SoftwareVersion', version)
    canvas.save(PREVIEW, optimize=True, pnginfo=metadata)
    native.save(OUTPUT, optimize=True, pnginfo=metadata)
    print(PREVIEW)
    print(OUTPUT)


if __name__ == "__main__":
    main()
