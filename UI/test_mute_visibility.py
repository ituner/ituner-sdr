import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import kiwi_gl_display as ui

class MuteVisibilityTests(unittest.TestCase):
    def visible(self,**changes):
        tree=ast.parse(Path(ui.__file__).read_text())
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='muted_rf_notice_visible')
        names={n.id for n in ast.walk(node) if isinstance(n,ast.Name)}
        env={name:False for name in names}
        for n in ast.walk(node):
            if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name):env[n.value.id]=SimpleNamespace(open=False,blocks_touch=False)
        env.update(waterfall_visible=True,spectrum_enabled=True,spectrum_h=200,shared_keyboard_open=lambda:False)
        env.update(changes)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),ui.__file__,'exec'),env)
        return env['muted_rf_notice_visible']()
    def test_rf_visible_with_drawers_and_theme_preview(self):
        for flags in ({},{'radio_setup_open':True},{'frequency_drawer_open':True},{'audio_panel_open':True},{'theme_editor':SimpleNamespace(open=True)}):
            self.assertTrue(self.visible(**flags))
    def test_spectrum_only_or_waterfall_only_keeps_notice(self):
        self.assertTrue(self.visible(waterfall_visible=False))
        self.assertTrue(self.visible(spectrum_enabled=False))
        self.assertFalse(self.visible(waterfall_visible=False,spectrum_enabled=False))
    def test_full_screen_pages_hide_notice(self):
        self.assertFalse(self.visible(picker_open=True))
        self.assertFalse(self.visible(network_panel_open=True))
        self.assertFalse(self.visible(station_workspace=SimpleNamespace(open=True)))
        self.assertFalse(self.visible(usb_radios_workspace=SimpleNamespace(open=True)))

if __name__=='__main__':unittest.main()
