"""Offline coverage for touchscreen Wi-Fi setup and the privileged helper."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import kiwi_gl_display as ui

loader = importlib.machinery.SourceFileLoader('network_helper', str(Path(__file__).resolve().parents[1] / 'systemd/ituner-network'))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

def result(stdout='', code=0):
    return SimpleNamespace(stdout=stdout, stderr='', returncode=code)

class WifiUITests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()

    def test_tap_decides_password_saved_open_and_connected(self):
        self.assertEqual(ui.network_selection_action({'security':'WPA2'}), 'password')
        self.assertEqual(ui.network_selection_action({'security':'WPA3', 'saved_uuid':'uuid'}), 'manage')
        self.assertEqual(ui.network_selection_action({'security':'--'}), 'connect')
        self.assertEqual(ui.network_selection_action({'active':True}), 'manage')
        self.assertEqual(ui.network_selection_action({'security':'WPA2 802.1X'}), 'unsupported')

    def test_list_is_one_column_and_has_touch_sized_rows(self):
        boxes=ui.network_scan_boxes([{}]*25)
        self.assertEqual(len(boxes), 6)
        self.assertEqual(len({b[0] for b in boxes}), 1)
        self.assertTrue(all(b[3]-b[1]>=56 for b in boxes))
        self.assertTrue(all(b[2]-b[0]>800 for b in boxes))

    def test_keyboard_hit_targets_match_labels_and_all_password_symbols_exist(self):
        chars=set(' ')
        for mode in ('lower','upper','symbols','symbols2'):
            for keys,x,y,w in ui.network_keyboard_rows(mode):
                for i,key in enumerate(keys):
                    actual=ui.network_password_key_at(x+(i+.5)*w,y+36,mode)
                    expected='BACK' if key=='<' and mode!='symbols2' else key
                    self.assertEqual(actual,expected)
                    if actual!='BACK': chars.add(actual)
                    self.assertLess(x+(i+1)*w, ui.LCD_NAV_X0)
            self.assertIsNone(ui.network_password_key_at(-10,-10,mode))
        self.assertTrue(set(chr(n) for n in range(32,127)) <= chars)

    def test_keyboard_case_and_requested_size_are_preserved(self):
        with patch.object(ui,'draw_styled_button_frame',return_value=SimpleNamespace(text=(255,255,255))), patch.object(ui,'draw_text') as text:
            ui.draw_network_button(None,(0,0,80,72),'a',32)
        self.assertEqual(text.call_args.args[3],'a')
        self.assertEqual(text.call_args.args[5],32)

    def test_connect_and_password_are_not_under_the_back_sidebar(self):
        boxes=ui.network_password_boxes()
        for name,b in boxes.items():
            self.assertLess(b[2],ui.LCD_NAV_X0,name)
            self.assertLessEqual(b[3],ui.LOGICAL_H,name)
        self.assertGreaterEqual(boxes['join'][2]-boxes['join'][0],200)
        self.assertGreaterEqual(boxes['join'][3]-boxes['join'][1],60)

    def test_failed_connect_is_not_reported_as_success_from_old_wifi_state(self):
        bridge=ui.NetworkManagerBridge()
        bridge._snapshot['devices']={'wlan0':{'state':'connected','connection':'Old network'}}
        with patch.object(ui.subprocess,'run',return_value=result(json.dumps({'ok':False,'error':'Wrong password'}),1)):
            bridge._run('connect',{'ssid':'New network','password':'not-a-real-secret'})
        snapshot,busy=bridge.snapshot()
        self.assertFalse(busy)
        self.assertEqual(snapshot['connect_result'],{'ssid':'New network','ok':False,'notice':'Wrong password'})
        self.assertNotIn('not-a-real-secret',str(snapshot))

    def test_success_updates_active_row_and_refresh_keeps_scan(self):
        bridge=ui.NetworkManagerBridge()
        bridge._snapshot['networks']=[{'ssid':'Old','active':True},{'ssid':'New','active':False}]
        with patch.object(ui.subprocess,'run',return_value=result(json.dumps({'ok':True,'connected_ssid':'New'}))):
            bridge._run('connect',{'ssid':'New'})
        self.assertEqual([n['active'] for n in bridge.snapshot()[0]['networks']],[False,True])
        with patch.object(ui.subprocess,'run',return_value=result(json.dumps({'ok':True,'devices':{'wlan0':{'state':'disconnected'}}}))):
            bridge._run('refresh',None)
        self.assertEqual([n['active'] for n in bridge.snapshot()[0]['networks']],[False,False])

    def test_forget_updates_row_without_another_rf_scan(self):
        bridge=ui.NetworkManagerBridge()
        bridge._snapshot['networks']=[{'ssid':'Home','saved_uuid':'uuid','active':True}]
        response={'ok':True,'forgotten_uuid':'uuid','devices':{'wlan0':{'state':'disconnected'}}}
        with patch.object(ui.subprocess,'run',return_value=result(json.dumps(response))):
            bridge._run('forget',{'ssid':'Home','saved_uuid':'uuid'})
        row=bridge.snapshot()[0]['networks'][0]
        self.assertFalse(row['active'])
        self.assertIsNone(row['saved_uuid'])

class WifiHelperTests(unittest.TestCase):
    def test_disconnect_checks_active_profile_and_keeps_password(self):
        def response(*args, **kw):
            if '802-11-wireless.ssid' in args: return result('Home\n')
            if 'GENERAL.CON-UUID' in args: return result('uuid\n')
            return result()
        with patch.object(helper,'run',side_effect=response) as run, patch.object(helper,'network_status',return_value={'devices':{}}):
            self.assertTrue(helper.manage_saved_network('disconnect',{'ssid':'Home','saved_uuid':'uuid'})['ok'])
        calls=[c.args for c in run.call_args_list]
        self.assertIn(('--wait','15','device','disconnect','wlan0'),calls)
        self.assertFalse(any('delete' in c or 'modify' in c for c in calls))

    def test_stale_selection_cannot_disconnect_another_network(self):
        with patch.object(helper,'run',side_effect=[result('Home\n'),result('other-uuid\n')]) as run:
            self.assertFalse(helper.manage_saved_network('disconnect',{'ssid':'Home','saved_uuid':'uuid'})['ok'])
        self.assertEqual(run.call_count,2)

    def test_forget_removes_only_validated_profile(self):
        with patch.object(helper,'run',side_effect=[result('Home\n'),result()]) as run, patch.object(helper,'network_status',return_value={'devices':{}}):
            reply=helper.manage_saved_network('forget',{'ssid':'Home','saved_uuid':'uuid'})
        self.assertEqual(reply['forgotten_uuid'],'uuid')
        self.assertEqual(run.call_args.args,('connection','delete','uuid','uuid'))

    def test_forget_rejects_mismatched_profile(self):
        with patch.object(helper,'run',return_value=result('Other\n')) as run:
            self.assertFalse(helper.manage_saved_network('forget',{'ssid':'Home','saved_uuid':'uuid'})['ok'])
        self.assertEqual(run.call_count,1)

    def test_scan_preserves_escaped_ssids_and_prefers_connected_bssid(self):
        data=':Home\\: West:WPA2:90\n*:Home\\: West:WPA2:40\n:Cafe:--:70\n'
        with patch.object(helper,'run',return_value=result(data)),patch.object(helper,'saved_networks',return_value={'Home: West':'uuid'}):
            networks=helper.scan_networks()['networks']
        self.assertEqual(len(networks),2)
        self.assertEqual(networks[0]['ssid'],'Home: West')
        self.assertTrue(networks[0]['active'])
        self.assertEqual(networks[0]['saved_uuid'],'uuid')

    def test_saved_reconnection_does_not_overwrite_password(self):
        def response(*args,**kw):
            return result('Home\n' if '802-11-wireless.ssid' in args else '')
        with patch.object(helper,'run',side_effect=response) as run:
            name,message=helper.ensure_persistent_profile('Home','',saved_uuid='uuid')
        self.assertIsNotNone(name)
        calls=[c.args for c in run.call_args_list]
        self.assertFalse(any('802-11-wireless-security.psk' in c or 'password' in c for c in calls))
        self.assertIn(('--wait','30','connection','up','uuid','uuid','ifname','wlan0'),calls)

    def test_wrong_saved_profile_cannot_activate(self):
        with patch.object(helper,'run',return_value=result('Other\n')) as run:
            name,_=helper.ensure_persistent_profile('Home','',saved_uuid='uuid')
        self.assertIsNone(name)
        self.assertEqual(run.call_count,1)

    def test_open_network_connect_has_no_password_or_wpa_setting(self):
        with patch.object(helper,'connection_exists',return_value=False),patch.object(helper,'run',return_value=result()) as run:
            name,_=helper.ensure_persistent_profile('Cafe','',open_network=True)
        self.assertIsNotNone(name)
        for call in run.call_args_list:
            self.assertNotIn('password',call.args)
            self.assertNotIn('802-11-wireless-security.psk',call.args)

    def test_bad_password_does_not_invoke_nmcli(self):
        with patch.object(helper,'run') as run:
            name,_=helper.ensure_persistent_profile('Home','short')
        self.assertIsNone(name)
        run.assert_not_called()

    def test_country_is_validated_before_privileged_call(self):
        with patch.object(helper,'wifi_countries',return_value=[{'code':'US','name':'United States'}]),patch.object(helper.subprocess,'run') as run:
            self.assertFalse(helper.set_wifi_country('ZZ')['ok'])
        run.assert_not_called()

    def test_country_applies_only_the_selected_code(self):
        with patch.object(helper,'wifi_countries',return_value=[{'code':'US','name':'United States'}]),patch.object(helper.subprocess,'run',return_value=result()) as run:
            self.assertEqual(helper.set_wifi_country('US')['country'],'US')
        self.assertEqual(run.call_args.args[0],['raspi-config','nonint','do_wifi_country','US'])

if __name__=='__main__': unittest.main()
