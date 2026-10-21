"""Shared receiver ownership and honest native spectrum / history rendering."""
import math
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image
from sdr_broker import ReceiverBroker
from spectrum_monitor import SpectrumSurvey, settings
from spectrum_workspace import SpectrumWorkspace, allocations, columns


class NativeSpectrumTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.hub=SimpleNamespace(root=Path(self.temp.name),broker=ReceiverBroker(),devices=[])
        self.hub.spectrum=SpectrumSurvey(self.hub)
        self.ui=Mock();self.ui.contains.side_effect=lambda box,x,y:box[0]<=x<=box[2] and box[1]<=y<=box[3]
        self.ui.fit_station_text.side_effect=lambda cache,text,*args:text
        self.workspace=SpectrumWorkspace(self.ui,self.hub)

    def tearDown(self):
        self.workspace.close();self.hub.spectrum.close();self.temp.cleanup()

    def test_viewing_existing_data_never_claims_or_restarts_the_radio(self):
        control=self.hub.spectrum.control=Mock()
        self.workspace.show()
        deadline=time.monotonic()+3
        while not self.workspace.frame and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsNotNone(self.workspace.frame,self.workspace.message)
        self.assertIs(self.workspace.survey,self.hub.spectrum)
        self.assertEqual(self.hub.broker.snapshot(),{})
        control.assert_not_called()
        self.assertFalse(self.hub.spectrum.enabled)

    def test_scan_is_native_and_idle_data_does_not_rebuild_or_upload_a_bitmap(self):
        w=self.workspace;s=self.hub.spectrum
        s.snapshot=Mock(side_effect=AssertionError('HTTP snapshot used by native UI'))
        s.insights.snapshot=Mock(side_effect=AssertionError('History analysis ran in Scan'))
        w.show();deadline=time.monotonic()+2
        while w.frame is None and time.monotonic()<deadline:time.sleep(.01)
        self.assertIsInstance(w.frame,dict);self.assertTrue(w.frame['native'])
        prepared=w.prepare_count;time.sleep(.7)
        self.assertEqual(w.prepare_count,prepared)
        w.upload(w.frame,w.frame_id)
        self.ui.GL.glTexImage2D.assert_not_called()
        self.ui.draw_logical_polyline.assert_called()

    def test_three_destinations_and_advanced_settings_do_not_clutter_scan(self):
        w=self.workspace;w.state=self.hub.spectrum.native_snapshot();w.draw(Mock())
        self.assertEqual(w.TABS,(('survey','Scan'),('signals','Signals'),('tools','Tools')))
        self.assertNotIn(('investigate',None),[a for _,a in w.actions])
        self.assertNotIn(('screen','activity'),[a for _,a in w.actions])
        self.assertLessEqual(len(w.actions),11)  # Includes persistent Back and Home.
        w.overlay='settings';w.draft=dict(w.state['settings']);w.draw(Mock())
        self.assertNotIn(('number','gain'),[a for _,a in w.actions])
        self.assertIn(('overlay','advanced'),[a for _,a in w.actions])
        w.overlay='advanced';w.draw(Mock())
        self.assertIn(('number','gain'),[a for _,a in w.actions])

    def test_native_snapshot_samples_are_isolated_from_receiver(self):
        s=self.hub.spectrum;s.data=dict(settings=s.settings,power=[-100,None],masked=[False,True])
        result=s.native_snapshot();result['data']['power'][0]=0
        result['settings']['gain']=49
        self.assertEqual(s.data['power'][0],-100)
        self.assertNotEqual(s.settings['gain'],49)

    def test_back_steps_out_of_tools_then_exits_to_decoders_without_rf_commands(self):
        w=self.workspace;w.open=True
        def back():
            w.actions=[((0,0,100,100),('back',None))];w.tap(10,10)
        for screen in ('activity','compare','watch','reports'):
            w.screen=screen;back();self.assertEqual(w.screen,'tools');self.assertTrue(w.open)
        back();self.assertEqual(w.screen,'survey');self.assertTrue(w.open)
        back();self.assertFalse(w.open);self.assertEqual(w.exit_target,'digi')
        self.assertTrue(w.commands.empty())

    def test_gain_keypad_back_returns_to_advanced_settings(self):
        w=self.workspace;w.open=True;w.overlay='number';w.edit_field='gain'
        w.actions=[((0,0,100,100),('back',None))];w.tap(10,10)
        self.assertEqual(w.overlay,'advanced');self.assertTrue(w.open)
        w.tap(10,10);self.assertEqual(w.overlay,'settings');self.assertTrue(w.open)
        self.assertTrue(w.commands.empty())

    def test_home_exits_nested_setup_and_propagates_through_vhf_host(self):
        from vhf_workspace import VHFWorkspace
        # Exercise the host's real dispatch rather than closing only the child.
        host=object.__new__(VHFWorkspace);host.mode='spectrum';host.open=True;host.spectrum=self.workspace
        w=self.workspace;w.open=True;w.overlay='advanced';w.screen='activity'
        w.actions=[((0,0,100,100),('home',None))];host.tap(10,10)
        self.assertFalse(w.open);self.assertFalse(host.open)
        self.assertIsNone(w.overlay);self.assertEqual(w.exit_target,'home')
        self.assertTrue(w.commands.empty())

    def test_back_and_home_remain_visible_in_tool_and_setup_views(self):
        w=self.workspace;w.state=self.hub.spectrum.native_snapshot();w.draft=dict(w.state['settings'])
        for screen,overlay in (('survey',None),('tools',None),('survey','settings'),('survey','advanced')):
            w.screen=screen;w.overlay=overlay;w.draw(Mock())
            for action in ('back','home'):
                boxes=[box for box,a in w.actions if a==(action,None)]
                self.assertEqual(len(boxes),1,(screen,overlay,action))
                self.assertGreaterEqual(boxes[0][3]-boxes[0][1],56)

    def test_chart_and_history_preserve_clipped_and_missing_bins(self):
        data=dict(settings=dict(low=100e6,high=101e6,bin=250000),power=[-100,-80,None,-50],
                  peak=[-90,-70,None,-40],masked=[False,False,False,True])
        self.assertEqual(columns(data,'power',(100e6,101e6),4).tolist(),[102,122,0,1])
        self.assertEqual(columns(data,'power',(100.5e6,101e6),2).tolist(),[0,1])
        row=dict(values=np.array([0]*452+[1]*452,dtype=np.uint8))
        self.workspace.display='waterfall'
        raw,_=self.workspace.paint(data,[row],(100e6,101e6))
        image=Image.frombytes('RGBA',(1232,380),raw)
        self.assertEqual(image.getpixel((140,44))[:3],(29,38,47))
        self.assertEqual(image.getpixel((1200,44))[:3],(232,148,72))

    def test_draft_controls_apply_together_without_starting_reception(self):
        w=self.workspace;w.state=self.hub.spectrum.snapshot()
        def press(action,value=None):
            w.actions=[((0,0,100,100),(action,value))];w.tap(10,10)
        press('overlay','settings');press('overlay','presets');press('preset',2)
        self.assertEqual((w.draft['low'],w.draft['high'],w.draft['bin']),(118e6,139e6,25000))
        press('number','gain');press('key','CLEAR');press('key','0');press('key','SAVE')
        self.assertEqual(w.draft['gain'],0)
        press('toggle','repeat');press('apply')
        action,values=w.commands.get_nowait();self.assertEqual(action,'configure')
        self.assertEqual(settings(values)['repeat'],True)
        self.assertFalse(self.hub.spectrum.enabled)

    def test_native_inspection_uses_the_same_regional_boundaries(self):
        eu,us=allocations(self.workspace.reference,147e6)
        self.assertIn('Mobile',eu);self.assertNotIn('Amateur',eu)
        self.assertIn('Amateur',us);self.assertNotIn('Land mobile',us)
        self.assertTrue(all('Aeronautical mobile' in s for s in allocations(self.workspace.reference,125e6)))

    def test_settings_overlay_does_not_leave_hidden_chart_buttons_intercepting_taps(self):
        w=self.workspace;w.state=self.hub.spectrum.snapshot();w.draft=dict(w.state['settings']);w.overlay='settings'
        w.draw(Mock())
        self.assertNotIn(('screen','chart'),[action for _,action in w.actions])
        w.tap(40,190)  # Upper portion of the visible Preset tile.
        self.assertEqual(w.overlay,'presets')

    def test_touch_zoom_and_pan_stay_within_acquired_range(self):
        w=self.workspace;w.state=dict(data=dict(settings=dict(low=118e6,high=139e6,bin=25000)))
        w.view=(118e6,139e6);w.zoom(.5)
        self.assertEqual(w.view,(123.25e6,133.75e6))
        w.drag_begin(500,400);w.drag_move(500,400,2000,400)
        self.assertEqual(w.view,(118e6,128.5e6))
        w.drag_begin(500,400);w.drag_move(500,400,-2000,400)
        self.assertEqual(w.view,(128.5e6,139e6))
        w.zoom(1e-6);self.assertAlmostEqual(w.view[1]-w.view[0],500000)

class NativeHistoryTests(unittest.TestCase):
 def test_raw_native_history_matches_wire_values_including_clipping(self):
  import base64
  from spectrum_history import SweepHistory
  with tempfile.TemporaryDirectory() as name:
   history=SweepHistory(Path(name)/'history.sqlite3');now=time.time()
   d=dict(settings=dict(low=100e6,high=100.3e6,bin=100000,gain=0,ppm=0),complete=True,started=now-2,finished=now,sweep=1,power=[-100,-90,None],masked=[False,True,False])
   history.append(d);wire=history.read(d,columns=3);native=history.read(d,columns=3,raw=True)
   self.assertEqual(native['rows'][0]['values'].tobytes(),base64.b64decode(wire['rows'][0]['values']))
   self.assertEqual(native['rows'][0]['values'].tolist(),[102,1,0])
