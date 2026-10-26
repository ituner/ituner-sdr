"""Identity, persistence and hardware-write guards for duplicate RTL receivers."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rtl_registry import DongleRegistry, identify, serial_image
from sdr_broker import ReceiverBroker


def physical(port,bus,address,serial='00001000'):
    return dict(usb_path=port,bus=bus,address=address,serial=serial,vendor='0bda',product_id='2832',manufacturer='Realtek',product='RTL2832U')


def raw_rows():return [dict(index=0,name='RTL',serial='',manufacturer='',product=''),dict(index=1,name='RTL',serial='00001000',manufacturer='Realtek',product='RTL2832U')]


def image(serial='00001000'):
    data=bytearray(256);data[:9]=bytes([0x28,0x32,0xda,0x0b,0x32,0x28,0xa5,0x14,2]);offset=9
    for text in ('Realtek','RTL2832U',serial):
        b=text.encode('utf-16le');data[offset:offset+len(b)+2]=bytes([len(b)+2,3])+b;offset+=len(b)+2
    return bytes(data)


class InventoryTests(unittest.TestCase):
    def test_actual_libusb_order_not_sorted_ports_and_missing_strings(self):
        rows=identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[(3,2),(1,6)])
        self.assertEqual([r['usb_path'] for r in rows],['3-1','1-1'])
        self.assertEqual([r['serial'] for r in rows],['00001000']*2)
        self.assertTrue(all(r['duplicate'] and not r['persistent'] for r in rows))
        self.assertEqual(rows[0]['id'],'port:3-1')

    def test_unreadable_receiver_cannot_make_other_look_unique(self):
        rows=identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[])
        self.assertFalse(any(r['persistent'] for r in rows))
        self.assertTrue(rows[1]['duplicate'])

    def test_ambiguous_order_never_associates_wrong_port(self):
        rows=identify(raw_rows(),[physical('1-1',1,6)],[(1,6)])
        self.assertNotIn('usb_path',rows[0])

    def test_saved_nickname_survives_but_disconnected_history_is_not_a_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp)
            rows=reg.remember(identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[(3,2),(1,6)]))
            reg.rename(rows[0]['id'],'Roof receiver')
            reg=DongleRegistry(tmp)
            single=reg.remember(identify([raw_rows()[0]],[physical('3-1',3,8)],[(3,8)],reg.shared_serials()))
            self.assertEqual(single[0]['nickname'],'Roof receiver');self.assertTrue(single[0]['persistent']);self.assertFalse(single[0]['duplicate'])
            history=reg.snapshot(single)['dongles']
            self.assertEqual(len(history),2);self.assertEqual(sum(r['connected'] for r in history),1)
            self.assertEqual(len(reg.snapshot([])['dongles']),2)

    def test_history_ghost_records_do_not_flag_a_sole_factory_serial(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);reg.shared.add('00000001')
            reg.records['slot:old']=dict(id='slot:old',serial='00000001',duplicate=True)
            rows=reg.remember(identify([dict(index=0,name='V4L',serial='00000001')],[physical('1-1',1,6,'00000001')],[(1,6)],reg.shared_serials()))
            self.assertFalse(rows[0]['duplicate']);self.assertTrue(rows[0]['persistent'])
            self.assertTrue(all(not r['duplicate'] for r in reg.snapshot(rows)['dongles']))

    def test_new_collision_preserves_the_original_receiver_nickname_and_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp)
            rows=reg.remember(identify([dict(index=0,name='RTL',serial='00000001')],[physical('1-1',1,6,'00000001')],[(1,6)]))
            reg.rename(rows[0]['id'],'Original antenna')
            rows=reg.remember(identify([dict(index=i,name='RTL',serial='00000001') for i in range(2)],[physical('1-1',1,6,'00000001'),physical('1-2',1,7,'00000001')],[(1,6),(1,7)]))
            self.assertEqual(rows[0]['nickname'],'Original antenna');self.assertEqual(rows[1]['nickname'],'')
            self.assertEqual(reg.resolve('serial:00000001',rows),'port:1-1')

    def test_pending_write_is_not_repeated_and_selection_follows_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp)
            reg.records['port:1-1']=dict(id='port:1-1',usb_path='1-1',serial='00000001',replacement_id='serial:10000014',eeprom=dict(status='verified',serial='10000014'))
            reg.records['serial:10000014']=dict(id='serial:10000014',usb_path='1-1',serial='10000014',eeprom=dict(status='verified',serial='10000014'))
            reg.aliases['port:1-1']='serial:10000014'
            rows=reg.remember(identify([dict(index=0,name='RTL',serial='00000001')],[physical('1-1',1,6,'00000001')],[(1,6)]))
            self.assertTrue(next(r for r in reg.snapshot(rows)['dongles'] if r['connected'])['needs_reconnect'])
            with patch('rtl_registry.threading.Thread.start') as launch:
                with self.assertRaisesRegex(ValueError,'already saved'):reg.assign_id(rows[0]['id'],'',lambda:rows,None)
                launch.assert_not_called()
            rows=reg.remember(identify([dict(index=0,name='RTL',serial='10000014')],[physical('1-1',1,7,'10000014')],[(1,7)]))
            self.assertEqual(reg.resolve('serial:00000001',rows),'serial:10000014')
            self.assertEqual(reg.resolve('port:1-1',rows),'serial:10000014')
            self.assertFalse(reg.snapshot(rows)['dongles'][0]['needs_reconnect'])

    def test_maintenance_blocks_every_decoder_and_releases(self):
        broker=ReceiverBroker();self.assertTrue(broker.acquire('dongle-maintenance','port:3-1'))
        self.assertFalse(broker.acquire('adsb','port:1-1'))
        broker.release('dongle-maintenance');self.assertTrue(broker.acquire('adsb','port:1-1'))

    def test_unsafe_hardware_operations_do_not_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);rows=reg.remember(identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[(3,2),(1,6)]))
            with patch('rtl_registry.threading.Thread.start') as launch:
                with self.assertRaisesRegex(ValueError,'Test EEPROM'):reg.start(rows[0]['id'],'program',lambda:rows,ReceiverBroker(),'10000011')
                with self.assertRaisesRegex(ValueError,'eight digits'):reg.start(rows[0]['id'],'program',lambda:rows,ReceiverBroker(),'00000000')
                with self.assertRaisesRegex(ValueError,'Stop SDR'):reg.start(rows[0]['id'],'probe',lambda:rows,ReceiverBroker(),busy=lambda:True)
                launch.assert_not_called()

    def test_program_verifies_bytes_preserves_name_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);rows=reg.remember(identify([raw_rows()[0]],[physical('3-1',3,2)],[(3,2)],{'00001000'}));d=rows[0]
            reg.rename(d['id'],'Roof');reg.records[d['id']]['eeprom']={'status':'readable'};broker=ReceiverBroker();calls=[]
            def tool(index,*args):
                calls.append(args)
                if args[0]=='-r':Path(args[1]).write_bytes(image())
            with patch.object(reg,'tool',side_effect=tool),patch.object(reg,'program') as program:
                reg._operate(d['id'],d,'program','10000011',lambda:rows,broker,lambda:False)
                program.assert_called_once()
            self.assertTrue(reg.operation['ok']);self.assertEqual(reg.records['serial:10000011']['nickname'],'Roof')
            self.assertEqual(reg.records['serial:10000011']['eeprom']['status'],'verified');self.assertEqual(broker.snapshot(),{})
            self.assertEqual([c[0] for c in calls],['-r'])

    def test_nonstandard_eeprom_is_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);rows=reg.remember(identify([raw_rows()[0]],[physical('3-1',3,2)],[(3,2)]));d=rows[0];calls=[]
            raw=bytearray(image());raw[6]=0
            def tool(index,*args):
                calls.append(args[0]);Path(args[1]).write_bytes(raw)
            with patch.object(reg,'tool',side_effect=tool):reg._operate(d['id'],d,'program','10000011',lambda:rows,ReceiverBroker(),lambda:False)
            self.assertFalse(reg.operation['ok']);self.assertEqual(calls,['-r'])

    def test_native_dongle_registry_has_back_and_rename_in_both_themes(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        from copy import deepcopy
        import theme_system
        from decoder_style import full_width_back_box
        from dongle_workspace import DongleWorkspace
        original=deepcopy(theme_system.runtime_theme)
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);rows=reg.remember(identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[(3,2),(1,6)]))
            ui=Mock();ui.fit_station_text.side_effect=lambda cache,text,*args:text
            w=DongleWorkspace(ui,SimpleNamespace(devices=rows))
            try:
                with patch('dongle_workspace.REGISTRY',reg):
                    w.show()
                    for side in ('left','right'):
                        theme=deepcopy(original);theme['sidebar']=side;theme_system.apply_theme(theme)
                        for selected in (None,reg.snapshot(rows)['dongles'][0]):
                            w.selected=selected;w.serial='';w.draw(Mock())
                            self.assertIn((full_width_back_box(),('back',None)),w.actions)
                            self.assertTrue(any(a[0] in ('select','edit') for _,a in w.actions))
                            for box,action in w.actions:
                                if action[0]!='back':
                                    back=full_width_back_box()
                                    self.assertFalse(min(box[2],back[2])>max(box[0],back[0]) and min(box[3],back[3])>max(box[1],back[1]))
                    w.field='Nickname';w.value='Roof';w.keyboard(Mock())
                    self.assertIn(('key','DONE'),[a for _,a in w.actions])
            finally:theme_system.apply_theme(original)

    def test_web_registry_uses_shared_saved_names_and_requires_same_origin_token(self):
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from adsb_monitor import ADSBManager
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(Path(tmp)/'registry')
            rows=reg.remember(identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[(3,2),(1,6)]))
            manager=ADSBManager(root=Path(tmp)/'adsb',scanner=lambda:rows,port=0)
            base=f'http://127.0.0.1:{manager.port}'
            try:
                with patch('dongle_web.REGISTRY',reg):
                    state=json.load(urlopen(base+'/api/dongles'));self.assertEqual(len(state['dongles']),2)
                    self.assertIn(b'Rename receiver',urlopen(base+'/dongles').read())
                    body=json.dumps(dict(action='rename',id=rows[0]['id'],nickname='Roof')).encode()
                    with self.assertRaises(HTTPError) as error:urlopen(Request(base+'/api/dongles',body))
                    self.assertEqual(error.exception.code,403)
                    headers={'X-Dongle-Token':state['control_token'],'Content-Type':'application/json'}
                    result=json.load(urlopen(Request(base+'/api/dongles',body,headers)))
                    self.assertEqual(next(r for r in result['dongles'] if r['id']==rows[0]['id'])['nickname'],'Roof')
                    with self.assertRaises(HTTPError) as error:urlopen(Request(base+'/api/dongles',body,dict(headers,Origin='https://other.example')))
                    self.assertEqual(error.exception.code,403)
            finally:manager.close()

    def test_legacy_verified_serial_repairs_inherited_duplicate_and_merges_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=dict(status='verified',serial='10000011')
            port=dict(id='port:1-1',serial='10000011',duplicate=True,usb_path='1-1',eeprom=e,nickname='Roof',replacement_id='serial:10000011',last_seen=50)
            serial=dict(port,id='serial:10000011',nickname='',last_seen=40);serial.pop('replacement_id')
            old=dict(id='port:3-1',serial='00001000',duplicate=True,usb_path='3-1')
            Path(tmp,'registry.json').write_text(json.dumps({port['id']:port,serial['id']:serial,old['id']:old}))
            reg=DongleRegistry(tmp)
            self.assertNotIn('10000011',reg.shared_serials());self.assertIn('00001000',reg.shared_serials())
            self.assertNotIn('port:1-1',reg.records)
            rows=reg.remember(identify([raw_rows()[0]],[physical('1-1',1,12,'10000011')],[(1,12)],reg.shared_serials()))
            self.assertFalse(rows[0]['duplicate']);self.assertTrue(rows[0]['persistent']);self.assertEqual(rows[0]['nickname'],'Roof')
            self.assertEqual(reg.resolve('port:1-1',rows),'serial:10000011')
            self.assertEqual(DongleRegistry(tmp).resolve('port:1-1',rows),'serial:10000011')

    def test_resolving_one_of_two_duplicates_makes_the_remaining_receiver_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp)
            rows=reg.remember(identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[(3,2),(1,6)]))
            reg.records['serial:10000011']=dict(id='serial:10000011',serial='10000011',previous_serial='00001000',eeprom=dict(status='verified',serial='10000011'),nickname='')
            reg.records.pop('port:1-1')
            def scan():
                raw=[dict(index=0,name='RTL',serial='00001000'),dict(index=1,name='RTL',serial='10000011')]
                return reg.remember(identify(raw,[physical('3-1',3,2),physical('1-1',1,7,'10000011')],[(3,2),(1,7)],reg.shared_serials()))
            scan();rows=scan()
            self.assertTrue(all(r['persistent'] and not r['duplicate'] for r in rows))
            self.assertEqual(set(reg.records),{'serial:00001000','serial:10000011'})

    def test_quick_assign_generates_unused_serial_pauses_resumes_and_preserves_optional_name(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);rows=reg.remember(identify([raw_rows()[0]],[physical('1-1',1,6,'00000001')],[(1,6)],{'00001000'}))
            reg.records['serial:10000011']=dict(serial='10000011',id='serial:10000011')
            broker=ReceiverBroker();enabled=[True];broker.acquire('adsb',rows[0]['id'])
            def stop():enabled[0]=False;broker.release('adsb')
            def resume():enabled[0]=True
            broker.register('adsb',stop,resume,lambda:enabled[0])
            def tool(index,*args):Path(args[1]).write_bytes(image('00000001'))
            with patch('rtl_registry.threading.Thread') as thread,patch.object(reg,'tool',side_effect=tool),patch.object(reg,'program') as program:
                reg.assign_id(rows[0]['id'],'',lambda:rows,broker,lambda:enabled[0])
                thread.call_args.kwargs['target']()
                program.assert_called_once();self.assertEqual(program.call_args.args[2],'10000012')
            self.assertTrue(enabled[0]);self.assertTrue(reg.operation['ok']);self.assertFalse(reg.records['serial:10000012']['duplicate'])
            new=reg.remember(identify([raw_rows()[0]],[physical('1-1',1,7,'10000012')],[(1,7)],reg.shared_serials()))
            self.assertFalse(new[0]['duplicate']);self.assertTrue(new[0]['persistent'])
            self.assertEqual(reg.resolve(rows[0]['id'],new),'serial:10000012')
            self.assertNotIn('Unplug',new[0]['eeprom']['message'])

    def test_serial_only_writer_preserves_vendor_bytes_and_verifies_in_one_handle(self):
        from rtl_eeprom_access import change_serial
        original=bytearray(image());original[8]=0x12;original[78]=42
        class Device:
            data=bytes(original)
            calls=[]
            def read(self):return self.data
            def write(self,offset,data):
                self.calls.append((offset,len(data)));self.data=self.data[:offset]+data+self.data[offset+len(data):]
        device=Device();change_serial(device,bytes(original),'10000011')
        self.assertEqual(device.calls,[(43,18)])
        self.assertEqual(device.data[8],0x12);self.assertEqual(device.data[78],42)
        self.assertEqual(device.data,serial_image(bytes(original),'10000011'))
        with self.assertRaisesRegex(ValueError,'differs from its backup'):change_serial(device,bytes(original),'10000012')

    def test_successful_dump_accepts_debian_tool_byte_count_exit(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            backup=Path(tmp)/'dump.bin';backup.write_bytes(image())
            result=SimpleNamespace(returncode=1,stdout='Dump to '+str(backup)+' successful.')
            with patch('rtl_registry.subprocess.run',return_value=result):DongleRegistry.tool(0,'-r',backup)
            result.stdout='Failed to read EEPROM'
            with patch('rtl_registry.subprocess.run',return_value=result):
                with self.assertRaises(ValueError):DongleRegistry.tool(0,'-r',backup)

    def test_quick_assign_targets_one_of_multiple_duplicates_and_retains_other_receiver(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);rows=reg.remember(identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[(3,2),(1,6)]))
            other=dict(reg.records[rows[1]['id']]);broker=ReceiverBroker()
            def tool(index,*args):self.assertEqual(index,0);Path(args[1]).write_bytes(image())
            with patch('rtl_registry.threading.Thread') as thread,patch.object(reg,'tool',side_effect=tool),patch.object(reg,'program') as program:
                reg.assign_id(rows[0]['id'],'V4L A',lambda:rows,broker)
                thread.call_args.kwargs['target']()
                self.assertEqual(program.call_args.args[0]['usb_path'],'3-1')
            self.assertTrue(reg.operation['ok']);self.assertEqual(reg.records[rows[1]['id']],other);self.assertEqual(broker.snapshot(),{})

    def test_factory_serial_can_be_assigned_after_its_duplicate_has_been_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);rows=reg.remember(identify([dict(index=0,name='V4',serial='00000001')],[physical('3-1',3,2,'00000001')],[(3,2)]))
            self.assertFalse(rows[0]['duplicate'])
            def tool(index,*args):Path(args[1]).write_bytes(image('00000001'))
            with patch('rtl_registry.threading.Thread') as thread,patch.object(reg,'tool',side_effect=tool),patch.object(reg,'program') as program:
                reg.assign_id(rows[0]['id'],'V4 B',lambda:rows,ReceiverBroker())
                thread.call_args.kwargs['target']();program.assert_called_once()
            self.assertTrue(reg.operation['ok'])

    def test_inventory_change_before_programming_cancels_with_backup(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            reg=DongleRegistry(tmp);rows=reg.remember(identify(raw_rows(),[physical('1-1',1,6),physical('3-1',3,2)],[(3,2),(1,6)]));d=rows[0]
            changed=[dict(r,address=r['address']+1) if r['id']==d['id'] else r for r in rows]
            scanner=Mock(side_effect=[rows,changed],spec=[])
            def tool(index,*args):Path(args[1]).write_bytes(image())
            with patch.object(reg,'tool',side_effect=tool),patch.object(reg,'program') as program:
                reg._operate(d['id'],d,'program','10000011',scanner,ReceiverBroker(),lambda:False)
                program.assert_not_called()
            self.assertFalse(reg.operation['ok']);self.assertTrue(Path(reg.records[d['id']]['eeprom']['backup']).is_file())

    def test_multi_receiver_handle_is_verified_before_eeprom_access(self):
        from unittest.mock import Mock
        from rtl_eeprom_access import EepromDevice
        lib=Mock();lib.rtlsdr_get_device_count.return_value=2;lib.rtlsdr_open.return_value=0
        rows=[physical('3-1',3,2),physical('1-1',1,6)]
        with patch('rtl_eeprom_access.ctypes.CDLL',return_value=lib),patch('rtl_eeprom_access.usb_order',return_value=[(3,2),(1,6)]),patch('rtl_eeprom_access.usb_inventory',return_value=rows),patch('rtl_eeprom_access.usb_handles',side_effect=[{},{9:'/dev/bus/usb/003/002'},{9:'/dev/bus/usb/003/002'},{9:'/dev/bus/usb/001/006'}]):
            device=EepromDevice(0,3,2)
            with self.assertRaisesRegex(ValueError,'changed or disconnected'):device.write(43,b'bad')
            lib.rtlsdr_write_eeprom.assert_not_called();device.close()
        lib.reset_mock()
        with patch('rtl_eeprom_access.ctypes.CDLL',return_value=lib),patch('rtl_eeprom_access.usb_order',return_value=[(3,2),(1,6)]),patch('rtl_eeprom_access.usb_inventory',return_value=rows),patch('rtl_eeprom_access.usb_handles',side_effect=[{},{9:'/dev/bus/usb/001/006'}]):
            with self.assertRaisesRegex(ValueError,'does not match'):EepromDevice(0,3,2)
            lib.rtlsdr_close.assert_called_once();lib.rtlsdr_write_eeprom.assert_not_called()
        lib.reset_mock()
        with patch('rtl_eeprom_access.ctypes.CDLL',return_value=lib),patch('rtl_eeprom_access.usb_order',return_value=[(1,6),(3,2)]),patch('rtl_eeprom_access.usb_inventory',return_value=rows):
            with self.assertRaisesRegex(ValueError,'USB order changed'):EepromDevice(0,3,2)
            lib.rtlsdr_open.assert_not_called()

    def test_serial_image_only_changes_serial_bytes(self):
        original=image();expected=serial_image(original,'10000011')
        self.assertIn('10000011'.encode('utf-16le'),expected)
        self.assertEqual(len(expected),256)
        self.assertEqual(expected[:45],original[:45])
        with self.assertRaises(ValueError):serial_image(image('short'),'10000011')


if __name__=='__main__':unittest.main()
