"""CM5-approved menu typography and live occupancy footer regression tests."""
import unittest
from unittest.mock import Mock, patch
import kiwi_gl_display as ui


class MenuStatusTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        self.fonts = ui.TextCache()

    def test_navigation_labels_fit_without_horizontal_scaling(self):
        cache=Mock()
        cache.font=self.fonts.font
        for kind,title in ui.MENU_ITEMS + ui.SETTINGS_MENU_ITEMS:
            subtitle=ui.menu_subtitle(kind)
            if not subtitle:
                continue
            with patch.object(ui,'draw_styled_button_frame',return_value=ui.APP_UI_STYLE.button.resolve()), \
                 patch.object(ui,'draw_text') as text, patch.object(ui,'draw_text_scaled_x') as stretched:
                ui.draw_navigation_button(cache,(0,0,114,64),title,subtitle)
            stretched.assert_not_called()
            self.assertEqual(len(text.call_args_list),2)
            for call,maximum in zip(text.call_args_list,(14,12)):
                caption,size=call.args[3],call.args[5]
                self.assertLessEqual(size,maximum)
                self.assertLessEqual(cache.font(size,bold=True,family=ui.APP_UI_STYLE.button.font_family).size(caption)[0],108)

    def test_decoder_subtitle_tracks_available_modes(self):
        count=sum(kind!='digital_back' for kind,_ in ui.DIGITAL_MENU_ITEMS)
        self.assertEqual(ui.menu_subtitle('digital'),f'{count} MODES')
        with patch.object(ui,'DIGITAL_MENU_ITEMS',ui.DIGITAL_MENU_ITEMS+(('new_mode','NEW'),)):
            self.assertEqual(ui.menu_subtitle('digital'),f'{count+1} MODES')

    def test_footer_shows_valid_occupancy_and_reserves_space_for_it(self):
        cache=Mock()
        cache.font=self.fonts.font
        cache.texture=lambda text,size,color,*a,**kw: (0,*self.fonts.font(size,bold=kw.get('bold',False),family=kw.get('family','Liberation Sans')).size(text))
        for capacity,expected in (((0,8),'0/8 USERS'),((3,8),'3/8 USERS'),((8,8),'8/8 USERS'),(None,None),((9,8),None)):
            with self.subTest(capacity=capacity), patch.object(ui,'draw_logical_rect'), \
                 patch.object(ui,'read_process_ram_mb',return_value=100), patch.object(ui,'draw_text') as text:
                ui.draw_lower_status(cache,15,50,712,800,station_name='A long receiver name '*15,station_capacity=capacity)
            labels=[call for call in text.call_args_list if str(call.args[3]).endswith(' USERS')]
            self.assertEqual([c.args[3] for c in labels],[expected] if expected else [])
            if labels:
                call=labels[0]
                width=cache.font(call.args[5],bold=True,family='Liberation Sans').size(expected)[0]
                self.assertLess(call.args[1]+width,800)

if __name__=='__main__':unittest.main()
