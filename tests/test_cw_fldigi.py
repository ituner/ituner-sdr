"""Engine selection, streaming continuity and optional real fldigi integration."""
import os
import importlib.util
from pathlib import Path
import queue
import sys
import tempfile
import time
import unittest
import numpy as np
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'UI'),str(Path(__file__).parent)]
from cw_modes import PRESETS,settings,center_offset
from cw_fldigi import FldigiEngine,VirtualDisplay
from cw_decoder import CWDecoder
from cw_monitor import CWManager,CWSession,CWAssembler
from test_cw import signal

class SelectionTests(unittest.TestCase):
    def test_engine_switch_preserves_center_and_limits(self):
        original=PRESETS[3]
        new=dict(original,**settings({'engine':'fldigi'},original))
        self.assertAlmostEqual(new['freq_khz']+center_offset(new),7025)
        self.assertEqual(settings({'tone_hz':2500},new)['tone_hz'],2500)
        old=settings({'engine':'ggmorse'},new)
        self.assertAlmostEqual(old['freq_khz'],original['freq_khz'])
        for p in ({'engine':'invalid'},{'engine':'ggmorse','tone_hz':2500},{'engine':'fldigi','rf_khz':29999}):
            with self.assertRaises(ValueError):settings(p,original)

    def test_no_stale_waterfall_after_reset_without_audio(self):
        with tempfile.TemporaryDirectory() as root:
            manager=CWManager(None,'test',root)
            config=dict(PRESETS[3],id='test',name='test',server='http://kiwi.local')
            session=CWSession(config,None,manager.gallery,'test')
            assembler=CWAssembler(session,manager.gallery)
            assembler.feed(np.zeros(12000,dtype='<i2').tobytes())
            self.assertGreater(session.image_version,0)
            assembler.reset();assembler.publish();assembler.flush()
            self.assertEqual(session.image_version,0)
            self.assertEqual(session.audio_seconds,0)
            manager.stop()

    def test_history_retains_engine_across_restart(self):
        with tempfile.TemporaryDirectory() as root:
            manager=CWManager(None,'test',root)
            config=dict(PRESETS[3],**settings({'engine':'fldigi'},PRESETS[3]))
            key=manager.add('Test','http://kiwi.local',config,running=False)
            manager.gallery.append(manager.configs[0],dict(id='one',rf_hz=7025000,wpm=20),'KN6KEZ','2026-10-09T00:00:00Z')
            manager.stop();manager=CWManager(None,'test',root)
            self.assertEqual(manager.configs[0]['engine'],'fldigi')
            self.assertEqual(manager.history()[0]['engine'],'fldigi')
            self.assertIn(b'fldigi',manager.gallery.export());manager.stop()

    @unittest.skipUnless(importlib.util.find_spec("scipy"),"optional fldigi resampler dependency")
    def test_resampling_independent_of_packet_boundaries(self):
        from scipy.signal import firwin,resample_poly
        source=signal('CQ TEST',20,2500)
        pcm=(source*32767).astype('<i2')
        def convert(chunks):
            engine=object.__new__(FldigiEngine)
            engine.error=None;engine.taps=firwin(63,1/3)*2;engine.zi=np.zeros(62);engine.phase=0
            engine.incoming=queue.Queue();engine.outgoing=queue.Queue()
            parts=[]
            for part in chunks:
                engine.feed(part.tobytes());parts.append(engine.incoming.get())
            return b''.join(parts)
        self.assertEqual(convert([pcm]),convert([pcm[i:i+511] for i in range(0,len(pcm),511)]))

@unittest.skipUnless(os.environ.get('ITUNER_TEST_FLDIGI')=='1','optional real Linux fldigi binary')
class LiveEngineTests(unittest.TestCase):
    def test_two_live_tracks_and_cleanup(self):
        config=dict(PRESETS[3],**settings({'engine':'fldigi'},PRESETS[3]))
        a=signal('VVV VVV CQ CQ DE KN6KEZ KN6KEZ TEST 73',20,600)
        b=signal('VVV VVV CQ CQ DE YO3ABC YO3ABC TEST 73',28,2500)
        audio=np.zeros(max(len(a),len(b))+12000*4);audio[:len(a)]+=a;audio[:len(b)]+=.7*b
        decoder=CWDecoder(config);texts={};pids=[]
        try:
            for i in range(0,len(audio),3000):
                decoder.feed((audio[i:i+3000]*32767).astype('<i2').tobytes())
                for t in decoder.tracks:
                    pids.append(t['engine'].process.pid)
                    texts[t['tone_hz']]=t['text']
                time.sleep(.10) # 2.5x real time, keeping process output ahead of audio gate.
            print('Live fldigi tracks:',texts,flush=True)
            self.assertTrue(any('KN6KEZ' in text for text in texts.values()),texts)
            self.assertTrue(any('YO3ABC' in text for text in texts.values()),texts)
        finally:decoder.close()
        self.assertEqual(VirtualDisplay.users,0)
        for pid in set(pids):
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)

if __name__=='__main__':unittest.main()
