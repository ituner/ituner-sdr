"""Reception evidence, persistence, geometry, bounded rendering and touch flow."""
import json
import math
import numpy as np
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from urllib.request import urlopen, Request
from adsb_coverage import ReceptionCoverage, ecef, enu, observation, retained_trail_links
from adsb_coverage_touch import paint, CoverageTouch
from adsb_view import CoverageWindow, COVERAGE_WINDOWS
import adsb_coverage_gl as dome_gl
from adsb_monitor import ADSBManager
from adsb_workspace import ADSBWorkspace

SITE=dict(lat=44.4268,lon=26.1025)


def row(stamp=None,**fields):
    return dict(time=time.time() if stamp is None else stamp, aircraft=dict(hex='abc123',type='adsb_icao',lat=44.5,lon=26.1,
                alt_geom=10000,alt_baro=9500,seen_pos=1,rssi=-22,flight='TEST123',**fields))


class CoverageTests(unittest.TestCase):
    def test_empty_dome_message_clears_height_controls_without_moving_them(self):
        w=ADSBWorkspace(Mock(),Mock());w.ink=Mock();w.manager.coverage_error=''
        view=w.coverage_view;view.mode='space';view.data=dict(status='NO SITE',meta={})
        view.draw(Mock(),dict(aircraft=[]))
        message=next(c for c in w.ink.call_args_list if c.args[3]=='Tap Site to enter antenna latitude / longitude.')
        center=message.args[1];width=message.kwargs['width']
        height=next(b for b,a in w.actions if a==('coverage_height',None))
        self.assertEqual(height,(24,468,152,550))
        self.assertGreater(center-width/2,height[2])
        self.assertLess(center+width/2,1128)  # right-side dome instruments

    def test_aircraft_card_buttons_consume_taps_above_underlying_dome_controls(self):
        ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        w=ADSBWorkspace(ui,Mock());w.coverage_open=True;view=w.coverage_view
        data=dict(base=1000,meta={},aircraft=[dict(hex='a',label='A')],points=[[0,0,1000,2000,3000,10000,-22,1,'A']])
        view.selected_observation=dome_gl.observation_info(data,0)
        w.actions=[((1128,636,1256,692),('coverage_tilt',10))]
        view.draw_aircraft(Mock(),dict(aircraft=[]));tilt=view.tilt
        w.tap(1140,644);self.assertEqual(view.aircraft,'a');self.assertEqual(view.tilt,tilt)
        box=next(box for box,action in view.panel_actions if action[0]=='coverage_close_aircraft')
        w.tap((box[0]+box[2])/2,(box[1]+box[3])/2);self.assertIsNone(view.selected_observation)

    def test_native_tap_opens_recorded_aircraft_without_filtering_or_retuning(self):
        ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        w=ADSBWorkspace(ui,Mock());w.coverage_open=True;view=w.coverage_view
        data=dict(base=1000,meta={},aircraft=[dict(hex='abc123',label='TEST')],points=[[0,0,10000,20000,3000,10000,-22,1,'TEST']],cells=[[24,6,1,-22,1,23000]])
        for mode in ('cells','trails','space'):
            view.mode=mode;view.projected=dome_gl.project(dome_gl.prepare(data,mode),0,55,920,558);view.pick_data=data
            hit=next(h for h in view.projected['hits'] if h[4] is not None)
            view.tap(hit[0]+180,hit[1]+154)
            self.assertEqual(view.selected_observation['hex'],'abc123')
            self.assertEqual(view.selected_observation['time'],1000)
            self.assertEqual(view.selected_observation['altitude'],10000)
            self.assertIsNone(view.aircraft)
            view.action('coverage_filter_aircraft',None);self.assertEqual(view.aircraft,'abc123')
            view.action('coverage_filter_aircraft',None);self.assertIsNone(view.aircraft)
            w.go_back();self.assertIsNone(view.selected_observation);self.assertTrue(w.coverage_open)
        w.manager.control.assert_not_called()

    def test_trail_midpoint_opens_an_actual_endpoint_sample_not_an_invented_position(self):
        data=dict(base=1000,meta=dict(horizontal_range_max_km=100),aircraft=[dict(hex='abc123',label='TEST')],points=[[0,0,-25000,0,5000,16000,-25,1,'TEST'],[100,0,25000,0,6000,20000,-20,1,'TEST']],segments=[[0,1]])
        frame=dome_gl.project(dome_gl.prepare(data,'space'),0,25,920,558)
        middle=frame['pick_segments'][0].mean(axis=0)
        index=dome_gl.pick_observation(frame,*middle)
        self.assertIn(index,(0,1))
        self.assertIn(dome_gl.observation_info(data,index)['time'],(1000,1100))
        self.assertIsNone(dome_gl.pick_observation(frame,-1000,-1000))

    def test_sky_trails_stay_on_the_dome_shell(self):
        arc=dome_gl.sky_arc(dome_gl.vector(0,10),dome_gl.vector(180,10))
        self.assertGreater(len(arc),2)
        for p in arc:self.assertAlmostEqual(math.sqrt(sum(v*v for v in p)),1)
        self.assertGreater(max(p[2] for p in arc),.9)

    def test_thinned_trails_preserve_continuity_without_joining_real_gaps(self):
        points=[[t,0,t*100,0,10000,35000,-20,1,'A'] for t in (0,10,20,30,80,90)]
        self.assertEqual(retained_trail_links(points,{0,3,5},[],1000),[[0,1]])
        self.assertEqual(retained_trail_links(points,{0,3,5},[1015],1000),[])
        points[1][2]=1000000
        self.assertEqual(retained_trail_links(points,{0,3},[],1000),[])

    def test_space_view_fits_all_aircraft_and_labels_height_expansion(self):
        points=[[0,0,-80000,0,10000,35000,-20,1,'A'],[10,0,80000,20000,14000,45000,-20,1,'A']]
        data=dict(base=1000,meta=dict(horizontal_range_max_km=100,max_altitude_ft=45000),aircraft=[dict(hex='a',label='A')],points=points,segments=[[0,1]])
        expanded=dome_gl.prepare(data,'space');true=dome_gl.prepare(data,'space',expanded=False)
        self.assertGreater(expanded['height_scale'],1)
        self.assertEqual(true['height_scale'],1)
        np.testing.assert_allclose(expanded['dots'][:,:2],true['dots'][:,:2])
        np.testing.assert_allclose(expanded['dots'][:,2],true['dots'][:,2]*expanded['height_scale'])
        for size in ((340,360),(920,558),(1232,460)):
            for yaw in (0,95,210):
                for tilt in (8,25,55,90):
                    frame=dome_gl.project(expanded,yaw,tilt,*size)
                    for x,y,*_ in frame['hits']:
                        self.assertTrue(30<=x<=size[0]-30,(x,size))
                        self.assertTrue(60<=y<=size[1]-60,(y,size))
        self.assertEqual(points[1][5],45000)

    def test_other_cells_do_not_dim_existing_reception(self):
        data=dict(meta=dict(rssi_min=-40,rssi_max=-20),points=[],aircraft=[],cells=[[0,0,1,-30,1,1000],[4,0,1,-30,1,1000]])
        busier=dict(data,meta=dict(rssi_min=-50,rssi_max=0),cells=[[0,0,1,-30,1,1000],[4,0,1000,-10,3,2000]])
        for signal in (False,True):
            a=dome_gl.prepare(data,'cells',signal);b=dome_gl.prepare(busier,'cells',signal)
            np.testing.assert_array_equal(a['colours'][0],b['colours'][0])

    def test_live_dome_anchor_stays_fixed_until_start_fresh(self):
        from adsb_view import TrafficView
        view=TrafficView(1000);first=view.coverage_since(1001)
        self.assertEqual(first,700)
        for now in (1010,1100,1800,10000):self.assertEqual(view.coverage_since(now),first)
        view.mode='history';view.trail_seconds=300
        self.assertEqual(view.coverage_since(1800),1500)
        view.mode='live';self.assertEqual(view.coverage_since(1800),first)
        view.start_fresh(1801)
        self.assertEqual(view.coverage_since(1802),1801)
        self.assertEqual(view.coverage_since(3000),1801)

    def test_native_loading_refresh_preserves_completed_scene_in_every_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp);now=time.time();c.add([row(now)]);c.tick(SITE,now)
            data=c.snapshot();touch=CoverageTouch(Mock())
            for mode in ('cells','trails','space'):
                touch.mode=mode;touch.update_data(data);frame=touch.frame;identity=touch.frame_id
                touch.yaw=123;touch.tilt=42;touch.detail='Pinned inspection'
                touch.update_data(dict(status='LOADING',meta={},points=[],aircraft=[],cells=[]))
                self.assertIs(touch.frame,frame);self.assertEqual(touch.frame_id,identity)
                self.assertIs(touch.data,data);self.assertEqual((touch.yaw,touch.tilt),(123,42))
                self.assertEqual(touch.detail,'Pinned inspection');self.assertTrue(touch.pending)
            later=row(now+5);later['aircraft'].update(lat=44.51,seen_pos=0)
            c.add([later]);c.snapshot();c.tick(SITE,now+6)
            touch.update_data(c.snapshot())
            self.assertFalse(touch.pending);self.assertEqual(len(touch.frame['highlights']),1)
            self.assertGreater(touch.pulse_until,time.monotonic())
            self.assertEqual(touch.detail,'Pinned inspection');c.close()

    def test_only_new_observations_flash_not_repacked_history_or_site_changes(self):
        before=dict(base=100,meta=dict(last_position=105),aircraft=[dict(hex='a'),dict(hex='b')],points=[[5,0,0,0,0,0,None,1,'']])
        # Base timestamps and aircraft indexes can change on every snapshot.
        after=dict(base=105,meta=dict(last_position=108),aircraft=[dict(hex='b'),dict(hex='a')],points=[[0,1,0,0,0,0,None,1,''],[3,0,0,0,0,0,None,1,''],[-90,1,0,0,0,0,None,1,'']])
        self.assertEqual(dome_gl.new_point_keys(before,after),{(108,'b')})
        changed=dict(after,meta=dict(last_position=108,reference=SITE))
        self.assertEqual(dome_gl.new_point_keys(before,changed),set())

    def test_maximum_footprint_survives_windows_pruning_restart_and_site_changes(self):
        from adsb_footprint import destination
        from adsb_coverage import RETENTION
        with tempfile.TemporaryDirectory() as tmp:
            now=time.time();c=ReceptionCoverage(tmp)
            for stamp,metres in ((now-100,10000),(now-2,1000)):
                p=destination(SITE,92,metres);sample=row(stamp);sample['receiver_position']=SITE
                sample['aircraft'].update(lat=p['lat'],lon=p['lon']);c.add([sample])
            c.tick(SITE,now)
            maximum=c.maximum_snapshot();self.assertEqual(maximum['meta']['retained_positions'],2)
            self.assertAlmostEqual(maximum['footprint']['sectors'][0]['radius_m'],10000,places=2)
            c.snapshot(now-10);c.tick(SITE,now+6)
            self.assertAlmostEqual(c.snapshot(now-10)['footprint']['sectors'][0]['radius_m'],1000,places=2)
            self.assertEqual(c.maximum_snapshot(),maximum)
            c.tick(SITE,now+RETENTION+10)
            self.assertEqual(c.db.execute('SELECT count(*) FROM positions').fetchone()[0],0)
            self.assertEqual(c.maximum_snapshot(),maximum);c.close()
            c=ReceptionCoverage(tmp);c.tick(SITE,now)
            self.assertEqual(c.maximum_snapshot(),maximum)
            c.tick(dict(lat=37.6624,lon=-121.8747),now+6)
            self.assertEqual(c.maximum_snapshot()['footprint']['regions'],[])
            c.tick(SITE,now+12);self.assertEqual(c.maximum_snapshot(),maximum)
            p=destination(SITE,92,12000);sample=row(now+15);sample['receiver_position']=SITE
            sample['aircraft'].update(lat=p['lat'],lon=p['lon']);c.add([sample]);c.tick(SITE,now+16)
            newer=c.maximum_snapshot();self.assertEqual(newer['meta']['retained_positions'],3)
            self.assertAlmostEqual(newer['footprint']['sectors'][0]['radius_m'],12000,places=2)
            c.tick(SITE,now+20);self.assertEqual(c.maximum_snapshot(),newer);c.close()

    def test_wgs84_overhead_and_earth_curvature(self):
        e,n,u=enu(SITE['lat'],SITE['lon'],1000,SITE)
        self.assertLess(math.hypot(e,n),1e-7);self.assertAlmostEqual(u,1000)
        e,n,u=enu(0,1,0,dict(lat=0,lon=0))
        self.assertAlmostEqual(math.degrees(math.atan2(u,math.hypot(e,n))),-.5)

    def test_only_fresh_direct_positions_with_numeric_altitude(self):
        valid=row();self.assertIsNotNone(observation(valid))
        for patch_fields in (dict(seen_pos=11),dict(seen_pos=-1),dict(lat=float('nan')),dict(type='mlat'),dict(mlat=['lat']),dict(tisb=['lon']),dict(alt_geom=None,alt_baro='ground')):
            candidate=json.loads(json.dumps(valid));candidate['aircraft'].update(patch_fields)
            self.assertIsNone(observation(candidate),patch_fields)
        valid['aircraft']['alt_geom']=None
        self.assertEqual(observation(valid)[4:6],(9500,0))
        valid['aircraft']['rssi']=None
        self.assertIsNone(observation(valid)[6])

    def test_rotated_log_import_dedup_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);sample=row()
            (root/'flights.jsonl').write_text(json.dumps(sample)+'\ninvalid\n')
            (root/'flights.jsonl.1').write_text(json.dumps(sample)+'\n')
            c=ReceptionCoverage(root);c.tick(SITE);data=c.snapshot()
            self.assertEqual(data['meta']['retained_positions'],1)
            self.assertEqual(data['meta']['max_altitude_ft'],10000)
            self.assertEqual(data['meta']['max_altitude_source'],'GNSS')
            c.close();c=ReceptionCoverage(root);c.tick(SITE)
            self.assertEqual(c.snapshot()['meta']['retained_positions'],1);c.close()

    def test_window_filters_full_database_statistics_cells_footprint_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp);now=time.time()
            old=row(now-120);old['aircraft'].update(alt_geom=35000,lat=44.9)
            recent=row(now-2);recent['aircraft'].update(alt_geom=1000)
            c.add([old,recent]);c.tick(SITE,now=now)
            self.assertEqual(c.snapshot()['meta']['retained_positions'],2)
            self.assertEqual(c.snapshot(now-10)['status'],'LOADING')
            with patch('adsb_coverage.DISPLAY_POINTS',1):c.tick(SITE,now=now+1)
            fresh=c.snapshot(now-10)
            self.assertEqual(fresh['meta']['retained_positions'],1);self.assertEqual(fresh['meta']['max_altitude_ft'],1000)
            self.assertEqual(sum(cell[2] for cell in fresh['cells']),1)
            self.assertEqual(sum(sector['positions'] for sector in fresh['footprint']['sectors']),1)
            self.assertEqual(c.snapshot()['meta']['retained_positions'],2)
            self.assertEqual(c.db.execute('SELECT count(*) FROM positions').fetchone()[0],2)
            c.snapshot(now+10);c.tick(SITE,now=now+2)
            empty=c.snapshot(now+10);self.assertEqual(empty['status'],'EMPTY');self.assertEqual(empty['points'],[])
            for index in range(10):c.snapshot(now-index)
            self.assertLessEqual(len(c.scoped),4);c.close()

    def test_reference_and_height_change_reprojects_without_changing_altitude(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp);c.add([row()]);c.tick(SITE);first=c.snapshot()
            c.set_height(100);c.tick(SITE,now=time.time()+6);changed=c.snapshot()
            self.assertEqual(first['points'],changed['points']) # packed ENU is referenced at zero ellipsoid height
            self.assertEqual(changed['meta']['reference_height_m'],100)
            self.assertEqual(first['meta']['max_altitude_ft'],changed['meta']['max_altitude_ft'])
            self.assertNotEqual(first['meta']['slant_range_max_km'],changed['meta']['slant_range_max_km'])
            c.snapshot();c.tick(dict(lat=44.5,lon=26.0),now=time.time()+12)
            self.assertEqual(c.snapshot()['status'],'EMPTY')
            self.assertEqual(c.snapshot()['meta']['excluded_other_sites'],1)
            c.snapshot();c.tick(SITE,now=time.time()+18)
            self.assertEqual(c.snapshot()['meta']['retained_positions'],1)
            c.close();c=ReceptionCoverage(tmp);self.assertEqual(c.height,100);c.close()

    def test_retention_and_full_history_statistics_with_thinned_dots(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp);now=time.time()
            samples=[]
            for i in range(25):
                sample=row(now-100+i);sample['aircraft'].update(lat=44.46+i*.001,alt_geom=12000 if i==13 else 1000)
                samples.append(sample)
            c.add(samples+[row(now-91*86400)])
            with patch('adsb_coverage.DISPLAY_POINTS',5):c.tick(SITE)
            data=c.snapshot();self.assertEqual(data['meta']['retained_positions'],25)
            self.assertLessEqual(len(data['points']),8);self.assertEqual(data['meta']['max_altitude_ft'],12000)
            self.assertEqual(sum(cell[2] for cell in data['cells']),25)
            self.assertEqual(sum(s['positions'] for s in data['footprint']['sectors']),25)
            self.assertIn(12000,[p[5] for p in data['points']]);c.close()

    def test_mobile_receiver_positions_are_kept_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=SITE;b=dict(lat=45.0,lon=26.0);first=row();first['receiver_position']=a
            second=row(time.time()+2);second['receiver_position']=b
            c=ReceptionCoverage(tmp);c.add([first,second]);c.tick(a)
            self.assertEqual(c.snapshot()['meta']['retained_positions'],1)
            self.assertEqual(c.snapshot()['meta']['excluded_other_sites'],1)
            c.snapshot();c.tick(b,time.time()+6)
            self.assertEqual(c.snapshot()['meta']['retained_positions'],1)
            self.assertEqual(c.snapshot()['meta']['excluded_other_sites'],1)
            self.assertEqual(c.snapshot()['footprint']['site'],b)
            self.assertEqual(sum(s['positions'] for s in c.snapshot()['footprint']['sectors']),1);c.close()

    def test_empty_and_unknown_site_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp);c.tick(None);self.assertEqual(c.snapshot()['status'],'NO SITE')
            c.tick(SITE,time.time()+6);self.assertEqual(c.snapshot()['status'],'EMPTY');c.close()

    def test_height_validation_and_lifecycle_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp)
            for invalid in (float('nan'),True,'100',9001):
                with self.assertRaises(ValueError):c.set_height(invalid)
            now=time.time();c.add([row(now-2)]);c.mark_break(now-1);c.tick(SITE)
            self.assertIn(now-1,c.snapshot()['breaks']);c.close()

    def test_native_all_modes_and_black_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp);c.add([row()]);c.tick(SITE);data=c.snapshot()
            for mode in ('cells','trails','space'):
                raster,labels,hits=paint(data,mode,0,55,True)
                self.assertEqual(len(raster),1232*460*4)
                self.assertEqual(raster[:4],bytes((0,0,0,255)))
                self.assertTrue(any('MAX ALT 10,000 ft' in item[2] for item in labels))
                self.assertTrue(hits)
            c.close()

    def test_dome_timespan_defaults_to_hour_rolls_and_supports_all_recorded(self):
        window=CoverageWindow();self.assertEqual(window.seconds,3600)
        self.assertEqual(window.since(10000),6360)
        self.assertEqual(window.since(10019),6360)
        self.assertEqual(window.since(10020),6420)
        for seconds,label in COVERAGE_WINDOWS:
            window.select(seconds,10000000);self.assertEqual(window.label,label)
            self.assertEqual(window.since(10000000),9999940 if seconds==60 else 9999960-seconds if seconds else 0)
        with self.assertRaises(ValueError):window.select(1)

    def test_fresh_minute_starts_now_rolls_without_periodic_reset_and_can_restart(self):
        window=CoverageWindow();window.select(60,1000.25)
        self.assertEqual(window.since(1000.25),940)
        window.reset(1000.25)
        self.assertEqual(window.since(1000.25),1000.25)
        self.assertEqual(window.since(1059),1000.25)
        self.assertEqual(window.since(1061),1000.25)
        self.assertEqual(window.since(1120),1060)
        window.reset(1123.5);self.assertEqual(window.since(1123.5),1123.5)
        window.select(300,1130);self.assertIsNone(window.started_at)
        self.assertEqual(window.since(1130),780)
        self.assertEqual([v for v,_ in COVERAGE_WINDOWS],[60,300,1800,3600,21600,86400,604800,0])

    def test_reset_preserves_each_duration_and_selection_restores_history(self):
        for seconds,_ in COVERAGE_WINDOWS:
            window=CoverageWindow();window.select(seconds)
            revision=window.revision;window.reset(10000000.25)
            self.assertEqual(window.seconds,seconds)
            self.assertEqual(window.revision,revision+1)
            self.assertEqual(window.since(10000001),10000000.25)
            window.select(seconds)
            self.assertIsNone(window.started_at)
            self.assertLess(window.since(10000001),10000000.25)

    def test_native_fresh_minute_clears_scene_and_stats_rejects_old_request_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=time.time();c=ReceptionCoverage(tmp);c.add([row(now-20)]);c.tick(SITE)
            data=c.snapshot();view=CoverageTouch(ADSBWorkspace(Mock(),Mock()))
            view.update_data(data);old_revision=view.window.revision
            self.assertEqual(view.data['meta']['retained_positions'],1)
            view.selected_observation={'hex':'abc123'};view.aircraft='abc123'
            view.action('coverage_span',300)
            self.assertEqual(view.data['meta']['retained_positions'],1)
            with patch('adsb_view.time.time',return_value=now):view.action('coverage_clock_reset',None)
            self.assertEqual(view.window.seconds,300)
            self.assertEqual(view.data['points'],[]);self.assertEqual(view.data['meta']['retained_positions'],0)
            self.assertEqual(view.data['meta']['horizontal_range_max_km'],0)
            self.assertIsNone(view.data['meta']['max_altitude_ft']);self.assertIsNone(view.selected_observation)
            self.assertIsNone(view.aircraft);self.assertFalse(view.update_data(data,old_revision))
            self.assertEqual(view.data['points'],[])
            self.assertEqual(c.snapshot()['meta']['retained_positions'],1)
            view.action('coverage_span',300);self.assertTrue(view.update_data(data,view.window.revision))
            self.assertEqual(view.data['meta']['retained_positions'],1);c.close()

    def test_native_dome_window_is_independent_and_back_cancels_picker(self):
        w=ADSBWorkspace(Mock(),Mock());w.coverage_open=True
        dome=w.coverage_view
        w.set_traffic_view('history');w.traffic_view.start_fresh(100)
        self.assertEqual(dome.window.seconds,3600)
        dome.action('coverage_window',None);self.assertTrue(dome.window_open)
        w.go_back();self.assertFalse(dome.window_open);self.assertTrue(w.coverage_open)
        dome.action('coverage_window',None);dome.action('coverage_span',300)
        self.assertFalse(dome.window_open);self.assertEqual(dome.window.seconds,300)
        self.assertTrue(dome.pending)
        dome.action('coverage_span',0);self.assertEqual(dome.window.since(10000),0)

    def test_native_coverage_navigation_and_drag_stay_in_coverage(self):
        ui=Mock();ui.contains.side_effect=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3]
        manager=Mock();w=ADSBWorkspace(ui,manager)
        with patch.object(w.coverage_view,'activate'):
            w.actions=[((0,0,100,60),('coverage',None))];w.tap(20,20)
        self.assertTrue(w.coverage_open)
        w.drag_begin(500,400);w.drag_move(500,400,600,420)
        self.assertTrue(w.dragged);self.assertEqual(w.coverage_view.yaw,35)
        w.actions=[((0,0,100,60),('map_view',None))];w.tap(20,20)
        self.assertFalse(w.coverage_open)

    def test_batched_dome_keeps_unknown_cells_filters_and_altitude(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp);c.add([row()]);c.tick(SITE);data=c.snapshot()
            for mode in ('cells','trails','space'):
                scene=dome_gl.prepare(data,mode)
                frame=dome_gl.project(scene,35,55,920,590)
                self.assertTrue(any('MAX ALT 10,000 ft' in item[2] for item in frame['labels']))
                self.assertTrue(frame['hits'])
                if mode=='cells':
                    self.assertEqual(len(scene['cells']),4050)
                    self.assertTrue(any('unobserved / unknown' in h[2] for h in frame['hits']))
                else:
                    self.assertEqual(len(scene['dots']),len(data['points']))
                    empty=dome_gl.prepare(data,mode,aircraft='missing')
                    self.assertEqual(len(empty['dots']),0)
                for _,vertices,colours in frame['batches']:
                    self.assertEqual(len(vertices),len(colours))
                    self.assertTrue(np.isfinite(vertices).all())
            c.close()

    def test_rotation_changes_projection_without_rebuilding_or_uploading_raster(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=ReceptionCoverage(tmp);c.add([row()]);c.tick(SITE)
            scene=dome_gl.prepare(c.snapshot(),'cells')
            frame=dome_gl.project(scene,0,55,920,590)
            rotated=dome_gl.project(scene,90,55,920,590)
            self.assertFalse(np.array_equal(frame['batches'][0][1],rotated['batches'][0][1]))
            ui=Mock();ui.logical_to_native.side_effect=lambda x,y:(800-y,x)
            dome_gl.draw(ui,frame,(180,154,1100,744));cached=frame['native']
            dome_gl.draw(ui,frame,(180,154,1100,744))
            self.assertIs(frame['native'],cached)
            ui.GL.glTexImage2D.assert_not_called()
            self.assertLessEqual(ui.GL.glDrawArrays.call_count,6)
            c.close()

    def test_distance_scale_stays_sparse_and_readable_at_large_ranges(self):
        for radius in (5000,90000,250000,500000):
            for pixels in (110,218,430):
                ticks=dome_gl.distance_ticks(radius,pixels)
                self.assertEqual(ticks[-1],radius)
                self.assertLessEqual(len(ticks),4)
                for a,b in zip(ticks,ticks[1:]):self.assertGreaterEqual((b-a)/radius*pixels,72)
        scene=dome_gl.prepare(dict(meta=dict(horizontal_range_max_km=490)),'space')
        self.assertLess(len(scene['lines']),600) # no hundred-ring mesh
        for width,height in ((340,360),(920,558)):
            for yaw in (0,90,213):
                for tilt in (8,55,90):
                    frame=dome_gl.project(scene,yaw,tilt,width,height)
                    labels=[p for p in frame['labels'] if p[2].replace('.','').isdigit()]
                    self.assertTrue(labels)
                    self.assertEqual(len({round(p[1],2) for p in labels}),1)
                    for a,b in zip(labels,labels[1:]):self.assertGreaterEqual(b[0]-a[0],71.99)
                    self.assertEqual(sum(p[2]=='Ground range · km' for p in frame['labels']),1)
                    self.assertTrue(all(0<p[0]<width and 0<p[1]<height for p in labels))

    def test_native_footprint_cache_toggle_and_fit_do_not_control_receiver(self):
        from adsb_footprint import build_footprint
        ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        ui.logical_to_native.side_effect=lambda x,y:(800-y,x)
        ui.radiogarden_project.side_effect=lambda p,*args:(p['lon']*10,p['lat']*10,1)
        manager=Mock();state=dict(receiver_position=SITE,aircraft=[])
        manager.snapshot.return_value=state
        manager.coverage.maximum_snapshot.return_value=dict(footprint=build_footprint(SITE,[(44.5,26.1),(44.4,26.2)]))
        w=ADSBWorkspace(ui,manager);w.dashboard=True
        w.draw_footprint(state);frame=w.rx_frame;w.draw_footprint(state)
        self.assertIs(w.rx_frame,frame)
        self.assertEqual(len(w.footprint_regions(state)),2)
        self.assertEqual(w.footprint_regions(dict(receiver_position=dict(lat=45,lon=26))),[])
        w.actions=[((0,0,100,60),('fit',None))];w.tap(20,20)
        self.assertGreater(w.scale,35)
        w.actions=[((0,0,100,60),('rx_footprint',None))];w.tap(20,20)
        self.assertEqual(w.footprint_regions(state),[])
        manager.control.assert_not_called();ui.GL.glTexImage2D.assert_not_called()

    def test_http_assets_coverage_and_authenticated_height_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'flights.jsonl').write_text(json.dumps(row())+'\n')
            manager=ADSBManager(root=tmp,scanner=lambda:[],port=0)
            try:
                manager.control('location',position=SITE)
                base=f'http://127.0.0.1:{manager.port}'
                for _ in range(30):
                    data=json.load(urlopen(base+'/api/coverage'))
                    if data['status']=='READY':break
                    time.sleep(.2)
                self.assertEqual(data['status'],'READY')
                self.assertEqual(data['meta']['retained_positions'],1)
                for asset in ('adsb_coverage.js','adsb_coverage.css'):
                    self.assertEqual(urlopen(base+'/'+asset).status,200)
                footprint=json.load(urlopen(base+'/api/footprint'))
                self.assertEqual(footprint['retained_positions'],1)
                self.assertTrue(footprint['footprint']['regions'])
                self.assertNotIn('points',footprint)
                maximum=json.load(urlopen(base+'/api/footprint?scope=maximum'))
                self.assertEqual(maximum['scope'],'accumulated maximum');self.assertTrue(maximum['footprint']['sectors'])
                token=json.load(urlopen(base+'/api/state'))['control_token']
                r=Request(base+'/api/control',data=json.dumps(dict(action='coverage_height',height_m=85)).encode(),headers={'X-ADSB-Token':token})
                self.assertTrue(json.load(urlopen(r))['ok'])
                self.assertFalse(manager.enabled);self.assertEqual(manager.coverage.height,85)
            finally:manager.close()


if __name__=='__main__':unittest.main()
