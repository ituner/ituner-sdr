#!/usr/bin/env python3
"""Build the landscape preview and native portrait CM5 boot splash."""

from io import BytesIO
from pathlib import Path
import shutil
import subprocess

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets/boot-splash/ituner-sdr-native.png"
PREVIEW = ROOT / "assets/boot-splash/ituner-sdr-preview.png"
LOGO = ROOT / "assets/boot-splash/ituner-logo-color.svg"
LOGO_WIDTH = 500


def main():
    renderer = shutil.which("rsvg-convert")
    if renderer is None:
        raise SystemExit("Install librsvg (rsvg-convert) to render the SVG logo.")
    # Specifying only width preserves the SVG's original aspect ratio.
    rendered = subprocess.check_output([renderer, "--width", str(LOGO_WIDTH), str(LOGO)])
    logo = Image.open(BytesIO(rendered)).convert("RGBA")
    canvas = Image.new("RGB", (1280, 800), "#000000")
    canvas.paste(logo, ((canvas.width - logo.width) // 2,
                        (canvas.height - logo.height) // 2), logo)

    # The landscape CM5 panel exposes an 800x1280 native portrait buffer.
    native = canvas.transpose(Image.Transpose.ROTATE_90)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(PREVIEW, optimize=True)
    native.save(OUTPUT, optimize=True)
    print(PREVIEW)
    print(OUTPUT)


if __name__ == "__main__":
    main()
