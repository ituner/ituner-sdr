"""Incremental projections must retain exact observations and immutable views."""
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from adsb_coverage import ReceptionCoverage

SITE=dict(lat=44.4268,lon=26.1025)


def row(stamp):
    return dict(time=stamp,aircraft=dict(hex='abc123',type='adsb_icao',lat=44.5,lon=26.1,
                alt_geom=10000,alt_baro=9500,seen_pos=1,rssi=-22,flight='TEST123'))


class IncrementalCoverageTests(unittest.TestCase):
    def test_incremental_projection_only_reads_new_rows_and_keeps_published_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=time.time();c=ReceptionCoverage(tmp)
            original=[row(now-30+i) for i in range(20)]
            c.add(original);c.tick(SITE,now)
            first=c.snapshot();saved=json.dumps(first,sort_keys=True)
            later=row(now+3);later['aircraft'].update(hex='000001',flight='NEW',alt_geom=20000)
            late=row(now-15);late['aircraft'].update(hex='def456',lat=44.52)
            with patch('adsb_coverage.project_rows',wraps=__import__('adsb_coverage').project_rows) as project:
                c.add([later,late,original[0]]);c.snapshot();c.tick(SITE,now+6)
                self.assertEqual(len(project.call_args.args[0]),2)
                current=c.snapshot()
                self.assertEqual(current['meta']['retained_positions'],22)
                self.assertEqual(current['meta']['positioned_aircraft'],3)
                self.assertEqual(current['meta']['max_altitude_ft'],20000)
                self.assertEqual([p[0] for p in current['points']],sorted(p[0] for p in current['points']))
                self.assertEqual(current['aircraft'][first['points'][0][1]]['hex'],'abc123')
                self.assertEqual(json.dumps(first,sort_keys=True),saved)
                c.tick(SITE,now+12)
                self.assertEqual(project.call_count,1)
            c.close()

    def test_rolling_cache_reuses_coordinates_and_expires_cells_extrema_and_aircraft(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=time.time();c=ReceptionCoverage(tmp)
            old=row(now-120);old['aircraft'].update(hex='old',lat=44.9,alt_geom=40000)
            recent=row(now-10);recent['aircraft'].update(hex='new',alt_geom=1000)
            c.add([old,recent]);c.tick(SITE,now)
            c.snapshot(now-130);c.tick(SITE,now+1)
            before=c.snapshot(now-130);saved=json.dumps(before,sort_keys=True)
            c.snapshot(now-70)
            with patch('adsb_coverage.project_rows',side_effect=AssertionError('Rolling a window must reuse its projected coordinates')):
                c.tick(SITE,now+2)
            after=c.snapshot(now-70)
            self.assertEqual(after['meta']['retained_positions'],1)
            self.assertEqual(after['meta']['max_altitude_ft'],1000)
            self.assertEqual([a['hex'] for a in after['aircraft']],['new'])
            self.assertEqual(sum(v[2] for v in after['cells']),1)
            self.assertEqual(sum(v['positions'] for v in after['footprint']['sectors']),1)
            self.assertEqual(json.dumps(before,sort_keys=True),saved)
            self.assertEqual(c.snapshot()['meta']['retained_positions'],2)
            c.close()

    def test_late_sample_before_cached_base_and_new_break_are_not_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=time.time();c=ReceptionCoverage(tmp);c.add([row(now)]);c.tick(SITE,now)
            initial=c.snapshot();c.add([row(now-10)]);c.mark_break(now-5)
            c.snapshot();c.tick(SITE,now+6)
            data=c.snapshot()
            self.assertLess(data['points'][0][0],0)
            self.assertAlmostEqual(data['base']+data['points'][0][0],now-11,places=3)
            self.assertEqual(data['meta']['retained_positions'],2)
            self.assertIn(now-5,data['breaks'])
            self.assertEqual(len(initial['points']),1)
            c.close()


if __name__=='__main__':unittest.main()
