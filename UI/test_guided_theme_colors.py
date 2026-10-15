import unittest

from theme_colors import recolor_family_shades


class GuidedThemeColorsTests(unittest.TestCase):
    def test_family_shades_preserve_alpha_and_order(self):
        base = {
            "dark": [25, 25, 25, 80],
            "light": [175, 175, 175, 220],
            "text": [240, 240, 240],
        }

        gray = recolor_family_shades(base, ("dark", "light"), 0.32, 0.50, 0.0)
        color = recolor_family_shades(base, ("dark", "light"), 0.32, 0.50, 1.0)

        self.assertEqual(gray["dark"][0], gray["dark"][1])
        self.assertLess(sum(gray["dark"][:3]), sum(gray["light"][:3]))
        self.assertNotEqual(color["dark"][0], color["dark"][1])
        self.assertLess(sum(color["dark"][:3]), sum(color["light"][:3]))
        self.assertEqual([gray["dark"][3], gray["light"][3]], [80, 220])
        self.assertEqual([color["dark"][3], color["light"][3]], [80, 220])
        self.assertEqual(gray["text"], base["text"])
        self.assertEqual(color["text"], base["text"])
        self.assertEqual(base["dark"], [25, 25, 25, 80])
        self.assertEqual(base["light"], [175, 175, 175, 220])

    def test_family_shades_keep_order_at_lightness_endpoints(self):
        cases = (
            ("high", {"near": [253, 253, 253], "far": [254, 254, 254]}, 1.0),
            ("low", {"near": [1, 1, 1], "far": [2, 2, 2]}, 0.0),
        )

        for label, base, target in cases:
            with self.subTest(endpoint=label):
                result = recolor_family_shades(
                    base, ("near", "far"), 0.32, target, 0.0,
                )
                self.assertLess(
                    sum(result["near"][:3]), sum(result["far"][:3]),
                )

    def test_family_shades_handle_black_white_span(self):
        base = {"black": [0, 0, 0, 30], "white": [255, 255, 255, 230]}

        result = recolor_family_shades(
            base, ("black", "white"), 0.32, 0.50, 0.0,
        )

        self.assertLess(sum(result["black"][:3]), sum(result["white"][:3]))
        for key in ("black", "white"):
            self.assertTrue(all(0 <= channel <= 255 for channel in result[key][:3]))
        self.assertEqual([result["black"][3], result["white"][3]], [30, 230])
