"""The Themes page must retain the actual captured SDR scene."""
from copy import deepcopy
import hashlib
import unittest

import kiwi_gl_display as ui
from theme_preview import CAPTURE_DIR, home_capture, frontend_preview
from theme_system import DEFAULT_THEME, BUILTIN_THEMES, new_theme, runtime_theme
from ui_style import UIPalette


class CapturedPreviewTests(unittest.TestCase):
    def test_original_capture_is_retained_at_its_recorded_checksum(self):
        metadata, image = home_capture()
        self.assertEqual(hashlib.sha256((CAPTURE_DIR / 'home.png').read_bytes()).hexdigest(), metadata['sha256'])
        self.assertEqual(image.size, (1280, 800))
        self.assertEqual(metadata['frequency_label'], '17.683.200')
        self.assertEqual(metadata['band_mode'], '16 m · SW AM')

    def test_default_frontend_is_a_pixel_exact_crop_of_the_real_capture(self):
        metadata, image = home_capture()
        theme = new_theme(source=DEFAULT_THEME)
        theme['colors'] = deepcopy(metadata['source_colors'])
        result = frontend_preview(theme, ui.themed_waterfall_pixels)
        self.assertEqual(result.tobytes(), image.crop(metadata['frontend_box']).tobytes())

    def test_theme_recoloring_maps_real_waterfall_pixels_without_replacing_patterns(self):
        metadata, image = home_capture()
        captured = image.crop(metadata['waterfall_box'])
        for identifier in ('green', 'black-white', 'straight-inverted'):
            with self.subTest(theme=identifier):
                theme = deepcopy(BUILTIN_THEMES[identifier])
                result = frontend_preview(theme, ui.themed_waterfall_pixels)
                palette = UIPalette(**{key: tuple(value) for key, value in theme['colors'].items()})
                expected = ui.themed_waterfall_pixels(captured.tobytes(), theme, palette)
                actual = result.crop(metadata['waterfall_box'])
                self.assertEqual(actual.tobytes(), expected)
                self.assertNotEqual(actual.tobytes(), captured.tobytes())

    def test_meter_changes_do_not_change_builtin_frontend_colors(self):
        for base in BUILTIN_THEMES.values():
            theme = {**deepcopy(base), "smeter_style": "linear_orange"}
            self.assertEqual(frontend_preview(theme, ui.themed_waterfall_pixels).tobytes(),
                             frontend_preview(base, ui.themed_waterfall_pixels).tobytes())

    def test_building_previews_does_not_apply_a_theme(self):
        before = deepcopy(runtime_theme)
        for theme in BUILTIN_THEMES.values():
            frontend_preview(deepcopy(theme), ui.themed_waterfall_pixels)
        self.assertEqual(runtime_theme, before)

    def test_candidate_images_cannot_modify_the_source_capture(self):
        metadata, image = home_capture()
        before = image.tobytes()
        result = frontend_preview(new_theme(source=DEFAULT_THEME), ui.themed_waterfall_pixels)
        result.putpixel((0, 0), (255, 0, 255, 255))
        self.assertEqual(image.tobytes(), before)


if __name__ == '__main__':unittest.main()
