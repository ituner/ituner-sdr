"""Ground maps align with ENU reception geometry and stay out of the UI thread."""
from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock
import numpy as np
from PIL import Image
from adsb_ground import GroundMap,ground_coordinates,tile_keys,raster
from adsb_coverage import enu
from adsb_coverage_gl import prepare,project
from adsb_globe import GlobeAssets

SITE=dict(lat=37.6624,lon=-121.8747)


class GroundTests(unittest.TestCase):
    def test_ground_coordinates_round_trip_wgs84_and_date_line(self):
        for site in (SITE,dict(lat=44.4,lon=26.1),dict(lat=0,lon=179.95),dict(lat=85,lon=-80)):
            e=np.asarray([0,1000,-90000,150000]);n=np.asarray([0,50000,10000,-20000])
            lat,lon=ground_coordinates(site,e,n)
            for i in range(len(e)):
                actual=enu(float(lat[i]),float(lon[i]),0,site)
                self.assertAlmostEqual(actual[0],e[i],places=3);self.assertAlmostEqual(actual[1],n[i],places=3)
            self.assertTrue(np.isfinite(lat).all());self.assertTrue((abs(lon)<=180).all())

    def test_patch_is_north_up_with_transparent_circle_and_bounded_tiles(self):
        base=np.zeros((180,360,3),dtype=np.uint8);base[:,:,0]=np.arange(180)[:,None];base[:,:,1]=np.arange(360)[None,:]%256
        image,lat,lon=raster(SITE,100000,base,[],65)
        a=np.asarray(image);self.assertEqual(a[0,0,3],0);self.assertEqual(a[32,32,3],255)
        self.assertGreater(lat[0,32],lat[-1,32]);self.assertGreater(lon[32,-1],lon[32,0])
        lat,lon=ground_coordinates(dict(lat=0,lon=179.95),*np.meshgrid(np.linspace(-2e6,2e6,33),np.linspace(-2e6,2e6,33)))
        self.assertLessEqual(len(tile_keys(lat,lon)),16)

    def test_background_map_cache_uses_shared_globe_tiles_and_stable_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            Image.new('RGB',(360,180),'green').save(Path(tmp)/'nasa-blue-marble-2048.jpg')
            globe=GlobeAssets(tmp);globe.fetcher=Mock();globe.fetcher.ready.return_value=None
            maps=GroundMap(globe)
            try:
                self.assertEqual(maps.snapshot(None,100000)['status'],'NO SITE');self.assertIsNone(maps.thread)
                first=maps.snapshot(SITE,100000);start=time.monotonic()
                for _ in range(20):maps.snapshot(SITE,100000)
                self.assertLess(time.monotonic()-start,.1)
                deadline=time.monotonic()+4
                while time.monotonic()<deadline:
                    result=maps.snapshot(SITE,100000)
                    if result['status']=='READY':break
                    time.sleep(.02)
                self.assertEqual(result['key'],first['key']);self.assertEqual(result['status'],'READY')
                self.assertEqual(len(maps.image(first['key'],raw=True)),512*512*4)
                self.assertTrue(maps.image(first['key']).startswith(b'\x89PNG'))
                self.assertIsNone(maps.image('../etc/passwd'))
                self.assertNotEqual(maps.snapshot(dict(lat=44.4,lon=26.1),100000)['key'],first['key'])
                with self.assertRaises(ValueError):maps.snapshot(SITE,float('inf'))
                with self.assertRaises(ValueError):maps.snapshot(SITE,5e6)
            finally:maps.close();maps.thread.join(3)

    def test_native_ground_texture_is_uploaded_once_and_toggle_does_not_retune(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock();ui.logical_to_native.side_effect=lambda x,y:(x,y)
        w=ADSBWorkspace(ui,Mock());view=w.coverage_view
        data=dict(meta=dict(reference=SITE,horizontal_range_max_km=100),points=[],aircraft=[])
        scene=prepare(data,'space');view.projected=project(scene,35,25,920,558);view.mode='space'
        w.manager.ground_map.snapshot.return_value=dict(status='READY',key='a',revision=1,width=2,height=2,radius=scene['radius'],reference=SITE)
        w.manager.ground_map.image.return_value=bytes(16)
        view.action('coverage_ground',None);self.assertTrue(view.ground_enabled)
        view.draw_ground(scene,data['meta']);view.draw_ground(scene,data['meta'])
        ui.GL.glTexImage2D.assert_called_once();self.assertEqual(ui.GL.glDrawArrays.call_count,2)
        view.action('coverage_ground',None);view.draw_ground(scene,data['meta'])
        self.assertEqual(ui.GL.glDrawArrays.call_count,2);w.manager.control.assert_not_called()
