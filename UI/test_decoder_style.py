"""Theme changes and navigation exercise the actual decoder renderers."""
from copy import deepcopy
import unittest
from unittest.mock import Mock

import theme_system
from decoder_style import full_width_back_box
from ui_style import APP_UI_STYLE
from ui_chrome import RAIL_BACK_BOX
import test_station_profile
import test_adsb
import test_spectrum_workspace


def overlap(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


class DecoderThemeTests(unittest.TestCase):
    def setUp(self):
        self.original=deepcopy(theme_system.runtime_theme)
        self.fixture=test_spectrum_workspace.NativeSpectrumTests();self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown();theme_system.apply_theme(self.original)

    def apply(self,side='right',name='default'):
        theme=deepcopy(theme_system.BUILTIN_THEMES[name]);theme['sidebar']=side
        theme_system.apply_theme(theme)

    def assert_navigation_clear(self,w,action=('back',None),rail=False):
        backs=[b for b,a in w.actions if a==action]
        self.assertEqual(backs,[RAIL_BACK_BOX if rail else full_width_back_box()])
        for box,item in w.actions:
            if item!=action:self.assertFalse(overlap(box,backs[0]),item)

    def test_spectrum_theme_updates_existing_workspace_and_navigation(self):
        w=self.fixture.workspace;w.state=self.fixture.hub.spectrum.native_snapshot()
        w.draft=dict(w.state['settings']);w.selected=100e6
        for side in ('left','right'):
            for name in theme_system.BUILTIN_THEMES:
                self.apply(side,name)
                for screen,overlay in (('survey',None),('signals',None),('tools',None),('survey','settings'),('survey','advanced')):
                    w.screen=screen;w.overlay=overlay;w.draw(Mock())
                    self.assert_navigation_clear(w)
                    self.assertEqual(w.BG,APP_UI_STYLE.palette.background)
                    # The rendered button uses the active palette, not a cached color.
                    self.assertTrue(any(c.args[5]==APP_UI_STYLE.palette.surface for c in self.fixture.ui.draw_logical_rounded_rect.call_args_list))
                    self.fixture.ui.reset_mock()

    def test_adsb_back_is_clear_in_map_traffic_logs_receiver_and_dome(self):
        w,ui,manager,state=test_adsb.WorkspaceTests().dashboard()
        manager.coverage_error='';w.coverage_view.data={'status':'EMPTY','meta':{}}
        for side in ('left','right'):
            self.apply(side)
            for view in ('map','traffic','logs','usb','coverage'):
                w.traffic_open=view=='traffic';w.logs_open=view=='logs';w.usb_open=view=='usb';w.coverage_open=view=='coverage'
                w.open=True;w.draw(Mock())
                self.assert_navigation_clear(w,rail=view!='coverage')
                box=next(box for box,action in w.actions if action==('back',None))
                w.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
                self.assertEqual(w.open, view != "map", view)
                self.assertFalse(w.coverage_open or w.traffic_open or w.logs_open or w.usb_open)

    def test_adsb_back_retraces_nested_views_before_leaving_decoder(self):
        w,ui,manager,state=test_adsb.WorkspaceTests().dashboard()
        w.open=True
        def tap(kind):
            w.actions=[((0,0,100,100),(kind,None))];w.tap(10,10)
        tap('traffic');tap('logs');tap('coverage')
        tap('back');self.assertTrue(w.logs_open);self.assertTrue(w.open)
        tap('back');self.assertTrue(w.traffic_open);self.assertTrue(w.open)
        tap('back');self.assertFalse(w.traffic_open);self.assertTrue(w.open)
        tap('back');self.assertFalse(w.open)

    def test_adsb_uses_home_rail_buttons_clock_and_status_typography(self):
        import time
        from unittest.mock import patch
        planes=[dict(hex=str(i),flight='FLIGHT '+str(i),lat=44,lon=26,last_seen_at=time.time(),position_time=time.time(),seen=0,seen_pos=0,alt_baro=10000) for i in range(5)]
        w,ui,manager,state=test_adsb.WorkspaceTests().dashboard(planes)
        w.selected='0';w.selected_plane=planes[0]
        self.apply('left')
        with patch('ui_chrome.time.strftime',return_value='12:34:56'):
            w.draw(Mock())
        boxes=[c.args[1] for c in ui.draw_styled_two_line_button.call_args_list]
        for box,action in w.actions:
            self.assertIn(box,boxes,action)
        self.assertIn(RAIL_BACK_BOX,boxes)
        self.assertIn((1034,12,1270,76),boxes)
        # A left-side physical BACK hit must map to the same HOME rail coordinates.
        self.assertEqual(theme_system.display_to_logical_x(20),1044)
        clock=[c for c in ui.draw_text.call_args_list if c.args[3]=='12:34:56 UTC (UTC)']
        self.assertEqual(len(clock),1)
        self.assertEqual(clock[0].args[1:3],(18,771))
        self.assertEqual(clock[0].args[5],18)
        for i,(box,action) in enumerate(w.actions):
            for other,item in w.actions[i+1:]:
                self.assertFalse(overlap(box,other),(action,item))
        w.open=True;w.tap(theme_system.display_to_logical_x(20),750)
        self.assertFalse(w.open)

    def test_footprint_control_uses_theme_and_stays_above_footer(self):
        w,ui,manager,state=test_adsb.WorkspaceTests().dashboard()
        for name in theme_system.BUILTIN_THEMES:
            self.apply(name=name)
            w.open=True;w.rx_footprint=True;ui.reset_mock();w.draw(Mock())
            box=next(box for box,action in w.actions if action==('rx_footprint',None))
            self.assertGreaterEqual(box[3]-box[1],56)
            self.assertLessEqual(box[3],712)
            call=next(c for c in ui.draw_styled_two_line_button.call_args_list if c.args[1]==box)
            self.assertTrue(call.kwargs['active'])
            self.assertIn(('fit',None),[action for _,action in w.actions])
            w.tap((box[0]+box[2])/2,(box[1]+box[3])/2)
            self.assertFalse(w.rx_footprint)
            self.assertTrue(w.open)

    def test_station_footer_and_keyboard_follow_theme_side_without_saving(self):
        fixture=test_station_profile.StationTests();fixture.setUp()
        self.addCleanup(fixture.tearDown)
        from station_workspace import StationWorkspace
        ui=Mock();ui.contains.side_effect=lambda b,x,y:b[0]<=x<=b[2] and b[1]<=y<=b[3]
        ui.fit_station_text.side_effect=lambda cache,text,*args:text
        w=StationWorkspace(ui,fixture.s);w.show()
        for side in ('left','right'):
            self.apply(side)
            for page in ('identity','location','gps'):
                w.page=page;w.field=None;w.draw(Mock());self.assert_navigation_clear(w)
            w.field='station_name';w.value='Unsaved';w.draw(Mock())
            self.assert_navigation_clear(w,('key','CANCEL'))
            b=full_width_back_box();w.tap(b[0]+10,b[1]+10)
            self.assertIsNone(w.field);self.assertTrue(w.open)
            self.assertNotEqual(w.draft['station_name'],'Unsaved')

    def test_disabled_button_does_not_register_an_action(self):
        w,ui,_,_=test_adsb.WorkspaceTests().dashboard();w.actions=[]
        w.button(Mock(),(0,0,200,64),'FOLLOW',('follow',None),enabled=False)
        self.assertEqual(w.actions,[])
        self.assertFalse(ui.draw_styled_two_line_button.call_args.kwargs['enabled'])

    def test_pressed_button_uses_theme_pressed_state(self):
        w=self.fixture.workspace;w.ui.ui_button_pressed.return_value=True
        w.button(Mock(),(0,0,200,64),'Scan',('start',None))
        self.assertEqual(w.ui.draw_logical_rounded_rect.call_args.args[5],APP_UI_STYLE.palette.pressed_surface)
