"""Touch paging must not open images or activate controls during a drag."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'UI'))
from hell_workspace import HellWorkspace
from qrss_workspace import QRSSWorkspace


class GallerySwipeTests(unittest.TestCase):
    def workspace(self, cls, count=8):
        rows=[dict(id=str(i),kind='saved') for i in range(count)]
        manager=SimpleNamespace(image_snapshot=Mock(return_value=rows))
        w=cls(SimpleNamespace(),manager)
        w.open=True
        return w

    def test_hell_live_saved_and_back_with_bounds(self):
        w=self.workspace(HellWorkspace)
        up=lambda:w.swipe(500,600,510,300)
        down=lambda:w.swipe(500,300,510,600)
        self.assertTrue(up());self.assertTrue(w.saved_view);self.assertEqual(w.page,0)
        w.visible_strips=['cached']
        up();self.assertEqual(w.page,1);self.assertIsNone(w.visible_strips)
        up();up();self.assertEqual(w.page,2)
        down();down();self.assertTrue(w.saved_view);self.assertEqual(w.page,0)
        down();self.assertFalse(w.saved_view);self.assertEqual(w.page,0)
        down();self.assertFalse(w.saved_view)

    def test_qrss_older_and_newer_pages_filtered(self):
        w=self.workspace(QRSSWorkspace,5);w.filter_id='receiver'
        for _ in range(6):self.assertTrue(w.swipe(600,650,600,350))
        self.assertEqual(w.page,2)
        w.manager.image_snapshot.assert_called_with('receiver')
        for _ in range(6):w.swipe(600,300,600,600)
        self.assertEqual(w.page,0)

    def test_controls_taps_horizontal_and_overlays_do_not_page(self):
        for cls in (HellWorkspace,QRSSWorkspace):
            w=self.workspace(cls)
            for points in ((500,20,500,300),(500,400,502,412),(500,400,800,350),(500,400,600,500)):
                self.assertFalse(w.swipe(*points))
            for attribute,value in (('open',False),('add_open',True),('decoders_open',True),('enlarged','img'),('field','freq_khz')):
                old=getattr(w,attribute);setattr(w,attribute,value)
                self.assertFalse(w.swipe(500,600,500,300),attribute)
                setattr(w,attribute,old)
            self.assertEqual(w.page,0)
        w=self.workspace(HellWorkspace);w.reporting={}
        self.assertFalse(w.swipe(500,600,500,300))
        self.assertFalse(w.swipe(500,750,500,300))

    def test_empty_galleries_and_pruned_last_page(self):
        for cls in (HellWorkspace,QRSSWorkspace):
            w=self.workspace(cls,0)
            self.assertTrue(w.swipe(500,600,500,300));self.assertEqual(w.page,0)
            w.page=30
            self.assertTrue(w.swipe(500,600,500,300));self.assertEqual(w.page,0)


if __name__ == '__main__':unittest.main()
