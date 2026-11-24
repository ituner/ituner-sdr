"""An attached RTL receiver must stay discoverable while a decoder owns it."""
import unittest
from unittest.mock import Mock, patch
import kiwi_gl_display as ui


class USBDiscoveryTests(unittest.TestCase):
    def test_attached_receiver_is_listed_without_opening_active_sdr(self):
        physical = [dict(product='RTL2832U', manufacturer='Realtek', serial='00001000')]
        def run(command, **kwargs):
            if command[0] == 'rtl_test':
                return Mock(stdout='', stderr='usb_claim_interface error -6')
            raise FileNotFoundError(command[0])
        with patch('rtl_registry.usb_inventory', return_value=physical), \
             patch.object(ui.subprocess, 'run', side_effect=run) as probe, \
             patch.object(ui.threading, 'Thread', side_effect=lambda **kw:Mock(start=kw['target'])):
            lab = ui.RTLSDRLab(Mock(), Mock(), Mock())
            rows = lab.receiver_rows()
            self.assertEqual(len(rows), 1)
            self.assertIn('00001000', rows[0][1])
            self.assertFalse(lab.snapshot()['probing'])
            self.assertFalse(any(c.args[0][0]=='rtl_test' for c in probe.call_args_list))

    def test_unplugged_receiver_disappears_on_rescan(self):
        with patch('rtl_registry.usb_inventory', return_value=[]) as inventory, \
             patch.object(ui.subprocess, 'run', return_value=Mock(stdout='No supported devices found',stderr='')), \
             patch.object(ui.threading, 'Thread', side_effect=lambda **kw:Mock(start=kw['target'])):
            inventory.return_value=[dict(product='RTL2832U',serial='00001000')]
            lab=ui.RTLSDRLab(Mock(),Mock(),Mock())
            self.assertEqual(len(lab.receiver_rows()),1)
            inventory.return_value=[];lab.probe()
            self.assertEqual(lab.receiver_rows(),[])

class USBStartupFeedbackTests(unittest.TestCase):
    def test_return_home_only_after_live_and_keep_errors_visible(self):
        import ast
        from pathlib import Path
        from types import SimpleNamespace
        tree=ast.parse(Path(ui.__file__).read_text())
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='pending_usb_selection')
        code=compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),ui.__file__,'exec')
        for status, panel, pending in [('STARTING',True,True),('LIVE',False,False),('ERROR',True,False)]:
            env=dict(pending_usb_selection=True,rtl_lab_open=True,rtl_lab=SimpleNamespace(snapshot=lambda:dict(status=status)))
            exec(code,env)
            self.assertEqual(env['rtl_lab_open'],panel)
            self.assertEqual(env['pending_usb_selection'],pending)
