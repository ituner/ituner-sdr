import unittest
import kiwi_gl_display as ui


class GlobeMotionTests(unittest.TestCase):
    def setUp(self):
        ui._receiver_map_render_cache = None
        self.rows=[dict(server=f'http://rx{i}.test:8073',lat=i%90,lon=i%180,
                        receiver_type='kiwi',name=str(i),location='test') for i in range(1500)]
        self.rows.append(dict(server='http://special.test:8073',lat=20,lon=25,
                             receiver_type='openwebrx',name='special',location='test'))

    def test_motion_reduces_markers_but_preserves_selected_pending_and_small_groups(self):
        rows,selected_key,pending_key,selected=ui.receiver_map_render_rows(
            self.rows,'http://rx999.test:8073/','http://rx998.test:8073/',True)
        self.assertLessEqual(len(rows),ui.GLOBE_MOVING_MARKER_BUDGET+4)
        self.assertIn(selected_key,{row[2] for row in rows})
        self.assertIn(pending_key,{row[2] for row in rows})
        self.assertIs(selected,self.rows[999])
        self.assertIn('openwebrx',{row[1] for row in rows})
        full,*_=ui.receiver_map_render_rows(self.rows,selected_key,pending_key,False)
        self.assertEqual(len(full),len(self.rows))

    def test_in_place_updates_and_replaced_catalog_refresh_metadata(self):
        ui.receiver_map_render_rows(self.rows,'','',True)
        first=ui._receiver_map_render_cache
        ui.receiver_map_render_rows(self.rows,'','',True)
        self.assertIs(ui._receiver_map_render_cache,first)
        self.rows[0]['receiver_type']='fmdx'
        full,*_=ui.receiver_map_render_rows(self.rows,'','',False)
        self.assertEqual(full[0][1],'fmdx')
        self.assertIsNot(ui._receiver_map_render_cache,first)
        replacement=[dict(r,name='new '+r['name']) for r in self.rows]
        _,_,_,selected=ui.receiver_map_render_rows(replacement,replacement[0]['server'],'',True)
        self.assertEqual(selected['name'],'new 0')

    def test_sixty_fps_only_when_globe_is_moving(self):
        self.assertEqual(ui.globe_frame_rate(30,True,True),60)
        for globe,moving in ((False,False),(False,True),(True,False)):
            self.assertEqual(ui.globe_frame_rate(30,globe,moving),30)
        self.assertEqual(ui.globe_frame_rate(90,True,True),90)
