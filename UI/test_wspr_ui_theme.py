"""Digital WSPR and saved-log surfaces retain theme and navigation boundaries."""
from copy import deepcopy
from unittest import TestCase
from unittest.mock import Mock, patch
import kiwi_gl_display as ui
from wspr_history_view import WSPRHistoryView
from log_search_workspace import SearchView
from decoder_style import full_width_back_box


class DigitalWSPRLayoutTests(TestCase):
    def fake_ui(self):
        fake=Mock()
        fake.fit_station_text.side_effect=lambda cache,value,*args:str(value)
        fake.contains.side_effect=ui.contains
        return fake

    def test_cpu_and_decode_header_buttons_do_not_overlap(self):
        boxes=(ui.WSPR_CPU_BOX,ui.WSPR_DECODE_BOX,ui.WSPR_ADD_BOX,ui.WSPR_HOME_BOX)
        for left,right in zip(boxes,boxes[1:]):self.assertGreaterEqual(right[0]-left[2],8)
        self.assertEqual(ui.wspr_workspace_action_at(950,38,[],0),('decoder_settings',None))
        self.assertEqual(ui.wspr_workspace_action_at(1200,38,[],0),('back',None))

    def test_history_uses_theme_background_single_back_and_clear_footer(self):
        fake=self.fake_ui();view=WSPRHistoryView(fake,Mock());view.refresh=lambda:None
        view.page={'total':12,'spots':[{'cycle_start':0,'callsign':'TEST','frequency_mhz':7.04} for _ in range(12)]}
        try:
            for side in ('left','right'):
                theme=deepcopy(ui.theme_system.DEFAULT_THEME);theme.update(id='wspr-test',sidebar=side)
                theme['colors']['background']=[41,42,43,255]
                with ui.theme_system.preview_theme(theme):
                    fake.reset_mock();view.draw(None)
                    self.assertEqual(fake.draw_logical_rect.call_args_list[0].args[-1],(41,42,43,255))
                    self.assertIn((full_width_back_box(),('back',)),view.actions)
                    self.assertFalse(any(a[0]=='home' for _,a in view.actions))
                    for box,action in view.actions:
                        if action[0]=='page':self.assertLessEqual(box[3],712)
                    bx=full_width_back_box();self.assertEqual(view.tap((bx[0]+bx[2])/2,760),'back')
        finally:view.close()

    def test_reporting_error_is_separated_from_explanation_and_back_returns_history(self):
        fake=self.fake_ui();view=WSPRHistoryView(fake,Mock());view.refresh=lambda:None
        view.settings=dict(name='Receiver',call='TEST',grid='AA00',confirmed=False,enabled=False)
        view.message='Invalid receiver grid'
        try:
            view.draw(None)
            texts={c.args[3]:c.args[2] for c in fake.draw_text.call_args_list}
            self.assertGreaterEqual(texts['Invalid receiver grid']-texts['Only new spots are uploaded. History and uncertain uploads are not sent automatically.'],32)
            bx=full_width_back_box();self.assertIsNone(view.tap((bx[0]+bx[2])/2,760));self.assertIsNone(view.settings)
        finally:view.close()

    def test_search_results_pagination_and_theme_back_do_not_overlap(self):
        fake=self.fake_ui();view=SearchView(fake,Mock());view.open=True
        view.result={'total':3,'results':[dict(mode='hell',utc='UTC',band='40',receiver='Receiver',frequency_hz=7000000,source='Local',text='TEST '*40,image_url='image',image_id=str(i)) for i in range(3)]}
        try:
            view.draw(None)
            self.assertIn((full_width_back_box(),('back',None)),view.actions)
            images=[b for b,a in view.actions if a[0]=='image'];pages=[b for b,a in view.actions if a[0]=='page']
            self.assertTrue(all(a[3]<b[1] for a in images for b in pages))
            self.assertTrue(all(b[3]<=712 for b in pages))
        finally:view.close()

    def test_cw_qrss_find_clears_toolbar_and_all_six_receiver_cards(self):
        from cw_workspace import CWWorkspace
        from qrss_workspace import QRSSWorkspace
        from log_search_workspace import install_search
        for kind, cls in (('cw',CWWorkspace),('qrss',QRSSWorkspace)):
            with self.subTest(mode=kind):
                fake=self.fake_ui();manager=Mock();manager.image_snapshot.return_value=[]
                view=cls(fake,manager);view.open=True;view.decoders_open=True
                row=dict(view.preset,name='Receiver',status='STOPPED',running=False,mode='usb')
                manager.snapshot.return_value=[dict(row,id=str(i)) for i in range(6)]
                install_search(view,kind,Mock())
                try:
                    view.draw(None,[])
                    find=next(box for box,action in view.actions if action==('search',None))
                    self.assertEqual(find,(1034,8,1270,72))
                    self.assertEqual(find[0]-1026,8)
                    for box,action in view.actions:
                        if action==('search',None):continue
                        self.assertFalse(find[0]<box[2] and box[0]<find[2] and find[1]<box[3] and box[1]<find[3],action)
                finally:view.close()
