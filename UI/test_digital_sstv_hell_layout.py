"""Theme and overlap coverage for SSTV and Hell native pages."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import theme_system
from ui_style import APP_UI_STYLE
from sstv_workspace import SSTVWorkspace
from hell_workspace import HellWorkspace
from hell_modes import MODES


def overlaps(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


class DigitalPictureLayoutTests(unittest.TestCase):
    def setUp(self):
        self.original=deepcopy(theme_system.runtime_theme)
        self.ui=SimpleNamespace(draw_logical_rect=Mock(),draw_logical_rounded_rect=Mock(),
            draw_text=Mock(),draw_styled_two_line_button=Mock(),
            fit_station_text=Mock(side_effect=lambda cache,value,*args:str(value)),
            station_fields=lambda r:(r[0],r[1],r[2],None,None),
            contains=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3],
            LOCAL_KIWI_SERVER='kiwi',station_receiver_type=lambda r:'kiwi')
        self.images=[]
        self.manager=SimpleNamespace(configs=[],snapshot=lambda:[],image_snapshot=lambda *args:self.images,
            web_error='',web_port=8073)

    def tearDown(self):
        theme_system.apply_theme(self.original)

    def test_all_sstv_and_hell_pages_use_live_theme_and_clear_button_targets(self):
        for cls in (SSTVWorkspace,HellWorkspace):
            w=cls(self.ui,self.manager);w.open=True
            w.image=Mock();w.strip_image=Mock()
            for theme_name in ('default','straight-inverted'):
                theme_system.apply_theme(theme_system.BUILTIN_THEMES[theme_name])
                for page in ('gallery','decoders','add','edit','number','report'):
                    if cls is SSTVWorkspace and page in ('number','report'):continue
                    with self.subTest(cls=cls.__name__,theme=theme_name,page=page):
                        w.add_open=page in ('add','edit');w.edit_id='saved' if page=='edit' else None
                        w.decoders_open=page=='decoders'
                        if cls is HellWorkspace:
                            w.field='freq_khz' if page=='number' else None
                            w.reporting=dict(receiver='RX',server='kiwi',call='',reporter='',grid='',confirmed=False) if page=='report' else None
                        self.ui.draw_logical_rect.reset_mock()
                        w.draw(None,[('Receiver','Location','kiwi')])
                        self.assertEqual(self.ui.draw_logical_rect.call_args_list[0].args[4],APP_UI_STYLE.palette.background)
                        self.assertNotIn(('home',None),[a for _,a in w.actions])
                        for i,(box,action) in enumerate(w.actions):
                            self.assertTrue(0<=box[0]<box[2]<=1280 and 0<=box[1]<box[3]<=800,(page,action,box))
                            self.assertGreaterEqual(box[3]-box[1],56)
                            for other,item in w.actions[i+1:]:
                                self.assertFalse(overlaps(box,other),(action,item))

    def test_footer_targets_clear_theme_side_back_and_full_width_content(self):
        from decoder_style import full_width_back_box
        for side in ('left', 'right'):
            theme=deepcopy(self.original);theme['sidebar']=side;theme_system.apply_theme(theme)
            back=full_width_back_box()
            for cls in (SSTVWorkspace,HellWorkspace):
                w=cls(self.ui,self.manager);w.preview=Mock();w.strip_image=Mock()
                for page in ('gallery','decoders','delete','add','enlarged'):
                    with self.subTest(side=side,cls=cls.__name__,page=page):
                        item=dict(id='picture',kind='saved',mode=next(iter(MODES)) if cls is HellWorkspace else 'Martin 2',
                                  band='20m',freq_khz=14000,rf_hz=14000000,receiver='RX',capture_utc='now',width=500,height=100)
                        self.images[:]=[item] if page=='enlarged' else []
                        w.enlarged='picture' if page=='enlarged' else None
                        w.decoders_open=page in ('decoders','delete')
                        w.delete_armed='decoder' if page=='delete' else None
                        w.add_open=page=='add'
                        w.draw(None,[])
                        for i,(box,action) in enumerate(w.actions):
                            self.assertTrue(0<=box[0]<box[2]<=1280,(action,box))
                            if box[1]>=712 and action[0]!='back_image':
                                self.assertFalse(overlaps(box,back),(action,box,back))
                            for other,item_action in w.actions[i+1:]:
                                self.assertFalse(overlaps(box,other),(action,item_action))
                        if page=='enlarged':
                            self.assertIn((back,('back_image',None)),w.actions)
                            if cls is SSTVWorkspace:
                                self.assertFalse(overlaps(w.preview.call_args.args[2],back))

    def test_sstv_live_placeholder_and_progress_use_theme_roles(self):
        w=SSTVWorkspace(self.ui,self.manager)
        theme=theme_system.new_theme('Picture screen test')
        theme['colors'].update(section_surface=[1,2,3,255],slider_track=[4,5,6,255],ready=[7,8,9])
        theme_system.apply_theme(theme)
        item=dict(id='live',kind='receiving',has_image=False,mode='Martin 2',progress_pct=150)
        w.preview(None,item,(10,20,210,220))
        fills=[c.args[4] for c in self.ui.draw_logical_rect.call_args_list]
        self.assertEqual(fills,[APP_UI_STYLE.palette.section_surface,APP_UI_STYLE.palette.section_surface,
                                APP_UI_STYLE.palette.slider_track,APP_UI_STYLE.palette.ready])
        self.assertEqual(self.ui.draw_logical_rect.call_args.args[:4],(10,215,210,220))

    def test_hell_expanded_scroll_hint_stops_before_right_button(self):
        item=dict(id='strip',mode=next(iter(MODES)),band='20m',rf_hz=14000000,
                  receiver='RX',capture_utc='2026-10-28',width=500,height=100)
        self.images.append(item)
        w=HellWorkspace(self.ui,self.manager);w.enlarged='strip';w.strip_image=Mock()
        w.draw(None,[])
        hint=next(c for c in self.ui.fit_station_text.call_args_list if c.args[1]=='Scroll across the strip · fixed letter size')
        right=next(b for b,a in w.actions if a==('pan_strip',1))
        self.assertLessEqual(280+hint.args[2]+16,right[0])

    def test_body_text_uses_theme_font_and_bounds_long_metadata(self):
        w=SSTVWorkspace(self.ui,self.manager)
        w.text(None,1000,100,'Long receiver name',20,width=500)
        fit=self.ui.fit_station_text.call_args
        self.assertEqual(fit.args[2],256)
        self.assertEqual(fit.args[-1],APP_UI_STYLE.button.font_family)
        self.assertEqual(self.ui.draw_text.call_args.kwargs['family'],APP_UI_STYLE.button.font_family)

if __name__=='__main__':unittest.main()
