"""Real decoder input, radar georeferencing, expiry and native navigation."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import socket
import threading
import time
import unittest
from unittest.mock import Mock, patch
from adsb_weather import WeatherStore, WeatherService, radar_block, ENGINE
from adsb_weather_touch import rectangles


def iso(seconds):return dt.datetime.fromtimestamp(seconds,dt.timezone.utc).isoformat().replace('+00:00','Z')


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=WeatherStore(self.root);self.now=time.time()
    def tearDown(self):self.tmp.cleanup()
    def product(self,kind='METAR',**kw):
        return dict(type=kind,unique_name='KLVK',contents='METAR KLVK TEST',observation_time=iso(self.now),expiration_time=iso(self.now+600),**kw)
    def block(self,name='NEXRAD_REGIONAL',bins=None):
        return dict(type='IMAGE',unique_name=name,scale_factor=0,alt_bn=565297,
                    bins=bins or chr(0)*128,observation_time=iso(self.now),expiration_time=iso(self.now+600))

    def test_radar_coordinates_orientation_and_zero_semantics(self):
        b=radar_block(self.block(bins=chr(7)*32+chr(0)*96))
        self.assertAlmostEqual(b['bounds'][0],-122.4);self.assertAlmostEqual(b['bounds'][1],37+2/3)
        rects=rectangles([b]);bounds,level=rects[0]
        self.assertEqual(level,7,'Extreme returns must never disappear as no-data')
        self.assertAlmostEqual(bounds[3],b['bounds'][3]);self.assertAlmostEqual(bounds[1],b['bounds'][3]-1/60)
        conus=radar_block(self.block('NEXRAD_CONUS'))
        self.assertEqual(conus['bins'],[255]*128);self.assertEqual(rectangles([conus]),[])
        self.assertEqual(b['bins'][32],0,'Received regional zero remains distinguishable from missing coverage')

    def test_expiry_restart_and_older_report_cannot_replace_newer(self):
        self.store.ingest(self.product(),self.now,'station')
        old=self.product();old['observation_time']=iso(self.now-300);old['contents']='OLD REPORT'
        self.store.ingest(old,self.now+1,'station')
        self.assertEqual(self.store.reports['METAR:KLVK']['text'],'METAR KLVK TEST')
        self.store.ingest(self.block(),self.now,'station');self.store.save()
        fresh=WeatherStore(self.root);self.assertEqual(len(fresh.reports),1);self.assertEqual(len(fresh.radar),1)
        fresh.prune(self.now+601);self.assertEqual(fresh.reports,{});self.assertEqual(fresh.radar,{})

    def test_cancellation_removes_report_and_does_not_create_fake_text(self):
        self.store.ingest(self.product('NOTAM'),self.now,'station')
        self.store.ingest(dict(type='CANCEL_NOTAM',unique_name='KLVK',expiration_time=iso(self.now+100)),self.now,'station')
        self.assertEqual(self.store.reports,{})

    def test_no_uplink_is_not_inferred_from_aircraft_packets(self):
        self.store.connected=True;self.store.save()
        service=WeatherService(self.root);service.process=Mock();service.process.poll.return_value=None
        service.started_at=self.store.started_at;service.enabled=service.receiver_running=True
        with patch('adsb_weather.ENGINE',self.root):
            data=service.snapshot(self.now+1)
        self.assertEqual(data['status'],'LISTENING');self.assertEqual(data['uplinks'],0)
        self.assertEqual(data['radar'],[]);self.assertIsNone(data['last_uplink_at'])

    def test_station_age_and_offline_are_honest(self):
        self.store.station(dict(station='37~-122',latitude=37,longitude=-122,position_valid=0),self.now,-21)
        self.store.connected=True;self.store.save()
        service=WeatherService(self.root);service.process=Mock();service.process.poll.return_value=None
        service.started_at=self.store.started_at;service.enabled=service.receiver_running=True
        with patch('adsb_weather.ENGINE',self.root):
            self.assertEqual(service.snapshot(self.now+1)['status'],'RECEIVING')
            late=service.snapshot(self.now+60)
        self.assertFalse(late['stations'][0]['live']);self.assertEqual(late['status'],'CONNECTING')

    def test_native_weather_and_report_back_stay_one_level(self):
        from adsb_workspace import ADSBWorkspace
        ui=Mock();ui.fit_station_text.side_effect=lambda cache,text,*_:text
        ui.logical_to_native.side_effect=lambda x,y:(x,y)
        ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        manager=Mock();manager.weather.snapshot.return_value=dict(now=self.now,status='LISTENING',uplinks=0,last_uplink_at=None,reports=[],radar=[],stations=[])
        w=ADSBWorkspace(ui,manager);w.open=True;w.navigate('weather');w.draw(Mock())
        labels=[str(c.args[3]) for c in ui.draw_text.call_args_list]
        self.assertIn('Waiting for received weather',labels)
        for b,a in w.actions:self.assertGreaterEqual(b[3]-b[1],56)
        w.weather_view.report=self.product();w.go_back();self.assertTrue(w.weather_open);self.assertIsNone(w.weather_view.report)
        w.go_back();self.assertEqual(w.current_screen(),'map');self.assertTrue(w.open)


@unittest.skipUnless(ENGINE.is_dir(),'Install FIS-B engine or set ITUNER_FISB_ENGINE')
class DecoderIntegrationTests(unittest.TestCase):
    def uplink(self,product,payload,now):
        # Construct a binary FIS-B APDU and a 432-byte ground uplink. These are
        # test inputs, never connected to the production service or its logs.
        bits='000'+format(product,'011b')+'0'+'00'+format(now.hour,'05b')+format(now.minute,'06b')
        apdu=int(bits.ljust(32,'0'),2).to_bytes(4,'big')+payload
        ba=bytearray(432);ba[6]=0xa0;ba[7]=0xc0
        ba[8]=len(apdu)>>1;ba[9]=(len(apdu)&1)<<7;ba[10:10+len(apdu)]=apdu
        return '+'+ba.hex()+';rssi=-20;t='+str(now.timestamp())+';'

    def test_binary_dlac_metar_and_run_length_radar_decode(self):
        from adsb_weather_worker import FISBDecoder
        decoder=FISBDecoder(ENGINE)
        from fisb.level0.utilities import textToDlac
        now=dt.datetime(2026,10,24,20,40,tzinfo=dt.timezone.utc)
        text='METAR KLVK 242040Z 27008KT 10SM CLR 22/10 A3001'
        station,products=decoder.decode(self.uplink(413,bytes.fromhex(textToDlac(text)),now))
        self.assertEqual(products[0]['type'],'METAR');self.assertEqual(products[0]['contents'],text)
        self.assertEqual(products[0]['observation_time'],'2026-10-24T20:40:00Z')
        # A 128-bin regional block encoded as four 32-bin runs, including level 7.
        block=565*450+297
        payload=bytes([0x80|(block>>16),(block>>8)&255,block&255,0xf8,0xf9,0xfe,0xff])
        _,products=decoder.decode(self.uplink(63,payload,now))
        radar=radar_block(products[0]);self.assertEqual(radar['bins'],[0]*32+[1]*32+[6]*32+[7]*32)
        self.assertEqual(radar['block'],565297);self.assertEqual(decoder.errors,[])

    def test_malformed_message_is_rejected(self):
        from adsb_weather_worker import FISBDecoder
        with self.assertRaises(Exception):FISBDecoder(ENGINE).decode('+0000;t=1792874400;')

    def test_worker_consumes_private_stream_and_publishes_real_decoded_products(self):
        # Actual subprocess/socket path, isolated from SDRs and production data.
        from adsb_weather_worker import FISBDecoder
        FISBDecoder(ENGINE)
        from fisb.level0.utilities import textToDlac
        now=dt.datetime.now(dt.timezone.utc)
        text=now.strftime('METAR KLVK %d%H%MZ 27008KT 10SM CLR 22/10 A3001')
        line=self.uplink(413,bytes.fromhex(textToDlac(text)),now)
        server=socket.socket();server.bind(('127.0.0.1',0));server.listen();server.settimeout(8)
        done=threading.Event()
        def feed():
            try:
                with server.accept()[0] as stream:
                    stream.sendall((line+'\n').encode());done.wait(8)
            except OSError:pass
        thread=threading.Thread(target=feed,daemon=True);thread.start()
        with tempfile.TemporaryDirectory() as root:
            service=WeatherService(root)
            try:
                service.step(server.getsockname()[1],True)
                deadline=time.monotonic()+8;data={}
                while time.monotonic()<deadline:
                    service.next_read=0;data=service.snapshot()
                    if data.get('reports'):break
                    time.sleep(.1)
                self.assertEqual(data['status'],'RECEIVING')
                self.assertEqual(data['reports'][0]['text'],text)
                self.assertEqual(data['uplinks'],1);self.assertEqual(data['errors'],0)
            finally:
                service.stop();done.set();server.close();thread.join(timeout=1)


if __name__=='__main__':unittest.main()
