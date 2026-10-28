import unittest
from unittest.mock import Mock, patch
from main_volume_control import MainVolumeControl
import kiwi_gl_display as ui


class MainVolumeTests(unittest.TestCase):
    def test_mute_unmute_restores_exact_level_repeatedly(self):
        setter = Mock(side_effect=lambda value: value)
        muted = Mock()
        control = MainVolumeControl(.73, setter, muted)
        for _ in range(3):
            control.mute(True)
            self.assertEqual(control.volume, .73)
            self.assertEqual(control.mute(False), .73)
        self.assertEqual(setter.call_count, 3)
        self.assertEqual(muted.call_args.args, (False,))

    def test_zero_volume_unmute_restores_previous_audible_level(self):
        control = MainVolumeControl(.73, lambda v: v, Mock())
        control.apply(0)
        self.assertEqual(control.mute(False), .73)

    def test_new_slider_level_becomes_restore_level(self):
        control = MainVolumeControl(.73, lambda v: v, Mock())
        control.mute(True)
        control.apply(.42)
        control.mute(True)
        self.assertEqual(control.mute(False), .42)

    def test_failed_restore_does_not_unmute(self):
        muted = Mock()
        control = MainVolumeControl(.73, lambda v: None, muted)
        control.mute(True)
        self.assertIsNone(control.mute(False))
        self.assertEqual(muted.call_args.args, (True,))

    def test_mute_popup_centered_clear_of_home_icons(self):
        box = ui.mute_waterfall_box()
        self.assertEqual(box, ui.ZOOM_OSD_BOX)
        for icon in (ui.favorite_waterfall_box(), ui.stream_waterfall_box()):
            self.assertTrue(box[2] <= icon[0] or box[0] >= icon[2] or
                            box[3] <= icon[1] or box[1] >= icon[3])

    def test_speaker_edge_cannot_set_slider_to_zero(self):
        ui.configure_output(True)
        for compact in (True, False):
            mute = ui.lcd_home_volume_mute_box(compact)
            track = ui.lcd_home_volume_track_box(compact)
            # A finger just outside the drawn speaker formerly hit the entire
            # volume panel and clamped its level to zero.
            self.assertEqual(ui.home_volume_action_at(
                mute[0] - 2, (mute[1] + mute[3])/2, compact), 'home_volume_mute')
            self.assertEqual(ui.home_volume_action_at(
                track[0], (track[1] + track[3])/2, compact), 'home_volume')
            self.assertEqual(ui.home_volume_at_x(track[0], compact), 0)

    def test_notice_center_accounts_for_left_rail_composition(self):
        for side in ('left', 'right'):
            with patch.dict(ui.theme_system.runtime_theme, sidebar=side):
                box = ui.mute_waterfall_box()
                self.assertEqual(box, ui.ZOOM_OSD_BOX)

    def test_mute_uses_zoom_typography_and_persistent_red_panel(self):
        with patch.object(ui, 'draw_analog_osd_panel') as panel, patch.object(ui, 'draw_text') as text:
            ui.draw_muted_waterfall_badge(None)
        red = ui.themed_instrument_color('danger_border', ui.MUTE_ACCENT)[:3]
        panel.assert_called_once_with(ui.ZOOM_OSD_BOX, 246, red, (8, 0, 0))
        self.assertEqual([c.args[3] for c in text.call_args_list], ['AUDIO MUTED', 'TAP TO UNMUTE'])
        for call in text.call_args_list:
            self.assertEqual(call.args[4:9], (red, 28, True, True, 'lm'))
