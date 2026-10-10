import json
from pathlib import Path
import sys
import unittest
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from kiwi_occupancy import OccupancyCache


class OccupancyTests(unittest.TestCase):
    def setUp(self):
        self.now=0.0
        self.cache=OccupancyCache(lambda:self.now)

    def test_shared_cadence_and_independent_receivers(self):
        self.assertTrue(self.cache.request_due('http://kiwi/'))
        self.assertFalse(self.cache.request_due('http://kiwi'))
        self.assertTrue(self.cache.request_due('http://second'))
        self.now=2.5
        self.assertTrue(self.cache.request_due('http://kiwi'))

    def test_counts_anonymous_busy_channels_and_expiry(self):
        self.cache.accept('k','[{"i":0,"n":""},{"i":1},{"i":2,"n":"private"}]')
        self.assertEqual(self.cache.snapshot('k'),(2,3))
        self.now=16
        self.assertIsNone(self.cache.snapshot('k'))

    def test_encoded_json_and_bad_responses(self):
        self.cache.accept('k',quote('[{"i":0},{"i":1}]'))
        self.assertEqual(self.cache.snapshot('k'),(0,2))
        for invalid in ('oops','{}','[]','[{"i":0},{"i":0}]','[{"i":2}]','[null]'):
            self.cache.accept('other',invalid)
            self.assertIsNone(self.cache.snapshot('other'))

if __name__=='__main__':unittest.main()
