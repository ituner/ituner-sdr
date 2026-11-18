"""Exercise the USB boot migration against files, never live GPIOs."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V4USBProfileTests(unittest.TestCase):
    def configure(self, text):
        source = (ROOT / 'scripts/enable-cm5-usb3.sh').read_text()
        migration = source.split("<<'PYCONF'\n", 1)[1].split('\nPYCONF', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.txt'
            config.write_text(text)
            subprocess.run([sys.executable, '-', str(config)], input=migration,
                           text=True, check=True)
            return config.read_text()

    def test_replaces_old_polarity_preserves_other_settings_and_is_idempotent(self):
        prefix = 'dtoverlay=cm5-main-es8316\n'
        suffix = '\ndtoverlay=cm5-v4-display-touch\n'
        before = (prefix + '# BEGIN ITUNER CM5 USB3\n[cm5]\n'
                  'gpio=42=op,dl\n[all]\n# END ITUNER CM5 USB3' + suffix)
        after = self.configure(before)
        self.assertTrue(after.startswith(prefix))
        self.assertTrue(after.endswith(suffix))
        self.assertIn('gpio=42=op,dh', after)
        self.assertNotIn('gpio=42=op,dl', after)
        self.assertEqual(after, self.configure(after))

    def test_adds_profile_when_no_workaround_exists(self):
        before = '# Existing configuration\ndtoverlay=vc4-kms-v3d\n'
        after = self.configure(before)
        self.assertTrue(after.startswith(before))
        self.assertEqual(after.count('gpio=42=op,dh'), 1)
        self.assertEqual(after, self.configure(after))


if __name__ == '__main__':
    unittest.main()
