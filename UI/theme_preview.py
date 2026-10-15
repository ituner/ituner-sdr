"""Use the user's unchanged CM5 screenshot as the SDR scene in previews."""
from functools import lru_cache
import json
from pathlib import Path

from PIL import Image, ImageOps
import theme_system
from ui_style import UIPalette

CAPTURE_DIR = Path(__file__).parent / 'assets' / 'theme-preview'


@lru_cache(maxsize=1)
def home_capture():
    metadata = json.loads((CAPTURE_DIR / 'home.json').read_text())
    with Image.open(CAPTURE_DIR / 'home.png') as source:
        image = source.convert('RGBA')
    if image.width < image.height:
        image = image.transpose(Image.Transpose.ROTATE_90)
    if list(image.size) != metadata['logical_size']:
        raise ValueError('Home capture dimensions do not match its metadata')
    return metadata, image


def frontend_preview(theme, waterfall_mapping):
    """Retain captured RF detail and map only its appearance to the candidate."""
    metadata, original = home_capture()
    bounds = metadata['frontend_box']
    scene = original.crop(bounds)
    colors, source = theme['colors'], metadata['source_colors']
    if any(colors[key] != source[key] for key in ('spectrum_field', 'spectrum_line')):
        rgb = scene.convert('RGB')
        if colors['spectrum_field'][:3] == [255 - value for value in source['spectrum_field'][:3]]:
            rgb = ImageOps.invert(rgb)
        else:
            gray = ImageOps.grayscale(rgb)
            low, high = colors['spectrum_field'], colors['spectrum_line']
            lut = [round(lo + (hi - lo) * (value / 255) ** .7)
                   for lo, hi in zip(low[:3], high[:3]) for value in range(256)]
            rgb = Image.merge('RGB', tuple(gray.point(lut[index * 256:(index + 1) * 256]) for index in range(3)))
        scene = rgb.convert('RGBA')
    render_theme = theme
    if theme_system.is_builtin_theme_id(theme['id']) and theme != theme_system.BUILTIN_THEMES[theme['id']]:
        render_theme = {**theme, 'id': 'preview-custom'}
    # Read the actual captured waterfall, including its real signal patterns.
    waterfall_bounds = metadata['waterfall_box']
    waterfall = original.crop(waterfall_bounds)
    mapped = waterfall_mapping(waterfall.tobytes(), render_theme,
                               UIPalette(**{key: tuple(value) for key, value in colors.items()}))
    scene.paste(Image.frombytes('RGBA', waterfall.size, mapped),
                (waterfall_bounds[0] - bounds[0], waterfall_bounds[1] - bounds[1]))
    return scene
