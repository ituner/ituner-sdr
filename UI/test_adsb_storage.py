"""The aggregate cap overrides age retention without resurrecting pruned history."""
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from adsb_coverage import ReceptionCoverage
from adsb_storage import StorageBudget, STORAGE_LIMIT, MIB

SITE=dict(lat=37.6624,lon=-121.8747)


def sample(stamp):
    return dict(time=stamp,receiver_position=SITE,aircraft=dict(hex='abc123',type='adsb_icao',
                lat=37.8,lon=-121.8,alt_geom=12000,seen_pos=0,rssi=-20))


class StorageTests(unittest.TestCase):
    def test_limit_is_250_mib_and_directory_total_includes_all_categories(self):
        self.assertEqual(STORAGE_LIMIT,250*MIB)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'aircraft-details').mkdir()
            for name in ('flights.jsonl','receiver.jsonl','weather-state.json','trails.json.gz','aircraft-details/a.jpg'):
                (root/name).write_bytes(b'x'*8192)
            b=StorageBudget(root)
            used=b.usage()
            self.assertEqual(len(b.files()),5)
            self.assertGreaterEqual(used,5*8192)  # CM5 allocates in larger filesystem blocks.
            self.assertEqual(b.snapshot()['used_bytes'],used)

    def test_old_rotated_logs_are_reclaimed_before_database_or_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('flights.jsonl.6','flights.jsonl.1','flights.jsonl','settings.json'):
                (root/name).write_bytes(b'x'*16384)
            import os
            os.utime(root/'flights.jsonl.6',(1,1));os.utime(root/'flights.jsonl.1',(2,2))
            b=StorageBudget(root,limit=80*1024,headroom=0)
            self.assertEqual(b.database_budget(required=32*1024),32*1024)
            self.assertFalse((root/'flights.jsonl.6').exists())
            self.assertTrue((root/'flights.jsonl.1').exists())
            self.assertTrue((root/'flights.jsonl').exists())
            self.assertTrue((root/'settings.json').exists())

    def test_pressure_compacts_disk_keeps_newest_and_restart_does_not_reimport_old_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);now=time.time();samples=[sample(now-5000+i) for i in range(5000)]
            c=ReceptionCoverage(root);c.storage=StorageBudget(root,limit=192*1024,headroom=16*1024)
            c.add(samples);c.tick(SITE,now);before=c.snapshot()
            self.assertEqual(before['meta']['retained_positions'],5000)
            maximum=c.maximum_snapshot()
            self.assertTrue(c.flush(force=True))
            self.assertLessEqual(c.storage.usage(),c.storage.limit)
            self.assertIsNotNone(c.storage_before)
            self.assertFalse(c.projections)
            c.tick(SITE,now+6);after=c.snapshot()
            self.assertGreater(after['meta']['retained_positions'],0)
            self.assertLess(after['meta']['retained_positions'],5000)
            self.assertAlmostEqual(after['meta']['last_position'],samples[-1]['time'],places=3)
            self.assertEqual(c.maximum_snapshot(),maximum)
            self.assertEqual(before['meta']['retained_positions'],5000)
            cutoff=c.storage_before;c.close()
            # A surviving/rotated packet log must not bypass the durable cutoff.
            (root/'flights.jsonl').write_text(json.dumps(samples[0])+'\n')
            c=ReceptionCoverage(root);c.storage=StorageBudget(root,limit=192*1024,headroom=16*1024)
            c.tick(SITE,now+7)
            self.assertEqual(c.storage_before,cutoff)
            self.assertEqual(c.db.execute('SELECT count(*) FROM positions WHERE time<=?',(cutoff,)).fetchone()[0],0)
            self.assertEqual(c.snapshot()['meta']['retained_positions'],after['meta']['retained_positions'])
            self.assertEqual(c.maximum_snapshot(),maximum)
            c.add([sample(now+10)]);c.tick(SITE,now+13);c.flush(force=True)
            self.assertLessEqual(c.storage.usage(),c.storage.limit)
            disk=sqlite3.connect(str(root/'coverage.sqlite3'))
            self.assertAlmostEqual(disk.execute('SELECT MAX(time) FROM positions').fetchone()[0],now+10,places=3);disk.close()
            c.close()

    def test_external_symlink_is_never_followed_or_deleted(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root=Path(tmp);other=Path(outside)/'flights.jsonl.9';other.write_bytes(b'x'*8192)
            (root/'flights.jsonl.9').symlink_to(other)
            b=StorageBudget(root,limit=1024,headroom=0)
            self.assertEqual(b.usage(),0);b.database_budget(required=10000)
            self.assertTrue(other.exists());self.assertTrue((root/'flights.jsonl.9').is_symlink())


if __name__=='__main__':unittest.main()
