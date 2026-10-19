"""Shared settings, GPS fix validation, live propagation and HTTP boundaries."""
from datetime import datetime,timezone
import json
from pathlib import Path
import tempfile
import threading
import socketserver
import time
import unittest
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from station_profile import StationProfile,validate,grid,distance_m
from adsb_monitor import ADSBManager
from vhf_monitor import VHFHub
from station_workspace import StationWorkspace


def tpv(now=None,**changes):
    now=time.time() if now is None else now
    data=dict(class_='TPV',device='/dev/ttyACM0',mode=3,lat=44.43,lon=26.1,altHAE=120.,altMSL=83.,epx=3.,epy=4.,time=datetime.fromtimestamp(now,timezone.utc).isoformat())
    data['class']=data.pop('class_');data.update(changes);return data


class StationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=StationProfile(self.root/'radio-user.json',start=False)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def test_optional_identity_coordinate_validation_and_grid(self):
        self.assertEqual(self.s.snapshot()['config']['callsign'],'')
        self.s.update(dict(callsign='yo3abc/p',latitude=44.43,longitude=26.1,elevation_m=80,antenna_height_m=15))
        data=self.s.snapshot();self.assertEqual(data['config']['callsign'],'YO3ABC/P');self.assertEqual(data['position']['altitude_msl_m'],95)
        self.assertEqual(data['grid'],'KN34BK')
        for bad in ({'latitude':float('nan')},{'latitude':91},{'callsign':'<script>'},{'timezone':'no/timezone'},{'local_kiwi_url':'http://user:password@host'},{'antenna_height_m':-1},{'gps_auto':1}):
            with self.assertRaises(ValueError):self.s.update(bad)
    def test_bad_save_is_atomic_and_no_fake_origin(self):
        before=self.s.path.read_text()
        with self.assertRaises(ValueError):self.s.update(dict(latitude=44.4))
        self.assertEqual(self.s.path.read_text(),before);self.assertIsNone(self.s.snapshot()['position'])
    def test_migration_prefers_explicit_adsb_site_over_stale_vhf(self):
        self.s.close();(self.root/'adsb').mkdir();(self.root/'vhf').mkdir()
        (self.root/'adsb/settings.json').write_text(json.dumps(dict(position=dict(lat=44.4,lon=26.1))))
        (self.root/'vhf/station.json').write_text(json.dumps(dict(lat=45,lon=25)))
        self.s.path.unlink();self.s=StationProfile(self.s.path,start=False)
        self.assertEqual(self.s.snapshot()['position']['lat'],44.4)
    def test_fresh_gps_moves_all_subscribers_and_retains_last_known_on_disconnect(self):
        self.s.update(dict(latitude=44.4,longitude=26.1));seen=[];self.s.subscribe(seen.append)
        self.s.gps['connected']=True;now=time.time()
        self.assertTrue(self.s.message(tpv(now),now))
        self.assertEqual(seen[-1]['position']['source'],'gps');self.assertEqual(seen[-1]['position']['ellipsoid_height_m'],120)
        self.assertEqual(self.s.snapshot()['position']['altitude_msl_m'],83)
        self.s.gps['connected']=False
        data=self.s.snapshot();self.assertTrue(data['position']['stale']);self.assertEqual(data['position']['lat'],44.43)
    def test_invalid_gps_does_not_override_manual_position(self):
        self.s.update(dict(latitude=44.4,longitude=26.1));now=time.time()
        for changes in (dict(mode=1),dict(lat=float('nan')),dict(lon=190),dict(epx=101),dict(time='invalid'),dict(time=datetime.fromtimestamp(now-30,timezone.utc).isoformat())):
            self.assertFalse(self.s.message(tpv(now,**changes),now))
            self.assertEqual(self.s.snapshot()['position']['source'],'manual')
    def test_2d_fix_keeps_altitude_unknown_and_manual_switch_is_immediate(self):
        self.s.update(dict(latitude=44.4,longitude=26.1,elevation_m=80,antenna_height_m=10,ellipsoid_height_m=130))
        self.s.message(tpv(mode=2));p=self.s.snapshot()['position'];self.assertIsNone(p['ellipsoid_height_m']);self.assertIsNone(p['altitude_msl_m'])
        self.s.update(dict(gps_auto=False));self.assertEqual(self.s.snapshot()['position']['lat'],44.4)
        self.assertEqual(self.s.snapshot()['position']['altitude_msl_m'],90)
    def test_gps_small_steps_publish_cumulative_motion(self):
        seen=[];self.s.subscribe(seen.append);now=time.time()
        for i in range(12):self.s.message(tpv(now+i,lat=44.43+i*.00001),now+i)
        self.assertGreater(len(seen),2)
    def test_persistence_and_remote_receiver_identity(self):
        self.s.update(dict(local_kiwi_url='http://kiwisdr.local:8073',operator_name='Operator'))
        self.s.message(tpv());self.s.close();self.s=StationProfile(self.s.path,start=False)
        self.assertEqual(self.s.snapshot()['position']['source'],'gps');self.assertTrue(self.s.snapshot()['position']['stale'])
        self.assertTrue(self.s.local_receiver('http://kiwisdr.local:8073/'))
        self.assertFalse(self.s.local_receiver('http://remote.example:8073'))
        self.assertFalse(self.s.local_receiver('http://kiwisdr.local:8073/another-receiver'))
    def test_gps_inventory_and_disabled_mode(self):
        self.s.message({'class':'DEVICES','devices':[{'path':'/dev/ttyACM0','driver':'u-blox'}]})
        self.s.message({'class':'SKY','satellites':[{'used':True},{'used':False}]})
        data=self.s.snapshot();self.assertEqual(data['gps']['used'],1);self.assertEqual(data['gps']['satellites'],2)
        self.s.message({'class':'DEVICE','path':'/dev/ttyACM1','driver':'NMEA0183','activated':1})
        self.assertEqual(len(self.s.snapshot()['gps']['devices']),2)
        self.s.message({'class':'DEVICE','path':'/dev/ttyACM1','activated':0})
        self.assertEqual(len(self.s.snapshot()['gps']['devices']),1)
        self.s.update(dict(gps_enabled=False));self.assertEqual(self.s.snapshot()['gps']['status'],'GPS disabled')
    def test_local_gpsd_watch_protocol_and_antenna_offset(self):
        received=[]
        class GPS(socketserver.BaseRequestHandler):
            def handle(server):
                received.append(server.request.recv(1024))
                server.request.sendall((json.dumps({'class':'DEVICES','devices':[{'path':'/dev/ttyACM0'}]})+'\n'+json.dumps(tpv())+'\n').encode())
        with socketserver.TCPServer(('127.0.0.1',0),GPS) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            self.s.close();self.s=StationProfile(self.s.path,gps_address=server.server_address)
            try:
                self.s.update(dict(gps_height_offset_m=12))
                for _ in range(50):
                    if self.s.snapshot()['position']:break
                    time.sleep(.02)
                p=self.s.snapshot()['position'];self.assertIsNotNone(p)
                self.assertEqual(p['ellipsoid_height_m'],132);self.assertEqual(p['altitude_msl_m'],95)
                self.assertIn(b'WATCH',received[0]);self.assertTrue(p['stale'])
            finally:self.s.close();server.shutdown()

    def test_native_editor_preserves_unknown_heights(self):
        ui=Mock();ui.contains.side_effect=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3]
        w=StationWorkspace(ui,self.s);w.show();w.field='elevation_m';w.value='';w.key('DONE')
        self.assertIsNone(w.draft['elevation_m']);w.field='callsign';w.value='';w.key('y');w.key('o');w.key('3');w.key('a');w.key('b');w.key('c');w.key('DONE')
        self.s.update(w.draft);self.assertEqual(self.s.snapshot()['config']['callsign'],'YO3ABC')
        w.show();self.s.update(dict(site_label='New label from web'));w.draw(Mock())
        self.assertEqual(w.draft['site_label'],'New label from web')
    def test_live_broadcast_updates_adsb_vhf_and_coverage_without_rf_restart_for_small_gps_moves(self):
        a=ADSBManager(root=self.root/'adsb',port=-1,scanner=lambda:[],station=self.s)
        h=VHFHub(root=self.root/'vhf',port=-1,scanner=lambda:[],station=self.s)
        try:
            self.s.update(dict(latitude=44.4,longitude=26.1,ellipsoid_height_m=130))
            self.assertEqual(a.position,dict(lat=44.4,lon=26.1));self.assertEqual(h.position['lat'],44.4);self.assertEqual(a.coverage.height,130)
            a.active_position=dict(a.position)
            self.s.message(tpv(lat=44.41,lon=26.1))
            self.assertEqual(h.position['lat'],44.41);self.assertEqual(a.position['lat'],44.41);self.assertFalse(a._location_restart_needed())
            self.s.message(tpv(lat=45.4,lon=26.1));self.assertTrue(a._location_restart_needed())
            a.control('location',position=dict(lat=44.5,lon=26.2));self.assertEqual(h.position['lat'],44.5)
            h.control('meteor','location',position=dict(lat=44.6,lon=26.3));self.assertEqual(a.position['lat'],44.6)
            self.assertFalse(a.enabled);self.assertFalse(any(s.enabled for s in h.sessions.values()))
        finally:a.close();h.close()
    def test_both_http_interfaces_share_settings_and_enforce_tokens_origin_and_validation(self):
        a=ADSBManager(root=self.root/'adsb',port=0,scanner=lambda:[],station=self.s)
        h=VHFHub(root=self.root/'vhf',port=0,scanner=lambda:[],station=self.s)
        try:
            for manager in (a,h):
                base=f'http://127.0.0.1:{manager.port}';data=json.load(urlopen(base+'/api/station'))
                self.assertEqual(urlopen(base+'/settings').status,200)
                for headers,code in (({},403),({'X-Station-Token':data['control_token'],'Origin':'http://other.example'},403),({'X-Station-Token':data['control_token']},200)):
                    req=Request(base+'/api/station',data=b'{"callsign":"YO3ABC"}',headers=headers)
                    if code!=200:
                        with self.assertRaises(HTTPError) as result:urlopen(req)
                        self.assertEqual(result.exception.code,code)
                    else:self.assertEqual(json.load(urlopen(req))['config']['callsign'],'YO3ABC')
                req=Request(base+'/api/station',data=b'{"latitude":999}',headers={'X-Station-Token':data['control_token']})
                with self.assertRaises(HTTPError) as result:urlopen(req)
                self.assertEqual(result.exception.code,400)
            self.assertEqual(self.s.snapshot()['config']['callsign'],'YO3ABC')
        finally:a.close();h.close()

if __name__=='__main__':unittest.main()
