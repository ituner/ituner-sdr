"""Reception updates must not replace a settled cloud with a sparse preview."""
import threading
import unittest
from unittest.mock import Mock, patch
from adsb_coverage_touch import CoverageTouch, BOX
import adsb_coverage_gl as dome_gl


def data(count):
    return dict(base=1000,meta={},aircraft=[dict(hex='abc123',label='TEST')],
                points=[[i,0,10000+i,20000,3000,10000,-20,1,'TEST'] for i in range(count)])


def scene(snapshot):
    result=dome_gl.prepare(snapshot,'space');result['snapshot']=snapshot
    return result


class ContinuityTests(unittest.TestCase):
    def test_reception_keeps_dense_frame_and_its_pick_data_until_atomic_replacement(self):
        w=Mock();w.ui.logical_to_native.side_effect=lambda x,y:(x,y);w.ui.NATIVE_H=800
        view=CoverageTouch(w);view.mode='space';view.interaction_until=0
        first_data,second_data=data(9000),data(9001)
        first,second=scene(first_data),scene(second_data)
        old=view.projection(first,1)
        entered=threading.Event();release=threading.Event();project=dome_gl.project
        def slow(*args,**kwargs):
            if args[0] is second:entered.set();release.wait(5)
            return project(*args,**kwargs)
        try:
            with patch('adsb_coverage_touch.dome_gl.project',side_effect=slow),patch('adsb_coverage_touch.dome_gl.draw') as draw:
                view.pulse_until=10**20
                view.draw_scene(Mock(),second_data,second,2)
                self.assertTrue(entered.wait(2))
                self.assertIs(view.projected,old)
                self.assertEqual(view.projected['drawn_positions'],9000)
                self.assertIs(view.pick_data,first_data)
                self.assertEqual(draw.call_args.args[3],0,'New reception cannot reflash the old cloud')
                release.set();view.projection_future.result(timeout=5)
                view.draw_scene(Mock(),second_data,second,2)
                self.assertEqual(view.projected['drawn_positions'],9001)
                self.assertIs(view.pick_data,second_data)
                self.assertEqual(view.project_key[0],2)
                self.assertGreater(draw.call_args.args[3],0)
        finally:
            release.set()
            if view.projection_pool:view.projection_pool.shutdown(wait=True)

    def test_reset_or_mode_change_cannot_hold_old_history_on_screen(self):
        view=CoverageTouch(Mock());view.mode='space';view.interaction_until=0
        first=scene(data(9000));view.projection(first,1)
        entered=threading.Event();release=threading.Event();project=dome_gl.project
        second=scene(data(9001));view.window.revision+=1
        def slow(*args,**kwargs):
            if kwargs.get('point_limit',0)>8000:entered.set();release.wait(5)
            return project(*args,**kwargs)
        try:
            with patch('adsb_coverage_touch.dome_gl.project',side_effect=slow):
                changed=view.projection(second,2,asynchronous=True)
                self.assertTrue(entered.wait(2))
                self.assertEqual(view.project_key[0],2)
                self.assertEqual(changed['drawn_positions'],8000)
                empty=scene(data(0))
                cleared=view.projection(empty,3,asynchronous=True)
                self.assertEqual(cleared['drawn_positions'],0)
                self.assertEqual(view.project_key[0],3)
        finally:
            release.set()
            if view.projection_pool:view.projection_pool.shutdown(wait=True)


if __name__=='__main__':unittest.main()
