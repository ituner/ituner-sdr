import math
import unittest
from unittest.mock import patch
import globe_gpu


class MotionDetailTests(unittest.TestCase):
    def test_fast_swipe_restores_after_slowdown_without_flicker(self):
        state = globe_gpu.MotionDetail()
        self.assertFalse(state.update(0, 0, 300, 1, False))
        self.assertTrue(state.update(.02, 0, 300, 1.02, True))  # 300 px/s
        self.assertTrue(state.update(.03, 0, 300, 1.04, True))  # 150 px/s: hold
        self.assertTrue(state.update(.03, 0, 300, 1.10, True))
        self.assertFalse(state.update(.03, 0, 300, 1.23, True))
        self.assertFalse(state.update(.04, 0, 300, 1.25, True))  # no re-entry at 150
        self.assertTrue(state.update(.06, 0, 300, 1.27, True))
        self.assertFalse(state.update(.06, 0, 300, 1.28, False))

    def test_dateline_gentle_drag_and_reopening_keep_detail(self):
        state = globe_gpu.MotionDetail()
        state.update(math.pi-.001, 0, 300, 1, False)
        self.assertFalse(state.update(-math.pi+.001, 0, 300, 1.02, True))
        self.assertFalse(state.update(0, 0, 300, 3, True))
        self.assertFalse(state.update(.001, 0, 300, 3.02, True))

    def test_fast_pitch_and_zoom_reduce_detail(self):
        for yaw, pitch, radius in ((0, .02, 300), (0, 0, 310)):
            state = globe_gpu.MotionDetail()
            state.update(0, 0, 300, 1, False)
            self.assertTrue(state.update(yaw, pitch, radius, 1.02, True))


class ProjectionTests(unittest.TestCase):
    def test_border_segments_do_not_join_islands_or_duplicate_shared_edges(self):
        data = globe_gpu.border_data([
            [(0, 0), (0, 10), (10, 10)],
            [(0, 10), (0, 0)],  # same boundary in reverse
            [(40, 40), (40, 41)],
            [(0, 180), (0, -180)],  # identical dateline endpoints
        ])
        self.assertEqual(len(data), 3*2*3)
        for i in range(0, len(data), 3):
            self.assertAlmostEqual(sum(x*x for x in data[i:i+3]), 1, places=6)

    def test_borders_upload_once_and_restore_gl_state(self):
        borders = globe_gpu.GlobeBorders([[(0, 0), (0, 10)]])
        with patch.object(globe_gpu, 'GL') as gl:
            gl.glGenBuffers.return_value = 123
            for _ in range(2):
                borders.draw([1]*16, (170, 190, 181, 105))
            gl.glBufferData.assert_called_once()
            self.assertEqual(gl.glDrawArrays.call_count, 2)
            gl.glDrawArrays.assert_called_with(gl.GL_LINES, 0, 2)
            self.assertEqual(gl.glPushAttrib.call_count, gl.glPopAttrib.call_count)
            self.assertEqual(gl.glPushClientAttrib.call_count, gl.glPopClientAttrib.call_count)
            self.assertEqual(gl.glPushMatrix.call_count, gl.glPopMatrix.call_count)

    def test_gpu_view_matches_existing_projection_and_lcd_orientations(self):
        # Independent scalar reference: same geographic point must remain under
        # its existing receiver marker across the dateline, poles and zooms.
        for convert in (lambda x,y:(x,y), lambda x,y:(800-y,x), lambda x,y:(y,1280-x)):
            for yaw in (-3.12, -1, 0, 0.6, 3.12):
                for pitch in (-1.3, 0, 0.7, 1.3):
                    for radius in (300, 1600, 12000):
                        m=globe_gpu.view_matrix(yaw,pitch,radius,(640,400),convert)
                        for lat,lon in ((0,0),(45,26),(-80,-179),(80,179),(12,110)):
                            la,lo=map(math.radians,(lat,lon))
                            xyz=(math.cos(la)*math.sin(lo),math.sin(la),math.cos(la)*math.cos(lo),1)
                            actual=[sum(m[c*4+r]*xyz[c] for c in range(4)) for r in range(4)]
                            x=640+radius*math.cos(la)*math.sin(lo-yaw)
                            y=400-radius*(math.cos(pitch)*math.sin(la)-math.sin(pitch)*math.cos(la)*math.cos(lo-yaw))
                            expected=convert(x,y)
                            self.assertAlmostEqual(actual[0],expected[0],places=8)
                            self.assertAlmostEqual(actual[1],expected[1],places=8)
                            depth=math.sin(pitch)*math.sin(la)+math.cos(pitch)*math.cos(la)*math.cos(lo-yaw)
                            self.assertAlmostEqual(actual[2],0.5*depth,places=10)

    def test_mesh_has_unit_sphere_and_correct_texture_edges(self):
        data=globe_gpu.mesh_data((-180,-90,180,90),16,8,0.7,0.2)
        self.assertEqual(len(data),16*8*4*9)
        vertices=[data[i:i+9] for i in range(0,len(data),9)]
        for v in vertices:
            self.assertAlmostEqual(sum(x*x for x in v[:3]),1,places=6)
            self.assertTrue(all(0<=x<=1 for x in v[3:5]))
            self.assertEqual(v[-1],1)
        self.assertEqual(min(v[3] for v in vertices),0)
        self.assertEqual(max(v[3] for v in vertices),1)
        self.assertEqual(min(v[4] for v in vertices),0)
        self.assertEqual(max(v[4] for v in vertices),1)

if __name__=='__main__': unittest.main()
