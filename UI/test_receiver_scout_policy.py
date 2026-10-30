"""Constellation must not offer or create speculative receiver streams."""
import inspect
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch
import kiwi_gl_display as ui


class ReceiverScoutPolicyTests(unittest.TestCase):
    def test_scouting_workers_and_scheduler_are_removed(self):
        for name in ('ConstellationScoutProbe', 'GlobeAudioMixer'):
            self.assertFalse(hasattr(ui, name), name)
        source = inspect.getsource(ui.main)
        for retired in ('globe_scout', 'globe_mixer', 'next_scout_rotation', 'choose_constellation'):
            self.assertNotIn(retired, source)

    def test_apps_tiles_render_and_select_without_constellation(self):
        original_mode = ui.DESKTOP_MODE
        try:
            for desktop in (False, True):
                with self.subTest(desktop=desktop):
                    ui.configure_output(desktop)
                    ui.configure_popup_layout()
                    with ExitStack() as stack:
                        renderers = {name: stack.enter_context(patch.object(ui, name)) for name in (
                            'draw_settings_leaf_sidebar', 'draw_lcd_audio_tile',
                            'draw_tests_button', 'draw_logical_rect',
                            'draw_section_divider', 'draw_text')}
                        ui.draw_tests_panel(Mock(), 0, None)
                    calls = renderers['draw_lcd_audio_tile' if ui.LCD_800_MODE else 'draw_tests_button'].call_args_list
                    self.assertEqual(len(calls), 7)
                    self.assertEqual({ui.tests_option_at((c.args[1][0]+c.args[1][2])/2,
                                                        (c.args[1][1]+c.args[1][3])/2)
                                      for c in calls},
                                     {'dj', 'rtl', 'pattern', 'font_lab', 'openwebrx', 'run', 'audio_test'})
                    self.assertNotIn('CONSTELLATION', repr(calls).upper())
                    self.assertNotIn('SNR MAP', repr(calls).upper())
        finally:
            ui.configure_output(original_mode)
            ui.configure_popup_layout()

    def test_transmitted_identity_ignores_legacy_name(self):
        ws = Mock()
        ui.kiwi.send_kiwi_setup(ws, 'kiwi', 'KiwiTouch')
        ws.send_text.assert_any_call('SET ident_user=ituner')


if __name__ == '__main__':
    unittest.main()
