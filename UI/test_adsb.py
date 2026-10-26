"""Receiver allocation, stale data, process recovery and HTTP control boundaries."""
import json
import math
import gzip
from pathlib import Path
import tempfile
import shutil
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from adsb_monitor import ADSBManager, aircraft_rows


DEVICE = dict(id='serial:123', index=0, serial='123', label='Test RTL', persistent=True)
OTHER = dict(id='serial:456', index=1, serial='456', label='Other RTL', persistent=True)


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Keep the supervisor deterministic; tests call one step at a time.
        with patch('adsb_monitor.threading.Thread.start'):
            self.manager = ADSBManager(root=self.tmp.name, scanner=lambda:[DEVICE,OTHER], binary=shutil.which('true'), port=-1)
        self.manager.thread = Mock()
        self.manager._step()

    def tearDown(self):
        self.manager.close()
        self.manager.coverage.close()  # The supervisor thread is mocked in these tests.
        self.tmp.cleanup()

    def test_comparison_start_includes_all_spares_and_restores_uat(self):
        third=dict(id='serial:789',index=2,serial='789',label='Third RTL',persistent=True)
        duplicate=dict(id='port:duplicate',index=3,label='Duplicate RTL',persistent=False)
        self.manager.devices=[DEVICE,OTHER,third,duplicate]
        self.manager.assigned=DEVICE
        self.manager.uat.enabled=True
        self.manager.control('comparison_start')
        self.assertEqual(self.manager.comparison.selections,[OTHER['id'],third['id']])
        self.assertTrue(self.manager.comparison.restore_uat);self.assertFalse(self.manager.uat.enabled)
        with self.assertRaises(ValueError):self.manager.control('assign',third['id'])
        self.manager.control('comparison_stop')
        self.assertFalse(self.manager.comparison.enabled);self.assertTrue(self.manager.uat.enabled)

    def test_reset_and_fresh_start_are_explicit_graph_actions(self):
        self.manager.assigned=DEVICE
        with patch.object(self.manager.comparison,'reset_graphs') as reset:
            self.manager.control('comparison_start');self.assertEqual(reset.call_count,1)
            self.manager.control('comparison_reset');self.assertEqual(reset.call_count,2)
            self.assertTrue(self.manager.comparison.enabled)
            self.manager.control('comparison_stop');self.assertEqual(reset.call_count,2)
            self.manager.control('comparison_start');self.assertEqual(reset.call_count,3)

    def test_comparison_start_queues_saved_receivers_when_usb_is_missing_after_boot(self):
        self.manager.devices=[];self.manager.scanner=lambda:[];self.manager.assigned=None
        self.manager.enabled=False;self.manager.selection=DEVICE['id']
        self.manager.comparison.selections=[OTHER['id'],'serial:789']
        self.manager.control('comparison_start')
        self.assertTrue(self.manager.enabled);self.assertTrue(self.manager.comparison.enabled)
        self.assertEqual(self.manager.comparison.selections,[OTHER['id'],'serial:789'])
        saved=json.loads((Path(self.tmp.name)/'settings.json').read_text())
        self.assertTrue(saved['enabled']);self.assertEqual(saved['selection'],DEVICE['id'])
        self.manager._step();self.assertEqual(self.manager.status,'WAITING FOR USB')

    def test_comparison_start_also_enables_the_stopped_primary(self):
        self.manager.devices=[DEVICE,OTHER];self.manager.assigned=None;self.manager.enabled=False
        self.manager.control('comparison_start')
        self.assertTrue(self.manager.enabled);self.assertTrue(self.manager.comparison.enabled)
        self.assertEqual(self.manager.selection,DEVICE['id'])
        self.assertEqual(self.manager.comparison.selections,[OTHER['id']])

    def test_comparison_keeps_saved_receiver_order_after_usb_reenumeration(self):
        third=dict(id='serial:789',index=2,serial='789',label='Third RTL',persistent=True)
        self.manager.devices=[DEVICE,third,OTHER];self.manager.assigned=DEVICE
        self.manager.comparison.selections=[OTHER['id'],third['id']]
        self.manager.control('comparison_start')
        self.assertEqual(self.manager.comparison.selections,[OTHER['id'],third['id']])

    def test_comparison_first_start_can_wait_for_usb_without_saved_assignments(self):
        self.manager.devices=[];self.manager.assigned=None;self.manager.enabled=False
        self.manager.comparison.selections=[]
        self.manager.control('comparison_start')
        self.assertTrue(self.manager.enabled);self.assertTrue(self.manager.comparison.enabled)
        self.assertEqual(self.manager.comparison.selection,'all')
        with self.assertRaises(ValueError):self.manager.control('comparison_start','serial:unknown')

    def test_comparison_can_still_target_one_explicit_receiver(self):
        third=dict(id='serial:789',index=2,serial='789',label='Third RTL',persistent=True)
        self.manager.devices=[DEVICE,OTHER,third];self.manager.assigned=DEVICE
        self.manager.control('comparison_start',third['id'])
        self.assertEqual(self.manager.comparison.selections,[third['id']])

    def test_snapshot_ages_cached_rf_and_position_from_observation_time(self):
        self.manager.aircraft_stamp=100
        self.manager.planes=[dict(hex='abc',seen=1,seen_pos=10,lat=44,lon=26)]
        with patch('adsb_monitor.time.time',return_value=104):
            p=self.manager.snapshot()['aircraft'][0]
        self.assertEqual(p['last_seen_at'],99);self.assertEqual(p['position_time'],90)
        self.assertEqual(p['seen'],5);self.assertEqual(p['seen_pos'],14)
        with patch('adsb_monitor.time.time',return_value=115):
            self.assertEqual(self.manager.snapshot()['aircraft'],[])

    def child(self, returncode=None):
        p=Mock()
        p.poll.return_value=returncode
        p.returncode=returncode
        return p

    def test_assignment_is_persisted_and_rejects_unknown_device(self):
        self.manager.control('assign',OTHER['id'])
        self.manager.control('start')
        data=json.loads((Path(self.tmp.name)/'settings.json').read_text())
        self.assertEqual(data,dict(enabled=True,selection=OTHER['id'],position=None))
        with self.assertRaises(ValueError):self.manager.control('assign','serial:missing')

    def test_auto_skips_busy_dongle_and_uses_next(self):
        self.manager.enabled=True
        with patch('adsb_monitor.subprocess.Popen',return_value=self.child(1)):
            self.manager._step()
        (self.manager.root/'readsb.txt').write_text('usb_claim_interface: device busy')
        with patch('adsb_monitor.subprocess.Popen',return_value=self.child()) as launch:
            self.manager._step()
        self.assertEqual(self.manager.assigned['id'],OTHER['id'])
        self.assertIn('--device=1',launch.call_args.args[0])

    def test_stop_releases_device_and_clears_live_map(self):
        child=self.child()
        self.manager.process=child
        self.manager.assigned=DEVICE
        self.manager.planes=[dict(hex='123456')]
        self.manager._step()
        child.terminate.assert_called_once()
        self.assertEqual(self.manager.snapshot()['aircraft'],[])
        self.assertEqual(json.loads((self.manager.data/'aircraft.json').read_text())['aircraft'],[])

    def test_missing_saved_device_does_not_claim_another(self):
        self.manager.enabled=True
        self.manager.selection='serial:missing'
        with patch('adsb_monitor.subprocess.Popen') as launch:self.manager._step()
        launch.assert_not_called()
        self.assertEqual(self.manager.status,'WAITING FOR DONGLE')

    def test_disconnect_terminates_child_and_clears_aircraft(self):
        child=self.child()
        self.manager.process=child
        self.manager.assigned=DEVICE
        self.manager.enabled=True
        self.manager.selection=DEVICE['id']
        self.manager.scanner=lambda:[]
        self.manager.next_scan=0
        self.manager._step()
        child.terminate.assert_called_once()
        self.assertEqual(self.manager.status,'WAITING FOR USB')

    def test_live_aircraft_written_as_jsonl(self):
        self.manager.enabled=True
        self.manager.process=self.child()
        self.manager.assigned=DEVICE
        self.manager.started=time.monotonic()
        plane=dict(hex='abc123',lat=45,lon=25,seen=1)
        (self.manager.data/'aircraft.json').write_text(json.dumps(dict(now=time.time(),messages=10,aircraft=[plane])))
        self.manager._step()
        self.assertEqual(self.manager.status,'RECEIVING')
        logged=json.loads((self.manager.root/'flights.jsonl').read_text())
        self.assertEqual(logged['aircraft'],plane)
        self.assertEqual(logged['device']['serial'],'123')

    def test_live_direct_positions_reach_persistent_coverage(self):
        manager=self.manager;manager.enabled=True;manager.process=self.child();manager.assigned=DEVICE
        manager.started=time.monotonic();manager.position=dict(lat=44.4,lon=26.1);manager.active_position=dict(manager.position)
        stamp=time.time();plane=dict(hex='abc123',type='adsb_icao',lat=44.5,lon=26.1,seen=0,seen_pos=0,alt_geom=10000,rssi=-22)
        (manager.data/'aircraft.json').write_text(json.dumps(dict(now=stamp,messages=10,aircraft=[plane])))
        manager._step();manager.coverage.tick(manager.position)
        data=manager.coverage.snapshot()
        self.assertEqual(data['meta']['retained_positions'],1)
        self.assertEqual(data['meta']['max_altitude_ft'],10000)
        self.assertEqual(data['aircraft'][0]['hex'],'abc123')

    def test_message_activity_and_position_activity_are_distinct(self):
        manager=self.manager;manager.enabled=True;manager.process=self.child();manager.assigned=DEVICE
        manager.started=time.monotonic();base=time.time()
        def receive(offset,messages,planes):
            stamp=base+offset
            (manager.data/'aircraft.json').write_text(json.dumps(dict(now=stamp,messages=messages,aircraft=planes)))
            with patch('adsb_monitor.time.time',return_value=stamp):manager._step();return manager.snapshot()
        plane=dict(hex='abc123',seen=0,alt_baro=1200,gs=120)
        first=receive(0,10,[plane])
        self.assertEqual(first['last_message_at'],base);self.assertIsNone(first['last_position_at'])
        idle=receive(2,10,[])
        self.assertEqual(idle['last_message_at'],base)
        later=receive(3,11,[plane])
        self.assertEqual(later['last_message_at'],base+3);self.assertIsNone(later['last_position_at'])
        located=receive(4,12,[dict(plane,lat=44.4,lon=26.1,seen_pos=0)])
        self.assertEqual(located['last_position_at'],base+4)
        unlocated=receive(5,13,[plane])
        self.assertEqual(unlocated['last_message_at'],base+5)
        self.assertEqual(unlocated['last_position_at'],base+4)
        self.assertEqual(manager.track_snapshot()['abc123'][-1]['time'],base+4)

    def test_stale_json_and_stale_aircraft_are_hidden(self):
        self.assertEqual(aircraft_rows(dict(now=1,aircraft=[dict(seen=0)]),now=100),[])
        rows=aircraft_rows(dict(now=100,aircraft=[dict(hex='a',seen=1),dict(hex='b',seen=19)]),now=101)
        self.assertEqual([r['hex'] for r in rows],['a'])


class HTTPTests(unittest.TestCase):
    def test_token_origin_and_path_boundaries(self):
        with tempfile.TemporaryDirectory() as root:
            map_root=Path(root)/'map'
            (map_root/'db2').mkdir(parents=True)
            (map_root/'db2'/'C.js').write_bytes(gzip.compress(b'{"test":true}'))
            manager=ADSBManager(root=root,scanner=lambda:[],port=0,map_root=map_root)
            try:
                base=f'http://127.0.0.1:{manager.port}'
                response=urlopen(base+'/map/db2/C.js')
                self.assertEqual(response.headers['Content-Encoding'],'gzip')
                self.assertEqual(json.loads(gzip.decompress(response.read())),dict(test=True))
                (manager.data/'receiver.json').write_text('{"binCraft":true,"zstd":true,"history":1}')
                receiver=json.load(urlopen(base+'/map/data/receiver.json'))
                self.assertFalse(receiver['binCraft'])
                self.assertFalse(receiver['zstd'])
                self.assertEqual(receiver['history'],0)
                state=json.load(urlopen(base+'/api/state'))
                for headers in ({},{'X-ADSB-Token':state['control_token'],'Origin':'http://evil.example'}):
                    request=Request(base+'/api/control',data=b'{"action":"start"}',headers=headers)
                    with self.assertRaises(HTTPError) as caught:urlopen(request)
                    self.assertEqual(caught.exception.code,403)
                request=Request(base+'/api/control',data=b'{"action":"stop"}',headers={'X-ADSB-Token':state['control_token']})
                self.assertTrue(json.load(urlopen(request))['ok'])
                with self.assertRaises(HTTPError):urlopen(base+'/map/%2e%2e/settings.json')
            finally:manager.close()


class WorkspaceTests(unittest.TestCase):
    def dashboard(self, aircraft=None):
        from adsb_workspace import ADSBWorkspace
        ui=Mock();ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.radiogarden_project.return_value=(400,350,1)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        ui.contains.side_effect=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3]
        state=dict(enabled=True,status='RECEIVING',aircraft=aircraft or [],messages=100,detail='',port=8090,devices=[],selection='auto',started_at=time.time()-100)
        manager=Mock();manager.snapshot.return_value=state;manager.track_snapshot.return_value={}
        manager.log_snapshot.return_value=dict(lines=[],entries=[])
        return ADSBWorkspace(ui,manager),ui,manager,state

    def test_receiver_site_opens_shared_location_editor_and_preserves_view(self):
        workspace, ui, manager, state = self.dashboard()
        workspace.show()
        workspace.navigate('usb')
        workspace.actions=[]
        workspace.draw_usb(Mock(), state)
        self.press(workspace, ('site', None))
        ui.station_settings.show.assert_called_once_with(parent='adsb')
        self.assertEqual(ui.station_settings.page, 'location')
        self.assertFalse(workspace.open)
        workspace.open=True
        self.assertEqual(workspace.current_screen(), 'usb')
        workspace.go_back()
        self.assertEqual(workspace.current_screen(), 'map')

    @staticmethod
    def press(workspace, action):
        box=next(box for box,item in workspace.actions if item==action)
        workspace.tap((box[0]+box[2])/2,(box[1]+box[3])/2)

    def test_dashboard_actions_select_follow_sort_and_clear_without_restarting_receiver(self):
        planes=[dict(hex='abc',flight='TEST',lat=44,lon=26,seen=0,seen_pos=0,alt_baro=3000),dict(hex='def',flight='OTHER',seen=2,alt_baro=9000)]
        workspace,ui,manager,state=self.dashboard(planes)
        workspace.draw(Mock());self.press(workspace,('view_options',None));workspace.draw(Mock())
        self.press(workspace,('traffic',None));workspace.draw(Mock());self.press(workspace,('select','abc'))
        workspace.draw(Mock());self.press(workspace,('follow',None))
        self.assertTrue(workspace.following)
        self.press(workspace,('view_options',None));workspace.draw(Mock());self.press(workspace,('traffic',None))
        for expected in ('altitude','callsign','recent'):
            workspace.draw(Mock());self.press(workspace,('sort',None))
            self.assertEqual(workspace.traffic_sort,expected)
        self.press(workspace,('back',None));workspace.draw(Mock());self.press(workspace,('close_options',None))
        workspace.draw(Mock());self.press(workspace,('clear',None))
        self.assertIsNone(workspace.selected);self.assertIsNone(workspace.selected_plane);self.assertFalse(workspace.following)
        manager.control.assert_not_called()

    def test_view_modes_and_start_fresh_are_display_only_and_default_back_to_live_on_entry(self):
        workspace,ui,manager,state=self.dashboard()
        now=time.time();manager.track_snapshot.return_value={'old':[dict(time=now-60,lat=44,lon=26)]}
        workspace.show();workspace.draw(Mock())
        self.assertEqual(workspace.traffic_view.mode,'live');self.assertEqual(workspace.trail_seconds,300)
        self.assertEqual(workspace.points,[])
        self.press(workspace,('traffic_view','history'));workspace.draw(Mock())
        self.assertEqual(len(workspace.points),1);self.assertEqual(workspace.trail_seconds,86400)
        self.press(workspace,('view_options',None));workspace.draw(Mock())
        self.press(workspace,('start_fresh',None));workspace.draw(Mock())
        self.assertEqual(workspace.traffic_view.mode,'live');self.assertEqual(workspace.points,[])
        self.assertIn('old',workspace.tracks);manager.control.assert_not_called()
        workspace.open=False;workspace.show();self.assertEqual(workspace.traffic_view.mode,'live')

    def test_comparison_reset_touch_dispatches_and_confirms_without_stopping(self):
        w,ui,manager,_=self.dashboard();w.navigate('comparison')
        frame=dict(now=110,enabled=True,status='RUNNING',current=None,receivers=[DEVICE,OTHER],
                   graph_reset_at=0,history=[],rate_history=[],rate_history_ids=[])
        manager.comparison.snapshot.return_value=frame
        w.draw(Mock())
        for seconds in (300,1800,3600,43200,86400):
            self.press(w,('comparison_range',seconds));self.assertEqual(w.comparison_view.span,seconds)
        self.press(w,('comparison_control','comparison_reset'))
        manager.control.assert_called_once_with('comparison_reset')
        self.assertEqual(w.comparison_view.next_read,0)
        manager.comparison.snapshot.return_value=dict(frame,graph_reset_at=110)
        ui.draw_styled_two_line_button.reset_mock();w.draw(Mock())
        labels=[call.args[2] for call in ui.draw_styled_two_line_button.call_args_list]
        self.assertIn('GRAPHS RESET',labels)
        self.assertIn(('comparison_control','comparison_reset'),[action for _,action in w.actions])

    def test_repeated_live_taps_confirm_then_cycle_without_resetting_selection(self):
        w,ui,manager,state=self.dashboard();w.show();w.selected='a';w.selected_plane={'hex':'a'}
        for seconds in (15,30,60,120,300,15):
            w.draw(Mock());self.press(w,('traffic_view','live'))
            self.assertEqual(w.traffic_view.live_seconds,seconds);self.assertEqual(w.selected,'a')
            self.assertEqual(w.trail_seconds,300)
        manager.control.assert_not_called()

    def test_history_trails_have_an_explicit_native_view_toggle(self):
        w,ui,manager,_=self.dashboard();w.show();w.set_traffic_view('history');w.navigate('options')
        self.assertFalse(w.traffic_view.history_trails);self.assertFalse(w.traffic_view.labels_visible(w.labels))
        w.draw(Mock());self.press(w,('labels',None))
        self.assertTrue(w.traffic_view.history_labels);self.assertFalse(w.traffic_view.history_trails)
        w.draw(Mock());self.press(w,('history_trails',None))
        self.assertTrue(w.traffic_view.history_trails)
        w.draw(Mock());self.press(w,('history_trails',None))
        self.assertFalse(w.traffic_view.history_trails);self.assertTrue(w.traffic_view.history_labels)
        w.draw(Mock());self.press(w,('aircraft_icons',None))
        self.assertFalse(w.traffic_view.history_icons);self.assertTrue(w.traffic_view.history_labels)
        w.set_traffic_view('live');self.assertTrue(w.labels)
        self.assertTrue(w.aircraft_icons)
        manager.control.assert_not_called()

    def test_hidden_history_symbols_have_no_native_map_click_targets(self):
        w,ui,manager,state=self.dashboard();w.dashboard=True;w.centered=True;w.rx_footprint=False;w.map_style='satellite'
        w.draw_map_hud=Mock()
        w.set_traffic_view('history');w.traffic_view.history_icons=False
        manager.track_snapshot.return_value={'old':[dict(time=time.time()-60,lat=44,lon=26)]}
        w.draw_map(Mock(),state,[])
        self.assertEqual(w.points,[])
        ui.draw_logical_polyline.assert_not_called();ui.draw_logical_points.assert_not_called()
        self.assertIn('old',w.tracks)

    def test_dashboard_saved_target_can_be_located_but_cannot_start_follow(self):
        workspace,ui,manager,state=self.dashboard()
        manager.track_snapshot.return_value={'old':[dict(time=time.time()-60,lat=44.5,lon=26.2,alt=4000)]}
        workspace.set_traffic_view('history');workspace.selected='old';workspace.draw(Mock())
        self.assertTrue(workspace.selected_plane['historical'])
        self.assertNotIn(('follow',None),[action for _,action in workspace.actions])
        workspace.yaw=workspace.pitch=0
        self.press(workspace,('locate',None))
        self.assertAlmostEqual(workspace.yaw,math.radians(26.2))
        self.assertAlmostEqual(workspace.pitch,math.radians(44.5))
        self.assertFalse(workspace.following);manager.control.assert_not_called()
        labels=[str(call.args[3]) for call in ui.draw_text.call_args_list]
        self.assertTrue(any('Position old' in label for label in labels))

    def test_back_returns_to_parent_and_history_can_cancel_or_apply(self):
        w,ui,manager,state=self.dashboard();w.show()
        with patch.object(w.coverage_view,'activate'):
            w.navigate('coverage');w.navigate('usb')
            w.draw(Mock());self.press(w,('back',None))
            self.assertEqual(w.current_screen(),'coverage');self.assertTrue(w.open)
            w.draw(Mock());self.press(w,('back',None))
        self.assertEqual(w.current_screen(),'map');self.assertTrue(w.open)
        w.navigate('traffic');w.navigate('options');w.draw(Mock())
        self.press(w,('history_window',None));w.draw(Mock())
        original=w.history_seconds
        self.press(w,('history_choice',3600));w.draw(Mock())
        self.press(w,('cancel_history',None));self.assertEqual(w.history_seconds,original)
        self.assertEqual(w.current_screen(),'options');self.assertTrue(w.open)
        w.draw(Mock());self.press(w,('history_window',None));w.draw(Mock())
        self.assertEqual(w.history_draft,original)
        self.press(w,('history_choice',3600));w.draw(Mock())
        self.press(w,('history_apply',None));self.assertEqual(w.history_seconds,3600)
        self.assertEqual(w.current_screen(),'options')
        w.draw(Mock());self.press(w,('close_options',None));self.assertEqual(w.current_screen(),'traffic')
        w.draw(Mock());self.press(w,('back',None));self.assertEqual(w.current_screen(),'map')
        self.assertTrue(w.open)
        w.draw(Mock());self.press(w,('back',None));self.assertFalse(w.open)
        manager.control.assert_not_called()

    def test_back_from_each_nested_screen_stays_in_adsb(self):
        for page in ('traffic','logs','usb','settings','options','history_window'):
            w,ui,manager,state=self.dashboard();w.show();w.navigate(page)
            w.draw(Mock());self.press(w,('back',None))
            self.assertEqual(w.current_screen(),'map',page);self.assertTrue(w.open,page)

    def test_dashboard_controls_do_not_overlap_or_intercept_other_targets(self):
        workspace,ui,manager,state=self.dashboard()
        for page in ('map','usb','logs','traffic','settings','options','history_window'):
            workspace.navigate(page,remember=False)
            workspace.draw(Mock())
            boxes=[box for box,_ in workspace.actions]
            for i,box in enumerate(boxes):
                self.assertGreaterEqual(box[0],0);self.assertGreaterEqual(box[1],0)
                self.assertLessEqual(box[2],1280);self.assertLessEqual(box[3],800)
                self.assertGreaterEqual(box[3]-box[1],34)
                for other in boxes[i+1:]:
                    self.assertFalse(box[0]<other[2] and box[2]>other[0] and box[1]<other[3] and box[3]>other[1],(box,other))

    def test_shared_radio_information_returns_to_airspace_settings(self):
        w,ui,manager,state=self.dashboard();w.show();w.navigate('settings')
        w.radio_info.station.snapshot.return_value={'config':{}}
        w.draw(Mock());self.press(w,('radio_info',None));self.assertTrue(w.radio_info.open)
        w.radio_info.actions=[((0,0,10,10),('back',None))];w.tap(5,5)
        self.assertFalse(w.radio_info.open);self.assertEqual(w.current_screen(),'settings');self.assertTrue(w.open)

    def test_dashboard_hud_does_not_select_or_drag_an_aircraft_behind_it(self):
        workspace,ui,manager,state=self.dashboard([dict(hex='abc',lat=44,lon=26,seen=0,seen_pos=0)])
        ui.radiogarden_project.return_value=(50,100,1)
        workspace.draw(Mock());workspace.tap(50,100)
        self.assertIsNone(workspace.selected)
        workspace.drag_begin(50,100);workspace.drag_move(50,100,100,110)
        ui.radiogarden_pan_angles.assert_not_called()
        workspace.traffic_open=True;workspace.draw(Mock())
        self.assertEqual(workspace.points,[])

    def test_full_width_map_and_movable_card_do_not_pan_or_activate_covered_controls(self):
        plane=dict(hex='abc',flight='TEST',lat=44,lon=26,seen=0,seen_pos=0,alt_baro=3000)
        w,ui,manager,state=self.dashboard([plane]);w.selected='abc';w.selected_plane=plane
        w.draw(Mock());self.assertEqual(w.MAP,(0,0,1280,712))
        self.assertNotIn(('logs',None),[action for _,action in w.actions])
        self.assertIn(('usb',None),[action for _,action in w.actions])  # Direct receiver status/control shortcut.
        x0,y0,x1,y1=w.card_handle;sx,sy=(x0+x1)/2,(y0+y1)/2
        w.drag_begin(sx,sy);w.drag_move(sx,sy,sx-300,sy-180)
        self.assertIsNotNone(w.card_position);self.assertTrue(w.dragged)
        ui.radiogarden_pan_angles.assert_not_called();w.swipe()
        w.card_position=(500,400);w.draw(Mock());scale=w.scale
        self.assertTrue(any(c.args[5][-1]<255 for c in ui.draw_logical_rounded_rect.call_args_list if len(c.args[5])==4))
        # The floating Follow control covers part of the zoom bar: the top layer wins.
        w.tap(580,654);self.assertTrue(w.following);self.assertEqual(w.scale,scale)
        manager.control.assert_not_called()

    def test_view_announcement_expires_without_being_extended_by_refresh(self):
        workspace,ui,manager,state=self.dashboard()
        workspace.dashboard=True
        with patch('adsb_touch.time.monotonic',return_value=100):
            workspace.draw_map_hud(Mock(),state,[])
        self.assertTrue(any('LIVE · trails' in str(c.args[3]) for c in ui.draw_text.call_args_list))
        for now in (103,106):
            ui.reset_mock()
            with patch('adsb_touch.time.monotonic',return_value=now):
                workspace.draw_map_hud(Mock(),state,[])
            shown=any('LIVE · trails' in str(c.args[3]) for c in ui.draw_text.call_args_list)
            self.assertEqual(shown,now<105)
        self.assertFalse(any(box[1]==134 for box in workspace.overlay_boxes))
        workspace.set_traffic_view('history');ui.reset_mock()
        with patch('adsb_touch.time.monotonic',return_value=107):
            workspace.draw_map_hud(Mock(),state,[])
        self.assertTrue(any('HISTORY · trails' in str(c.args[3]) for c in ui.draw_text.call_args_list))

    def test_saved_endpoint_is_visible_selectable_and_not_followable(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock();ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        ui.radiogarden_project.return_value=(400,300,1);ui.contains.return_value=True
        manager=Mock();now=time.time()
        manager.track_snapshot.return_value={'abc':[dict(time=now-60,lat=44.5,lon=26,alt=3000)]}
        manager.snapshot.return_value=dict(aircraft=[])
        workspace=ADSBWorkspace(ui,manager)
        state=dict(enabled=True,started_at=now-100,aircraft=[])
        workspace.draw_map(Mock(),state,[])
        self.assertEqual(len(workspace.points),1)
        marker=workspace.points[0][2]
        self.assertTrue(marker['historical']);self.assertEqual(marker['lat'],44.5)
        self.assertFalse(workspace.positioned(marker))
        workspace.actions=[];workspace.tap(400,300)
        self.assertEqual(workspace.selected,'abc')
        workspace.actions=[((0,0,10,10),('follow',None))];workspace.tap(5,5)
        self.assertFalse(workspace.following)
        workspace.trail_seconds=0;workspace.draw_map(Mock(),state,[])
        self.assertEqual(workspace.points,[])
        workspace.trail_seconds=86400;state['empty_title']='AIS'
        workspace.draw_map(Mock(),state,[])
        self.assertEqual(workspace.points,[],'Other VHF modes must not gain aircraft history icons')

    def test_history_markers_expire_and_live_positions_replace_them(self):
        from adsb_traffic import historical_aircraft,TrafficHistory
        tracks={'abc':[dict(time=100,lat=44,lon=26)]}
        self.assertEqual(historical_aircraft(tracks,[],300,110),[])
        self.assertEqual(len(historical_aircraft(tracks,[],300,160)),1)
        self.assertEqual(historical_aircraft(tracks,[dict(hex='abc')],300,160),[])
        self.assertEqual(historical_aircraft(tracks,[],300,401),[])
        history=TrafficHistory();history.ingest([dict(hex='abc',lat=44,lon=26,flight='TEST123',track=130,gs=230,seen_pos=0)],100)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'trails.json.gz';history.save(path,110)
            restored=TrafficHistory();restored.load(path,160)
            marker=historical_aircraft(restored.snapshot(),[],300,160)[0]
            self.assertEqual((marker['flight'],marker['track'],marker['gs']),('TEST123',130,230))

    def test_zoomed_trail_crossing_viewport_keeps_its_offscreen_endpoint(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock();ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        ui.radiogarden_project.side_effect=[(-100,300,1),(400,300,1)]
        manager=Mock();now=time.time()
        manager.track_snapshot.return_value={'abc':[dict(time=now-10,lat=44.5,lon=26),dict(time=now,lat=44.5,lon=26.01)]}
        workspace=ADSBWorkspace(ui,manager);workspace.scale=12000
        workspace.draw_map(Mock(),dict(enabled=True,started_at=now-100,aircraft=[]),[])
        ui.draw_logical_polyline.assert_called_once_with([(-100,300),(400,300)],(*workspace.CYAN,150),2)
        ui.draw_logical_points.assert_called_once_with([(400,300)],(*workspace.CYAN,220),4)

    def test_manual_zoom_passes_imagery_detail_limit_and_stays_selected(self):
        from adsb_workspace import ADSBWorkspace
        from adsb_traffic import MAP_ZOOM_MAX
        ui=Mock();ui.contains.return_value=True
        workspace=ADSBWorkspace(ui,Mock());workspace.scale=120
        workspace.actions=[((0,0,10,10),('zoom',1.6))]
        workspace.tap(5,5)
        self.assertEqual(workspace.scale,192)
        self.assertTrue(workspace.centered,'New aircraft must not undo a manually chosen zoom')
        for _ in range(20):workspace.tap(5,5)
        self.assertEqual(workspace.scale,MAP_ZOOM_MAX)
        workspace.zoom(1/1.6)
        self.assertLess(workspace.scale,MAP_ZOOM_MAX)

    def test_startup_notice_expires_after_five_seconds_without_hiding_history(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock();ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        manager=Mock();manager.track_snapshot.return_value={}
        workspace=ADSBWorkspace(ui,manager)
        state=dict(enabled=True,started_at=100,aircraft=[])
        for stamp,visible in ((100,True),(104.99,True),(105,False),(1000,False)):
            with self.subTest(stamp=stamp):
                ui.draw_text.reset_mock()
                with patch('adsb_workspace.time.time',return_value=stamp):workspace.draw_map(Mock(),state,[])
                labels=[str(call.args[3]) for call in ui.draw_text.call_args_list]
                self.assertEqual('LISTENING FOR AIRCRAFT' in labels,visible)
        # VHF modes supply their own explanatory panels, unaffected by this timer.
        state.update(empty_title='METEOR RECEPTION')
        with patch('adsb_workspace.time.time',return_value=1000):workspace.draw_map(Mock(),state,[])
        self.assertIn('METEOR RECEPTION',[str(call.args[3]) for call in ui.draw_text.call_args_list])

    def test_touchscreen_trails_cycle_through_24_hours_and_off(self):
        from adsb_workspace import ADSBWorkspace
        from adsb_traffic import TRAIL_WINDOWS,trail_label
        ui=Mock();ui.contains.return_value=True
        workspace=ADSBWorkspace(ui,Mock())
        self.assertEqual(workspace.trail_seconds,300)
        workspace.trail_seconds=86400
        workspace.actions=[((0,0,10,10),('trails',None))]
        values=[]
        for _ in TRAIL_WINDOWS:
            workspace.tap(5,5);values.append(workspace.trail_seconds)
        self.assertEqual(values,list(TRAIL_WINDOWS))
        self.assertEqual(trail_label(86400),'24 H')

    def test_receiver_controls_are_available_through_settings_from_each_screen(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock()
        ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800;ui.GL.GL_SCISSOR_BIT=1;ui.GL.GL_ENABLE_BIT=2
        ui.contains.side_effect=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3]
        manager=Mock();manager.track_snapshot.return_value={}
        manager.log_snapshot.return_value=dict(entries=[],lines=[])
        state=dict(enabled=False,status='STOPPED',aircraft=[],messages=0,detail='',port=8090,devices=[],selection='auto')
        manager.snapshot.side_effect=lambda:dict(state)
        def control(action,value):state.update(enabled=action=='start')
        manager.control.side_effect=control
        workspace=ADSBWorkspace(ui,manager);workspace.show()
        for drawer in (None,'usb_open','logs_open','traffic_open'):
            workspace.usb_open=workspace.logs_open=workspace.traffic_open=False
            workspace.settings_open=False;workspace.navigation=[]
            if drawer:setattr(workspace,drawer,True)
            workspace.draw(Mock());self.press(workspace,('settings',None))
            for action in ('start','stop'):
                workspace.draw(Mock())
                box=next(box for box,item in workspace.actions if item==(action,None))
                workspace.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
                manager.control.assert_called_with(action,None)
                self.assertEqual(state['enabled'],action=='start')

    def test_aircraft_render_select_and_drag(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock()
        ui.fit_station_text.side_effect=lambda cache,text,*args:text
        ui.radiogarden_project.return_value=(400,450,1)
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.NATIVE_H=800
        ui.GL.GL_SCISSOR_BIT=1
        ui.GL.GL_ENABLE_BIT=2
        ui.contains.side_effect=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3]
        manager=Mock()
        manager.snapshot.return_value=dict(enabled=True,status='RECEIVING',aircraft=[dict(hex='abc123',lat=45,lon=25,seen=0,seen_pos=0,flight='TEST123',track=90)],messages=100,detail='Test',port=8090,devices=[],selection='auto')
        workspace=ADSBWorkspace(ui,manager)
        workspace.show()
        workspace.draw(Mock())
        self.assertEqual(len(workspace.points),1)
        workspace.tap(400,450)
        self.assertEqual(workspace.selected,'abc123')
        workspace.drag_begin(400,450)
        ui.radiogarden_pan_angles.return_value=(1,2)
        workspace.drag_move(400,450,460,470)
        self.assertTrue(workspace.swipe())
        self.assertFalse(workspace.dragged)
        self.assertEqual((workspace.yaw,workspace.pitch),(1,2))
        workspace.draw(Mock())
        labels=[str(call.args[3]) for call in ui.draw_text.call_args_list]
        self.assertTrue(any('ICAO ABC123' in label for label in labels))


class LogsAndHistoryTests(unittest.TestCase):
    def test_deep_zoom_reuses_bounded_imagery_tiles(self):
        from adsb_globe import GlobeAssets
        from adsb_traffic import MAP_ZOOM_MAX
        import globe_tiles
        globe=GlobeAssets();globe.fetcher=Mock();globe.fetcher.ready.return_value=None
        view=globe.view(dict(yaw=['26.03'],pitch=['44.50'],scale=[str(MAP_ZOOM_MAX)],width=['1024'],height=['624']))
        keys=globe.fetcher.prefetch.call_args.args[0]
        self.assertTrue(keys)
        self.assertLessEqual(len(keys),globe_tiles.MAX_VISIBLE_TILES)
        self.assertTrue(all(key.level<=globe_tiles.MAX_LEVEL for key in keys))
        self.assertEqual(view['tiles'],[])
        with self.assertRaises(ValueError):globe.view(dict(scale=[str(MAP_ZOOM_MAX+1)]))

    def test_trails_keep_a_full_day_with_bounded_points_and_recent_detail(self):
        from adsb_traffic import TrafficHistory
        history=TrafficHistory()
        start=100000
        for elapsed in range(0,86401,60):
            history.ingest([dict(hex='abc',lat=45,lon=25+elapsed/864000,seen_pos=0)],start+elapsed)
        points=history.snapshot()['abc']
        self.assertEqual(points[0]['time'],start)
        self.assertEqual(points[-1]['time'],start+86400)
        self.assertGreater(len(points),512)
        self.assertLessEqual(len(points),2048)
        for elapsed in (86404,86408,86412):
            history.ingest([dict(hex='abc',lat=45,lon=26,seen_pos=0)],start+elapsed)
        self.assertEqual([p['time'] for p in history.snapshot()['abc'][-3:]],[start+86404,start+86408,start+86412])
        self.assertTrue(all(p['time']>=start+12 for p in history.snapshot()['abc']))
        history.ingest([],start+2*86400+13)
        self.assertEqual(history.snapshot(),{})

    def test_day_trails_are_bounded_and_reload_after_manager_restart(self):
        from adsb_traffic import TrafficHistory
        now=time.time()
        history=TrafficHistory(limit=3,max_points=4)
        for n in range(6):
            history.ingest([dict(hex=str(n),lat=45,lon=25,seen_pos=0)],now-3600+n)
        self.assertLessEqual(len(history.snapshot()),3)
        self.assertLessEqual(sum(map(len,history.snapshot().values())),4)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'trails.json.gz'
            history.save(path,now)
            with patch('adsb_monitor.threading.Thread.start'):
                manager=ADSBManager(root=root,scanner=lambda:[],port=-1)
            manager.thread=Mock()
            try:
                self.assertEqual(manager.track_snapshot(),history.snapshot())
                manager._save_history(force=True)
                restored=TrafficHistory();restored.load(path,now+86400)
                self.assertEqual(restored.snapshot(),{})
                path.write_bytes(b'broken checkpoint')
                restored.load(path,now)
                self.assertEqual(restored.snapshot(),{})
            finally:manager.close()

    def test_rotated_tail_skips_partial_writes_and_keeps_newest_entries(self):
        from adsb_logs import read_log_tail
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'receiver.jsonl.1').write_text(json.dumps(dict(time=1,event='old'))+'\n')
            (root/'receiver.jsonl').write_text(json.dumps(dict(time=2,event='new'))+'\n{"partial":')
            data=read_log_tail(root,'receiver')
            self.assertEqual([r['event'] for r in data['entries']],['old','new'])
            self.assertIn('UTC',data['lines'][-1])
            with self.assertRaises(ValueError):read_log_tail(root,'../settings')

    def test_trail_history_retains_departed_aircraft_and_expires_old_tracks(self):
        from adsb_traffic import TrafficHistory
        history=TrafficHistory(limit=2,points=3,retention=30)
        for stamp in (100,105,110,115):
            history.ingest([dict(hex='abc',lat=45,lon=25+stamp/1000,seen_pos=0)],stamp)
        self.assertEqual(len(history.snapshot()['abc']),3)
        history.ingest([],120)
        self.assertIn('abc',history.snapshot())
        history.ingest([],146)
        self.assertEqual(history.snapshot(),{})

    def test_invalid_positions_are_not_turned_into_trails(self):
        from adsb_traffic import TrafficHistory, receiver_position
        history=TrafficHistory()
        history.ingest([dict(hex='bad',lat=float('nan'),lon=25),dict(hex='stale',lat=45,lon=25,seen_pos=90)],100)
        self.assertEqual(history.snapshot(),{})
        for value in (dict(lat=91,lon=0),dict(lat=0,lon=float('nan')),'bad'):
            with self.assertRaises(ValueError):receiver_position(value)
        self.assertEqual(receiver_position(dict(lat=0,lon=0)),dict(lat=0,lon=0))

    def test_site_persists_and_uat_reports_actual_installed_binaries(self):
        with tempfile.TemporaryDirectory() as root:
            manager=ADSBManager(root=root,scanner=lambda:[],port=-1)
            try:
                manager.control('location',position=dict(lat=44.4,lon=26.1))
                self.assertEqual(json.loads((Path(root)/'settings.json').read_text())['position'],dict(lat=44.4,lon=26.1))
                manager.uat.binary=str(Path(root)/'missing-dump978')
                bands=manager.snapshot()['bands']
                self.assertEqual([b['id'] for b in bands],['1090','978'])
                self.assertFalse(bands[1]['installed'])
                manager.uat.binary=manager.uat.tracker=shutil.which('true')
                self.assertTrue(manager.snapshot()['bands'][1]['installed'])
            finally:manager.close()

    def test_visible_log_endpoint_and_download_are_the_same_saved_data(self):
        with tempfile.TemporaryDirectory() as root:
            manager=ADSBManager(root=root,scanner=lambda:[],port=0)
            try:
                manager._event('test',detail='Receiver <ready>')
                manager.next_logs=0;manager._refresh_logs()
                base=f'http://127.0.0.1:{manager.port}'
                data=json.load(urlopen(base+'/api/logs?kind=receiver'))
                self.assertEqual(data['entries'][-1]['event'],'test')
                raw=urlopen(base+'/api/log?kind=receiver').read().decode()
                self.assertIn('Receiver <ready>',raw)
                for asset,mime in (('adsb_globe.js','text/javascript'),('adsb_controls.js','text/javascript'),('adsb_map.css','text/css')):
                    self.assertIn(mime,urlopen(base+'/'+asset).headers['Content-Type'])
                with self.assertRaises(HTTPError):urlopen(base+'/api/log?kind=../settings')
            finally:manager.close()

if __name__=='__main__':unittest.main()
