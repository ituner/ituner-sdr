import math
import unittest
import globe_gpu


class ProjectionTests(unittest.TestCase):
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
