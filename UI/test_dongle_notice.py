"""USB notices are passive until Yes; hotplug/reboot and deliberate receiver assignment."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import dongle_notice
from dongle_notice import USBNotices,NoticeView,inject_notice,scan_status
from rtl_registry import DongleRegistry,same_usb_attachment


def device(serial='10000012',port='3-1.4.1',address=10,conflict=False):
    return dict(id='port:'+port if conflict else 'serial:'+serial,name='RTL',product='Blog V4L',serial=serial,usb_path=port,bus=3,address=address,duplicate=conflict,persistent=not conflict,nickname='Roof antenna')


class NoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.registry=DongleRegistry(self.tmp.name)
        self.scanner=Mock(return_value=[device()],spec=[]);self.service=USBNotices(self.scanner,self.registry)
    def tearDown(self):self.service.close();self.tmp.cleanup()

    def test_new_at_boot_shown_once_and_later_survives_restart(self):
        self.service.observe([device()]);first=self.service.notice
        self.assertEqual(first['kind'],'discovery');self.assertEqual(first['timeout_seconds'],180)
        self.service.dismiss(first['id']);self.service.observe([device()])
        self.assertIsNone(self.service.notice)
        reboot=USBNotices(self.scanner,self.registry);reboot.observe([device(address=11)])
        self.assertIsNone(reboot.notice)
        self.scanner.assert_not_called()

    def test_known_at_boot_stays_quiet_even_with_stale_reconnect_record(self):
        a=device();self.registry.records[a['id']]=dict(a,eeprom=dict(status='verified',serial='10000099'))
        service=USBNotices(self.scanner,self.registry);service.observe([a])
        self.assertIsNone(service.notice);self.assertEqual(len(service.snapshot()['receivers']),1)

    def test_existing_duplicates_remind_once_per_boot_without_writing(self):
        rows=[device('00000001',conflict=True),device('00000001','3-1.2',11,True)]
        self.registry.records={r['id']:r for r in rows}
        service=USBNotices(self.scanner,self.registry)
        with patch.object(self.registry,'assign_id') as write:
            service.observe(rows);n=service.notice
            self.assertEqual(n['title'],'Duplicate ID found');self.assertTrue(n['startup'])
            self.assertTrue(n['duplicate_warning']);self.assertEqual(len(n['receivers']),2)
            self.assertEqual(n['timeout_seconds'],180)
            v=NoticeView();v.update(n,100);v.update(n,279.9);self.assertIsNotNone(v.notice)
            v.update(n,280);self.assertIsNone(v.notice)
            service.dismiss(n['id']);service.observe(rows);self.assertIsNone(service.notice)
            reboot=USBNotices(self.scanner,self.registry);reboot.observe(rows)
            self.assertTrue(reboot.notice['startup'])
            with patch('dongle_notice.time.time',return_value=reboot.notice['expires_at']+1):self.assertIsNone(reboot.snapshot()['notice'])
            reboot.observe(rows);self.assertIsNone(reboot.notice)
            write.assert_not_called()

    def test_hotplug_notice_only_new_device_and_expires(self):
        a=device();self.service.observe([a]);self.service.dismiss(self.service.notice['id'])
        b=device('10000013','3-1.2',11);self.service.observe([a,b]);n=self.service.notice
        self.assertEqual(n['kind'],'arrival');self.assertEqual([r['id'] for r in n['receivers']],[b['id']])
        v=NoticeView();v.update(n,100);v.update(n,114.9);self.assertIsNotNone(v.notice)
        v.update(n,115);self.assertIsNone(v.notice);v.update(n,200);self.assertIsNone(v.notice)
        self.service.observe([a,b]);self.assertEqual(self.service.notice['id'],n['id'])
        with patch('dongle_notice.time.time',return_value=n['expires_at']+1):self.assertIsNone(self.service.snapshot()['notice'])
        self.service.observe([a]);self.service.observe([a,dict(b,address=22)])
        self.assertEqual(self.service.notice['kind'],'arrival','Every physical replug gets a short notice')

    def test_conflict_is_sticky_cancel_does_not_write_and_yes_targets_verified_port(self):
        self.service.details=True  # Explicitly opened receiver management.
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
        self.service.details=True  # Explicitly opened receiver management.
        a=device('00000001',conflict=True);a.pop('bus');self.service.observe([a])
        self.assertFalse(self.service.notice['can_assign'])
        with self.assertRaises(ValueError):self.service.assign(self.service.notice['id'],a['id'])

    def test_success_waits_for_reconnect_then_becomes_ready(self):
        self.service.details=True  # Explicitly opened receiver management.
        a=device('00000001',conflict=True);self.service.observe([a])
        self.registry.aliases[a['id']]='serial:10000014'
        self.registry.records['serial:10000014']=dict(product='Blog V4L',serial=a['serial'],usb_path=a['usb_path'],eeprom=dict(status='verified',serial='10000014'))
        op=dict(id=a['id'],action='program',running=False,ok=True)
        self.service.observe([a],op);notice=self.service.notice
        self.assertEqual(notice['kind'],'reconnect');self.assertEqual(notice['pending_reconnects'][0]['serial'],'10000014')
        self.service.observe([],op);self.assertEqual(self.service.notice['kind'],'reconnect')
        self.service.observe([device('10000014',address=12)],op)
        self.assertEqual(self.service.notice['kind'],'ready')

    def test_pending_reconnect_is_only_shown_on_explicit_review(self):
        a=device('00000001');self.registry.records[a['id']]=dict(a,eeprom=dict(status='verified',serial='10000014'))
        service=USBNotices(self.scanner,self.registry);service.observe([a]);self.assertIsNone(service.notice)
        b=device('10000015','3-1.4.2',12);service.observe([a,b])
        self.assertEqual(service.notice['kind'],'arrival');self.assertEqual(len(service.notice['receivers']),1)
        restart=USBNotices(self.scanner,self.registry);restart.observe([a,b]);self.assertIsNone(restart.notice)
        service.details=True;service.previous=None;service.observe([a,b])
        self.assertEqual(service.notice['kind'],'reconnect')
        service.observe([device('10000014','3-9',13),b])
        self.assertEqual(service.notice['kind'],'ready','New serial at another port clears stale reconnect')

    def test_multiple_choices_queue_separately_and_writes_are_serialized(self):
        self.service.details=True  # Explicitly opened receiver management.
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
        self.service.details=True  # Explicitly opened receiver management.
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
        self.assertEqual(len(self.service.snapshot()['receivers']),2)
        self.scanner.assert_not_called();self.assertEqual(self.registry.records,{})

    def test_program_failure_reports_error_without_fake_reconnect(self):
        self.service.details=True  # Explicitly opened receiver management.
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
        self.service.details=True  # Explicitly opened receiver management.
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

    def test_open_native_popup_moves_to_new_fifth_radio_while_reconnect_is_pending(self):
        self.service.details=True  # Explicitly opened receiver management.
        from dongle_notice_touch import USBNoticePopup
        a=device('00000001')
        self.registry.records[a['id']]=dict(a,eeprom=dict(status='verified',serial='10000014'))
        rows=[a]+[device(str(10000020+i),f'3-1.{i+2}',20+i) for i in range(3)]
        self.scanner.return_value=rows;self.service._check()
        popup=USBNoticePopup(Mock(),self.service);popup.draw(Mock());first=popup.view.last
        self.assertEqual(popup.page,0)
        fifth=device('10000030','3-1.9',30);self.scanner.return_value=[*rows,fifth]
        self.service._check();popup.draw(Mock())
        self.assertTrue(popup.visible());self.assertNotEqual(first,popup.view.last)
        self.assertEqual(len(popup.view.notice['receivers']),5);self.assertEqual(popup.page,1)
        self.assertEqual(popup.view.notice['arrived_ports'],['3-1.9'])
        self.assertEqual(popup.view.notice['receivers'][0]['state'],'reconnect')
        self.assertIn('5 connected',scan_status(self.service.snapshot()))
        # Ordinary checks leave the user's chosen page and notice alone.
        popup.page=0;self.service._check();popup.draw(Mock());self.assertEqual(popup.page,0)
        self.service.refresh();self.assertTrue(self.service.wake.is_set())

    def test_scan_failure_is_visible_and_next_check_recovers_without_programming(self):
        self.scanner.side_effect=[[device()],KeyError('USB descriptor disappeared'),[device(),device('10000015','3-1.2',11)]]
        with patch.object(self.registry,'assign_id') as write:
            self.service._check();stamp=self.service.snapshot()['checked_at']
            with self.assertLogs('dongle_notice',level='WARNING'):self.service._check()
            state=self.service.snapshot()
            self.assertEqual(state['checked_at'],stamp);self.assertFalse(state['checking'])
            self.assertIn('USB check failed',scan_status(state))
            self.service._check();state=self.service.snapshot()
            self.assertEqual(state['scan_error'],'');self.assertEqual(len(state['receivers']),2)
            self.assertIn('waiting for USB check',scan_status(state,now=state['checked_at']+20))
            write.assert_not_called()

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
            s=json.load(urlopen(base+'/api/dongle-notice'));self.assertTrue(s['notice']['duplicate_warning'])
            page=urlopen(base+'/').read();self.assertIn(b'/dongle-notice.js',page)
            self.assertEqual(inject_notice(page),page)
            request=Request(base+'/api/dongle-notice',data=b'{"action":"assign_id"}',headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as e:urlopen(request)
            self.assertEqual(e.exception.code,403)
            request=Request(base+'/api/dongle-notice',data=b'{"action":"refresh"}',headers={'X-USB-Notice-Token':s['control_token']})
            self.assertTrue(json.load(urlopen(request))['ok']);self.assertTrue(self.service.wake.is_set())
            with patch.object(self.registry,'assign_id') as write:
                r=Request(base+'/api/dongle-notice',data=json.dumps(dict(action='assign_id',event=s['notice']['id'],target=device('00000001',conflict=True)['id'])).encode(),headers={'X-USB-Notice-Token':s['control_token'],'Origin':'http://unrelated.test'})
                with self.assertRaises(HTTPError):urlopen(r)
                write.assert_not_called()
        finally:manager.close();dongle_notice.SERVICE=old

class StartChoiceTests(unittest.TestCase):
    setUp=NoticeTests.setUp
    tearDown=NoticeTests.tearDown
    # Exercise real start decisions without accessing RF hardware.
    def request(self,rows=None,selection='auto',blocked=()):
        rows=rows if rows is not None else [device()]
        self.scanner.return_value=rows;self.service.observe(rows)
        self.configure=Mock();self.start=Mock()
        self.service.require_receiver('ais',selection,rows,self.configure,self.start,blocked)

    def test_unassigned_start_requires_choice_even_with_one_radio(self):
        with self.assertRaises(ValueError):self.request()
        n=self.service.notice;self.assertEqual(n['kind'],'select');self.start.assert_not_called()
        self.service.choose(n['id'],device()['id'])
        self.configure.assert_called_once_with(device()['id']);self.start.assert_called_once()
        with self.assertRaises(ValueError):self.service.choose(n['id'],device()['id'])

    def test_valid_assignment_bypasses_picker(self):
        self.request(selection=device()['id']);self.configure.assert_not_called();self.start.assert_not_called()
        self.assertNotEqual(self.service.notice['kind'],'select')

    def test_cancel_does_not_assign_or_start_and_does_not_reopen(self):
        with self.assertRaises(ValueError):self.request()
        self.service.dismiss(self.service.notice['id']);self.service.observe([device()])
        self.assertIsNone(self.service.notice);self.configure.assert_not_called();self.start.assert_not_called()

    def test_disconnected_assignment_lists_other_receivers_without_starting(self):
        with self.assertRaises(ValueError):self.request(selection='serial:missing')
        self.assertEqual(self.service.notice['kind'],'select');self.start.assert_not_called()

    def test_duplicate_warning_only_after_choosing_that_receiver(self):
        a=device('00000001',conflict=True);b=device('00000001','3-1.2',11,True)
        with self.assertRaises(ValueError):self.request([a,b])
        self.assertEqual(self.service.notice['kind'],'select')
        with patch.object(self.registry,'assign_id') as write:
            self.service.choose(self.service.notice['id'],a['id'])
            self.assertEqual(self.service.notice['kind'],'conflict')
            write.assert_not_called();self.configure.assert_not_called();self.start.assert_not_called()
        self.service.dismiss(self.service.notice['id']);self.service.observe([a,b]);self.assertIsNone(self.service.notice)

    def test_unique_factory_serial_does_not_require_eeprom_write(self):
        a=device('00000001')
        with self.assertRaises(ValueError):self.request([a])
        with patch.object(self.registry,'assign_id') as write:self.service.choose(self.service.notice['id'],a['id']);write.assert_not_called()
        self.start.assert_called_once()

    def test_unplug_or_reenumerate_between_choice_and_click_is_rejected(self):
        for rows in ([],[device(address=99)]):
            with self.assertRaises(ValueError):self.request()
            self.scanner.return_value=rows
            with self.assertRaises(ValueError):self.service.choose(self.service.notice['id'],device()['id'])
            self.start.assert_not_called()

    def test_no_receivers_picker_survives_empty_scan_and_updates_hotplug(self):
        with self.assertRaises(ValueError):self.request([])
        self.service.observe([]);self.assertEqual(self.service.notice['kind'],'select')
        self.service.observe([device()]);self.assertEqual(self.service.notice['kind'],'select')
        self.assertEqual(len(self.service.notice['receivers']),1)

    def test_busy_and_blocked_receivers_cannot_be_claimed(self):
        from sdr_broker import ReceiverBroker
        self.service.broker=ReceiverBroker();self.service.broker.acquire('adsb',device()['id'])
        with self.assertRaises(ValueError):self.request()
        self.assertFalse(self.service.notice['receivers'][0]['can_choose'])
        with self.assertRaises(ValueError):self.service.choose(self.service.notice['id'],device()['id'])
        self.start.assert_not_called()
        with self.assertRaises(ValueError):self.request(blocked=[device()['id']])
        self.assertEqual(self.service.notice['receivers'],[])

    def test_duplicate_hotplug_offers_fix_without_programming(self):
        a=device('00000001');self.service.observe([a]);self.service.dismiss(self.service.notice['id'])
        a=device('00000001',conflict=True);b=device('00000001','3-1.2',11,True)
        self.service.observe([a,b]);n=self.service.notice
        self.assertTrue(n['duplicate_warning']);self.assertEqual(n['target'],b['id']);self.assertEqual(n['timeout_seconds'],180)
        from dongle_notice_touch import USBNoticePopup
        popup=USBNoticePopup(Mock(),self.service);popup.draw(Mock())
        self.assertTrue(popup.visible());self.assertIn('review',[a[0] for _,a in popup.actions])
        with patch.object(self.registry,'assign_id') as write:
            self.service.review(n['id']);write.assert_not_called()
            self.assertEqual(self.service.notice['target'],b['id'])
            self.assertEqual(self.service.notice['kind'],'conflict')

    def test_hotplug_toast_does_not_capture_native_touch(self):
        from dongle_notice_touch import USBNoticePopup,NoticeTouchCapture
        self.service.observe([]);self.service.observe([device()]);popup=USBNoticePopup(Mock(),self.service)
        popup.draw(Mock());self.assertFalse(popup.visible());self.assertEqual(popup.actions,[])
        self.assertFalse(NoticeTouchCapture().handle(True,400,700,popup,12))

class DecoderStartIntegrationTests(unittest.TestCase):
    setUp=NoticeTests.setUp
    tearDown=NoticeTests.tearDown

    def test_vhf_tools_and_spectrum_require_assignment_before_claiming(self):
        from vhf_monitor import VHFHub
        self.service.observe([device()]);old=dongle_notice.SERVICE;dongle_notice.SERVICE=self.service
        try:
            with patch('threading.Thread.start'):
                hub=VHFHub(root=Path(self.tmp.name)/'vhf',port=-1,scanner=self.scanner)
                hub.devices=[device()];self.service.broker=hub.broker
                for session in hub.sessions.values():
                    with self.subTest(mode=session.mode):
                        session.enabled=False
                        with self.assertRaisesRegex(ValueError,'Choose a USB receiver'):session.control('start')
                        self.assertFalse(session.enabled);self.assertEqual(hub.broker.snapshot(),{})
                        session.control('configure',selection=device()['id']);session.control('start');self.assertTrue(session.enabled)
                        session.enabled=False
                with self.assertRaisesRegex(ValueError,'Choose a USB receiver'):hub.spectrum.control('start')
                self.assertFalse(hub.spectrum.enabled)
                self.service.choose(self.service.notice['id'],device()['id'])
                self.assertTrue(hub.spectrum.enabled);self.assertEqual(hub.spectrum.settings['selection'],device()['id'])
                hub.spectrum.enabled=False
        finally:dongle_notice.SERVICE=old

    def test_adsb_and_uat_require_assignment_before_enabling(self):
        from adsb_monitor import ADSBManager
        self.service.observe([device()]);old=dongle_notice.SERVICE;dongle_notice.SERVICE=self.service
        try:
            with patch('threading.Thread.start'):
                manager=ADSBManager(root=Path(self.tmp.name)/'adsb',scanner=self.scanner,port=-1)
                manager.devices=[device()]
                for band in ('1090','978'):
                    with self.subTest(band=band):
                        receiver=manager.uat if band=='978' else manager
                        receiver.enabled=False
                        with self.assertRaisesRegex(ValueError,'Choose a USB receiver'):manager.control('start',band=band)
                        self.assertFalse(receiver.enabled)
                        self.service.choose(self.service.notice['id'],device()['id'])
                        self.assertTrue(receiver.enabled);self.assertEqual(receiver.selection,device()['id'])
                        receiver.enabled=False
        finally:dongle_notice.SERVICE=old
