import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from location_detection import LocationDetector, parse_estimate, CACHE_SECONDS
from station_profile import StationProfile
from station_workspace import StationWorkspace

class LocationDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def estimate(self):return parse_estimate(dict(lat=44.43,lon=26.1,city='Bucharest',country='Romania'),now=1000)
    def test_validate_response_without_inventing_accuracy(self):
        value=self.estimate();self.assertEqual(value['lat'],44.43);self.assertIsNone(value['accuracy_m'])
        self.assertEqual(parse_estimate({'location':{'latitude':44.,'longitude':26.}})['lat'],44.)
        for bad in ({'lat':None,'lon':0},{'lat':float('nan'),'lon':0},{'lat':0,'lon':181},{'error':'bad'},{'lat':True,'lon':0}):
            with self.assertRaises(ValueError):parse_estimate(bad)
    def test_cache_survives_restart_without_another_request(self):
        path=self.root/'estimate.json';fetch=Mock(return_value=self.estimate())
        detector=LocationDetector(path,fetch=fetch,clock=lambda:1000);detector._run()
        again=LocationDetector(path,fetch=fetch,clock=lambda:1100)
        self.assertTrue(again.request());self.assertTrue(again.snapshot()['cached']);self.assertEqual(fetch.call_count,1)
        self.assertEqual(again.snapshot()['result']['place'],'Bucharest, Romania')
        stale=LocationDetector(path,fetch=fetch,clock=lambda:1000+CACHE_SECONDS+1)
        self.assertIsNone(stale.snapshot()['result'])
    def test_worker_is_on_demand_and_repeated_taps_are_coalesced(self):
        detector=LocationDetector(self.root/'cache',fetch=Mock(),clock=lambda:1000)
        with patch('location_detection.threading.Thread') as thread:
            self.assertTrue(detector.request());self.assertFalse(detector.request())
            thread.assert_called_once();self.assertEqual(thread.call_args.kwargs['name'],'location-lookup')
    def test_failure_and_rate_limit_never_replace_estimate(self):
        from urllib.error import HTTPError
        detector=LocationDetector(self.root/'cache',fetch=Mock(side_effect=HTTPError('https://api.ipapi.is/',429,'limit',{},None)),clock=lambda:1000)
        detector._run();self.assertIsNone(detector.snapshot()['result']);self.assertFalse(detector.request(refresh=True))
        self.assertIn('limit',detector.snapshot()['error'])
    def test_only_confirmation_updates_saved_position_and_preserves_other_edits(self):
        station=StationProfile(self.root/'station.json',start=False)
        station.update(dict(latitude=45.,longitude=25.,station_name='Home'))
        workspace=StationWorkspace(Mock(),station);workspace.show();workspace.draft['station_name']='Unsaved name';workspace.dirty=True
        detector=LocationDetector(self.root/'cache',fetch=lambda:self.estimate(),clock=lambda:1000)
        workspace.location_detector=detector;workspace.location_preview=True;detector._run()
        self.assertEqual(station.snapshot()['config']['latitude'],45.)
        workspace.cancel_location_preview();self.assertEqual(station.snapshot()['config']['latitude'],45.)
        workspace.location_preview=True;workspace.confirm_location()
        self.assertEqual(station.snapshot()['config']['latitude'],44.43)
        self.assertEqual(station.snapshot()['grid'],'KN34BK');self.assertFalse(station.snapshot()['config']['gps_auto'])
        self.assertEqual(station.snapshot()['config']['station_name'],'Home')
        self.assertEqual(workspace.draft['station_name'],'Unsaved name');self.assertTrue(workspace.dirty)
        reopened=StationProfile(station.path,start=False);self.assertEqual(reopened.snapshot()['config']['latitude'],44.43)
        reopened.close();station.close()
    def test_failed_request_cannot_be_confirmed(self):
        station=StationProfile(self.root/'station.json',start=False)
        workspace=StationWorkspace(Mock(),station);workspace.show()
        workspace.location_detector=Mock(snapshot=lambda:dict(busy=False,error='Offline',result=self.estimate()))
        workspace.confirm_location();self.assertIsNone(station.snapshot()['position']);station.close()

if __name__=='__main__':unittest.main()
