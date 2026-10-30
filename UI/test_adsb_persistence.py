"""Disk batching must preserve live RAM views, durable restarts and log downloads."""
import json
import logging
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from adsb_coverage import ReceptionCoverage
from adsb_persistence import BufferedFlightHandler, PERSIST_SECONDS

SITE=dict(lat=37.6624,lon=-121.8747)


def sample(stamp):
    return dict(time=stamp,aircraft=dict(hex='abc123',type='adsb_icao',lat=37.7,lon=-121.8,seen_pos=0,alt_geom=10000,rssi=-20))


class PersistenceTests(unittest.TestCase):
    def test_live_ram_window_precedes_disk_flush_and_interval_is_five_minutes(self):
        self.assertEqual(PERSIST_SECONDS,300)
        with tempfile.TemporaryDirectory() as tmp:
            now=time.time();c=ReceptionCoverage(tmp);c.add([sample(now)]);c.tick(SITE,now=now)
            self.assertFalse((Path(tmp)/'coverage.sqlite3').exists())
            c.snapshot(now-60)
            with patch('adsb_coverage.sqlite3.connect',side_effect=AssertionError('A live view must not reopen SD storage')):
                c.add([sample(now+5)]);c.tick(SITE,now=now+5)
                self.assertEqual(c.snapshot(now-60)['meta']['retained_positions'],2)
            self.assertFalse(c.flush());c.next_flush=0
            with patch('adsb_coverage.sqlite3.connect',side_effect=OSError('temporarily unavailable')):
                with self.assertRaises(OSError):c.flush()
            self.assertGreater(c.db.execute('SELECT count(*) FROM dirty_positions').fetchone()[0],0)
            self.assertTrue(c.flush())
            disk=sqlite3.connect(str(Path(tmp)/'coverage.sqlite3'))
            self.assertEqual(disk.execute('SELECT count(*) FROM positions').fetchone()[0],2);disk.close()
            c.add([sample(now+10)]);c.close() # A normal stop persists its pending batch.
            again=ReceptionCoverage(tmp);again.tick(SITE,now=now+11)
            self.assertEqual(again.snapshot()['meta']['retained_positions'],3)
            self.assertEqual(sum(s['positions'] for s in again.maximum_snapshot()['footprint']['sectors']),3)
            again.close()

    def test_flight_log_is_live_in_ram_download_and_only_persists_at_due_or_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'flights.jsonl';handler=BufferedFlightHandler(path,100000,2)
            first=json.dumps(dict(time=1,aircraft=dict(hex='abc123')))
            handler.handle(logging.LogRecord('test',logging.INFO,'',0,first,(),None))
            self.assertFalse(path.exists());self.assertEqual(handler.pending_lines(),[first])
            self.assertEqual(handler.read_log().decode().strip(),first)
            handler.flush_if_due();self.assertFalse(path.exists())
            handler.next_flush=0;handler.flush_if_due();self.assertEqual(path.read_text().strip(),first)
            second=json.dumps(dict(time=2));handler.handle(logging.LogRecord('test',logging.INFO,'',0,second,(),None))
            self.assertEqual(len(handler.read_log().splitlines()),2);self.assertEqual(len(path.read_text().splitlines()),1)
            handler.close();self.assertEqual(len(path.read_text().splitlines()),2)


if __name__=='__main__':unittest.main()
