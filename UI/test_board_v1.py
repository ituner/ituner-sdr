"""CM5 1280x800 regression coverage for board_v1."""
import unittest
from unittest.mock import patch
import kiwi_gl_display as ui

class BoardLayoutTests(unittest.TestCase):
    def test_settings_and_digital_back_have_same_target(self):
        for items in (ui.SETTINGS_MENU_ITEMS, ui.DIGITAL_MENU_ITEMS):
            self.assertEqual(ui.lcd_nav_box(len(items)-1, len(items)), ui.lcd_drawer_back_box())
            boxes = [ui.lcd_nav_box(i, len(items)) for i in range(len(items))]
            for i,a in enumerate(boxes):
                for b in boxes[i+1:]:
                    self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3])

    def test_home_controls_fit_before_navigation(self):
        for compact in (True, False):
            self.assertLess(ui.lcd_home_volume_box(compact)[3], ui.lcd_nav_top())

    def test_fmdx_waterfall_retains_carrier_above_30mhz(self):
        self.assertEqual(ui.receiver_waterfall_center(101700,20,'fmdx'),101700)
        self.assertLess(ui.receiver_waterfall_center(29999,20,'kiwi'),29999)

    def test_kiwi_palette_is_default(self):
        self.assertEqual(ui.WATERFALL_DEFAULT_PALETTE,'kiwi')

    def test_mode_hit_selects_before_drawer(self):
        for compact in (True,False):
            for label, box in ui.lcd_home_mode_boxes(compact):
                expected = 'NBFM' if label=='NFM' else label
                state=ui.SharedState('http://kiwi.test',7075,8,-95,-125,-15,3,'lsb',True)
                selected=ui.engage_home_mode(state,(box[0]+box[2])/2,(box[1]+box[3])/2,compact)
                self.assertEqual(selected,expected)
                self.assertEqual(state.radio_snapshot()[0].upper(),expected)


class ReceiverHandoffTests(unittest.TestCase):
    def state(self):
        return ui.SharedState('http://kiwi.test',7075,8,-95,142,245,3,'lsb',True)

    def test_landing_chooses_strong_peak_and_preserves_mode(self):
        state=self.state()
        state.set_server('http://new-kiwi.test',receiver_type='kiwi')
        self.assertTrue(state.kiwi_landing_snapshot()['active'])
        samples=[0.05]*128
        samples[64]=0.9
        result=ui.resolve_kiwi_landing_scan(state,samples,0.5)
        self.assertEqual(result[0],'tuned')
        self.assertTrue(7000 <= result[1] <= 7300)
        self.assertEqual(state.radio_snapshot()[0].upper(),'LSB')
        self.assertFalse(state.kiwi_landing_snapshot()['active'])

    def test_noise_timeout_leaves_useful_band_frequency(self):
        state=self.state();state.set_server('http://new-kiwi.test')
        self.assertIsNone(ui.resolve_kiwi_landing_scan(state,[0.05]*128,1))
        self.assertEqual(ui.resolve_kiwi_landing_scan(state,[0.05]*128,2.1),('no_signal',7150))

    def test_manual_tune_cancels_landing(self):
        state=self.state();state.set_server('http://new-kiwi.test')
        state.set_view(freq_khz=7100)
        self.assertIsNone(ui.resolve_kiwi_landing_scan(state,[0,0,1,0,0],3))
        self.assertEqual(state.snapshot()[1],7100)

    def test_late_landing_cannot_change_replacement_receiver(self):
        state=self.state();state.set_server('http://first.test')
        generation=state.snapshot()[-1]
        state.set_server('http://second.test')
        self.assertIsNone(state.finish_kiwi_landing(generation,7001))
        self.assertEqual(state.snapshot()[1],7150)

    def test_fmdx_scan_manual_tune_and_receiver_change_win(self):
        state=self.state();state.set_server('http://fm.test',receiver_type='fmdx')
        generation=state.snapshot()[-1]
        state.request_fmdx_scan(True,generation)
        scan_view=state.scan_tune(generation,state.snapshot()[4],99500)
        self.assertIsNotNone(scan_view)
        state.set_view(freq_khz=101700)
        self.assertIsNone(state.scan_tune(generation,scan_view,99600))
        self.assertEqual(state.snapshot()[1],101700)
        self.assertFalse(state.fmdx_scan_request_snapshot()[0])
        state.set_server('http://new-kiwi.test')
        self.assertIsNone(state.scan_tune(generation,state.snapshot()[4],99500,finished=True))
        self.assertEqual(state.snapshot()[1],7150)

    def test_scan_stop_restores_origin(self):
        state=self.state();state.set_server('http://fm.test',receiver_type='fmdx')
        generation=state.snapshot()[-1]
        state.request_fmdx_scan(True,generation)
        view=state.scan_tune(generation,state.snapshot()[4],99500)
        state.request_fmdx_scan(False,generation)
        self.assertIsNotNone(state.scan_tune(generation,view,101700,finished=True))
        self.assertEqual(state.snapshot()[1],101700)

class WaterfallPresentationTests(unittest.TestCase):
    def test_fm_rows_reach_visible_texture_strip(self):
        # Exercise the real renderer: HF-clamping this view makes all rows
        # fall outside the viewport and yields no textured strips.
        texture=object.__new__(ui.WaterfallTexture)
        texture.tex=1;texture.row=0
        texture.row_center_khz=[101700]*ui.WF_TEX_H
        texture.row_span_khz=[20]*ui.WF_TEX_H
        with patch.object(ui,'GL') as draw:
            texture._draw_frequency_aligned(0,0,1024,100,
                ui.receiver_waterfall_center(101700,20,'fmdx'),20)
        self.assertGreater(draw.glVertex2f.call_count,0)

    def test_settings_and_drawers_do_not_draw_home_frequency(self):
        from contextlib import ExitStack
        # Test the compositor call site, not just the visibility predicate.
        for kwargs in ({'settings_menu_open':True},{'digital_menu_open':True},{'sidebar_open':True}):
            with ExitStack() as stack:
                mocks={}
                for name in ('draw_logical_rect','draw_ruler','draw_lower_status',
                    'draw_waterfall_operating_controls','draw_connection_annunciator',
                    'draw_squelch_closed_annunciator','draw_lcd_navigation','draw_lcd_mode_annunciators'):
                    mocks[name]=stack.enter_context(patch.object(ui,name))
                stack.enter_context(patch.object(ui,'top_instrument_layout',return_value=('7.075.000',(0,0,1,1))))
                ui.draw_ui(None,7075,20,-95,-95,None,'LSB','DIG',100,instrument_layout='compact',**kwargs)
                mocks['draw_lcd_mode_annunciators'].assert_not_called()

    def test_settings_back_uses_shared_renderer(self):
        with patch.object(ui,'draw_logical_rect'), patch.object(ui,'draw_logical_line'), \
             patch.object(ui,'lcd_nav_tile_background',return_value=(1,1,1)), \
             patch.object(ui,'menu_icon_texture',return_value=(1,1,1)), \
             patch.object(ui,'draw_textured_quad'), patch.object(ui,'draw_radio_close_button') as back:
            ui.draw_lcd_navigation(None,settings_open=True)
        back.assert_called_once_with(None,ui.lcd_drawer_back_box())

class NavigationAndLandingBoundaryTests(unittest.TestCase):
    def test_all_primary_back_targets_match_after_configuration(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        expected = ui.lcd_drawer_back_box()
        for box in (ui.TEST_BACK_BOX, ui.PICKER_EXIT_BOX, ui.RADIOGARDEN_EXIT_BOX,
                    ui.RTL_LAB_BACK_BOX, ui.FONT_LAB_BACK_BOX, ui.WSPR_EXPANDED_LOG_BACK_BOX,
                    ui.network_panel_boxes()["back"]):
            self.assertEqual(box, expected)
        for count in (2, 7, 8):
            for index in range(count - 1):
                self.assertLess(ui.lcd_nav_box(index, count)[3], expected[1])

    def test_audio_alone_does_not_start_landing_timeout(self):
        state = ui.SharedState('http://kiwi.test', 7075, 8, -95, 142, 245, 3, 'lsb', True)
        state.set_server('http://next.test')
        generation = state.snapshot()[-1]
        state.connection_ready(generation, 'audio')
        self.assertFalse(state.kiwi_landing_ready())
        state.connection_ready(generation, 'waterfall')
        self.assertTrue(state.kiwi_landing_ready())
        state.set_radio_mode('AM')
        self.assertFalse(state.kiwi_landing_ready())

if __name__ == '__main__':
    unittest.main()

