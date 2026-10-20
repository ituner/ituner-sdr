"""Hardware ownership, real decoder output, command contracts and HTTP boundaries."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from sdr_broker import ReceiverBroker, soapy_args
from vhf_monitor import VHFHub, parse_packet, clean_position

D1=dict(id='serial:123',serial='123',index=0,persistent=True,label='RTL one')
D2=dict(id='serial:456',serial='456',index=1,persistent=True,label='RTL two')

class BrokerTests(unittest.TestCase):
    def test_automatic_expansion_never_hands_off_a_busy_receiver(self):
        broker=ReceiverBroker();stop=Mock();broker.register('adsb',stop);broker.acquire('adsb',D1['id'])
        self.assertIsNone(broker.request('ism-2',[D1],D1['id'],handoff=False));stop.assert_not_called()
        self.assertEqual(broker.snapshot(),{D1['id']:'adsb'})
        self.assertEqual(broker.request('ism-2',[D1,D2],handoff=False),D2['id'])
    def test_handoff_waits_for_release_and_auto_prefers_unused(self):
        broker=ReceiverBroker();stop=Mock();broker.register('adsb',stop)
        self.assertTrue(broker.acquire('adsb',D1['id']))
        self.assertEqual(broker.request('ais',[D1,D2]),D2['id']);stop.assert_not_called()
        self.assertEqual(broker.request('ais',[D1,D2],D1['id']),D1['id']);stop.assert_called_once()
        self.assertFalse(broker.acquire('ais',D1['id']))
        broker.release('adsb');self.assertTrue(broker.acquire('ais',D1['id']))
        self.assertEqual(soapy_args(D1),'driver=rtlsdr,serial=123')

    def test_duplicate_serial_uses_explicit_index(self):
        with self.assertRaises(ValueError):soapy_args(dict(D1,persistent=False))

class ParserTests(unittest.TestCase):
    def test_ais_static_dynamic_and_noise(self):
        item=parse_packet('ais','{"mmsi":123456789,"lat":44.1,"lon":26.2,"speed":4.2}')
        self.assertTrue(clean_position(item));self.assertEqual(item['kind'],'ship')
        self.assertIsNone(parse_packet('ais','Starting SoapySDR'))
        self.assertFalse(clean_position(dict(lat=float('nan'),lon=26)))
        self.assertFalse(clean_position(dict(lat=91,lon=26)))

    def test_sensor_identity_includes_channel(self):
        first=parse_packet('ism','{"model":"Weather","id":3,"channel":1,"temperature_C":22.5}')
        second=parse_packet('ism','{"model":"Weather","id":3,"channel":2}')
        self.assertNotEqual(first['id'],second['id']);self.assertEqual(first['fields']['temperature_C'],22.5)
        self.assertIsNone(parse_packet('ism','{"time":1,"stats":true}'))

    def test_sonde_and_aprs_packets(self):
        self.assertEqual(parse_packet('sonde','{"id":"V123","lat":45,"lon":25,"alt":1200}')['altitude'],1200)
        item=parse_packet('aprs','[0.2] YO3ABC>APRS,WIDE1-1:!4425.00N/02606.00E-Test')
        self.assertEqual(item['id'],'YO3ABC');self.assertAlmostEqual(item['lat'],44.4166667,places=4)
        self.assertIsNone(parse_packet('aprs','Audio input device: stdin'))

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        with patch('vhf_monitor.threading.Thread.start'):
            self.hub=VHFHub(root=self.temp.name,port=-1,scanner=lambda:[D1,D2])
        self.hub.devices=[D1,D2]
        self.hub.thread=Mock()
        for session in self.hub.sessions.values():session.thread=Mock()
        for session in self.hub.sensor_receivers.values():session.thread=Mock()

    def tearDown(self):self.hub.close();self.temp.cleanup()

    def test_settings_validate_and_never_execute_arbitrary_commands(self):
        session=self.hub.sessions['ism']
        for value in (float('nan'),29e6,1701e6):
            with self.assertRaises(ValueError):session.control('configure',frequency=value)
        with self.assertRaises(ValueError):session.control('configure',profile='; touch /tmp/bad')
        session.control('configure',frequency=868300000,gain=28.5,ppm=-2)
        self.assertEqual(json.loads((session.root/'settings.json').read_text())['frequency'],868300000)

    def test_stop_preserves_observations_but_releases_hardware(self):
        session=self.hub.sessions['ais'];session.ingest(parse_packet('ais','{"mmsi":123,"lat":44,"lon":26}'))
        session.ingest(parse_packet('ais','{"mmsi":123,"shipname":"VESSEL"}'))
        row=session.snapshot()['records'][0]
        self.assertEqual(row['label'],'VESSEL');self.assertEqual(row['lat'],44);self.assertEqual(row['count'],2)
        self.hub.broker.acquire('ais',D1['id']);session.stop()
        self.assertEqual(self.hub.broker.snapshot(),{});self.assertEqual(len(session.snapshot()['records']),1)
        self.assertEqual(len((session.root/'observations.jsonl').read_text().splitlines()),2)

    def test_kiss_counts_frames_excluding_timestamp_and_preserves_partial(self):
        session=self.hub.sessions['cubesat'];session.run=session.root/'capture';session.run.mkdir()
        file=session.run/'frames.kiss'
        file.write_bytes(b'\xc0\x09'+b'\0'*8+b'\xc0\xc0\x00\x12\xdb\xdc\x34\xc0\xc0\x00\x56')
        session.poll_kiss();self.assertEqual(session.messages,1)
        with file.open('ab') as handle:handle.write(b'\x78\xc0')
        session.poll_kiss();self.assertEqual(session.messages,2)
        self.assertEqual(session.snapshot()['events'][0]['fields']['hex'],'12c034')

    def test_missing_receiver_waits_without_claiming_other(self):
        session=self.hub.sessions['aprs'];session.control('configure',selection=D2['id']);session.control('start')
        self.hub.devices=[D1];session.step();self.assertEqual(session.status,'WAITING FOR USB')
        self.assertEqual(self.hub.broker.snapshot(),{})

    def test_auto_switches_to_another_receiver_after_disconnect(self):
        session=self.hub.sessions['aprs'];session.enabled=True;session.assigned=D1
        session.target=D1['id'];session.active_generation=session.generation
        child=Mock();child.poll.return_value=None;session.processes=[child]
        self.hub.broker.acquire('aprs',D1['id']);self.hub.devices=[D2]
        session.launch=Mock()
        with patch('vhf_monitor.os.killpg'):session.step()
        session.launch.assert_called_once_with(D2)
        self.assertEqual(session.target,'auto')
        self.assertEqual(self.hub.broker.snapshot(),{})

    def test_continuous_meteor_restarts_after_successful_capture(self):
        session=self.hub.sessions['meteor'];session.settings['continuous']=True
        session.enabled=True;session.assigned=D1;session.active_generation=session.generation
        child=Mock();child.poll.return_value=0;child.returncode=0;session.processes=[child]
        session.step()
        self.assertTrue(session.enabled);self.assertEqual(session.status,'STARTING')
        self.assertEqual(session.processes,[]);self.assertNotIn(D1['id'],session.device_retry)

    def test_continuous_meteor_finalizes_only_after_received_pass_ends(self):
        session=self.hub.sessions['meteor'];session.settings['continuous']=True
        session.enabled=True;session.processes=[Mock()];session.stop=Mock()
        self.assertFalse(session.rotate_meteor_if_finished(1000));session.stop.assert_not_called()
        session.first_frame=800;session.last_frame=950
        self.assertFalse(session.rotate_meteor_if_finished(1000))
        session.last_frame=900
        self.assertTrue(session.rotate_meteor_if_finished(1000));session.stop.assert_called_once()
        self.assertTrue(session.enabled)
        session.processes=[]

    def test_installed_sensor_dashboard_resumes_only_an_explicitly_enabled_session(self):
        from vhf_monitor import DecoderSession
        self.hub.rtl433_ui_installed=True
        session=self.hub.sessions['ism'];session.control('start')
        with patch('vhf_monitor.threading.Thread.start'):resumed=DecoderSession(self.hub,'ism')
        resumed.thread=Mock()
        try:
            self.assertTrue(resumed.enabled)
            resumed.control('stop')
        finally:resumed.close()
        with patch('vhf_monitor.threading.Thread.start'):stopped=DecoderSession(self.hub,'ism')
        stopped.thread=Mock()
        try:self.assertFalse(stopped.enabled)
        finally:stopped.close()

    def test_continuous_meteor_resumes_after_restart_and_stop_cancels(self):
        from vhf_monitor import DecoderSession
        session=self.hub.sessions['meteor']
        for norad in (57166,59051):(self.hub.tle_root/f'{norad}.json').write_text('{}')
        session.control('configure',profile='auto-72',continuous=True)
        session.control('start')
        with patch('vhf_monitor.threading.Thread.start'):
            resumed=DecoderSession(self.hub,'meteor')
        resumed.thread=Mock()
        try:
            self.assertTrue(resumed.enabled)
            resumed.control('stop')
            self.assertFalse(json.loads((resumed.root/'settings.json').read_text())['enabled'])
        finally:resumed.close()

    def test_meteor_reception_history_keeps_weak_signals_without_frames(self):
        session=self.hub.sessions['meteor'];session.event=Mock()
        session.rf=dict(time=100,samples=1024000,rate=1024000,power_dbfs=-28.3,spectrum=[-55]*64)
        session.decoder_stats=dict(psk_demod=dict(snr=.2,peak_snr=.4),decoder=dict(viterbi_ber=.41,viterbi_lock=0,deframer_lock=False))
        with patch('vhf_monitor.time.time',return_value=100):session.record_reception();session.record_reception()
        self.assertEqual(session.reception['measurements'],1)
        session.rf.update(time=101,samples=2048000,power_dbfs=-23)
        session.decoder_stats['psk_demod']['snr']=2
        with patch('vhf_monitor.time.time',return_value=101):session.record_reception()
        self.assertEqual(session.reception['max_snr_db'],2)
        self.assertEqual(session.reception['min_power_dbfs'],-28.3)
        self.assertFalse(session.reception['deframer_lock_seen'])
        self.assertEqual(session.messages,0);session.event.assert_called_once()
        session.rf.update(time=161)
        session.decoder_stats['decoder']['viterbi_lock']=1
        with patch('vhf_monitor.time.time',return_value=161):session.record_reception()
        self.assertTrue(session.reception['viterbi_lock_seen']);self.assertEqual(session.event.call_count,2)
        session.run=session.root/'capture';session.run.mkdir()
        child=Mock();child.poll.return_value=0;session.processes=[child]
        session.stop()
        saved=json.loads((session.run/'capture-summary.json').read_text())
        self.assertEqual(saved['reception']['max_snr_db'],2)
        self.assertTrue(saved['reception']['viterbi_lock_seen'])
        self.assertEqual(saved['messages'],0)

    def test_meteor_adsb_handoff_waits_for_usb_release_in_both_directions(self):
        from adsb_monitor import ADSBManager
        session=self.hub.sessions['meteor'];self.hub.devices=[D1]
        for norad in (57166,59051):(self.hub.tle_root/f'{norad}.json').write_text('{}')
        with patch('adsb_monitor.threading.Thread.start'):
            adsb=ADSBManager(root=str(self.hub.root/'adsb'),port=-1,scanner=lambda:[D1],binary=__file__,broker=self.hub.broker)
        adsb.thread=Mock();adsb.devices=[D1]
        child=Mock();child.poll.return_value=None
        session.enabled=True;session.assigned=D1;session.processes=[child];session.active_generation=session.generation
        self.hub.broker.acquire('meteor',D1['id'])
        try:
            adsb.control('start')
            self.assertFalse(session.enabled)
            with patch('adsb_monitor.subprocess.Popen') as launch:
                adsb._step();launch.assert_not_called()
            with patch('vhf_monitor.os.killpg'):session.step()
            self.assertEqual(self.hub.broker.snapshot(),{})
            receiver=Mock();receiver.poll.return_value=None
            with patch('adsb_monitor.subprocess.Popen',return_value=receiver):adsb._step()
            self.assertEqual(self.hub.broker.snapshot(),{D1['id']:'adsb'})
            session.control('start');self.assertFalse(adsb.enabled)
            session.launch=Mock()
            session.step();session.launch.assert_not_called()
            adsb._step();receiver.terminate.assert_called_once()
            self.assertEqual(self.hub.broker.snapshot(),{})
            session.step();session.launch.assert_called_once_with(D1)
        finally:adsb.close()

    def test_cube_and_meteor_use_the_assigned_soapy_frontend(self):
        for mode in ('aprs','ism','cubesat','sonde'):
            session=self.hub.sessions[mode];session.child=Mock()
            session.launch(D2)
            commands=[c.args[0] for c in session.child.call_args_list]
            self.assertTrue(any('driver=rtlsdr,serial=456' in c for c in commands))
            self.assertEqual(self.hub.broker.snapshot().get(D2['id']),mode)
            session.stop()

    def test_sensor_rate_and_log_frequency_follow_actual_tuning(self):
        session=self.hub.sessions['ism'];session.child=Mock()
        for frequency,rate in ((433920000,'250000'),(868300000,'1000000'),(915000000,'1000000')):
            session.control('configure',frequency=frequency);session.launch(D1)
            command=session.child.call_args.args[0]
            self.assertEqual(command[command.index('-s')+1],rate)
            self.assertEqual(session.snapshot()['receiving_frequency'],frequency)
            # A pending retune must not relabel a message from the old process.
            session.control('configure',frequency=frequency+1000)
            self.assertIsNone(session.snapshot()['receiving_frequency'])
            session.ingest(parse_packet('ism','{"model":"Weather","id":7}'))
            self.assertEqual(session.snapshot()['events'][-1]['frequency'],frequency)
            self.assertEqual(json.loads((session.root/'observations.jsonl').read_text().splitlines()[-1])['frequency'],frequency)
            session.stop()

    def test_parallel_sensors_have_separate_serials_leases_and_logs(self):
        primary=self.hub.sessions['ism'];extra=self.hub.sensor_receivers['ism-2']
        for session,device,frequency in ((primary,D1,433920000),(extra,D2,915000000)):
            session.child=Mock();session.control('configure',selection=device['id'],frequency=frequency)
            session.control('start');session.launch(device)
            command=session.child.call_args.args[0];self.assertIn(soapy_args(device),command)
            session.ingest(parse_packet('ism','{"model":"Weather","id":7}'))
            row=json.loads((session.root/'observations.jsonl').read_text().splitlines()[-1])
            self.assertEqual(row['receiver'],session.owner);self.assertEqual(row['serial'],device['serial'])
        self.assertEqual(self.hub.broker.snapshot(),{D1['id']:'ism',D2['id']:'ism-2'})
        extra.stop();self.assertEqual(self.hub.broker.snapshot(),{D1['id']:'ism'})
        # A competing decoder wins a handoff of just the requested receiver.
        extra.control('start');extra.launch(D2)
        self.hub.broker.request('adsb',[D1,D2],D2['id'])
        self.assertFalse(extra.enabled);self.assertTrue(primary.enabled)
        self.hub.control('ism','stop');self.assertFalse(primary.enabled);self.assertFalse(extra.enabled)

    def test_auxiliary_start_rejects_a_lease_race_without_stopping_adsb(self):
        extra=self.hub.sensor_receivers['ism-2'];extra.control('configure',selection=D2['id'])
        stop=Mock();self.hub.broker.register('adsb',stop);self.hub.broker.acquire('adsb',D2['id'])
        with self.assertRaises(ValueError):self.hub.control('ism-2','start')
        stop.assert_not_called();self.assertFalse(extra.enabled)

class TouchTests(unittest.TestCase):
    setUp=ManagerTests.setUp
    tearDown=ManagerTests.tearDown
    def test_map_tab_reopens_for_every_decoder_running_and_stopped(self):
        from vhf_workspace import VHFWorkspace
        ui=Mock()
        ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        workspace=VHFWorkspace(ui,self.hub)
        for mode,session in self.hub.sessions.items():
            for enabled in (False,True):
                with self.subTest(mode=mode,enabled=enabled):
                    session.enabled=enabled
                    session.control=Mock()
                    workspace.show(mode)
                    for _ in range(3):
                        workspace.view='data';workspace.draw(Mock())
                        box=next(box for box,action in workspace.actions if action==('view','map'))
                        workspace.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
                        self.assertEqual(workspace.view,'map')
                        workspace.draw(Mock())
                    labels=[str(call.args[3]) for call in ui.draw_text.call_args_list]
                    if mode=='meteor' and enabled:
                        self.assertIn('METEOR RECEPTION',labels)
                        self.assertIn('Open PRODUCTS for decoded imagery.',labels)
                    self.assertEqual(session.enabled,enabled)
                    session.control.assert_not_called()
                    self.assertEqual(self.hub.broker.snapshot(),{})

    def test_back_retraces_views_and_nested_editor_without_leaving_decoder(self):
        from vhf_workspace import VHFWorkspace
        ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        ui.station_settings=None
        w=VHFWorkspace(ui,self.hub);w.show('ais')
        def press(action,value=None):
            w.actions=[((0,0,100,100),(action,value))];w.tap(10,10)
        press('view','data');press('overlay','location');press('number','lat')
        press('back');self.assertEqual(w.overlay,'location');self.assertTrue(w.open)
        press('back');self.assertIsNone(w.overlay);self.assertEqual(w.view,'data');self.assertTrue(w.open)
        press('back');self.assertEqual(w.view,'map');self.assertTrue(w.open)
        press('back');self.assertFalse(w.open)

    def test_shared_station_settings_records_decoder_parent(self):
        from vhf_workspace import VHFWorkspace
        ui=Mock();ui.contains.return_value=True
        w=VHFWorkspace(ui,self.hub);w.show('ais')
        w.actions=[((0,0,100,100),('overlay','location'))];w.tap(10,10)
        ui.station_settings.show.assert_called_once_with(parent='vhf')
        self.assertFalse(w.open)

    def test_frequency_keypad_applies_mhz_and_station_coordinates_save(self):
        from vhf_workspace import VHFWorkspace
        ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        ui.fit_station_text.side_effect=lambda cache,text,*args:text
        workspace=VHFWorkspace(ui,self.hub);workspace.show('ism')
        def press(action,value):
            workspace.draw(Mock())
            box=next(box for box,item in workspace.actions if item==(action,value))
            workspace.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
        press('number','frequency');press('key','CLEAR')
        for character in '868.3':press('key',character)
        press('key','SAVE')
        self.assertEqual(workspace.session.settings['frequency'],868300000)
        workspace.overlay='location';workspace.station_edit=dict(lat=44.4,lon=26.1)
        press('save_site',None)
        self.assertEqual(self.hub.position,dict(lat=44.4,lon=26.1))

class HTTPTests(unittest.TestCase):
    def test_controls_origin_and_capture_paths(self):
        with tempfile.TemporaryDirectory() as root:
            hub=VHFHub(root=root,port=0,scanner=lambda:[])
            try:
                base=f'http://127.0.0.1:{hub.port}'
                state=json.load(urlopen(base+'/api/state'));self.assertEqual(len(state['sessions']),6)
                for headers in ({},{'X-VHF-Token':state['control_token'],'Origin':'http://evil.example'}):
                    with self.assertRaises(HTTPError) as caught:urlopen(Request(base+'/api/control',data=b'{"mode":"ais","action":"start"}',headers=headers))
                    self.assertEqual(caught.exception.code,403)
                headers={'X-VHF-Token':state['control_token']}
                request=Request(base+'/api/control',data=b'{"mode":"ism","action":"configure","frequency":433920000}',headers=headers)
                self.assertTrue(json.load(urlopen(request))['ok'])
                with self.assertRaises(HTTPError):urlopen(base+'/products/../ais/settings.json')
                with self.assertRaises(HTTPError):urlopen(base+'/api/log?mode=../adsb')
            finally:hub.close()

if __name__=='__main__':unittest.main()
