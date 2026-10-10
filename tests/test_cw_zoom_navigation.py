import sys,struct,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from cw_modes import overview_bounds,VIEW_SPANS,settings,PRESETS,bounds
from cw_waterfall import kiwi_row,overview_zoom,LiveWaterfall,WIDTH
from cw_monitor import CWManager,CWSession
from cw_workspace import CWWorkspace
from sstv_workspace import SSTVWorkspace
from hell_workspace import HellWorkspace
from qrss_workspace import QRSSWorkspace
from digital_navigation import install_navigation

class ZoomTests(unittest.TestCase):
    def test_real_header_geometry_across_all_spans(self):
        dial=7023300;bandwidth=30000000
        for span in VIEW_SPANS:
            lo,hi=overview_bounds(dict(freq_khz=dial/1000,view_span_khz=span))
            zoom=overview_zoom(span);native=bandwidth/2**zoom
            start=round((dial+(lo+hi)/2-native/2)*1024*2**14/bandwidth)
            left=start*bandwidth/(1024*2**14);freq=left+np.arange(WIDTH)*native/WIDTH
            values=np.full(WIDTH,100,dtype=np.uint8);idx=np.argmin(abs(freq-(dial+1700)))
            values[idx]=145
            packet=b'W/F\0'+struct.pack('<III',start,zoom,1)+values.tobytes()
            row=kiwi_row(packet,dial,span_khz=span)
            self.assertIsNotNone(row,span)
            peak=dial+lo+np.argmax(row)*(hi-lo)/(WIDTH-1)
            self.assertAlmostEqual(peak,dial+1700,delta=native/WIDTH*2)
            self.assertEqual(bounds(dict(engine='fldigi',view_span_khz=span)),(200,3200))
        for dial in (.001,29996.8):
            lo,hi=overview_bounds(dict(freq_khz=dial,view_span_khz=50))
            self.assertGreaterEqual(dial*1000+lo,0);self.assertLessEqual(dial*1000+hi,30000000)

    def test_wide_source_fallback_returns_true_audio_range(self):
        clock=[1.];w=LiveWaterfall(clock=lambda:clock[0])
        w.receive(np.ones(WIDTH,dtype=np.uint8),(-23300,26700))
        w.feed(bytes(12000));wide=w.read();self.assertEqual(w.display_range(),(-23300,26700))
        clock[0]=5;w.feed(bytes(12000));narrow=w.read()
        self.assertEqual(narrow['source'],'audio');self.assertEqual(w.display_range(),(200,3200))
        self.assertNotEqual(wide['epoch'],narrow['epoch'])

    def test_zoom_keeps_audio_session_and_validates_limits(self):
        with tempfile.TemporaryDirectory() as root:
            m=CWManager(None,'test',root)
            row=dict(PRESETS[3],id='rx',name='local',server='kiwi',paused=False)
            m.configs=[row];s=CWSession(row,Mock(),m.gallery,'test');m.sessions['rx']=s
            s.stop=Mock();m.start=Mock()
            m.set_span('rx',50)
            self.assertEqual(s.config['view_span_khz'],50)
            s.stop.assert_not_called();m.start.assert_not_called()
            self.assertEqual(s.bandpass(),(150,3250))
            for bad in (100,0,None,True):
                with self.assertRaises(ValueError):m.set_span('rx',bad)
            m.sessions.clear();m.stop()

class NavigationTests(unittest.TestCase):
    def make(self,cls):
        ui=Mock();ui.contains=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        ui.fit_station_text=lambda cache,text,*args:text
        row=dict(PRESETS[3],id='rx',name='local',server='kiwi',paused=False,status='LISTENING',running=True)
        m=SimpleNamespace(configs=[row],snapshot=lambda:[row],image_snapshot=lambda *args:[],web_error='',web_port=8073)
        w=cls(ui,m);w.open=True;install_navigation(w)
        return w
    def test_shared_back_home_hierarchy(self):
        for cls in (CWWorkspace,HellWorkspace,QRSSWorkspace,SSTVWorkspace):
            w=self.make(cls);w.enlarged='image';w.tap(1130,35,[])
            self.assertIsNone(w.enlarged);self.assertTrue(w.open)
            w.tap(1130,35,[]);self.assertTrue(w.decoders_open);self.assertTrue(w.open)
            w.add_open=True;w.tap(1130,35,[]);self.assertFalse(w.add_open)
            w.tap(1220,35,[]);self.assertFalse(w.open)
    def test_receiver_card_opens_live_and_buttons_do_not(self):
        w=self.make(CWWorkspace);w.decoders_open=True;w.draw_receivers(None)
        self.assertFalse(any(a[0]=='select_rx' for b,a in w.actions if b[1]>210))
        w.tap(200,140,[]);self.assertFalse(w.decoders_open);self.assertEqual(w.receiver_index,0)
        w.decoders_open=True;w.actions=[];w.draw_receivers(None)
        w.tap(300,245,[]);self.assertTrue(w.add_open);self.assertTrue(w.decoders_open)

if __name__=='__main__':unittest.main()
