"""Blocking surfaces share a backdrop without dimming live overlays."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import kiwi_gl_display as ui

class ModalBackdropTests(unittest.TestCase):
    def test_backdrop_covers_full_screen_with_theme_color(self):
        with patch.object(ui,'draw_logical_rect') as draw:
            ui.draw_modal_backdrop()
        draw.assert_called_once_with(0,0,ui.LOGICAL_W,ui.LOGICAL_H,ui.APP_UI_STYLE.palette.modal_backdrop)

    def test_band_backdrop_precedes_popup_content(self):
        events=[]
        with patch.object(ui,'draw_modal_backdrop',side_effect=lambda:events.append('dim')), \
             patch.object(ui,'draw_logical_rect',side_effect=lambda *a:events.append('panel')), \
             patch.object(ui,'draw_logical_line'),patch.object(ui,'draw_text'), \
             patch.object(ui,'draw_styled_text_button'),patch.object(ui,'draw_styled_two_line_button'):
            ui.draw_band_navigation(Mock(),7075,'AM')
        self.assertEqual(events[:2],['dim','panel'])

    def test_modal_pass_follows_base_navigation_and_precedes_compositor(self):
        source=Path(ui.__file__).read_text()
        render=source[source.index('            # draw_ui painted Zoom first.'):]
        self.assertLess(render.index('draw_desktop_1280_navigation('),render.index('draw_band_navigation('))
        self.assertLess(render.index('draw_band_navigation('),render.index('if rail_relocation_active():'))

    def test_live_notices_and_drawers_do_not_add_modal_backdrop(self):
        tree=ast.parse(Path(ui.__file__).read_text())
        names={'draw_volume_osd','draw_frequency_drawer','draw_zoom_osd','draw_audio_transport_graph','draw_cpu_utilization_graph'}
        for node in tree.body:
            if isinstance(node,ast.FunctionDef) and node.name in names:
                calls=[n.func.id for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
                self.assertNotIn('draw_modal_backdrop',calls,node.name)

if __name__=='__main__':unittest.main()
