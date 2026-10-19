"""Regression coverage for the CM5 appliance-style boot handoff."""

from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "UI"))

from boot_ready import mark_boot_ready


class Cm5ApplianceBootTests(unittest.TestCase):
    def test_renderer_publishes_first_frame_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "runtime" / "ready"
            self.assertTrue(mark_boot_ready(marker))
            self.assertEqual(marker.read_text(encoding="utf-8"), "ready\n")

    def test_native_splash_matches_cm5_panel(self):
        with Image.open(ROOT / "assets/boot-splash/ituner-sdr-native.png") as image:
            self.assertEqual(image.size, (800, 1280))
            self.assertEqual(image.mode, "RGB")

    def test_splash_version_matches_release(self):
        version = (ROOT / 'VERSION').read_text().strip()
        self.assertRegex(version, r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
        for filename in ('ituner-sdr-native.png', 'ituner-sdr-preview.png'):
            with Image.open(ROOT / 'assets/boot-splash' / filename) as image:
                self.assertEqual(image.info.get('SoftwareVersion'), version,
                                 'Rebuild the splash after changing VERSION')

    def test_installer_keeps_network_out_of_app_critical_path(self):
        source = (ROOT / "scripts/install-cm5-app-only.sh").read_text()
        unit = source.split("cat > /etc/systemd/system/ituner-sdr.service <<EOF", 1)[1]
        unit = unit.split("EOF", 1)[0]
        self.assertNotIn("network-online.target", unit)
        self.assertIn("After=display-manager.service ituner-sdr-touch-ready.service", unit)
        self.assertIn("ITUNER_BOOT_READY_FILE=/run/ituner-sdr/ready", unit)

    def test_installer_replaces_desktop_with_matching_wayland_splash(self):
        source = (ROOT / "scripts/install-cm5-app-only.sh").read_text()
        self.assertIn("swaybg -i /usr/local/share/ituner-sdr/boot-splash.png", source)
        self.assertIn("labwc-system-autostart.before-appliance", source)
        self.assertNotIn("/usr/bin/lwrespawn /usr/bin/pcmanfm-pi", source)
        self.assertNotIn("/usr/bin/lwrespawn /usr/bin/wf-panel-pi", source)
        self.assertIn("plymouth-set-default-theme -R ituner-sdr", source)
        self.assertIn("vt.global_cursor_default=0", source)
        self.assertIn("disable_splash=1", source)


if __name__ == "__main__":
    unittest.main()
