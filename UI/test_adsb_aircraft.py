"""Aircraft lookups stay off the receiver/UI thread and verify identity."""
import gzip
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from PIL import Image
from adsb_aircraft import AircraftDetails, valid_url, PHOTO_HOSTS


def wait(service,key):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        row=service.snapshot(key)
        if row['status']!='loading':return row
        time.sleep(.01)
    raise AssertionError('lookup did not finish')


class AircraftDetailsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.db=self.root/'map/db2';self.db.mkdir(parents=True)
        for name,data in [('A',dict(children=['AB'])),('AB',dict(children=['ABC'])),('ABC',{'123':['N123AB','C172','00',None]}),('icao_aircraft_types2',{'C172':['CESSNA 172 Skyhawk','L1P','L']})]:
            (self.db/(name+'.js')).write_bytes(gzip.compress(json.dumps(data).encode()))
        self.services=[]

    def tearDown(self):
        for s in self.services:
            s.close()
            if s.thread:s.thread.join(timeout=2)
        self.tmp.cleanup()

    def service(self,fetcher):
        s=AircraftDetails(self.root,self.root/'map',fetcher);self.services.append(s);return s

    def test_offline_local_database_still_shows_registration_and_full_type(self):
        def offline(*args):raise OSError('offline')
        row=wait(self.service(offline),'abc123')
        self.assertEqual(row['model'],'CESSNA 172 Skyhawk');self.assertEqual(row['registration'],'N123AB')
        self.assertEqual(row['icao_type'],'C172');self.assertNotIn('photo',row)

    def test_deduplicated_nonblocking_lookup_and_persistent_matched_thumbnail(self):
        gate=threading.Event();calls=[]
        image=BytesIO();Image.new('RGB',(400,300),'blue').save(image,format='JPEG')
        payload=dict(mode_s='ABC123',manufacturer='Cessna',type='172S Skyhawk',registration='N123AB',icao_type='C172',url_photo='https://image.airport-data.com/aircraft/123.jpg',url_photo_thumbnail='https://airport-data.com/images/123.jpg')
        def fetch(url,*args):
            calls.append(url)
            if 'adsbdb' in url:
                gate.wait(1);return json.dumps(dict(response=dict(aircraft=payload))).encode()
            return image.getvalue()
        s=self.service(fetch);start=time.monotonic()
        for _ in range(10):self.assertEqual(s.snapshot('ABC123')['status'],'loading')
        self.assertLess(time.monotonic()-start,.2);gate.set();row=wait(s,'abc123')
        self.assertEqual(row['manufacturer'],'Cessna');self.assertTrue(row['photo_cached']);self.assertEqual(len(calls),2)
        with Image.open(s.photo_path('abc123')) as photo:self.assertLessEqual(photo.width,240);self.assertLessEqual(photo.height,160)
        row2=wait(self.service(lambda *_:self.fail('Persistent cache must avoid network')),'abc123')
        self.assertEqual(row2['model'],'172S Skyhawk')

    def test_mismatched_identity_and_untrusted_photo_are_not_used(self):
        def wrong(url,*args):return json.dumps(dict(response=dict(aircraft=dict(mode_s='ffffff',manufacturer='Wrong',url_photo_thumbnail='https://localhost/photo')))).encode()
        row=wait(self.service(wrong),'abc123');self.assertNotEqual(row.get('manufacturer'),'Wrong');self.assertNotIn('photo',row)
        for url in ('http://airport-data.com/a','https://airport-data.com.evil.test/a','https://user@airport-data.com/a','https://127.0.0.1/a'):
            self.assertFalse(valid_url(url,PHOTO_HOSTS))

    def test_hexdb_fallback_and_no_requests_for_non_icao_addresses(self):
        calls=[]
        def fetch(url,*args):
            calls.append(url)
            if 'adsbdb' in url:raise OSError('404')
            return json.dumps(dict(ModeS='ABC123',Manufacturer='Cessna',Type='172R',Registration='N123AB')).encode()
        s=self.service(fetch)
        for key in ('~abc123','abc','../../a','<script>'):
            self.assertEqual(s.snapshot(key)['status'],'unavailable');self.assertIsNone(s.photo_path(key))
        self.assertIsNone(s.thread);row=wait(s,'abc123');self.assertEqual(row['manufacturer'],'Cessna');self.assertEqual(len(calls),2)

    def test_worker_failure_is_retryable_and_cache_is_bounded(self):
        s=self.service(lambda *_: (_ for _ in ()).throw(OSError('offline')))
        self.assertEqual(wait(s,'123456')['status'],'unavailable')
        for i in range(150):s._publish(f'{i:06x}',dict(status='ready',expires=time.time()+100))
        self.assertLessEqual(len(s.rows),128)

    def test_shared_http_identity_and_thumbnail_routes(self):
        from adsb_monitor import ADSBManager
        from urllib.request import urlopen
        from urllib.error import HTTPError
        manager=ADSBManager(root=self.root/'http',scanner=lambda:[],port=0)
        try:
            manager.aircraft_details._publish('abc123',dict(status='ready',manufacturer='Cessna',model='172S',expires=time.time()+100))
            photo=manager.aircraft_details.photo_path('abc123');photo.parent.mkdir(parents=True,exist_ok=True);photo.write_bytes(b'thumbnail fixture')
            base=f'http://127.0.0.1:{manager.port}'
            self.assertEqual(json.load(urlopen(base+'/api/aircraft?hex=ABC123'))['manufacturer'],'Cessna')
            self.assertEqual(urlopen(base+'/api/aircraft/photo?hex=abc123').read(),b'thumbnail fixture')
            with self.assertRaises(HTTPError):urlopen(base+'/api/aircraft/photo?hex=../settings')
            self.assertEqual(json.load(urlopen(base+'/api/aircraft?hex=~abc123'))['status'],'unavailable')
        finally:manager.close()

    def test_native_card_uses_same_identity_without_changing_recorded_point(self):
        from unittest.mock import Mock
        from adsb_workspace import ADSBWorkspace
        from adsb_coverage_gl import observation_info
        w=ADSBWorkspace(Mock(),Mock());w.ink=Mock();view=w.coverage_view;view.draw_photo=Mock()
        view.selected_observation=observation_info(dict(base=1000,meta={},aircraft=[dict(hex='abc123',label='TEST')],points=[[0,0,1000,2000,3000,10000,-22,1,'TEST']]),0)
        w.manager.aircraft_details.snapshot.return_value=dict(status='ready',manufacturer='Cessna',model='172S Skyhawk',registration='N123AB',photo_cached=True,photo=dict(credit='Photo: Airport-Data.com'))
        view.draw_aircraft(Mock(),dict(aircraft=[]))
        labels=[c.args[3] for c in w.ink.call_args_list]
        self.assertIn('Cessna',labels);self.assertIn('172S Skyhawk',labels);self.assertIn('10,000 GNSS',labels)
        view.draw_photo.assert_called_once();self.assertEqual(view.selected_observation['time'],1000)
