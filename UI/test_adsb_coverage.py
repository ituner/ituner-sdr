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
from adsb_coverage import ReceptionCoverage, ecef, enu, observation
from adsb_coverage_touch import paint, CoverageTouch
import adsb_coverage_gl as dome_gl
from adsb_monitor import ADSBManager
from adsb_workspace import ADSBWorkspace

SITE=dict(lat=44.4268,lon=26.1025)


def row(stamp=None,**fields):
    return dict(time=time.time() if stamp is None else stamp, aircraft=dict(hex='abc123',type='adsb_icao',lat=44.5,lon=26.1,
                alt_geom=10000,alt_baro=9500,seen_pos=1,rssi=-22,flight='TEST123',**fields))


class CoverageTests(unittest.TestCase):
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
            self.assertEqual(c.snapshot()['meta']['excluded_other_sites'],1);c.close()

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
                token=json.load(urlopen(base+'/api/state'))['control_token']
                r=Request(base+'/api/control',data=json.dumps(dict(action='coverage_height',height_m=85)).encode(),headers={'X-ADSB-Token':token})
                self.assertTrue(json.load(urlopen(r))['ok'])
                self.assertFalse(manager.enabled);self.assertEqual(manager.coverage.height,85)
            finally:manager.close()


if __name__=='__main__':unittest.main()
