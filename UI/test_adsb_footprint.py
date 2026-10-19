"""Historical reception extent, empty bearings, site isolation and map projection."""
import unittest
import numpy as np
from adsb_footprint import build_footprint,destination,projected_frame

SITE=dict(lat=44.45908,lon=26.06622)


def position(bearing,distance):
    p=destination(SITE,bearing,distance)
    return p['lat'],p['lon']


class FootprintTests(unittest.TestCase):
    def test_maximum_in_each_bearing_keeps_empty_directions_and_north_wrap(self):
        data=build_footprint(SITE,[position(1,1000),position(2,2000),position(358,3000),position(92,4000)])
        self.assertEqual([s['azimuth_deg'] for s in data['sectors']],[0,90,355])
        self.assertEqual([s['positions'] for s in data['sectors']],[2,1,1])
        self.assertAlmostEqual(data['sectors'][0]['radius_m'],2000,places=2)
        self.assertEqual(len(data['regions']),2,'Unobserved bearings must split the footprint')
        for region in data['regions']:
            self.assertEqual(region['vertices'][0]['east'],0)
            self.assertEqual(region['vertices'][-1]['north'],0)
        self.assertEqual(sorted(len(r['vertices']) for r in data['regions']),[5,8])

    def test_all_bearings_close_without_spoke_and_empty_data_stays_empty(self):
        data=build_footprint(SITE,[position(a+1,1000) for a in range(0,360,5)])
        self.assertEqual(len(data['regions']),1)
        outline=data['regions'][0]['outline']
        self.assertEqual(outline[0],outline[-1])
        self.assertTrue(all(np.hypot(p['east'],p['north'])>999 for p in outline))
        self.assertEqual(build_footprint(SITE,[])['regions'],[])
        self.assertEqual(build_footprint(None,[])['regions'],[])

    def test_date_line_is_wrapped_and_map_horizon_is_not_bridged(self):
        site=dict(lat=0,lon=179.99);p=destination(site,90,10000)
        self.assertLess(p['lon'],0)
        data=build_footprint(site,[(p['lat'],p['lon'])])
        frame=projected_frame(data['regions'],lambda p:(p['east'],p['north'],1))
        self.assertEqual(len(frame['batches']),2)
        for _,vertices,colours in frame['batches']:
            self.assertEqual(len(vertices),len(colours));self.assertTrue(np.isfinite(vertices).all())
        self.assertEqual(projected_frame(data['regions'],lambda p:None)['batches'],[])


if __name__=='__main__':unittest.main()
