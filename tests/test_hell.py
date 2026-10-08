"""Independent modulation fixtures, persistence, controls and upload guards."""
import json
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from hell_decoder import HellDecoder
from hell_modes import MODES, PRESETS, settings, fit_modes
from hell_monitor import HellManager, HellSession, StripAssembler
from hell_reporting import HellReporter, packet, RX_TEMPLATE, TX_TEMPLATE
from digital_web import ReceiverController, ControlError


# Independent transmitter: physical raster rates and shifts from fldigi's TX
# send_symbol/restart. Does not import receiver coefficients or mode constants.
TX = {'HELL':(245,0,1500),'SLOWHELL':(30.625,0,1500),'HELLX5':(1225,0,2000),
      'HELLX9':(2205,0,2400),'FSKH245':(245,122.5,1500),'FSKH105':(245,55,1500),'HELL80':(490,300,1500)}


def modulate(mode, seconds=3):
    rate,shift,tone=TX[mode]
    rng=np.random.default_rng(175)
    # Each original 7-row dot occupies two vertical transmit pixels.
    bits=np.repeat(rng.integers(0,2,int(seconds*rate/2)+100),2)
    t=np.arange(round(seconds*12000))/12000
    b=bits[np.floor(t*rate).astype(int)]
    phase=2*np.pi*np.cumsum(tone+(1-2*b)*shift)/12000
    audio=np.sin(phase)*(.6 if shift else .6*b)
    audio+=rng.normal(0,.003,len(t))
    return (np.clip(audio,-1,1)*32767).astype('<i2').tobytes(),bits,tone,rate


class DSPTests(unittest.TestCase):
    def test_all_seven_modes_recover_independently_modulated_pixels(self):
        for mode in TX:
            with self.subTest(mode=mode):
                pcm,bits,tone,rate=modulate(mode,8 if mode=='SLOWHELL' else 3)
                d=HellDecoder(mode,tone)
                result=d.feed(pcm)
                # Undo raster packing to inspect the recovered temporal pixels.
                recovered=result[:28,:][::-1,:].T.reshape(-1)<128
                expected=np.repeat(bits,2).astype(bool)
                # FIR group delay and arbitrary start phase are expected for Hell.
                scores=[]
                for lag in range(0,200):
                    n=min(len(recovered)-lag,len(expected))
                    if n>100:scores.append(np.mean(recovered[lag:lag+n][50:]==expected[:n][50:]))
                self.assertGreater(max(scores),.90,(mode,max(scores)))

    def test_chunk_boundaries_silence_reverse_and_reset(self):
        pcm,*_=modulate('FSKH245')
        whole=HellDecoder('FSKH245').feed(pcm)
        decoder=HellDecoder('FSKH245')
        chunks=[decoder.feed(pcm[n:n+1018]) for n in range(0,len(pcm),1018)]
        np.testing.assert_array_equal(whole,np.concatenate(chunks,axis=1))
        reverse=HellDecoder('FSKH245',reverse=True).feed(pcm)
        self.assertLess(np.mean(np.abs(whole[:28].astype(float)+reverse[:28]-255)),1.01)
        decoder.reset()
        np.testing.assert_array_equal(whole,decoder.feed(pcm))
        blank=HellDecoder().feed(bytes(24000))
        self.assertTrue(np.all(blank==255))

    def test_invalid_tone_bandwidth_nan_and_modes_rejected(self):
        for payload in [dict(hell_mode='BAD'),dict(tone_hz=float('nan')),dict(freq_khz=float('inf')),
                        dict(hell_mode='HELLX9',tone_hz=1500),dict(reverse='yes')]:
            with self.assertRaises(ValueError):settings(payload,PRESETS[4])


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.manager=HellManager(None,'test',self.temp.name)
        self.options=dict(receivers=[dict(name='Local',server='http://kiwi.local',location='Romania')],
                          presets=dict(hell=list(PRESETS)))
        self.controller=ReceiverController(None,[],None,lambda:self.options,self.manager)

    def tearDown(self):
        self.manager.stop();self.temp.cleanup()

    def test_create_edit_restart_delete_preserves_images_and_state(self):
        payload=dict(server='http://kiwi.local',preset='20',start=False,hell_mode='FSKH105',tone_hz=1500)
        self.controller.apply('hell','test','add',payload)
        self.controller.apply('hell','test','add',payload)
        self.assertEqual(len(self.manager.configs),1)
        self.controller.apply('hell','test','edit',dict(payload,preset='40',freq_khz=7068))
        row=json.loads(self.manager.config_path.read_text())[0]
        self.assertTrue(row['paused']);self.assertEqual(row['freq_khz'],7068)
        self.assertEqual(row['hell_mode'],'FSKH105')
        session=HellSession(row,None,self.manager.gallery,'test')
        assembler=StripAssembler(session,self.manager.gallery)
        pcm,*_=modulate('FSKH105')
        assembler.feed(pcm)
        image=self.manager.image_snapshot()[0]
        self.assertEqual(image['kind'],'receiving');key=image['id']
        assembler.flush()
        self.assertEqual(self.manager.image_snapshot()[0]['id'],key)
        self.assertEqual(self.manager.image_snapshot()[0]['kind'],'saved')
        self.controller.apply('hell','test','delete',{})
        self.assertEqual(self.manager.configs,[])
        self.assertTrue(self.manager.gallery.image_path(key).exists())
        self.manager.stop()
        restarted=HellManager(None,'test',self.temp.name)
        try:self.assertEqual(len(restarted.image_snapshot()),1)
        finally:restarted.stop()

    def test_fm_only_receivers_are_not_accepted_by_hell(self):
        self.options['hell_receivers'] = list(self.options['receivers'])
        self.options['receivers'].append(dict(name='FM only',server='http://fm.test',location=''))
        with self.assertRaises(ControlError):
            self.controller.apply('hell','bad','add',dict(server='http://fm.test',preset='20',start=False))
        self.assertEqual(self.manager.configs,[])

    def test_native_editor_same_config_and_report_requires_confirmation(self):
        from hell_workspace import HellWorkspace
        ui=SimpleNamespace(contains=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3],
                           station_fields=lambda r:(r[0],r[1],r[2],0,8),LOCAL_KIWI_SERVER='http://kiwi.local')
        w=HellWorkspace(ui,self.manager);w.selected_server='http://kiwi.local'
        w.actions=[((0,0,10,10),('create',None))]
        with patch.object(self.manager,'start'):
            w.tap(5,5,[('Local','Romania','http://kiwi.local')])
        self.assertEqual(self.manager.configs[0]['hell_mode'],'HELL')
        self.assertFalse(w.add_open)
        with self.assertRaises(ValueError):self.manager.reporter.submit(dict(call='KN6KEZ',confirmed=False))

    def test_all_modes_share_one_session_and_keep_rf_center(self):
        config=fit_modes(dict(PRESETS[4]),list(MODES))
        self.assertEqual(config['freq_khz']*1000+config['tone_hz'],14063000)
        config.update(settings(config,config))
        key=self.manager.add('Local','http://kiwi.local',config,running=False)
        row=self.manager.configs[0]
        session=HellSession(row,None,self.manager.gallery,'test')
        bank=session.make_assembler()
        self.assertEqual(len(bank.assemblers),7)
        low,high=session.bandpass()
        self.assertGreater(low,0);self.assertLessEqual(high,5100)
        with patch.object(self.manager.gallery,'classify'):
            bank.feed(bytes(12000*2));bank.flush()
        images=self.manager.image_snapshot()
        self.assertEqual({r['mode'] for r in images},set(MODES))
        self.assertEqual({r['session_id'] for r in images},{key})
        self.assertEqual({r['rf_hz'] for r in images},{14063000})
        self.assertEqual(len({id(a.session) for a in bank.assemblers}),1)
        # A legacy singular-mode edit must override a saved multiselect.
        self.manager.update(key,'Local','http://kiwi.local',dict(PRESETS[4],hell_mode='FSKH105'))
        self.assertEqual(self.manager.configs[0]['hell_modes'],['FSKH105'])

    def test_mode_list_validation_and_native_multiselect(self):
        for invalid in ([],None,'HELL',['INVALID'],[{}],['HELL']*8):
            with self.assertRaises(ValueError):settings(dict(hell_modes=invalid),PRESETS[4])
        from hell_workspace import HellWorkspace
        ui=SimpleNamespace(contains=lambda b,x,y:True)
        w=HellWorkspace(ui,self.manager)
        w.actions=[((0,0,10,10),('hell_all',None))]
        w.tap(5,5,[])
        self.assertEqual(len(w.preset['hell_modes']),7)
        self.assertEqual(w.preset['freq_khz']*1000+w.preset['tone_hz'],14063000)


class OCRTests(unittest.TestCase):
    def test_one_letter_or_digit_is_sufficient_but_punctuation_is_not(self):
        from hell_ocr import recognize
        for token,confidence,expected in [('A',20,'A'),('7',20,'7'),('',99,''),('/',99,''),('fake',0,'')]:
            result=SimpleNamespace(returncode=0,stdout='level\tconf\ttext\n5\t'+str(confidence)+'\t'+token+'\n')
            with patch('hell_ocr.shutil.which',return_value='/usr/bin/tesseract'),patch('hell_ocr.subprocess.run',return_value=result):
                self.assertEqual(recognize(Path('test.png')),expected)

    def test_negative_previews_roll_over_without_deleting_candidates_or_legacy(self):
        from hell_ocr import HellGallery
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            gallery=HellGallery(tmp)
            try:
                for i in range(5):
                    key=f'{i:032x}';path=Path(tmp)/(key+'.working.png')
                    Image.new('L',(16,56),255).save(path)
                    gallery.publish(path,dict(id=key,session_id='rx',mode='HELL' if i<4 else 'FSKH105',kind='saved',received_at=i,capture_utc=str(i)))
                gallery.complete(f'{0:032x}','A')
                gallery.complete(f'{1:032x}','')
                gallery.complete(f'{2:032x}','')
                gallery.complete(f'{4:032x}','')
                self.assertEqual({r['id'] for r in gallery.snapshot()},{f'{i:032x}' for i in (0,2,3,4)})
                self.assertFalse(gallery.image_path(f'{1:032x}').exists())
                # OCR failure keeps its original image, and the worker continues.
                with patch('hell_ocr.recognize',side_effect=RuntimeError('missing')):
                    gallery.classify(f'{3:032x}');gallery.pending.join()
                self.assertTrue(gallery.image_path(f'{3:032x}').exists())
                self.assertEqual(next(r for r in gallery.snapshot() if r['id']==f'{3:032x}')['ocr_status'],'unchecked')
            finally:gallery.close()

    def test_real_ocr_on_single_character_and_blank(self):
        import shutil
        if not shutil.which('tesseract'):self.skipTest('Tesseract not installed')
        from hell_ocr import recognize
        from PIL import Image,ImageDraw,ImageFont
        font_path='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
        if not Path(font_path).exists():self.skipTest('Reference font not installed')
        with tempfile.TemporaryDirectory() as tmp:
            for char in ('A','7',''):
                image=Image.new('L',(300,100),255)
                ImageDraw.Draw(image).text((30,10),char,font=ImageFont.truetype(font_path,60),fill=0)
                path=Path(tmp)/'single.png';image.save(path)
                self.assertEqual(bool(recognize(path)),bool(char))
            # A single 5x7 glyph, independently modulated as Feld Hell, must
            # survive retention even if OCR mistakes its exact identity.
            pattern=np.array([[int(c) for c in row] for row in
                ['01110','10001','10001','11111','10001','10001','10001']])
            raster=np.zeros((14,70));raster[:,20:25]=np.repeat(pattern,2,axis=0)
            bits=raster[::-1].T.reshape(-1)
            t=np.arange(int(len(bits)/245*12000))/12000
            b=bits[np.minimum((t*245).astype(int),len(bits)-1)]
            pcm=(np.sin(2*np.pi*1500*t)*b*.65*32767).astype('<i2').tobytes()
            decoded=HellDecoder().feed(pcm)
            image=Image.fromarray(decoded).resize((decoded.shape[1]*4,112),Image.Resampling.NEAREST)
            image.save(path)
            self.assertTrue(recognize(path))


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.image=dict(id='a'*32,server='http://kiwi.local',rf_hz=14063000,mode='HELL',received_at=time.time())
        self.gallery=SimpleNamespace(snapshot=lambda:[self.image])
        self.reporter=HellReporter(Path(self.temp.name)/'reports.json',self.gallery,start=False)
        self.payload=dict(image='a'*32,call='YO1ABC',reporter='KN6KEZ',grid='KN34AL',confirmed=True)

    def tearDown(self):
        self.reporter.close();self.temp.cleanup()

    def test_opt_in_identity_duplicate_age_and_cancel(self):
        for changes in (dict(confirmed=False),dict(grid='bad'),dict(call='???'),dict(image='no')):
            with self.assertRaises(ValueError):self.reporter.submit(dict(self.payload,**changes))
        self.reporter.submit(self.payload)
        with self.assertRaises(ValueError):self.reporter.submit(self.payload)
        row=self.reporter.snapshot()['reports'][0];self.assertEqual(row['status'],'queued')
        self.reporter.cancel(row['id'])
        with patch('hell_reporting.socket.socket') as sock:
            self.reporter.send_pending();sock.assert_not_called()
        self.image['received_at']=time.time()-90000
        with self.assertRaises(ValueError):self.reporter.submit(dict(self.payload,call='YO2ABC'))

    def test_ipfix_lengths_fields_and_manual_information_source(self):
        self.assertEqual(len(RX_TEMPLATE),36);self.assertEqual(len(TX_TEMPLATE),44)
        self.reporter.submit(self.payload)
        data=packet(self.reporter.rows,0,123,1700000000)
        self.assertEqual(struct.unpack('!HH',data[:4]),(10,len(data)))
        offset=16;sets=[]
        while offset<len(data):
            kind,length=struct.unpack('!HH',data[offset:offset+4]);sets.append(kind)
            self.assertEqual(length%4,0);self.assertGreaterEqual(length,4);offset+=length
        self.assertEqual(offset,len(data));self.assertEqual(sets,[3,2,0x9992,0x9993])
        self.assertIn(b'\x04HELL\x03',data)
        self.assertIn(struct.pack('!I',14063000),data)

    def test_send_is_unconfirmed_and_uncertain_never_retried(self):
        self.reporter.submit(self.payload)
        sock=Mock()
        with patch('hell_reporting.socket.socket',return_value=sock):
            self.reporter.send_pending();self.reporter.send_pending()
        sock.sendto.assert_called_once()
        self.assertEqual(sock.sendto.call_args.args[1],('report.pskreporter.info',4739))
        self.assertEqual(self.reporter.rows[0]['status'],'sent (unconfirmed)')
        self.reporter.submit(dict(self.payload,call='YO2ABC'))
        sock.sendto.side_effect=OSError('network down')
        self.reporter.send_pending();self.reporter.send_pending()
        self.assertEqual(sock.sendto.call_count,2)
        self.assertEqual(self.reporter.rows[-1]['status'],'uncertain')



class HellHTTPTests(unittest.TestCase):
    def test_routes_control_persistence_and_security(self):
        import threading
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from sstv_monitor import Gallery,GalleryServer
        from digital_web import DigitalWebBridge
        with tempfile.TemporaryDirectory() as tmp:
            manager=HellManager(None,'test',Path(tmp)/'hell')
            bridge=DigitalWebBridge()
            options=dict(receivers=[dict(name='Local',location='',server='kiwi.local')],presets=dict(hell=list(PRESETS)))
            bridge.publish_options(options);bridge.publish([],[],[])
            controller=ReceiverController(None,[],None,lambda:options,manager)
            server=GalleryServer(Gallery(Path(tmp)/'sstv'),lambda:[],('127.0.0.1',0))
            server.bridge=bridge;server.hell=manager
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            stop=threading.Event()
            def owner():
                while not stop.wait(.01):
                    bridge.drain(controller.apply);bridge.publish([],[],manager.snapshot())
            owner_thread=threading.Thread(target=owner,daemon=True);owner_thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                self.assertEqual(urlopen(base+'/hell').status,200)
                self.assertEqual(json.load(urlopen(base+'/api/hell'))['decoders'],[])
                payload=dict(id='http-test',action='add',config=dict(server='kiwi.local',preset='eu30',start=False))
                for headers,code in [({'Content-Type':'application/json'},403),
                  ({'Content-Type':'application/json','X-SDR-Control':server.control_token,'Origin':'http://evil.test'},403)]:
                    with self.assertRaises(HTTPError) as e:urlopen(Request(base+'/api/hell/control',data=json.dumps(payload).encode(),headers=headers))
                    self.assertEqual(e.exception.code,code)
                headers={'Content-Type':'application/json','X-SDR-Control':server.control_token}
                result=json.load(urlopen(Request(base+'/api/hell/control',data=json.dumps(payload).encode(),headers=headers)))
                self.assertTrue(result['ok']);self.assertEqual(manager.configs[0]['hell_mode'],'FSKH105')
                self.assertTrue(manager.configs[0]['paused'])
                result=json.load(urlopen(base+'/api/hell/reporting'));self.assertEqual(result['reports'],[])
                with self.assertRaises(HTTPError) as e:
                    urlopen(Request(base+'/api/hell/reporting',data=b'{"confirmed":false}',headers=headers))
                self.assertEqual(e.exception.code,400)
            finally:
                stop.set();owner_thread.join();bridge.close();server.shutdown();server.server_close();thread.join();manager.stop()


if __name__=="__main__":unittest.main()
