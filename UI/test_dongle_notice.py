"""USB notices are passive until Yes; hotplug/reboot and ten-second timeout UX."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import dongle_notice
from dongle_notice import USBNotices,NoticeView,inject_notice
from rtl_registry import DongleRegistry,same_usb_attachment


def device(serial='10000012',port='3-1.4.1',address=10,conflict=False):
    return dict(id='port:'+port if conflict else 'serial:'+serial,name='RTL',product='Blog V4L',serial=serial,usb_path=port,bus=3,address=address,duplicate=conflict,persistent=not conflict,nickname='Roof antenna')


class NoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.registry=DongleRegistry(self.tmp.name)
        self.scanner=Mock(return_value=[device()],spec=[]);self.service=USBNotices(self.scanner,self.registry)
    def tearDown(self):self.service.close();self.tmp.cleanup()

    def test_startup_hotplug_no_repeat_and_reboot(self):
        self.service.observe([device()]);first=self.service.snapshot()['notice']
        self.assertEqual(first['kind'],'ready')
        self.service.observe([device()]);self.assertEqual(self.service.notice['id'],first['id'])
        self.service.observe([dict(device(),nickname='Changed nickname')]);self.assertEqual(self.service.notice['id'],first['id'])
        self.service.observe([device(address=11)]);self.assertNotEqual(self.service.notice['id'],first['id'])
        reboot=USBNotices(self.scanner,self.registry);reboot.observe([device(address=11)])
        self.assertNotEqual(reboot.notice['id'],self.service.notice['id'])
        self.scanner.assert_not_called()

    def test_ready_expires_after_ten_seconds_and_stays_closed_on_refresh(self):
        self.service.observe([device()]);v=NoticeView();v.update(self.service.notice,100)
        v.update(self.service.notice,109.9);self.assertIsNotNone(v.notice)
        v.update(self.service.notice,110);self.assertIsNone(v.notice)
        v.update(self.service.notice,200);self.assertIsNone(v.notice)
        self.service.observe([device(address=11)]);v.update(self.service.notice,201);self.assertIsNotNone(v.notice)
        v.dismiss();v.update(self.service.notice,202);self.assertIsNone(v.notice)

    def test_conflict_is_sticky_cancel_does_not_write_and_yes_targets_verified_port(self):
        a=device('00000001',conflict=True);b=device('00000001','3-1.4.2',11,True)
        self.service.observe([a,b]);v=NoticeView();v.update(self.service.notice,1);v.update(self.service.notice,1000)
        self.assertEqual(v.notice['kind'],'conflict');self.assertIn('Connected receivers',v.notice['message'])
        with patch.object(self.registry,'assign_id') as write:
            v.dismiss();write.assert_not_called()
            with self.assertRaises(ValueError):self.service.assign('stale',a['id'])
            self.service.assign(self.service.notice['id'],a['id'])
            write.assert_not_called()
            self.scanner.return_value=[a,b];self.service._dispatch_next()
            write.assert_called_once_with(a['id'],'Roof antenna',self.scanner,None,allow_unique=True)

    def test_unverified_ports_do_not_offer_hardware_programming(self):
        a=device('00000001',conflict=True);a.pop('bus');self.service.observe([a])
        self.assertFalse(self.service.notice['can_assign'])
        with self.assertRaises(ValueError):self.service.assign(self.service.notice['id'],a['id'])

    def test_success_waits_for_reconnect_then_becomes_ready(self):
        a=device('00000001',conflict=True);self.service.observe([a])
        self.registry.aliases[a['id']]='serial:10000014'
        self.registry.records['serial:10000014']=dict(product='Blog V4L',usb_path=a['usb_path'],eeprom=dict(status='verified',serial='10000014'))
        op=dict(id=a['id'],action='program',running=False,ok=True)
        self.service.observe([a],op);notice=self.service.notice
        self.assertEqual(notice['kind'],'reconnect');self.assertEqual(notice['serial'],'10000014')
        self.service.observe([],op);self.assertEqual(self.service.notice['kind'],'reconnect')
        self.service.observe([device('10000014',address=12)],op)
        self.assertEqual(self.service.notice['kind'],'ready')

    def test_pending_reconnect_never_hides_new_arrival_and_survives_restart(self):
        a=device('00000001');a['usb_path']='3-1.4.1'
        self.registry.records[a['id']]=dict(a,eeprom=dict(status='verified',serial='10000014'))
        self.service.observe([a]);first=self.service.notice['id']
        self.assertEqual(self.service.notice['kind'],'reconnect')
        b=device('10000015','3-1.4.2',12)
        self.service.observe([a,b]);self.assertNotEqual(self.service.notice['id'],first)
        self.assertEqual(len(self.service.notice['receivers']),2)
        self.assertEqual(self.service.notice['receivers'][0]['state'],'reconnect')
        self.assertFalse(self.service.notice['receivers'][0]['can_assign'])
        restart=USBNotices(self.scanner,self.registry);restart.observe([a,b])
        self.assertEqual(restart.notice['pending_reconnects'][0]['serial'],'10000014')
        self.service.observe([b]);self.assertEqual(len(self.service.notice['receivers']),1)
        self.assertEqual(len(self.service.notice['pending_reconnects']),1)
        self.service.observe([device('10000014',a['usb_path'],13),b])
        self.assertEqual(self.service.notice['kind'],'ready')

    def test_multiple_choices_queue_separately_and_writes_are_serialized(self):
        a=device('00000001',conflict=True);b=device('00000001','3-1.4.2',11,True)
        self.scanner.return_value=[a,b];self.service.observe([a,b])
        with patch.object(self.registry,'assign_id') as write:
            self.service.assign(self.service.notice['id'],a['id'])
            self.service.assign(self.service.notice['id'],b['id'])
            self.assertEqual(len(self.service.requests),2);write.assert_not_called()
            with self.assertRaises(ValueError):self.service.assign(self.service.notice['id'],b['id'])
            self.service._dispatch_next();self.assertEqual(write.call_count,1)
            self.registry.operation=dict(running=True,id=a['id'])
            self.service._dispatch_next();self.assertEqual(write.call_count,1)
            self.registry.operation=dict(running=False,id=a['id'],ok=True)
            self.service._dispatch_next();self.assertEqual(write.call_count,2)
            self.assertEqual([call.args[0] for call in write.call_args_list],[a['id'],b['id']])

    def test_queued_receiver_with_changed_attachment_is_not_programmed(self):
        a=device('00000001',conflict=True);self.service.observe([a])
        self.service.assign(self.service.notice['id'],a['id'])
        self.scanner.return_value=[dict(a,address=99)]
        with patch.object(self.registry,'assign_id') as write:
            self.service._dispatch_next();write.assert_not_called()
        self.assertEqual(self.service.notice['receivers'][0]['state'],'failed')

    def test_discovery_during_eeprom_write_reads_descriptors_without_rf_or_registry_changes(self):
        a=device('10000012');self.service.observe([a])
        physical=[dict(a,vendor='0bda',product_id='2838',manufacturer='RTL'),dict(device('10000015','3-1.4.2',11),vendor='0bda',product_id='2838',manufacturer='RTL')]
        with patch('dongle_notice.usb_inventory',return_value=physical),patch('dongle_notice.usb_order',return_value=[(3,10),(3,11)]):
            rows=self.service._scan_during_write()
        self.service.observe(rows,dict(running=True,id=a['id']))
        self.assertEqual(len(self.service.notice['receivers']),2)
        self.scanner.assert_not_called();self.assertEqual(self.registry.records,{})

    def test_program_failure_reports_error_without_fake_reconnect(self):
        a=device('00000001',conflict=True);self.service.observe([a])
        self.service.observe([a],dict(id=a['id'],action='program',running=False,ok=False,message='EEPROM is not writable'))
        self.assertEqual(self.service.notice['receivers'][0]['state'],'failed');self.assertIn('not writable',self.service.notice['receivers'][0]['error'])

    def test_popup_dismiss_consumes_touch_and_uses_shared_renderer(self):
        from dongle_notice_touch import USBNoticePopup
        ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        self.service.observe([device()]);popup=USBNoticePopup(ui,self.service);popup.draw(Mock())
        box=next(b for b,a in popup.actions if a[0]=='dismiss');popup.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
        self.assertFalse(popup.visible());self.scanner.assert_not_called()

    def test_native_can_select_each_conflict_and_keep_ready_selection_open(self):
        from dongle_notice_touch import USBNoticePopup
        ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        rows=[device('00000001',conflict=True),device('00000001','3-1.4.2',11,True)]
        self.service.observe(rows);popup=USBNoticePopup(ui,self.service);popup.draw(Mock())
        choices=[(b,a) for b,a in popup.actions if a[0]=='select']
        self.assertEqual(len(choices),2)
        box,action=choices[1];popup.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
        self.assertEqual(popup.selected,rows[1]['id'])
        self.service.observe([device('00000001')]);popup.draw(Mock())
        box=next(b for b,a in popup.actions if a[0]=='select')
        popup.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
        self.assertIsNone(popup.view.until)

    def test_native_lift_uses_last_position_and_captures_no_click_through(self):
        from dongle_notice_touch import NoticeTouchCapture
        capture=NoticeTouchCapture();popup=Mock();popup.visible.return_value=True
        self.assertTrue(capture.handle(True,900,665,popup,12))
        self.assertTrue(capture.handle(False,0,0,popup,12));popup.tap.assert_called_once_with(900,665)
        popup.tap.reset_mock();capture.handle(True,500,400,popup,12,underlying_started=True)
        capture.handle(False,0,0,popup,12);popup.tap.assert_not_called()
        capture.handle(True,500,400,popup,12);popup.visible.return_value=False
        self.assertTrue(capture.handle(False,0,0,popup,12));popup.tap.assert_not_called()
        self.assertFalse(capture.handle(False,0,0,popup,12))

    def test_same_id_new_usb_address_is_a_new_attachment(self):
        self.assertTrue(same_usb_attachment(device(),device()))
        self.assertFalse(same_usb_attachment(device(),device(address=11)))
        self.assertFalse(same_usb_attachment(device(),device(port='3-1.4.2')))
        self.assertFalse(same_usb_attachment(device(),None))

    def test_http_csrf_and_passive_inventory_and_html_injection(self):
        from adsb_monitor import ADSBManager
        self.service.observe([device('00000001',conflict=True)])
        old=dongle_notice.SERVICE;dongle_notice.SERVICE=self.service
        manager=ADSBManager(root=Path(self.tmp.name)/'adsb',scanner=lambda:[],port=0)
        try:
            base=f'http://127.0.0.1:{manager.port}'
            s=json.load(urlopen(base+'/api/dongle-notice'));self.assertEqual(s['notice']['kind'],'conflict')
            page=urlopen(base+'/').read();self.assertIn(b'/dongle-notice.js',page)
            self.assertEqual(inject_notice(page),page)
            request=Request(base+'/api/dongle-notice',data=b'{"action":"assign_id"}',headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as e:urlopen(request)
            self.assertEqual(e.exception.code,403)
            with patch.object(self.registry,'assign_id') as write:
                r=Request(base+'/api/dongle-notice',data=json.dumps(dict(action='assign_id',event=s['notice']['id'],target=s['notice']['target'])).encode(),headers={'X-USB-Notice-Token':s['control_token'],'Origin':'http://unrelated.test'})
                with self.assertRaises(HTTPError):urlopen(r)
                write.assert_not_called()
        finally:manager.close();dongle_notice.SERVICE=old
