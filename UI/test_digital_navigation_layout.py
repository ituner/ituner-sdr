"""Digital modes keep navigation semantic and leave controls clear of content."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import theme_system
from ui_style import APP_UI_STYLE
from ui_chrome import RAIL_BACK_BOX
from decoder_style import full_width_back_box
from digital_navigation import install_navigation
from cw_workspace import CWWorkspace
from qrss_workspace import QRSSWorkspace


def ui_fixture():
    ui=Mock()
    ui.contains.side_effect=lambda b,x,y:b[0]<=x<b[2] and b[1]<=y<b[3]
    ui.fit_station_text.side_effect=lambda cache,value,*args:str(value)
    ui.station_receiver_type.return_value='kiwi'
    return ui


def tap_action(w, kind, value=None):
    w.actions=[((0,0,100,60),(kind,value))]
    w.tap(10,10,[])


def back(w):
    w.tap(1152,760,[])


class DigitalNavigationTests(unittest.TestCase):
    def workspace(self):
        ui=ui_fixture();manager=Mock();manager.snapshot.return_value=[];manager.image_snapshot.return_value=[]
        w=CWWorkspace(ui,manager);install_navigation(w);w.show('server',7000,'AM')
        return w,ui,manager

    def test_back_retraces_live_history_receivers_instead_of_exiting(self):
        w,_,_=self.workspace()
        tap_action(w,'history');tap_action(w,'decoders')
        self.assertTrue(w.decoders_open)
        back(w);self.assertTrue(w.history_open);self.assertFalse(w.decoders_open)
        back(w);self.assertFalse(w.history_open);self.assertTrue(w.open)
        back(w);self.assertFalse(w.open)

    def test_create_from_history_back_returns_to_history(self):
        w,ui,_=self.workspace();tap_action(w,'history');tap_action(w,'add')
        ui.station_fields.return_value=('Receiver','Place','server',0,1)
        w.selected_server='server';w.actions=[((0,0,100,60),('create',None))]
        w.tap(10,10,[{}]);self.assertTrue(w.decoders_open)
        back(w);self.assertTrue(w.history_open);self.assertFalse(w.decoders_open)

    def test_reopening_resets_navigation_history(self):
        w,_,_=self.workspace();tap_action(w,'history')
        w.show('server',7000,'AM');w.history_open=False
        back(w);self.assertFalse(w.open)

    def test_forms_and_numeric_editor_have_cancel_without_injected_navigation(self):
        w,_,_=self.workspace()
        for field,add in ((None,True),('tone_hz',True)):
            w.field=field;w.add_open=add;w.draw(None,[])
            self.assertFalse(any(a[0] in ('nav_back','nav_home','home') for _,a in w.actions))
            self.assertTrue(any(a[0] in ('cancel_add','cancel_number') for _,a in w.actions))

    def test_top_level_has_one_back_and_no_home(self):
        w,_,_=self.workspace();w.draw(None,[])
        self.assertEqual([b for b,a in w.actions if a[0]=='nav_back'],[RAIL_BACK_BOX])
        self.assertFalse(any(a[0] in ('home','nav_home') for _,a in w.actions))


class DigitalLayoutTests(unittest.TestCase):
    def test_cw_history_cards_leave_bottom_and_search_controls_clear(self):
        ui=ui_fixture();manager=Mock()
        manager.history.return_value=[dict(rf_hz=7000000,wpm=20,receiver='Receiver',start_utc='Start',end_utc='End',text='Decoded message')]*3
        w=CWWorkspace(ui,manager);w.history_open=True;install_navigation(w);w.draw(None,[])
        cards=[c.args[:4] for c in ui.draw_logical_rect.call_args_list if c.args[0]==16]
        self.assertEqual(len(cards),3)
        self.assertTrue(all(b[2]<=1020 and b[3]<712 for b in cards))

    def test_cw_listen_button_does_not_cover_decoded_text_or_status(self):
        ui=ui_fixture();manager=Mock();manager.sessions={}
        w=CWWorkspace(ui,manager)
        row=dict(w.preset,id='rx',name='Receiver',running=False,status='STOPPED',tracks=[dict(id='track',rf_hz=w.preset['freq_khz']*1000+700,wpm=20,active=True,text='CQ CQ')])
        manager.snapshot.return_value=[row]
        w.message='Receiver notice';w.draw(None,[])
        listen=next(b for b,a in w.actions if a[0]=='listen')
        self.assertEqual(listen,(1034,563,1270,627))
        text=[c.args for c in ui.draw_text.call_args_list]
        notice=next(c for c in text if c[3]=='Receiver notice')
        self.assertEqual(notice[2],770)
        self.assertTrue(all(c[2]<755 for c in text if c[3]=='CQ CQ'))

    def test_cw_waterfall_stays_continuous_and_footer_clears_theme_side_back(self):
        ui=ui_fixture();manager=Mock();manager.sessions={}
        w=CWWorkspace(ui,manager);install_navigation(w)
        manager.snapshot.return_value=[dict(w.preset,id='rx',name='Receiver',running=False,status='STOPPED',tracks=[])]
        for side in ('left','right'):
            theme=deepcopy(theme_system.DEFAULT_THEME);theme['sidebar']=side
            with self.subTest(side=side),theme_system.preview_theme(theme):
                ui.reset_mock();w.draw(None,[])
                rectangles=[c.args[:4] for c in ui.draw_logical_rect.call_args_list]
                self.assertIn((16,150,1260,524),rectangles)
                panel=next(b for b in rectangles if b[1]==647)
                back_box=full_width_back_box()
                self.assertIn((back_box,('nav_back',None)),w.actions)
                self.assertTrue(panel[0]>=back_box[2] or panel[2]<=back_box[0])
                for box,action in w.actions:
                    if action[0]!='nav_back':
                        self.assertFalse(min(box[2],back_box[2])>max(box[0],back_box[0]) and min(box[3],back_box[3])>max(box[1],back_box[1]),action)

    def test_qrss_gallery_and_enlarged_body_clear_back_on_both_sides(self):
        ui=ui_fixture();manager=Mock()
        item=dict(id='capture',kind='saved',band='30 m',mode='AUTO',receiver='Receiver',capture_utc='2026-10-28T10:00:00Z',text_message='Tentative text',rf_hz=10140000,dot_seconds=6,tracks=[])
        manager.image_snapshot.return_value=[item,item]
        w=QRSSWorkspace(ui,manager);w.draw_plot=Mock();install_navigation(w)
        for side in ('left','right'):
            theme=deepcopy(theme_system.DEFAULT_THEME);theme['sidebar']=side
            with self.subTest(side=side),theme_system.preview_theme(theme):
                for enlarged in (None,'capture'):
                    w.enlarged=enlarged;w.draw(None,[])
                    back_box=full_width_back_box()
                    for box,action in w.actions:
                        if action[0] not in ('nav_back','back_image'):
                            self.assertFalse(min(box[2],back_box[2])>max(box[0],back_box[0]) and min(box[3],back_box[3])>max(box[1],back_box[1]),action)
                    plot=w.draw_plot.call_args.args[2]
                    self.assertTrue(plot[0]>=back_box[2] or plot[2]<=back_box[0])

    def test_qrss_status_is_outside_top_buttons_and_themes_apply_live(self):
        ui=ui_fixture();manager=Mock();manager.image_snapshot.return_value=[]
        w=QRSSWorkspace(ui,manager);w.message='Capture unavailable'
        for theme in theme_system.BUILTIN_THEMES.values():
            with theme_system.preview_theme(deepcopy(theme)):
                ui.reset_mock();w.draw(None,[])
                self.assertEqual(ui.draw_logical_rect.call_args_list[0].args[4],APP_UI_STYLE.palette.background)
                status=next(c.args for c in ui.draw_text.call_args_list if c.args[3]=='Capture unavailable')
                self.assertEqual(status[1:3],(1034,108))
                self.assertFalse(any(a[0]=='home' for _,a in w.actions))

if __name__=='__main__':unittest.main()
