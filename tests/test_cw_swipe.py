"""CW waterfall drags retune the receiver, not the receiver selection."""
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'UI'))
from cw_workspace import CWWorkspace
from cw_monitor import CWManager
from cw_modes import PRESETS
from gallery_motion import GalleryMotion
from log_search_workspace import install_search

class CWSwipeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.manager=CWManager(None,'test',root=self.temp.name)
        row=dict(PRESETS[3],id='rx',name='Local',server='http://kiwi.local',paused=True,engine='fldigi',freq_khz=7023.3)
        self.manager.configs=[row,dict(row,id='other')]
        self.manager.start=Mock()
        self.w=CWWorkspace(SimpleNamespace(),self.manager);self.w.open=True;self.w.selected_track='old'
    def tearDown(self):
        self.manager.stop();self.temp.cleanup()
    def test_pan_updates_current_receiver_and_persists(self):
        row=self.manager.configs[0];row['paused']=False
        self.assertTrue(self.w.swipe(900,300,280,310))
        self.assertAlmostEqual(row['freq_khz'],7024.8)
        self.assertEqual(self.w.receiver_index,0);self.assertIsNone(self.w.selected_track)
        self.assertEqual(self.manager.configs[1]['freq_khz'],7023.3)
        self.manager.start.assert_called_once_with(row)
        self.assertTrue(self.w.swipe(280,300,900,300))
        self.assertAlmostEqual(row['freq_khz'],7023.3)
        loaded=CWManager(None,'test',root=self.temp.name)
        self.assertAlmostEqual(loaded.configs[0]['freq_khz'],7023.3);loaded.stop()
    def test_taps_diagonals_cards_and_overlays_do_not_tune(self):
        for points in [(500,300,505,302),(500,300,550,345),(500,600,100,600),(500,100,100,100)]:
            self.assertFalse(self.w.swipe(*points))
        for attr,value in [('open',False),('history_open',True),('add_open',True),('decoders_open',True),('enlarged','x'),('field','rf_khz')]:
            old=getattr(self.w,attr);setattr(self.w,attr,value)
            self.assertFalse(self.w.swipe(900,300,280,300));setattr(self.w,attr,old)
        self.assertEqual(self.manager.configs[0]['freq_khz'],7023.3)
    def test_bounds_paused_and_vertical_navigation(self):
        row=self.manager.configs[0];row['freq_khz']=29996.5
        self.w.swipe(900,300,280,300);self.assertEqual(row['freq_khz'],29996.8)
        row['freq_khz']=.2
        self.w.swipe(280,300,900,300);self.assertEqual(row['freq_khz'],.001)
        self.manager.start.assert_not_called()
        self.assertTrue(self.w.swipe(500,450,510,200));self.assertTrue(self.w.history_open)
        self.assertTrue(self.w.swipe(500,200,510,450));self.assertFalse(self.w.history_open)
        self.w.move_receiver(1);self.assertEqual(self.w.receiver_index,1)
    def test_real_touch_route_through_search_and_gallery_animation(self):
        # Production installs search first, then replaces swipe with GalleryMotion.release.
        install_search(self.w,'cw',Mock())
        motion=GalleryMotion(self.w,'cw')
        try:
            self.w.drag_begin(900,300)
            self.w.drag_move(900,300,650,305)
            self.w.drag_move(900,300,280,310)
            self.assertTrue(self.w.swipe(900,300,280,310))
            self.assertAlmostEqual(self.manager.configs[0]['freq_khz'],7024.8)
            self.assertFalse(motion.active);self.assertIsNone(motion.animation)
            self.w.drag_begin(280,300)
            self.w.drag_move(280,300,900,300)
            self.assertTrue(self.w.swipe(280,300,900,300))
            self.assertAlmostEqual(self.manager.configs[0]['freq_khz'],7023.3)
            # A tap remains a tap; vertical swipes still animate history.
            self.w.drag_begin(500,300)
            self.assertFalse(self.w.swipe(500,300,502,302))
            self.w.drag_begin(500,450);self.w.drag_move(500,450,505,200)
            self.assertTrue(self.w.swipe(500,450,505,200));motion.finish()
            self.assertTrue(self.w.history_open)
            self.assertAlmostEqual(self.manager.configs[0]['freq_khz'],7023.3)
            self.w.history_open=False;self.w.log_search_view.open=True
            self.w.drag_begin(900,300)
            self.assertTrue(self.w.swipe(900,300,280,300))
            self.assertAlmostEqual(self.manager.configs[0]['freq_khz'],7023.3)
        finally:self.w.close()

    def test_retune_errors_stay_in_ui(self):
        with patch.object(self.manager,'update',side_effect=ValueError('Receiver is still stopping')):
            self.assertTrue(self.w.swipe(900,300,280,300))
        self.assertIn('still stopping',self.w.message)
        self.assertEqual(self.w.selected_track,'old')

if __name__=='__main__':unittest.main()
