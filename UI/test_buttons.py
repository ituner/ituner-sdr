import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from cm5_button_input import PressFilter, ButtonReader


class DebounceTests(unittest.TestCase):
    def test_measured_volume_push_and_existing_mute_button_share_action(self):
        self.assertEqual(ButtonReader.LINES[8], 'mute')
        self.assertEqual(ButtonReader.LINES[11], 'mute')
        self.assertNotIn(10, ButtonReader.LINES)

    def test_bounce_hold_and_release(self):
        f = PressFilter()
        events = [(True, 1), (False, 1.01), (True, 1.02),
                  (True, 1.07), (True, 2), (True, 10),
                  (False, 11), (True, 11.01), (False, 11.02),
                  (False, 11.07), (True, 12), (True, 12.05)]
        self.assertEqual([t for level, t in events if f.feed(level, t)], [1.07, 12.05])

    def test_boot_held_requires_release(self):
        f = PressFilter(pressed=True)
        self.assertFalse(f.feed(True, 1))
        self.assertFalse(f.feed(False, 2))
        self.assertFalse(f.feed(False, 2.05))
        self.assertFalse(f.feed(True, 3))
        self.assertTrue(f.feed(True, 3.05))

    def test_short_glitch_ignored(self):
        f = PressFilter()
        self.assertFalse(f.feed(True, 1))
        self.assertFalse(f.feed(False, 1.02))
        self.assertFalse(f.feed(False, 2))


class DispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Execute the actual nested UI handler with controlled UI dependencies.
        tree = ast.parse(Path(__file__).with_name('kiwi_gl_display.py').read_text())
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                       and n.name == 'apply_v4_button')
        handler.body = [ast.Global(names=n.names) if isinstance(n, ast.Nonlocal)
                        else n for n in handler.body]
        cls.code = compile(ast.fix_missing_locations(ast.Module(body=[handler], type_ignores=[])),
                           'button-dispatch', 'exec')

    def setUp(self):
        self.state = Mock()
        self.state.audio_controls_snapshot.return_value = ({'mute': False}, 0)
        self.state.smart_seek_snapshot.return_value = {'open': False}
        self.state.start_smart_seek.return_value = True
        self.env = dict(themed_instrument_color=lambda *a:(255,85,85), MUTE_ACCENT=(255,85,85), state=self.state, print=Mock(), seek_view=Mock(),
                        set_main_mute=Mock(return_value=.73), wake_controls=Mock(),
                        time=SimpleNamespace(monotonic=lambda:10),
                        args=SimpleNamespace(zoom_osd_seconds=2), audio_volume=.73,
                        shared_keyboard_open=Mock(return_value=False),
                        web_apps=SimpleNamespace(blocks_touch=False,publish_encoder_notice=Mock()),
                        activate_navigation_item=Mock(), focus_receiver_map_on_active=Mock(),
                        MENU_ITEMS=(('rx', 'RECEIVERS'), ('display', 'DISPLAY')),
                        GLOBE_DEFAULT_VIEW='globe', globe_fetch_started=True)
        for name in ('radio_setup_open', 'band_navigation_open', 'display_setup_open',
                     'picker_open', 'picker_map_open', 'frequency_entry_open',
                     'network_panel_open', 'cpu_utilization_graph_open', 'fmdx_disclaimer_open'):
            self.env[name] = False
        exec(self.code, self.env)
        self.press = self.env['apply_v4_button']

    def test_mute_uses_shared_audio_action_even_in_keyboard(self):
        self.env['shared_keyboard_open'].return_value = True
        self.press('mute')
        self.env['set_main_mute'].assert_called_once_with(True)
        self.assertTrue(self.env['preferences_dirty'])
        self.assertEqual(self.env['volume_osd_title'],'MUTE')
        self.assertEqual(self.env['volume_osd_until'],0)
        self.env['web_apps'].publish_encoder_notice.assert_called_once_with('MUTE','Audio muted',2, colors=dict(background='#080000',border='#ff5555',title='#ff5555',detail='#ff5555'))

    def test_second_press_unmutes_with_feedback_even_over_browser(self):
        self.state.audio_controls_snapshot.return_value=({'mute':True},0)
        self.env['web_apps'].blocks_touch=True
        self.press('mute')
        self.env['set_main_mute'].assert_called_once_with(False)
        self.assertEqual(self.env['volume_osd_title'],'UNMUTE')
        self.env['web_apps'].publish_encoder_notice.assert_called_once_with('UNMUTE','Volume 73%',2,colors=None)

    def test_failed_unmute_does_not_report_success(self):
        self.env['set_main_mute'].return_value=None
        self.press('mute')
        self.env['web_apps'].publish_encoder_notice.assert_not_called()

    def test_ptt_unassigned(self):
        self.press('ptt')
        self.env['activate_navigation_item'].assert_not_called()
        self.env['set_main_mute'].assert_not_called()
        self.state.start_smart_seek.assert_not_called()

    def test_mode_and_band_toggle(self):
        self.press('mode')
        self.env['activate_navigation_item'].assert_called_with(0, (('physical_mode', 'MODE'),))
        self.press('band')
        self.assertTrue(self.env['band_navigation_open'])
        self.press('band')
        self.assertFalse(self.env['band_navigation_open'])
        self.env['activate_navigation_item'].assert_called_with(0, (('physical_home', 'HOME'),))

    def test_map_uses_existing_picker_and_focus(self):
        self.press('map')
        self.env['activate_navigation_item'].assert_called_once_with(0)
        self.env['focus_receiver_map_on_active'].assert_called_once()
        self.assertTrue(self.env['picker_map_open'])

    def test_display_uses_existing_destination(self):
        self.press('display')
        self.env['activate_navigation_item'].assert_called_once_with(1)

    def test_scan_starts_and_cancels(self):
        self.press('scan')
        self.state.start_smart_seek.assert_called_once()
        self.state.smart_seek_snapshot.return_value = {'open': True}
        self.press('scan')
        self.env['seek_view'].close.assert_called_once()

    def test_modal_does_not_discard_text(self):
        self.env['shared_keyboard_open'].return_value = True
        for role in ('mode', 'band', 'display', 'map', 'scan'):
            self.press(role)
        self.env['activate_navigation_item'].assert_not_called()
        self.state.start_smart_seek.assert_not_called()


if __name__ == '__main__':
    unittest.main()
