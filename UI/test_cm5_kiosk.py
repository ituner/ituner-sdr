import runpy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

configure = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/configure-cm5-kiosk.py'))['configure']

class KioskTests(unittest.TestCase):
    def test_preserves_touch_and_display_and_overrides_menu_bindings(self):
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/'.config/labwc/rc.xml';path.parent.mkdir(parents=True)
            original='<openbox_config xmlns="http://openbox.org/3.4/rc"><touch deviceName="Goodix" mapToOutput="DSI-2" mouseEmulation="yes"/><mouse><context name="Root"><mousebind button="Left" action="Press"><action name="ShowMenu" menu="root-menu"/></mousebind></context></mouse></openbox_config>'
            path.write_text(original);configure(home)
            root=ET.parse(path).getroot();ns={'l':'http://openbox.org/3.4/rc'}
            self.assertEqual(root.find('l:touch',ns).attrib,dict(deviceName='Goodix',mapToOutput='DSI-2',mouseEmulation='yes'))
            bindings=root.findall('l:mouse/l:context/l:mousebind',ns)
            self.assertEqual(len(bindings),18);self.assertTrue(all(len(b)==0 for b in bindings))
            first=path.read_bytes();configure(home);self.assertEqual(path.read_bytes(),first)
            self.assertEqual(path.with_name('rc.xml.before-ituner-kiosk').read_text(),original)
    def test_new_install_has_explicit_noop_mouse_bindings(self):
        with tempfile.TemporaryDirectory() as home:
            root=ET.parse(configure(home)).getroot()
            self.assertEqual(len(root.findall('mouse/context/mousebind')),18)
            self.assertEqual([k.get('key') for k in root.findall('keyboard/keybind')],['W-space','Menu'])
