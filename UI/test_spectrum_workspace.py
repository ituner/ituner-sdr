"""Shared receiver ownership and honest native spectrum / history rendering."""
import math
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

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

    def test_chart_and_history_preserve_clipped_and_missing_bins(self):
        data=dict(settings=dict(low=100e6,high=101e6,bin=250000),power=[-100,-80,None,-50],
                  peak=[-90,-70,None,-40],masked=[False,False,False,True])
        self.assertEqual(columns(data,'power',(100e6,101e6),4).tolist(),[102,122,0,1])
        self.assertEqual(columns(data,'power',(100.5e6,101e6),2).tolist(),[0,1])
        row=dict(values=np.array([0]*452+[1]*452,dtype=np.uint8))
        raw,_=self.workspace.paint(data,[row],(100e6,101e6))
        image=Image.frombytes('RGBA',(984,480),raw)
        self.assertEqual(image.getpixel((100,275))[:3],(8,18,29))
        self.assertEqual(image.getpixel((900,275))[:3],(232,148,72))

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
        w.tap(40,105)  # Upper portion of the visible Preset tile.
        self.assertEqual(w.overlay,'presets')

    def test_touch_zoom_and_pan_stay_within_acquired_range(self):
        w=self.workspace;w.state=dict(data=dict(settings=dict(low=118e6,high=139e6,bin=25000)))
        w.view=(118e6,139e6);w.zoom(.5)
        self.assertEqual(w.view,(123.25e6,133.75e6))
        w.drag_begin(500,200);w.drag_move(500,200,2000,200)
        self.assertEqual(w.view,(118e6,128.5e6))
        w.drag_begin(500,200);w.drag_move(500,200,-2000,200)
        self.assertEqual(w.view,(128.5e6,139e6))
        w.zoom(1e-6);self.assertAlmostEqual(w.view[1]-w.view[0],500000)
