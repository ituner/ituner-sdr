"""Independent QRSS transmitter fixtures, capture continuity and controls."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from qrss_modes import PRESETS,settings
from qrss_decoder import QRSSDecoder,MorseTiming
from qrss_monitor import QRSSManager,QRSSSession,QRSSAssembler
from digital_web import ReceiverController,ControlError


def audio(dot=3,mode='FSKCW',reverse=False,letter='SOS',chunk=12000):
    # Explicit independent ITU Morse timing. No receiver code table is used.
    codes={'S':'...','O':'---','A':'.-','7':'--...'}
    units=[(False,5)]
    for char in letter:
        for symbol in codes[char]:units.extend([(True,1 if symbol=='.' else 3),(False,1)])
        units[-1]=(False,3)
    units[-1]=(False,7)
    rng=np.random.default_rng(43);sample=0
    for mark,count in units:
        n=round(count*dot*12000)
        for offset in range(0,n,chunk):
            t=(np.arange(min(chunk,n-offset))+sample)/12000;sample+=len(t)
            frequency=1500-(0 if mark!=reverse else 5)
            signal=(.25 if mark or mode=='FSKCW' else 0)*np.sin(2*np.pi*frequency*t)
            signal+=rng.normal(0,.005,len(t))
            yield (signal*32767).astype('<i2').tobytes()


class DSPTests(unittest.TestCase):
    def test_cw_fsk_all_dot_lengths_and_reverse(self):
        for dot in (3,6,10,30,60):
            for mode,reverse in (('CW',False),('FSKCW',False),('FSKCW',True)):
                with self.subTest(dot=dot,mode=mode,reverse=reverse):
                    d=QRSSDecoder(dict(PRESETS[2],dot_seconds=dot,qrss_mode=mode,reverse=reverse))
                    # A exercises both mark lengths and the within-letter gap.
                    for pcm in audio(dot,mode,reverse,letter='A'):d.feed(pcm)
                    self.assertEqual(''.join(c for t,c in d.morse.events).strip(),'A')

    def test_sos_chunk_invariance_and_visual_only(self):
        pcm=b''.join(audio());config=dict(PRESETS[2],dot_seconds=3,qrss_mode='FSKCW')
        whole=QRSSDecoder(config);frames=whole.feed(pcm)
        split=QRSSDecoder(config);parts=[]
        for i in range(0,len(pcm),10018):parts+=split.feed(pcm[i:i+10018])
        self.assertEqual(list(whole.morse.events),list(split.morse.events))
        self.assertEqual(''.join(c for t,c in whole.morse.events).strip(),'SOS')
        np.testing.assert_allclose(np.stack([f[1] for f in frames]),np.stack([f[1] for f in parts]))
        visual=QRSSDecoder(dict(config,qrss_mode='VISUAL'));self.assertTrue(visual.feed(pcm));self.assertFalse(visual.morse.events)
        split.reset();self.assertFalse(split.morse.events);self.assertEqual(split.samples,0)

    def test_silence_noise_constant_carrier_and_gap_do_not_invent_letters(self):
        for noise,carrier in ((0,0),(.01,0),(0,.3)):
            d=QRSSDecoder(dict(PRESETS[2],dot_seconds=3,qrss_mode='CW'))
            rng=np.random.default_rng(5)
            for second in range(60):
                t=np.arange(12000)/12000
                pcm=(32767*(rng.normal(0,noise,12000)+carrier*np.sin(2*np.pi*1500*t))).astype('<i2').tobytes()
                d.feed(pcm)
            self.assertFalse(d.morse.events,(noise,carrier,d.morse.events))
        m=MorseTiming(3)
        for mark,t in ((False,0),(True,5),(False,8),(None,9),(False,20),(False,30)):m.feed(mark,t)
        self.assertFalse(m.events)

    def test_bad_settings_rejected(self):
        for payload in [dict(freq_khz=float('nan')),dict(dot_seconds=0),dict(tone_hz=40),dict(minutes=0),dict(qrss_mode='DFCW'),dict(reverse='true'),dict(shift_hz=100),dict(span_hz=10000)]:
            with self.assertRaises(ValueError):settings(payload,PRESETS[2])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.manager=QRSSManager(None,'test',self.temp.name)
        self.options=dict(receivers=[dict(name='Local',server='http://kiwi.local',location='')],presets=dict(qrss=list(PRESETS)))
        self.controller=ReceiverController(None,[],None,lambda:self.options,qrss=self.manager)
    def tearDown(self):self.manager.stop();self.temp.cleanup()

    def test_crud_capture_text_persistence_and_no_deletion_on_stop(self):
        payload=dict(server='http://kiwi.local',preset='30',start=False,dot_seconds=3,qrss_mode='FSKCW')
        self.controller.apply('qrss','test','add',payload);self.controller.apply('qrss','test','add',payload)
        self.assertEqual(len(self.manager.configs),1)
        c=self.manager.configs[0];a=QRSSAssembler(QRSSSession(c,None,self.manager.gallery,'test'),self.manager.gallery)
        for pcm in audio():a.feed(pcm)
        a.flush();image=self.manager.image_snapshot()[0]
        self.assertEqual(image['tentative_text'],'SOS');self.assertEqual(image['kind'],'saved')
        self.controller.apply('qrss','test','stop',{})
        self.controller.apply('qrss','test','edit',dict(payload,preset='40',qrss_mode='CW'))
        restored=QRSSManager(None,'test',self.temp.name)
        try:
            self.assertEqual(restored.configs[0]['band'],'40 m');self.assertTrue(restored.configs[0]['paused'])
            self.assertEqual(restored.image_snapshot()[0]['tentative_text'],'SOS')
        finally:restored.stop()
        self.controller.apply('qrss','test','delete',{})
        self.assertTrue(self.manager.gallery.image_path(image['id']).exists())

    def test_rollover_keeps_morse_timing_audio_gap_resets_it(self):
        c=dict(PRESETS[2],id='test',name='Local',server='http://kiwi.local',dot_seconds=3,qrss_mode='FSKCW')
        session=QRSSSession(c,None,self.manager.gallery,'test');a=QRSSAssembler(session,self.manager.gallery)
        # Test a 30-second rollover, with a letter spanning the boundary.
        session.config['minutes']=.5
        for pcm in audio(letter='A'):a.feed(pcm)
        a.flush()
        self.assertGreaterEqual(len(self.manager.image_snapshot()),2)
        self.assertIn('A',''.join(r['tentative_text'] for r in self.manager.image_snapshot()))
        a.reset();self.assertFalse(a.decoder.morse.events)

    def test_new_capture_grows_on_fixed_time_axis(self):
        from PIL import Image
        import time
        c=dict(PRESETS[2],id='scale',name='Local',server='http://kiwi.local',
               minutes=10,qrss_mode='VISUAL')
        a=QRSSAssembler(QRSSSession(c,None,self.manager.gallery,'test'),self.manager.gallery)
        a.key='a'*32;a.started=time.time();a.start_sample=0
        column=np.zeros(a.rows,dtype=np.float32)
        column[a.rows//3:2*a.rows//3]=35
        a.columns=[column.copy() for _ in range(101)]
        for duration,expected_width in ((0,1),(60,160),(180,480),(600,1600)):
            with self.subTest(duration=duration):
                a.times=list(np.linspace(0,duration,101));a.publish('receiving')
                row=self.manager.image_snapshot()[0]
                self.assertEqual(row['window_seconds'],600)
                with Image.open(self.manager.gallery.image_path(a.key)) as im:
                    self.assertEqual(im.size,(1700,390))
                    # Bright keyed data occupies only elapsed time; future is blank.
                    self.assertNotEqual(im.getpixel((90+expected_width-1,150)),(7,18,25))
                    if duration<600:
                        self.assertEqual(im.getpixel((90+expected_width+2,150)),(7,18,25))
        # Stopping early saves the same time scale, rather than stretching it.
        a.times=list(np.linspace(0,60,101));a.flush()
        row=self.manager.image_snapshot()[0]
        self.assertEqual(row['kind'],'saved')
        with Image.open(self.manager.gallery.image_path(row['id'])) as im:
            self.assertEqual(im.getpixel((900,150)),(7,18,25))

    def test_local_editor_updates_same_manager(self):
        from qrss_workspace import QRSSWorkspace
        ui=SimpleNamespace(contains=lambda box,x,y:True,station_fields=lambda r:(*r,0,8))
        w=QRSSWorkspace(ui,self.manager);w.selected_server='http://kiwi.local'
        w.actions=[((0,0,1,1),('create',None))]
        with unittest.mock.patch.object(self.manager,'start'):
            w.tap(0,0,[('Local','','http://kiwi.local')])
        self.assertEqual(self.manager.configs[0]['qrss_mode'],'AUTO')
        self.assertFalse(w.add_open)

    def test_http_gallery_controls_and_path_guards(self):
        import threading,urllib.request,urllib.error
        from sstv_monitor import GalleryServer,Gallery
        from digital_web import DigitalWebBridge
        bridge=DigitalWebBridge();bridge.publish([],[],[],self.manager.snapshot());bridge.publish_options(self.options)
        server=GalleryServer(Gallery(Path(self.temp.name)/'sstv'),lambda:[],('127.0.0.1',0));server.qrss=self.manager;server.bridge=bridge
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        root='http://127.0.0.1:'+str(server.server_port)
        try:
            data=json.load(urllib.request.urlopen(root+'/api/qrss'));self.assertEqual(data['images'],[])
            self.assertIn(b'Tentative Morse text',urllib.request.urlopen(root+'/qrss').read())
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(root+'/qrss-images/bad.png')
            request=urllib.request.Request(root+'/api/qrss/control',data=b'{}',headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,403)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
