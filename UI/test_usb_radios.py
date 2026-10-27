"""USB management uses actual leases and a shared, six-row picker."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import tempfile
import unittest
from rtl_registry import DongleRegistry
from sdr_broker import ReceiverBroker
from usb_radios import RadioManagement,choices


def device(i):return dict(id='serial:'+str(10000010+i),serial=str(10000010+i),index=i,persistent=True,nickname='',name='RTL',product='Blog V4L',usb_path='3-1.'+str(i),label='USB '+str(i)+' · Blog V4L · '+str(10000010+i))


class RadioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.registry=DongleRegistry(self.tmp.name);self.broker=ReceiverBroker();self.devices=[device(i) for i in range(1,7)];self.registry.remember(self.devices)
    def tearDown(self):self.tmp.cleanup()
    def test_actual_lease_is_a_connection_but_saved_assignment_is_not(self):
        self.broker.acquire('aprs',self.devices[0]['id'])
        aprs=SimpleNamespace(enabled=True,settings=dict(selection=self.devices[0]['id'],frequency=144390000),status='RECEIVING')
        meteor=SimpleNamespace(enabled=True,settings=dict(selection=self.devices[1]['id'],frequency=137900000),status='WAITING FOR USB')
        hub=SimpleNamespace(sessions={'aprs':aprs,'meteor':meteor},sensor_receivers={},spectrum=SimpleNamespace(enabled=False))
        service=RadioManagement(self.registry,self.broker,vhf=hub);s=service.snapshot(self.devices)
        self.assertEqual(s['connected_count'],6);self.assertEqual(s['active_count'],1)
        first=next(r for r in s['dongles'] if r['id']==self.devices[0]['id']);second=next(r for r in s['dongles'] if r['id']==self.devices[1]['id'])
        self.assertEqual(first['connection']['label'],'APRS');self.assertEqual(first['connection']['detail'],'144.39 MHz')
        self.assertIsNone(second['connection']);self.assertEqual(second['waiting'],['Meteor-M'])
        self.broker.release('aprs');self.assertEqual(service.snapshot([])['active_count'],0)
    def test_management_order_is_stable_and_pending_ids_are_not_extra_radios(self):
        original=self.devices[0];self.registry.records[original['id']]['eeprom']=dict(status='verified',serial='10000100')
        self.registry.records['serial:10000100']=dict(id='serial:10000100',serial='10000100',usb_path=original['usb_path'])
        self.registry.records['slot:old']=dict(id='slot:old',serial=original['serial'])
        service=RadioManagement(self.registry,self.broker)
        first=service.snapshot(self.devices)
        self.assertEqual(len(first['dongles']),6)
        self.registry.records[self.devices[-1]['id']]['last_seen']=9999999999
        second=service.snapshot(list(reversed(self.devices)))
        self.assertEqual([r['id'] for r in first['dongles']],[r['id'] for r in second['dongles']])

    def test_choices_are_short_honest_and_preserve_a_missing_selection(self):
        self.registry.rename(self.devices[0]['id'],'Roof antenna');self.registry.remember(self.devices)
        self.broker.acquire('uat',self.devices[1]['id'])
        rows=choices(self.devices,self.broker.snapshot(),'adsb','serial:missing')
        self.assertEqual(rows[0]['name'],'Auto');self.assertEqual(rows[1]['name'],'Roof antenna')
        self.assertIn('978 UAT',rows[2]['detail']);self.assertEqual(rows[-1]['id'],'serial:missing')
        self.assertTrue(rows[-1]['selected']);self.assertNotIn('USB 1',rows[1]['name'])
        bad=dict(device(8),persistent=False,duplicate=True)
        self.assertFalse(choices([bad])[1]['enabled']);self.assertTrue(choices([bad],unique=False)[1]['enabled'])
    def test_native_management_fits_six_rows_and_back_keeps_the_parent(self):
        from dongle_workspace import DongleWorkspace
        from decoder_style import full_width_back_box
        ui=Mock();ui.fit_station_text.side_effect=lambda cache,text,*args:text;ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        self.broker.acquire('spectrum',self.devices[1]['id'])
        manager=SimpleNamespace(devices=self.devices,broker=self.broker)
        with patch('dongle_workspace.REGISTRY',self.registry),patch('usb_radios.SERVICE',None):
            w=DongleWorkspace(ui,manager);w.show();w.draw(Mock())
            rows=[(b,a) for b,a in w.actions if a[0]=='select'];self.assertEqual(len(rows),6)
            self.assertTrue(all(b[3]<640 and b[3]-b[1]>=56 for b,a in rows))
            self.assertIn((full_width_back_box(),('back',None)),w.actions)
            b,_=rows[0];w.tap((b[0]+b[2])/2,(b[1]+b[3])/2);self.assertIsNotNone(w.selected);self.assertIsNone(w.field)
            w.draw(Mock());b=full_width_back_box();w.tap((b[0]+b[2])/2,(b[1]+b[3])/2)
            self.assertIsNone(w.selected);self.assertTrue(w.open)
    def test_web_management_and_assets_share_the_same_live_inventory(self):
        from adsb_monitor import ADSBManager
        from urllib.request import urlopen
        import json
        import usb_radios
        manager=ADSBManager(root=Path(self.tmp.name)/'adsb',scanner=lambda:self.devices,broker=self.broker,port=0)
        manager.devices=self.devices;self.broker.acquire('spectrum',self.devices[0]['id'])
        try:
            with patch('dongle_web.REGISTRY',self.registry),patch('usb_radios.SERVICE',None):
                base=f'http://127.0.0.1:{manager.port}'
                data=json.load(urlopen(base+'/api/usb-radios'))
                self.assertEqual(data['connected_count'],6);self.assertEqual(data['active_count'],1)
                page=urlopen(base+'/usb-radios').read();self.assertIn(b'USB-Radios',page)
                self.assertIn(b'/usb-radio-select.js',page)
                self.assertIn(b'USB_Radios',urlopen(base+'/usb-radio-select.js').read())
                self.assertEqual(json.load(urlopen(base+'/api/dongles'))['leases'],data['leases'])
        finally:manager.close()

    def test_shared_picker_paginates_and_never_hides_conflicts(self):
        from usb_radio_controls import receiver_rows
        workspace=Mock();workspace.decoder_button=Mock()
        page,last=receiver_rows(workspace,Mock(),self.devices,self.broker.snapshot(),'ism','auto')
        self.assertEqual((page,last),(0,1));self.assertEqual(workspace.decoder_button.call_count,6)
        bad=dict(device(8),persistent=False,duplicate=True)
        workspace.decoder_button.reset_mock();receiver_rows(workspace,Mock(),[bad],{},'ism','auto')
        self.assertEqual(workspace.decoder_button.call_count,2)
        self.assertFalse(workspace.decoder_button.call_args.kwargs['enabled'])
