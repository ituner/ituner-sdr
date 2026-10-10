"""Signal resolution, paired-W/F geometry, fallback, and local listening."""
import base64
from pathlib import Path
import struct
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from cw_waterfall import LiveWaterfall,KiwiWaterfall,kiwi_row,WIDTH,HEIGHT
from cw_listen import SlotFilter,CWListener
from digital_web import DigitalWebBridge,ControlError,ReceiverController


def tone(hz,seconds=1):
    return (.25*32767*np.sin(np.arange(round(12000*seconds))*2*np.pi*hz/12000)).astype('<i2').tobytes()


class LiveTests(unittest.TestCase):
    def test_audio_resolution_and_packet_continuity(self):
        pcm=tone(703)+tone(2503)
        a=LiveWaterfall();b=LiveWaterfall();a.feed(pcm)
        for i in range(0,len(pcm),1024):b.feed(pcm[i:i+1024])
        self.assertEqual(a.read()['rows'],b.read()['rows'])
        first=np.frombuffer(a.read()['rows'][0],dtype=np.uint8)
        self.assertAlmostEqual(200+first.argmax()*3000/(WIDTH-1),703,delta=3)
        # The visible peak occupies <15 Hz, unlike the old 11.7 Hz FFT bins.
        self.assertLess(np.count_nonzero(first>first.max()-20)*3000/WIDTH,15)

    def test_fallback_resumes_and_source_change_clears_old_rows(self):
        clock=[10.];w=LiveWaterfall(clock=lambda:clock[0]);w.feed(tone(700))
        initial=w.read();self.assertEqual(initial['source'],'audio')
        w.receive(np.full(WIDTH,100,dtype=np.uint8));w.feed(tone(700,.1))
        kiwi=w.read(initial['epoch'],initial['seq']);self.assertTrue(kiwi['reset'])
        self.assertEqual(kiwi['source'],'kiwi');self.assertEqual(set(kiwi['rows'][0]),{100})
        clock[0]+=3.1;w.feed(tone(700,.1));fallback=w.read(kiwi['epoch'],kiwi['seq'])
        self.assertEqual(fallback['source'],'audio');self.assertTrue(fallback['reset'])
        w.receive(np.full(WIDTH,200,dtype=np.uint8));w.feed(tone(700,.1));self.assertEqual(w.source,'kiwi')
        w.unavailable('No hardware waterfall');w.feed(tone(700,.1));self.assertEqual(w.source,'audio')

    def test_bounded_incremental_transport_and_restart(self):
        w=LiveWaterfall();w.feed(tone(700,20));one=w.read(encoded=True)
        self.assertEqual(len(base64.b64decode(one['rows'])),WIDTH*HEIGHT)
        self.assertEqual(w.read(one['epoch'],one['seq'])['rows'],[])
        w.feed(tone(700,.1));two=w.read(one['epoch'],one['seq']);self.assertEqual(len(two['rows']),2)
        w.reset();self.assertTrue(w.read(one['epoch'],two['seq'])['reset']);self.assertEqual(w.read()['rows'],[])

    def test_actual_kiwi_header_crop_not_assumed_center(self):
        dial=7023300;left=7023125;start=round(left*1024*2**14/30000000)
        left=start*30000000/(1024*2**14);step=30000000/(8192*1024)
        values=np.full(1024,100,dtype=np.uint8);index=480;values[index]=145
        packet=b'W/F\x00'+struct.pack('<III',start,13,5)+values.tobytes()
        row=kiwi_row(packet,dial);self.assertIsNotNone(row)
        measured=dial+200+row.argmax()*3000/(WIDTH-1)
        self.assertAlmostEqual(measured,left+index*step,delta=4)
        self.assertIsNone(kiwi_row(packet,dial+5000))
        self.assertIsNone(kiwi_row(b'W/F\x00'+struct.pack('<III',start,12,5)+values.tobytes(),dial))
        self.assertIsNone(kiwi_row(b'W/F\x00'+struct.pack('<III',start,13|65536,5)+values.tobytes(),dial))

    def test_bare_ready_flag_not_required_and_idle_pair_is_kept_open(self):
        # The shared MSG parser intentionally omits bare flags such as wf_setup.
        worker=object.__new__(KiwiWaterfall);worker.timestamp=123;worker.ws=None
        stop=Mock();worker.stop_event=stop
        calls=[0]
        def stopped():
            calls[0]+=1
            return calls[0]>30
        stop.is_set.side_effect=stopped;stop.wait.return_value=True
        ws=Mock();ws.recv.return_value=b'MSG badp=0'
        kiwi=SimpleNamespace(KiwiWebSocket=Mock(),send_kiwi_setup=Mock(),send_wf_setup=Mock(),parse_msg_params=lambda message:{'badp':'0'})
        kiwi.KiwiWebSocket.connect.return_value=ws
        worker.session=SimpleNamespace(kiwi=kiwi,config={'server':'http://kiwi.local','freq_khz':7023.3},user='test',waterfall=LiveWaterfall())
        clock=[0.]
        def now():clock[0]+=.5;return clock[0]
        ready=[True]
        def readable(*args):
            if ready.pop() if ready else False:return [ws.sock],[],[]
            return [],[],[]
        with patch('cw_waterfall.time.monotonic',side_effect=now),patch('cw_waterfall.select.select',side_effect=readable):worker.run()
        kiwi.KiwiWebSocket.connect.assert_called_once_with('http://kiwi.local','W/F',timeout=5,session_timestamp=123)
        kiwi.send_wf_setup.assert_called_once()
        self.assertGreater(calls[0],30) # no early timeout/disconnect after authentication
        self.assertIn('using audio',worker.session.waterfall.reason)

    def test_slot_filter_rejects_adjacent_station_and_is_continuous(self):
        pcm=(np.frombuffer(tone(700,2),dtype='<i2')+np.frombuffer(tone(1700,2),dtype='<i2')).astype('<i2').tobytes()
        a=SlotFilter(700).feed(pcm);f=SlotFilter(700)
        b=b''.join(f.feed(pcm[i:i+1024]) for i in range(0,len(pcm),1024));self.assertEqual(a,b)
        spectrum=np.abs(np.fft.rfft(np.frombuffer(a,dtype='<i2')[12000:]))
        self.assertGreater(spectrum[700],spectrum[1700]*100)

    def test_listen_is_cw_only_and_uses_validated_receiver(self):
        bridge=DigitalWebBridge()
        with self.assertRaises(ControlError):bridge.request('sstv','test','listen',config={'track_id':'x'})
        with self.assertRaises(ControlError):bridge.request('cw','test','listen',config=None)
        manager=SimpleNamespace(configs=[dict(id='rx')],listen=Mock())
        ctrl=ReceiverController(None,[],None,lambda:{},cw=manager)
        ctrl.apply('cw','rx','listen',{'track_id':'one'});manager.listen.assert_called_once_with('rx','one')
        with self.assertRaises(ControlError):ctrl.apply('cw','rx','listen',{})
        ctrl.apply('cw','rx','unlisten',{});self.assertEqual(manager.listen.call_args.args,('rx',None))

    def test_listener_releases_output_and_preserves_new_owner(self):
        state=SimpleNamespace(lock=threading.Lock(),external_audio=False,external_audio_sink_released=False)
        state.external_audio_sink_released_snapshot=lambda:state.external_audio_sink_released
        state.audio_controls_snapshot=lambda:({'mute':False},0)
        player=Mock();ui=SimpleNamespace(BufferedAudioPlayer=Mock(return_value=player),stop_audio_player=Mock())
        listener=CWListener(ui,SimpleNamespace(audio_rate=48000),state)
        listener.start('rx',dict(id='slot',tone_hz=700));state.external_audio_sink_released=True
        listener.submit('rx',tone(700,.1))
        deadline=time.monotonic()+1
        while not player.submit.called and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(player.submit.called);self.assertEqual(ui.BufferedAudioPlayer.call_args.args[0].audio_rate,12000)
        listener.stop();self.assertFalse(state.external_audio);ui.stop_audio_player.assert_called_with(player)
        listener.start('rx',dict(id='slot',tone_hz=700));state.external_audio_sink_released=True
        with state.lock:state.external_audio_generation+=1
        listener.stop();self.assertTrue(state.external_audio)
        with self.assertRaises(ValueError):listener.start('rx',dict(id='slot',tone_hz=700))

if __name__=='__main__':unittest.main()
