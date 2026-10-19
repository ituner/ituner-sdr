#!/usr/bin/env python3
"""Build the landscape preview and native portrait CM5 boot splash."""

from io import BytesIO
from pathlib import Path
import argparse
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets/boot-splash/ituner-sdr-native.png"
PREVIEW = ROOT / "assets/boot-splash/ituner-sdr-preview.png"
LOGO = ROOT / "assets/boot-splash/ituner-logo-color.svg"
LOGO_WIDTH = 350


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', help='Software version or build ID displayed beneath the logo')
    args = parser.parse_args()
    version = args.version or ('Build ' + subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', '--short=7', 'HEAD'], text=True).strip())
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
              version, font=font, fill='#C0C0C0', anchor='mt')

    # The landscape CM5 panel exposes an 800x1280 native portrait buffer.
    native = canvas.transpose(Image.Transpose.ROTATE_90)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(PREVIEW, optimize=True)
    native.save(OUTPUT, optimize=True)
    print(PREVIEW)
    print(OUTPUT)


if __name__ == "__main__":
    main()
