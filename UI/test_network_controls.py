import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from network_interface import InterfaceSettings

loader=importlib.machinery.SourceFileLoader('network_helper_test', str(Path(__file__).resolve().parents[1]/'systemd/ituner-network'))
spec=importlib.util.spec_from_loader(loader.name,loader)
helper=importlib.util.module_from_spec(spec);loader.exec_module(helper)

class NetworkControlsTests(unittest.TestCase):
    def result(self, text='', code=0): return SimpleNamespace(stdout=text,stderr='',returncode=code)

    def test_replacement_password_is_written_before_saved_profile_activation(self):
        calls=[]
        def run(*args,**kwargs):
            calls.append(args)
            if '802-11-wireless.ssid' in args: return self.result('new-ap\n' if args[-1]=='target' else 'old-ap\n')
            if 'GENERAL.CON-UUID' in args:return self.result('old\n')
            return self.result()
        with patch.object(helper,'run',side_effect=run):
            name,_=helper.ensure_persistent_profile('new-ap','new-secret','target')
        self.assertIsNotNone(name)
        password=next(i for i,c in enumerate(calls) if '802-11-wireless-security.psk' in c)
        down=next(i for i,c in enumerate(calls) if 'down' in c)
        up=next(i for i,c in enumerate(calls) if 'up' in c)
        self.assertLess(password,down);self.assertLess(down,up)
        self.assertIn('new-secret',calls[password])
        self.assertTrue(any('ipv4.route-metric' in c and '50' in c for c in calls))

    def test_failed_switch_restores_previous_ap(self):
        calls=[]
        def run(*args,**kwargs):
            calls.append(args)
            if '802-11-wireless.ssid' in args:return self.result('new-ap' if args[-1]=='target' else 'old-ap')
            if 'GENERAL.CON-UUID' in args:return self.result('old')
            return self.result(code=int('up' in args and 'target' in args))
        with patch.object(helper,'run',side_effect=run):
            name,_=helper.ensure_persistent_profile('new-ap','new-secret','target')
        self.assertIsNone(name)
        self.assertIn((' --wait'.strip(),'20','connection','up','uuid','old','ifname','wlan0'),calls)

    def test_invalid_static_address_cannot_mutate_connection(self):
        with patch.object(helper,'run') as run:
            result=helper.configure_interface(dict(device='wlan0',method='manual',addresses='oops'))
        self.assertFalse(result['ok']);run.assert_not_called()

    def test_changed_connection_is_not_modified(self):
        with patch.object(helper,'interface_profile',return_value='new'),patch.object(helper,'run') as run:
            result=helper.configure_interface(dict(device='wlan0',uuid='old'))
        self.assertFalse(result['ok']);run.assert_not_called()

    def test_interface_apply_preserves_requested_100mbps(self):
        with patch.object(helper,'interface_profile',return_value='wired'),patch.object(helper,'network_status',return_value={}),patch.object(helper,'run',return_value=self.result()) as run:
            result=helper.configure_interface(dict(device='eth0',uuid='wired',speed=100,autoneg=True,duplex='full'))
        self.assertTrue(result['ok'])
        modify=run.call_args_list[0].args
        self.assertEqual(modify[modify.index('802-3-ethernet.speed')+1],'100')
        self.assertEqual(modify[modify.index('802-3-ethernet.auto-negotiate')+1],'yes')

    def test_interface_editor_requires_confirmation_before_disconnect(self):
        bridge=Mock();bridge.snapshot.return_value=({},False)
        editor=InterfaceSettings(bridge);editor.draft=dict(device='wlan0',uuid='wifi')
        editor.key('off',None);bridge.request.assert_not_called()
        editor.key('confirm',None)
        bridge.request.assert_called_once_with('configure-interface',dict(device='wlan0',uuid='wifi',operation='off'))

    def test_shared_keyboard_delete_and_mode(self):
        editor=InterfaceSettings(Mock());editor.field='addresses';editor.value='123'
        editor.key('BACK',None)
        self.assertEqual(editor.value,'12')
        ui=SimpleNamespace(touch_keyboard_next_mode=Mock(return_value='lower'))
        editor.key('MODE',ui)
        ui.touch_keyboard_next_mode.assert_called_once_with('symbols','MODE')
        self.assertEqual(editor.mode,'lower')

    def test_cancel_keyboard_keeps_old_value(self):
        editor=InterfaceSettings(Mock());editor.field='addresses';editor.draft={'addresses':'old'};editor.value='new'
        editor.key('CANCEL',None)
        self.assertEqual(editor.draft['addresses'],'old');self.assertIsNone(editor.field)

if __name__=='__main__':unittest.main()
