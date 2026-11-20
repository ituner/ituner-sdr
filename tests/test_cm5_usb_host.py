import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('usb_host_config', ROOT/'scripts/configure-cm5-usb-host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class USBHostTests(unittest.TestCase):
    def test_conflicting_live_configuration_is_host_and_idempotent(self):
        before = '[cm5]\ndtoverlay=dwc2,dr_mode=host\n[all]\ndtoverlay=dwc2,dr_mode=peripheral\ndtoverlay=cm5-v4-display-touch\ngpio=42=op,dh\n'
        after = host.host_config(before)
        self.assertEqual(after.count('dtoverlay=dwc2'), 1)
        self.assertNotIn('dr_mode=peripheral', after)
        self.assertIn('dtoverlay=cm5-v4-display-touch\ngpio=42=op,dh', after)
        self.assertEqual(after, host.host_config(after))

    def test_no_host_adds_cm5_scope_preserving_other_board(self):
        before = '[cm4]\ndtoverlay=dwc2,dr_mode=peripheral\n[none]\ndtoverlay=dwc2,dr_mode=host\n'
        after = host.host_config(before)
        self.assertTrue(after.startswith(before))
        self.assertIn('[cm5]\ndtoverlay=dwc2,dr_mode=host\n[all]', after)
        self.assertEqual(after, host.host_config(after))

    def test_preserves_overlay_options_and_comments(self):
        before = '[all]\ndtoverlay=dwc2,dr_mode=peripheral,g-rx-fifo-size=558 # custom FIFO\n'
        after = host.host_config(before)
        self.assertIn('dr_mode=host,g-rx-fifo-size=558 # custom FIFO', after)
        self.assertEqual(after, host.host_config(after))

    def test_only_serial_gadget_removed_from_cmdline(self):
        before = 'root=PARTUUID=test modules-load=dwc2,g_serial,other quiet\n'
        after = host.host_cmdline(before)
        self.assertEqual(after, 'root=PARTUUID=test modules-load=dwc2,other quiet\n')
        self.assertEqual(after, host.host_cmdline(after))
        self.assertNotIn('modules-load=', host.host_cmdline('quiet modules-load=g_serial\n'))

    def test_both_originals_backed_up_and_rerun_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            config, cmdline = Path(d)/'config.txt', Path(d)/'cmdline.txt'
            config.write_text('[all]\ndtoverlay=dwc2,dr_mode=peripheral\n')
            cmdline.write_text('quiet modules-load=dwc2,g_serial\n')
            original = {p.name: p.read_text() for p in (config, cmdline)}
            backup = host.configure(config, cmdline)
            for name, text in original.items():
                self.assertEqual((backup/name).read_text(), text)
            self.assertIsNone(host.configure(config, cmdline))

    def test_invalid_cmdline_leaves_both_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            config, cmdline = Path(d)/'config.txt', Path(d)/'cmdline.txt'
            config.write_text('dtoverlay=dwc2,dr_mode=peripheral\n')
            cmdline.write_text('quiet\nbad second line\n')
            before = {p: p.read_bytes() for p in (config, cmdline)}
            with self.assertRaises(ValueError):
                host.configure(config, cmdline)
            self.assertEqual(before, {p: p.read_bytes() for p in before})
            self.assertEqual(len(list(Path(d).iterdir())), 2)


if __name__ == '__main__':
    unittest.main()
