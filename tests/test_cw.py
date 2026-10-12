"""Known independent Morse transmissions exercise the actual native engine."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from cw_decoder import CWDecoder
from cw_modes import PRESETS,settings
from cw_monitor import CWHistory,CWManager,CWSession,CWAssembler
from digital_web import ReceiverController,ControlError,DigitalWebBridge

alphabet=dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',['.-','-...','-.-.','-..','.','..-.','--.','....','..','.---','-.-','.-..','--','-.','---','.--.','--.-','.-.','...','-','..-','...-','.--','-..-','-.--','--..','-----','.----','..---','...--','....-','.....','-....','--...','---..','----.']))
def signal(text,wpm=20,tone=650):
 unit=round(12000*1.2/wpm);out=[np.zeros(12000)]
 for word in text.split():
  for c in word:
   for element in alphabet[c]:
    n=unit*(3 if element=='-' else 1);x=np.sin(np.arange(n)*2*np.pi*tone/12000)*.3
    ramp=min(60,n//4);x[:ramp]*=np.linspace(0,1,ramp);x[-ramp:]*=np.linspace(1,0,ramp)
    out.extend([x,np.zeros(unit)])
   out.append(np.zeros(2*unit))
  out.append(np.zeros(4*unit))
 out.append(np.zeros(5*12000));return np.concatenate(out)


def decode(audio,config=None):
    decoder=CWDecoder(config or PRESETS[3]);found={}
    for pos in range(0,len(audio),512):
        decoder.feed((np.clip(audio[pos:pos+512],-1,1)*32767).astype('<i2').tobytes())
        for track in decoder.snapshot():
            if track['text'].strip():found[track['id']]=track
    decoder.close();return list(found.values())


class EngineTests(unittest.TestCase):
    def test_auto_speed_and_pitch(self):
        for speed in (8,20,35,50):
            with self.subTest(speed=speed):
                audio=signal('VVV VVV CQ CQ DE KN6KEZ KN6KEZ TEST 123 73',speed,650)
                tracks=decode(audio)
                self.assertTrue(any('KN6KEZ' in t['text'] for t in tracks),tracks)
                best=max(tracks,key=lambda t:len(t['text']))
                self.assertLess(abs(best['wpm']-speed),3)
                self.assertLess(abs(best['tone_hz']-650),5)

    def test_two_simultaneous_signals(self):
        a=signal('VVV VVV CQ CQ DE KN6KEZ KN6KEZ TEST 123 73',20,600)
        b=signal('VVV VVV CQ CQ DE YO3ABC YO3ABC TEST 456 73',28,950)
        audio=np.zeros(max(len(a),len(b)));audio[:len(a)]+=a;audio[:len(b)]+=b*.7
        tracks=decode(audio)
        self.assertTrue(any('KN6KEZ' in t['text'] and abs(t['tone_hz']-600)<10 for t in tracks),tracks)
        self.assertTrue(any('YO3ABC' in t['text'] and abs(t['tone_hz']-950)<10 for t in tracks),tracks)
        self.assertLessEqual(len(tracks),4)

    def test_noise_and_fading(self):
        audio=signal('VVV VVV CQ CQ DE KN6KEZ KN6KEZ TEST 123 73',20,700)
        audio*=.7+.3*np.sin(np.arange(len(audio))/12000*.7)
        audio+=np.random.default_rng(902).normal(0,.02,len(audio))
        self.assertTrue(any('KN6KEZ' in t['text'] for t in decode(audio)))
        self.assertFalse(decode(np.random.default_rng(17).normal(0,.04,12000*15)))

    def test_locked_tone_rejects_other_signal(self):
        audio=signal('VVV VVV CQ CQ DE KN6KEZ KN6KEZ',20,650)
        self.assertFalse(decode(audio,dict(PRESETS[3],cw_mode='LOCK',tone_hz=950)))


class HistoryTests(unittest.TestCase):
    def test_append_survives_new_process_and_receiver_delete(self):
        with tempfile.TemporaryDirectory() as root:
            m=CWManager(None,'test',root)
            key=m.add('Receiver','http://kiwi.local',PRESETS[3],running=False)
            c=m.configs[0];track=dict(id='t1',rf_hz=7025000,wpm=20)
            m.gallery.append(c,track,'CQ DE ','2026-10-09T14:00:00Z')
            m.gallery.append(c,track,'KN6KEZ','2026-10-09T14:00:03Z')
            m.delete(key)
            other=CWManager(None,'test',root)
            self.assertEqual(other.history()[0]['text'],'CQ DE KN6KEZ')
            self.assertEqual(other.configs,[])
            self.assertIn(b'KN6KEZ',other.gallery.export())

    def test_assembler_gap_resets_track_not_history(self):
        with tempfile.TemporaryDirectory() as root:
            store=CWHistory(root);config=dict(PRESETS[3],id='test',name='Synthetic',server='http://kiwi.local')
            session=CWSession(config,None,store,'test');a=CWAssembler(session,store)
            pcm=(signal('VVV VVV CQ CQ DE KN6KEZ KN6KEZ',20,650)*32767).astype('<i2').tobytes()
            for pos in range(0,len(pcm),1024):a.feed(pcm[pos:pos+1024])
            a.flush();rows=store.rows();self.assertTrue(any('KN6KEZ' in r['text'] for r in rows))
            self.assertTrue(store.image_path('test').is_file())
            a.reset();self.assertEqual(session.tracks,[]);self.assertEqual(len(store.rows()),len(rows));a.flush()


class ControlTests(unittest.TestCase):
    def test_full_kiwi_reports_channel_limit_without_timeout(self):
        from sstv_monitor import Session
        ws=Mock();ws.recv.return_value=b'MSG too_busy=8'
        kiwi=SimpleNamespace(KiwiWebSocket=SimpleNamespace(connect=Mock(return_value=ws)),
            send_kiwi_setup=Mock(),parse_msg_params=Mock(return_value={'too_busy':'8'}))
        session=Session(dict(PRESETS[3],id='busy',server='http://kiwi.local'),kiwi,None,'test')
        session.make_assembler=Mock(return_value=Mock())
        with patch('sstv_monitor.select.select',return_value=([ws.sock],[],[])):
            session.run()
        self.assertEqual(session.status,'NO AUDIO')
        self.assertIn('channels are occupied',session.detail)
        self.assertEqual(ws.recv.call_count,1)

    def test_settings_reject_invalid_input_and_compute_rf(self):
        self.assertAlmostEqual(settings({'rf_khz':7025},PRESETS[3])['freq_khz'],7024.3)
        for payload in ({'wpm':2},{'wpm':56},{'rf_khz':float('nan')},{'tone_hz':199},{'max_tracks':7},{'cw_mode':'TX'}):
            with self.assertRaises(ValueError):settings(payload,PRESETS[3])

    def test_web_add_edit_stop_delete_share_local_manager(self):
        with tempfile.TemporaryDirectory() as root:
            m=CWManager(None,'test',root)
            options={'receivers':[dict(name='Test',server='http://kiwi.local')],'presets':{'cw':list(PRESETS)}}
            c=ReceiverController(None,[],None,lambda:options,cw=m)
            payload=dict(server='http://kiwi.local',preset='40',start=False)
            c.apply('cw','receiver1','add',payload);self.assertEqual(len(m.configs),1)
            c.apply('cw','receiver1','add',payload);self.assertEqual(len(m.configs),1)
            c.apply('cw','receiver1','edit',dict(payload,rf_khz=7030,wpm=18))
            self.assertAlmostEqual(m.configs[0]['freq_khz'],7029.3)
            c.apply('cw','receiver1','stop',{});self.assertTrue(m.configs[0]['paused'])
            c.apply('cw','receiver1','delete',{});self.assertEqual(m.configs,[])
            with self.assertRaises(ControlError):c.apply('cw','absent','stop',{})

if __name__=='__main__':unittest.main()
