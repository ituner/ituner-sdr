import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from lcd_backlight import LCDBacklight, clamp_brightness


class BrightnessTests(unittest.TestCase):
    def test_clamps_and_invalid_saved_values(self):
        for value, expected in [(-1, 5), (0, 5), (50.3, 50), (101, 100),
                                (None, 100), ('bad', 100), (float('nan'), 100)]:
            self.assertEqual(clamp_brightness(value), expected)

    def test_real_sysfs_shape_scaling_and_failed_write(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'max_brightness').write_text('1000')
            (path/'brightness').write_text('1000')
            control = LCDBacklight(path)
            self.assertTrue(control.available)
            self.assertTrue(control.set_percent(25))
            self.assertEqual((path/'brightness').read_text(), '250\n')
            self.assertTrue(control.set_percent(0))
            self.assertEqual((path/'brightness').read_text(), '50\n')
            (path/'brightness').unlink()
            (path/'brightness').mkdir()
            self.assertFalse(control.set_percent(80))
            self.assertEqual(control.percent, 5)
            self.assertFalse(control.available)

    def test_old_gpio_driver_is_not_used_as_pwm(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'max_brightness').write_text('1')
            (path/'brightness').write_text('1')
            control = LCDBacklight(path)
            self.assertFalse(control.available)
            self.assertFalse(control.set_percent(25))
            self.assertEqual((path/'brightness').read_text(), '1')
        self.assertFalse(LCDBacklight('/no/such/backlight').available)

    def test_main_display_layout_and_advanced_hit_area(self):
        tree = ast.parse(Path(__file__).with_name('kiwi_gl_display.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'set_display_page')
        scope = dict(LCD_800_MODE=True, LCD_NAV_X0=1024, LOGICAL_W=1280,
                     LCD_NAV_GAP=8, SPECTRUM_STYLE_OPTIONS=(('fill','FILL'),),
                     lcd_drawer_back_box=lambda:(1034,728,1270,792))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'layout','exec'),scope)
        scope['set_display_page'](False)
        b=scope['DISPLAY_BRIGHTNESS_BOX']
        self.assertGreaterEqual(b[1],600)
        self.assertLess(b[3],scope['DISPLAY_ADVANCED_BOX'][1])
        self.assertGreaterEqual(b[3]-b[1],48)
        scope['set_display_page'](True)
        self.assertEqual(scope['DISPLAY_BRIGHTNESS_BOX'],(-1,-1,-1,-1))

if __name__ == '__main__':
    unittest.main()
