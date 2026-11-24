import ast
from pathlib import Path
import runpy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import system_power as power
import kiwi_gl_display as ui


class PowerTests(unittest.TestCase):
    def setUp(self):
        self.runner = Mock(return_value=NS(returncode=0))
        self.controller = power.PowerController(helper=__file__, runner=self.runner)

    def run_now(self, target, args, **_kwargs):
        return NS(start=lambda: target(*args))

    def test_selection_and_cancel_never_execute_a_power_command(self):
        self.controller.select('poweroff')
        self.assertTrue(self.controller.open)
        self.controller.cancel()
        self.assertFalse(self.controller.open)
        self.controller.confirm()
        self.runner.assert_not_called()

    def test_each_confirmed_action_runs_once_without_force(self):
        for action in power.ACTIONS:
            c = power.PowerController(helper=__file__, runner=self.runner)
            c.select(action)
            with patch.object(power.threading, 'Thread', side_effect=self.run_now):
                c.confirm(); c.confirm(); c.cancel()
            self.assertTrue(c.busy)
            self.runner.assert_called_with(['sudo', '-n', __file__, action], capture_output=True, text=True, timeout=15)
        self.assertEqual(self.runner.call_count, 2)

    def test_desktop_without_helper_cannot_shutdown(self):
        c = power.PowerController(helper='/missing/ituner-power', runner=self.runner)
        c.select('poweroff'); c.confirm()
        self.runner.assert_not_called()
        self.assertFalse(c.busy)
        self.assertIn('not installed', c.message)

    def test_failed_action_remains_open_and_allows_retry_or_back(self):
        self.runner.return_value = NS(returncode=1, stderr='Permission denied', stdout='')
        c = self.controller; c.select('reboot')
        with patch.object(power.threading, 'Thread', side_effect=self.run_now): c.confirm()
        c.poll()
        self.assertFalse(c.busy)
        self.assertTrue(c.open)
        self.assertEqual(c.message, 'Permission denied')
        c.cancel(); self.assertFalse(c.open)

    def test_unknown_operation_is_never_selected(self):
        self.controller.select('reboot --force')
        self.controller.confirm()
        self.runner.assert_not_called()

    def test_system_entries_and_confirmation_geometry(self):
        labels = dict(ui.SETTINGS_MENU_ITEMS)
        self.assertEqual(labels['reboot'], 'REBOOT')
        self.assertEqual(labels['poweroff'], 'SHUT DOWN')
        b = power.boxes(ui)
        self.assertEqual(b['back'], ui.lcd_drawer_back_box())
        self.assertEqual(b['confirm'], (32, 304, 368, 371))
        self.assertLess(b['confirm'][2], ui.LCD_NAV_X0)
        for name, box in b.items():
            x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
            self.assertEqual(power.action_at(self.controller, ui, x, y), name)
        self.controller.busy = True
        self.assertIsNone(power.action_at(self.controller, ui, x, y))

    def test_release_outside_confirm_cannot_issue_command(self):
        tree = ast.parse(Path(ui.__file__).read_text())
        branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and
                      ast.unparse(n.test) == "touch_started and gesture == 'system_power'")
        code = compile(ast.fix_missing_locations(ast.Module(body=branch.body, type_ignores=[])), '<power-touch>', 'exec')
        self.controller.select('poweroff')
        b = power.boxes(ui)['confirm']; x, y = b[0]+2, b[1]+2
        env = dict(start_x=x, start_y=y, x=x-4, y=y, args=NS(tap_px=10),
                   power_control=self.controller, system_power=power, sys=NS(modules={'power_test':ui}),
                   __name__='power_test', confirmed_tap_action=ui.confirmed_tap_action,
                   restore_navigation_parent=Mock(), wake_controls=Mock())
        exec(code, env)
        self.runner.assert_not_called()

    def test_privileged_helper_rejects_extra_arguments_and_uses_orderly_systemd(self):
        helper = runpy.run_path(str(Path(__file__).parents[1]/'scripts/ituner-power'))['main']
        with patch('os.geteuid', return_value=0), patch.object(Path, 'read_text', return_value='Raspberry Pi Compute Module 5'), patch('subprocess.run') as run:
            for invalid in ([], ['halt'], ['poweroff','--force']):
                with self.assertRaises(SystemExit): helper(invalid)
            run.assert_not_called()
            helper(['poweroff'])
            run.assert_called_once_with(['/usr/bin/systemctl','--no-block','poweroff'],check=True)
