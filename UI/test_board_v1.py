"""CM5 1280x800 regression coverage for board_v1."""
import math
import time
import unittest
from unittest.mock import Mock, call, patch
import kiwi_gl_display as ui


class AudioJitterBufferTests(unittest.TestCase):
    def test_waterfall_close_waits_for_paired_audio_access_refusal(self):
        state = ui.SharedState(
            'http://example.test:8073', 7075.0, 4, -95.0,
            142, 245, 3, 'am', True,
        )
        generation = state.snapshot()[5]

        class RefusalDuringGrace:
            def wait(self, _seconds):
                state.connection_access_denied(generation)
                return False

        self.assertTrue(ui.paired_stream_access_denied_after_close(
            state, generation, RefusalDuringGrace(),
        ))
        self.assertEqual(state.connection_snapshot(), 'access_blocked')

    def test_access_policy_failure_does_not_enter_reconnect_loop(self):
        state = ui.SharedState(
            'http://example.test:8073', 7075.0, 4, -95.0,
            142, 245, 3, 'am', True,
        )
        generation = state.snapshot()[5]

        self.assertTrue(state.connection_access_denied(generation))
        self.assertEqual(state.connection_snapshot(), 'access_blocked')
        self.assertTrue(state.connection_failed(generation, 'waterfall'))
        self.assertEqual(state.connection_snapshot(), 'access_blocked')
        self.assertIsNone(state.connection_retry_snapshot())

    def test_reserve_duration_is_preserved_at_fmdx_sample_rate(self):
        kiwi_target, kiwi_max = ui.audio_jitter_packet_limits(12_000)
        fmdx_target, fmdx_max = ui.audio_jitter_packet_limits(48_000)

        self.assertEqual((kiwi_target, kiwi_max), (6, 24))
        self.assertEqual((fmdx_target, fmdx_max), (24, 96))
        self.assertAlmostEqual(kiwi_target * 512 / 12_000, fmdx_target * 512 / 48_000)
        self.assertAlmostEqual(kiwi_max * 512 / 12_000, fmdx_max * 512 / 48_000)

    @staticmethod
    def player_stub():
        player = ui.BufferedAudioPlayer.__new__(ui.BufferedAudioPlayer)
        player.condition = ui.threading.Condition()
        player.state = None
        player.packets = ui.deque()
        player.last_submit_at = 1.0
        player.stable_since = 1.0
        player.last_reserve_change_at = 0.0
        player.target_packets = 6
        player.max_packets = 24
        player.rebuffering = False
        player.transport_reconnecting = False
        return player

    def test_socket_reconnect_rebuffers_without_learning_false_jitter(self):
        player = self.player_stub()

        player.suspend_for_reconnect()
        reserve_grew = player._begin_output_gap_locked()

        self.assertTrue(player.transport_reconnecting)
        self.assertTrue(player.rebuffering)
        self.assertFalse(reserve_grew)
        self.assertEqual(player.target_packets, 6)

    def test_live_stream_underflow_still_grows_the_reserve(self):
        player = self.player_stub()

        reserve_grew = player._begin_output_gap_locked()

        self.assertTrue(reserve_grew)
        self.assertEqual(player.target_packets, 7)

class BoardLayoutTests(unittest.TestCase):
    def test_only_horizontal_smeters_share_the_top_frequency_strip(self):
        self.assertTrue(ui.smeter_supports_top_instrument_strip('led'))
        self.assertTrue(ui.smeter_supports_top_instrument_strip('linear_orange'))
        self.assertFalse(ui.smeter_supports_top_instrument_strip('bakelite_square'))
        self.assertFalse(ui.smeter_supports_top_instrument_strip('aviation'))
        self.assertFalse(ui.smeter_supports_top_instrument_strip('oe3ide_eye_plain'))

    def test_meterless_middle_frequency_is_forced_to_the_1280_screen_center(self):
        ui.configure_output(True)
        text_cache = Mock()
        text_cache.font.return_value.size.return_value = (300, 58)
        with patch.dict(ui.theme_system.runtime_theme, {'smeter_style': 'bakelite_square'}):
            self.assertEqual(ui.large_frequency_placement('middle'), (640, 'cm'))
            box = ui.frequency_display_box(text_cache, 7075, position='middle')
            self.assertEqual((box[0] + box[2]) / 2, 640)
        with patch.dict(ui.theme_system.runtime_theme, {'smeter_style': 'linear_orange'}):
            self.assertEqual(ui.large_frequency_placement('middle')[1], 'rm')

    def test_saving_large_meter_moves_frequency_to_visible_right_rail(self):
        ui.configure_output(True)
        with patch.dict(ui.theme_system.runtime_theme, {'sidebar': 'right'}):
            self.assertEqual(
                ui.instrument_layout_after_theme_save('left', 'bakelite_square'),
                'right',
            )
            self.assertEqual(
                ui.instrument_layout_after_theme_save('middle', 'aviation'),
                'right',
            )
            self.assertEqual(
                ui.instrument_layout_after_theme_save('left', 'linear_orange'),
                'left',
            )
        with patch.dict(ui.theme_system.runtime_theme, {'sidebar': 'left'}):
            self.assertEqual(
                ui.instrument_layout_after_theme_save('middle', 'bakelite_square'),
                'left',
            )

    def test_old_frequency_positions_keep_their_screen_locations(self):
        self.assertEqual(ui.normalize_frequency_position('compact'), 'right')
        self.assertEqual(ui.normalize_frequency_position('expanded'), 'middle')
        self.assertEqual(ui.normalize_frequency_position('left'), 'left')
        self.assertEqual(ui.normalize_frequency_position('unknown'), 'right')

    def test_left_frequency_is_drawn_and_tappable_at_top_left(self):
        from contextlib import ExitStack
        ui.configure_output(True)
        text_cache = Mock()
        text_cache.font.return_value.size.return_value = (300, 58)
        left_box = ui.frequency_display_box(text_cache, 7075, position='left')
        self.assertEqual(left_box, (ui.LEFT_FREQUENCY_X - 8, 4,
                                    ui.LEFT_FREQUENCY_X + 308, 70))
        self.assertEqual(ui.frequency_display_box(text_cache, 7075, position='right'),
                         ui.compact_frequency_touch_box())
        self.assertTrue(ui.is_frequency_readout_touch(left_box[0] + 4, 39, left_box))
        meter_box = ui.left_smeter_box(text_cache, 7075)
        self.assertEqual(meter_box, (334, 0, 756, 80))
        self.assertEqual(ui.main_band_context_box(text_cache, 7075, position='left'),
                         (meter_box[2] + 8, 24, meter_box[2] + 184, 53))
        self.assertFalse(ui.is_waterfall_tune_touch(400, 50, 'left', meter_box))
        self.assertTrue(ui.is_waterfall_tune_touch(100, 140, 'left', meter_box))
        self.assertTrue(ui.is_waterfall_tune_touch(100, 140, 'middle'))
        with ExitStack() as stack:
            for name in ('draw_logical_rect',
                         'draw_ruler', 'draw_lower_status', 'draw_waterfall_operating_controls',
                         'draw_connection_annunciator', 'draw_squelch_closed_annunciator',
                         'draw_lcd_navigation'):
                stack.enter_context(patch.object(ui, name))
            stack.enter_context(patch.object(ui, 'top_instrument_layout',
                                            return_value=('7.075.000', (0, 0, 1, 1))))
            draw_frequency = stack.enter_context(patch.object(ui, 'draw_big_frequency'))
            draw_context = stack.enter_context(patch.object(ui, 'draw_band_context_chip'))
            draw_meter = stack.enter_context(patch.object(ui, 'draw_lcd_compact_smeter'))
            draw_analog_meter = stack.enter_context(patch.object(ui, 'draw_smeter'))
            ui.draw_ui(text_cache, 7075, 20, -95, -95, None, 'LSB', 'DIG', 100,
                       instrument_layout='left', sidebar_open=True)
        self.assertEqual(draw_frequency.call_args.args[2], ui.LEFT_FREQUENCY_X)
        self.assertEqual(draw_frequency.call_args.args[4], 330.0)
        self.assertEqual(draw_frequency.call_args.kwargs['family'], ui.COMPACT_FREQUENCY_FONT_FAMILY)
        self.assertNotIn('fit_text', draw_frequency.call_args.kwargs)
        self.assertEqual(draw_frequency.call_args.kwargs['anchor'], 'lm')
        self.assertEqual(draw_context.call_args.kwargs['compact'], True)
        draw_meter.assert_not_called()
        draw_analog_meter.assert_called_once_with(
            text_cache, -95, False, -95, meter_x0=439,
        )

    def test_left_meter_stays_beside_frequency_for_different_font_widths(self):
        ui.configure_output(True)
        text_cache = Mock()
        for font_width in (127, 187, 400):
            text_cache.font.return_value.size.return_value = (font_width, 36)
            frequency_box = ui.frequency_display_box(text_cache, 7075, position='left')
            meter_box = ui.left_smeter_box(text_cache, 7075)
            self.assertLess(frequency_box[2], meter_box[0])
            self.assertLess(meter_box[2], ui.rf_canvas_width())

    def test_top_frequency_uses_right_rail_font_and_size(self):
        from contextlib import ExitStack
        ui.configure_output(True)
        text_cache = Mock()
        text_cache.font.return_value.size.return_value = (187, 36)
        with ExitStack() as stack:
            for name in ('draw_logical_rect', 'draw_ruler', 'draw_lower_status',
                         'draw_waterfall_operating_controls', 'draw_connection_annunciator',
                         'draw_squelch_closed_annunciator', 'draw_lcd_navigation',
                         'draw_band_context_chip', 'draw_smeter'):
                stack.enter_context(patch.object(ui, name))
            stack.enter_context(patch.object(ui, 'top_instrument_layout',
                                            return_value=('7.075.000', (0, 0, 1, 1))))
            draw_frequency = stack.enter_context(patch.object(ui, 'draw_big_frequency'))
            for position in ('left', 'middle'):
                ui.draw_ui(text_cache, 7075, 20, -95, -95, None, 'LSB', 'DIG', 100,
                           instrument_layout=position, sidebar_open=True)
            top_calls = draw_frequency.call_args_list
            draw_frequency.reset_mock()
            stack.enter_context(patch.object(ui, 'lcd_home_mode_boxes', return_value=()))
            stack.enter_context(patch.object(ui, 'draw_lcd_compact_smeter'))
            ui.draw_lcd_mode_annunciators(
                text_cache, 'LSB', 'DIG', 7075, -95,
                compact_frequency_font_family=ui.COMPACT_FREQUENCY_FONT_FAMILY,
            )
            right_call = draw_frequency.call_args

        self.assertEqual(len(top_calls), 2)
        self.assertEqual([entry.args[4] for entry in top_calls], [330.0, 330.0])
        for entry in (*top_calls, right_call):
            self.assertEqual(entry.kwargs['family'], ui.COMPACT_FREQUENCY_FONT_FAMILY)
        for entry in top_calls:
            self.assertNotIn('fit_text', entry.kwargs)
        self.assertEqual(right_call.kwargs['fit_text'], '30.000.000')
        self.assertEqual(right_call.args[4], 236)
        self.assertEqual(right_call.kwargs['size'], ui.COMPACT_FREQUENCY_SIZE)

    def test_top_instrument_band_follows_frequency_position(self):
        from contextlib import ExitStack
        ui.configure_output(True)
        text_cache = Mock()
        text_cache.font.return_value.size.return_value = (187, 36)
        with ExitStack() as stack:
            rectangles = stack.enter_context(patch.object(ui, 'draw_logical_rect'))
            for name in ('draw_ruler', 'draw_lower_status',
                         'draw_waterfall_operating_controls', 'draw_connection_annunciator',
                         'draw_squelch_closed_annunciator', 'draw_lcd_navigation',
                         'draw_band_context_chip', 'draw_smeter', 'draw_big_frequency'):
                stack.enter_context(patch.object(ui, name))
            stack.enter_context(patch.object(ui, 'top_instrument_layout',
                                            return_value=('7.075.000', (0, 0, 1, 1))))
            for position, height in (
                ('right', None),
                ('middle', ui.LCD_TOP_INSTRUMENT_BAND_H),
                ('left', ui.LCD_TOP_INSTRUMENT_BAND_H),
            ):
                rectangles.reset_mock()
                ui.draw_ui(text_cache, 7075, 20, -95, -95, None, 'LSB', 'DIG', 100,
                           instrument_layout=position, sidebar_open=True)
                expected = [] if height is None else [
                    call(0, 0, ui.rf_canvas_width(), height, (0, 0, 0, 144))
                ]
                self.assertEqual(rectangles.call_args_list, expected)

        self.assertEqual(ui.LCD_TOP_INSTRUMENT_BAND_H, 88)
        self.assertEqual(ui.LCD_LEFT_INSTRUMENT_BAND_H, ui.LCD_TOP_INSTRUMENT_BAND_H)
        self.assertEqual(ui.LCD_TOP_INSTRUMENT_CENTER_Y, 39)
        with patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_text') as labels:
            ui.draw_smeter(text_cache, -95, False, meter_x0=320)
        top_label = next(entry for entry in labels.call_args_list if entry.args[3] == 'S')
        bottom_label = next(entry for entry in labels.call_args_list if entry.args[3] == '-121')
        self.assertGreaterEqual(top_label.args[2] - top_label.args[5] / 2, 8)
        self.assertGreaterEqual(
            ui.LCD_TOP_INSTRUMENT_BAND_H - bottom_label.args[2] - bottom_label.args[5] / 2,
            8,
        )
        context_box = ui.main_band_context_box(text_cache, 7075, position='left')
        context_center = (context_box[1] + context_box[3]) / 2 + 0.5
        self.assertEqual(context_center, ui.LCD_TOP_INSTRUMENT_CENTER_Y)

    def test_smeter_lower_labels_align_with_major_ruler_bars(self):
        ui.configure_output(True)
        expected_dbm = (-121, -109, -97, -85, -73, -53, -33)
        for meter_x0 in (320, 675):
            with patch.object(ui, 'draw_logical_line') as lines, \
                 patch.object(ui, 'draw_logical_circle'), \
                 patch.object(ui, 'draw_text') as labels:
                ui.draw_smeter(Mock(), -95, False, meter_x0=meter_x0)
            major_xs = {
                entry.args[0] for entry in lines.call_args_list
                if entry.args[1] == 26
                and entry.args[2] == entry.args[0]
                and entry.args[3] == 52
            }
            lower_labels = {
                int(entry.args[3]): entry.args[1]
                for entry in labels.call_args_list
                if entry.args[3] in {str(dbm) for dbm in expected_dbm}
            }
            s_label = next(entry for entry in labels.call_args_list if entry.args[3] == 'S')
            scale_unit = next(
                entry for entry in labels.call_args_list
                if entry.args[3] == 'dBm' and entry.args[5] == 13
            )
            first_dbm = next(entry for entry in labels.call_args_list if entry.args[3] == '-121')
            self.assertEqual(set(lower_labels), set(expected_dbm))
            self.assertEqual(set(lower_labels.values()), major_xs)
            self.assertEqual(scale_unit.args[1], s_label.args[1])
            self.assertEqual(scale_unit.args[2], first_dbm.args[2])
            self.assertEqual(scale_unit.args[8], 'cm')
            self.assertLess(scale_unit.args[1], first_dbm.args[1])

    def test_band_navigation_alignment_follows_frequency_position(self):
        ui.configure_output(True)
        text_cache = Mock()
        text_cache.font.return_value.size.return_value = (300, 58)
        left_frequency = ui.frequency_display_box(text_cache, 7075, position='left')
        left_meter = ui.left_smeter_box(text_cache, 7075)
        left_band = ui.main_band_context_box(text_cache, 7075, position='left')
        self.assertGreater(left_band[0], left_meter[2])
        self.assertGreater(left_band[0], left_frequency[2])
        self.assertGreaterEqual(
            ui.LCD_TOP_INSTRUMENT_BAND_H - ((left_band[1] + left_band[3]) / 2 + 0.5 + 17 / 2),
            8,
        )
        self.assertEqual((left_band[1] + left_band[3]) / 2 + 0.5,
                         ui.LCD_TOP_INSTRUMENT_CENTER_Y)

        middle_frequency = ui.frequency_display_box(text_cache, 7075, position='middle')
        middle_band = ui.main_band_context_box(text_cache, 7075, position='middle')
        self.assertLess(middle_band[2], middle_frequency[0])
        self.assertEqual((middle_band[1] + middle_band[3]) / 2 + 0.5,
                         ui.LCD_TOP_INSTRUMENT_CENTER_Y)

    def test_band_navigation_uses_stats_close_button(self):
        ui.configure_output(True)
        boxes = ui.band_navigation_layout()
        close = boxes['close']
        self.assertEqual(close, ui.compact_header_close_box(boxes['panel']))
        self.assertEqual((close[2] - close[0], close[3] - close[1]), (102, 30))
        self.assertEqual(ui.band_navigation_action_at(
            (close[0] + close[2]) / 2, (close[1] + close[3]) / 2,
        ), 'close')
        text_cache = Mock()
        with patch.object(ui, 'draw_logical_rect'), \
             patch.object(ui, 'draw_logical_line') as lines, \
             patch.object(ui, 'draw_text'), \
             patch.object(ui, 'draw_styled_button_frame'), \
             patch.object(ui, 'draw_styled_text_button') as close_button:
            ui.draw_band_navigation(text_cache, 7075, 'LSB')
        self.assertEqual(len(lines.call_args_list), 1)
        close_button.assert_called_once_with(text_cache, close, 'CLOSE', size=12)

    def test_audio_rail_uses_full_width_sliders_and_bottom_reset_mute_row(self):
        ui.configure_output(True)
        back = ui.lcd_audio_drawer_close_box()
        full_edges = (back[0], back[2])
        for box in (ui.AUDIO_VOLUME_BOX, ui.AUDIO_SQUELCH_BOX,
                    ui.AUDIO_DENOISE_BOX, ui.AUDIO_BACKEND_BOX):
            self.assertEqual((box[0], box[2]), full_edges)
            self.assertEqual(box[2] - box[0], 236)

        reset, mute = ui.AUDIO_RESET_BOX, ui.AUDIO_MUTE_BOX
        self.assertEqual((reset[1], reset[3]), (mute[1], mute[3]))
        self.assertEqual((reset[0], mute[2]), full_edges)
        self.assertEqual(mute[0] - reset[2], 8)
        self.assertEqual(ui.AUDIO_BACKEND_BOX[3] + 8, reset[1])
        self.assertGreaterEqual(back[1] - mute[3], 16)
        self.assertEqual(ui.AUDIO_DENOISE_BOX[3] + 8,
                         ui.AUDIO_VOICE_CLEAN_BOX[1])
        for action, box in (('reset', reset), ('mute', mute),
                            ('backend', ui.AUDIO_BACKEND_BOX),
                            ('filter', ui.AUDIO_FILTER_BOX)):
            self.assertEqual(ui.audio_option_at(
                (box[0] + box[2]) / 2, (box[1] + box[3]) / 2,
            ), action)

        controls = (
            ui.AUDIO_VOLUME_BOX, ui.AUDIO_SQUELCH_BOX, ui.AUDIO_DENOISE_BOX,
            ui.AUDIO_VOICE_CLEAN_BOX, ui.AUDIO_HF_ENHANCE_BOX,
            ui.AUDIO_AGC_BOX, ui.AUDIO_BLANKER_BOX, ui.AUDIO_NOTCH_BOX,
            ui.AUDIO_DEEMP_BOX, ui.AUDIO_TONE_BOX, ui.AUDIO_FILTER_BOX,
            ui.AUDIO_BACKEND_BOX, reset, mute,
        )
        for index, box in enumerate(controls):
            for other in controls[index + 1:]:
                self.assertFalse(
                    box[0] < other[2] and other[0] < box[2]
                    and box[1] < other[3] and other[1] < box[3],
                    (box, other),
                )

    def test_audio_rail_draws_full_width_volume_and_slider_tracks(self):
        ui.configure_output(True)
        controls = dict(mute=False, voice_clean_level=0, hf_enhance_level=0,
                        tone_profile=0, squelch_level=0, agc=True,
                        agc_hang=False, nb_algo=0, denoise_level=0,
                        deemphasis=0, autonotch=False)
        with patch.object(ui, 'draw_logical_rect') as rectangles, \
             patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_text'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'draw_lcd_audio_tile'), \
             patch.object(ui, 'draw_lcd_audio_slider_tile'), \
             patch.object(ui, 'draw_sidebar_header'):
            ui.draw_lcd_audio_drawer(object(), 0.5, controls, -400, 400,
                                     True, 'am', 'pipewire')
        volume = ui.AUDIO_VOLUME_BOX
        track_y = volume[3] - 16
        self.assertIn((volume[0], track_y - 3, volume[2], track_y + 3),
                      [entry.args[:4] for entry in rectangles.call_args_list])

        for box in (ui.AUDIO_SQUELCH_BOX, ui.AUDIO_DENOISE_BOX):
            with patch.object(ui, 'draw_logical_rect') as rectangles, \
                 patch.object(ui, 'draw_logical_line'), patch.object(ui, 'draw_text'):
                ui.draw_lcd_audio_slider_tile(object(), box, 'LEVEL', 0, 10,
                                              'OFF', full_width=True)
            track_y = box[3] - 15
            self.assertIn((box[0], track_y - 3, box[2], track_y + 3),
                          [entry.args[:4] for entry in rectangles.call_args_list])
        self.assertEqual(ui.audio_denoise_level_at_x(ui.AUDIO_DENOISE_BOX[0]), 0)
        self.assertEqual(ui.audio_denoise_level_at_x(ui.AUDIO_DENOISE_BOX[2]),
                         len(ui.DENOISE_SLIDER_POSITIONS) - 1)

    def test_scope_drag_requires_a_held_vertical_move(self):
        self.assertFalse(ui.scope_hold_drag_ready(0.2, 0, 80, 10))
        self.assertFalse(ui.scope_hold_drag_ready(0.6, 80, 10, 10))
        self.assertFalse(ui.scope_hold_drag_ready(0.6, 0, 8, 10))
        self.assertTrue(ui.scope_hold_drag_ready(0.6, 4, 35, 10))
        self.assertTrue(ui.scope_hold_drag_ready(0.6, 4, -35, 10))

    def test_scope_drag_from_waterfall_uses_relative_motion(self):
        self.assertEqual(ui.scope_height_from_drag(240, 650, 690, 350), 280)
        self.assertEqual(ui.scope_height_from_drag(240, 650, 610, 350), 200)
        self.assertEqual(ui.scope_height_from_drag(240, 650, 200, 350), 0)
        self.assertEqual(ui.scope_height_from_drag(240, 650, 900, 350), 350)
        self.assertEqual(ui.scope_height_from_drag(280, 100, 620, ui.LOGICAL_H), ui.LOGICAL_H)
        self.assertEqual(ui.scope_height_from_drag(280, 650, 0, ui.LOGICAL_H), 0)

    def test_scope_and_waterfall_reach_both_screen_edges(self):
        ui.configure_output(True)
        self.assertEqual(ui.scope_waterfall_y_bounds(0, True), (0, 0, 0))
        self.assertEqual(ui.scope_waterfall_y_bounds(ui.LOGICAL_H, True),
                         (0, ui.LOGICAL_H, ui.LOGICAL_H))
        self.assertEqual(ui.scope_waterfall_y_bounds(ui.LCD_SPECTRUM_H, True),
                         (0, 280, 280))
        self.assertEqual(ui.scope_waterfall_y_bounds(ui.LCD_SPECTRUM_H, False),
                         (0, 0, 0))

    def test_spectrum_ruler_has_a_16px_top_label_gap(self):
        text_cache = Mock()
        text_cache.texture.return_value = (1, 64, 16)
        with patch.object(ui, 'draw_logical_rect'), \
             patch.object(ui, 'draw_logical_line') as line, \
             patch.object(ui, 'draw_textured_quad') as text_quad, \
             patch.object(ui, 'draw_logical_area'), \
             patch.object(ui, 'draw_logical_polyline') as trace:
            ui.draw_spectrum(0, 240, (0.0, 1.0), text_cache=text_cache)

        self.assertEqual(min(entry.args[2] for entry in text_quad.call_args_list), 16)
        self.assertEqual(
            [entry.args[1] for entry in line.call_args_list
             if entry.args[0] == 8 and entry.args[2] == 22][0],
            26,
        )
        self.assertEqual(trace.call_args.args[0][-1][1], 26)

    def test_spectrum_fill_reaches_the_waterfall_boundary(self):
        text_cache = Mock()
        text_cache.texture.return_value = (1, 64, 16)
        with patch.object(ui, 'draw_logical_rect'), \
             patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_logical_area') as areas, \
             patch.object(ui, 'draw_logical_polyline'):
            ui.draw_spectrum(0, 240, (0.0, 0.8), (0.2, 1.0), text_cache)

        self.assertEqual([entry.args[1] for entry in areas.call_args_list], [240, 240])

    def test_spectrum_passband_extension_meets_waterfall_band(self):
        ui.configure_output(True)
        text_cache = Mock()
        with patch.object(ui, 'draw_logical_rect') as rectangles, \
             patch.object(ui, 'draw_logical_line') as lines, \
             patch.object(ui, 'draw_text') as labels:
            ui.draw_filter_overlay(
                text_cache, 20, -3000, 3000, 0, 280,
                tuned_offset_hz=1000, show_markers=False,
            )
            spectrum_band = rectangles.call_args.args
            self.assertEqual(len(lines.call_args_list), 2)
            spectrum_edge = lines.call_args_list[0].args[4]
            labels.assert_not_called()
            rectangles.reset_mock()
            ui.draw_filter_overlay(
                text_cache, 20, -3000, 3000, 280, 800,
                tuned_offset_hz=1000,
            )
            waterfall_band = rectangles.call_args.args

        self.assertEqual(spectrum_band[:4], (
            waterfall_band[0], 0, waterfall_band[2], 280,
        ))
        self.assertEqual(waterfall_band[1:4:2], (280, 800))
        self.assertEqual(spectrum_band[4][:3], ui.APP_UI_STYLE.palette.passband_fill[:3])
        self.assertEqual(spectrum_band[4][3], ui.APP_UI_STYLE.palette.passband_fill[3])
        self.assertEqual(spectrum_edge, ui.APP_UI_STYLE.palette.passband_border)
        self.assertLess(spectrum_edge[3], ui.APP_UI_STYLE.palette.passband_center[3])

    def test_waterfall_tap_tunes_under_finger_without_recentering_passband(self):
        ui.configure_output(True)
        width = ui.rf_canvas_width()
        state = ui.SharedState(
            'http://example.test:8073', 7075.0, 4, -95.0,
            142, 245, 3, 'am', True,
        )
        for tap_x in (width * 0.25, width * 0.75):
            target = ui.waterfall_tap_frequency_khz(tap_x, 7075.0, 20.0)
            state.set_view(freq_khz=target, waterfall_center_khz=7075.0)
            self.assertEqual(state.waterfall_view_center_snapshot(), 7075.0)
            center = ui.receiver_waterfall_center(
                state.snapshot()[1], 20.0, 'kiwi',
                state.waterfall_view_center_snapshot(),
            )
            self.assertEqual(center, 7075.0)
            with patch.object(ui, 'draw_logical_rect') as rectangles, \
                 patch.object(ui, 'draw_logical_line'):
                ui.draw_filter_overlay(
                    Mock(), 20.0, -1000, 1000, 0, 800,
                    tuned_offset_hz=(target - center) * 1000.0,
                    show_markers=False,
                )
            left, _top, right, _bottom, _color = rectangles.call_args.args
            self.assertAlmostEqual((left + right) / 2, tap_x)

        state.set_view(freq_khz=7080.0)
        self.assertIsNone(state.waterfall_view_center_snapshot())

    def test_waterfall_tap_maps_full_canvas_and_clamps_outside_it(self):
        ui.configure_output(True)
        width = ui.rf_canvas_width()
        self.assertEqual(ui.waterfall_touch_bounds()[0], 0)
        self.assertEqual(ui.waterfall_touch_bounds()[1], 0)
        self.assertEqual(ui.waterfall_touch_bounds()[2], width)
        self.assertEqual(ui.waterfall_tap_frequency_khz(-20, 7000, 20), 6990)
        self.assertEqual(ui.waterfall_tap_frequency_khz(width / 2, 7000, 20), 7000)
        self.assertEqual(ui.waterfall_tap_frequency_khz(width + 20, 7000, 20), 7010)

    def test_settings_back_has_an_isolated_target(self):
        items = ui.SETTINGS_MENU_ITEMS
        self.assertEqual(ui.lcd_nav_box(len(items)-1, len(items), True), ui.lcd_drawer_back_box())
        boxes = [ui.lcd_nav_box(i, len(items), True) for i in range(len(items))]
        for i,a in enumerate(boxes):
            for b in boxes[i+1:]:
                self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3])

    def test_empty_annunciator_space_is_not_a_mode_control(self):
        # The mode grid is shorter than the tappable annunciator block, so the
        # empty space beneath it must never be treated as a control (it used to
        # open the MODES drawer).
        ui.configure_output(True)
        for compact in (True, False):
            boxes = [box for _label, box in ui.lcd_home_mode_boxes(compact)]
            grid_bottom = max(box[3] for box in boxes)
            self.assertLess(grid_bottom, ui.LCD_ANNUNCIATOR_BOX[3])
            empty_y = (grid_bottom + ui.LCD_ANNUNCIATOR_BOX[3]) / 2
            empty_x = (ui.LCD_ANNUNCIATOR_BOX[0] + ui.LCD_ANNUNCIATOR_BOX[2]) / 2
            self.assertFalse(any(
                box[0] <= empty_x <= box[2] and box[1] <= empty_y <= box[3]
                for box in boxes
            ))

    def test_globe_rail_zooms_use_text_buttons(self):
        # Rail actions have text labels instead of icon-only glyphs.
        receivers = [
            {'name': 'A', 'location': '', 'server': 'http://a.kiwi:8073', 'lat': 0.0, 'lon': 0.0, 'receiver_type': 'kiwi'},
            {'name': 'C', 'location': '', 'server': ui.LOCAL_KIWI_SERVER, 'lat': 2.0, 'lon': 2.0, 'receiver_type': 'kiwi'},
            {'name': 'D', 'location': '', 'server': 'https://d.fmdx', 'lat': 3.0, 'lon': 3.0, 'receiver_type': 'fmdx'},
        ]
        texts = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline'), patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_text',
                          side_effect=lambda _c, _x, _y, text, *_a, **_k: texts.append(str(text))), \
             patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'radiogarden_project', return_value=(300.0, 200.0, 1.0)), \
             patch.object(ui, 'draw_logical_points'):
            ui.draw_receiver_map(
                None, receivers, 0.0, 0.0, 1.0, '', None, 'idle', {},
                map_view='satellite_only',
            )
        self.assertIn('ZOOM IN', texts)
        self.assertIn('ZOOM OUT', texts)
        self.assertNotIn('+', texts)
        self.assertNotIn('−', texts)

    def test_home_controls_fit_before_navigation(self):
        for compact in (True, False):
            self.assertLess(ui.lcd_home_volume_box(compact)[3], ui.lcd_nav_top())

    def test_fmdx_waterfall_retains_carrier_above_30mhz(self):
        self.assertEqual(ui.receiver_waterfall_center(101700,20,'fmdx'),101700)
        self.assertLess(ui.receiver_waterfall_center(29999,20,'kiwi'),29999)

    def test_kiwi_palette_is_default(self):
        self.assertEqual(ui.WATERFALL_DEFAULT_PALETTE,'kiwi')

    def test_home_rail_controls_are_inert_under_settings_and_modes(self):
        # Settings and MODES draw their title over the Home annunciator
        # placeholders; the covered mode grid must not react underneath them.
        self.assertTrue(ui.home_rail_controls_available(False, False, False))
        self.assertFalse(ui.home_rail_controls_available(False, True, False))
        self.assertFalse(ui.home_rail_controls_available(False, False, True))
        self.assertFalse(ui.home_rail_controls_available(True, False, False))
        self.assertFalse(ui.home_rail_controls_available(False, False, False, True))

    def test_waterfall_zoom_is_glyph_only_and_display_button_is_gone(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        texts = []
        with patch.object(ui, 'draw_zoom_button') as zoom, \
             patch.object(ui, 'draw_control_group_background') as group, \
             patch.object(ui, 'draw_spectrum_toggle_button') as spectrum, \
             patch.object(ui, 'draw_text',
                          side_effect=lambda _c, _x, _y, text, *_a, **_k: texts.append(str(text))):
            ui.draw_waterfall_operating_controls(None, True, 1.0)
        # Two standalone + / - icons, no pill background, no ZOOM caption, and
        # the DISPLAY button is no longer drawn on the waterfall.
        self.assertEqual(zoom.call_count, 2)
        group.assert_not_called()
        spectrum.assert_not_called()
        self.assertNotIn('ZOOM', texts)
        self.assertNotIn('DISPLAY', texts)

    def test_waterfall_zoom_tiles_show_a_pressed_state(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        with patch.object(ui, 'draw_zoom_button') as zoom:
            ui.draw_waterfall_operating_controls(None, True, 1.0, pressed='zoom_minus')
        calls = {call.args[1]: call.args[4] for call in zoom.call_args_list}
        self.assertTrue(calls[ui.ZOOM_MINUS_BOX])   # pressed tile is active
        self.assertFalse(calls[ui.ZOOM_PLUS_BOX])   # the other stays idle

    def test_waterfall_zoom_pressed_palette_keeps_translucent_feedback(self):
        fill, border, icon = ui.zoom_button_palette(active=True, pressed=True)
        self.assertEqual(fill, (*ui.APP_UI_STYLE.palette.pressed_surface[:3], 216))
        self.assertEqual(border, ui.APP_UI_STYLE.palette.pressed_border)
        self.assertEqual(icon, (0, 0, 0, 255))

    def test_waterfall_zoom_matches_favorite_and_pause_size_and_spacing(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        favorite = ui.favorite_waterfall_box()
        pause = ui.stream_waterfall_box()
        expected_size = (pause[2] - pause[0], pause[3] - pause[1])
        self.assertEqual(
            (favorite[2] - favorite[0], favorite[3] - favorite[1]),
            expected_size,
        )
        self.assertEqual(
            (ui.ZOOM_MINUS_BOX[2] - ui.ZOOM_MINUS_BOX[0],
             ui.ZOOM_MINUS_BOX[3] - ui.ZOOM_MINUS_BOX[1]),
            expected_size,
        )
        self.assertEqual(
            (ui.ZOOM_PLUS_BOX[2] - ui.ZOOM_PLUS_BOX[0],
             ui.ZOOM_PLUS_BOX[3] - ui.ZOOM_PLUS_BOX[1]),
            expected_size,
        )
        self.assertEqual(
            ui.ZOOM_PLUS_BOX[0] - ui.ZOOM_MINUS_BOX[2],
            pause[0] - favorite[2],
        )

    def test_waterfall_zoom_uses_the_shared_home_button_frame(self):
        visual = ui.APP_UI_STYLE.button.resolve()
        with patch.object(ui, 'ui_button_pressed', return_value=False), \
             patch.object(ui, 'draw_styled_button_frame', return_value=visual) as frame, \
             patch.object(ui, 'draw_logical_line') as line:
            ui.draw_zoom_button(None, ui.ZOOM_PLUS_BOX, '+')
        frame.assert_called_once_with(ui.ZOOM_PLUS_BOX, active=False, pressed=False,
                                      fill_alpha=184)
        self.assertEqual(line.call_count, 2)

    def test_waterfall_pause_uses_the_zoom_icon_stroke_weight(self):
        visual = ui.APP_UI_STYLE.button.resolve()
        with patch.object(ui, 'ui_button_pressed', return_value=False), \
             patch.object(ui, 'draw_styled_button_frame', return_value=visual), \
             patch.object(ui, 'draw_logical_line') as line, \
             patch.object(ui, 'draw_logical_rect') as rect:
            ui.draw_stream_waterfall_button(None, False)
        self.assertEqual(line.call_count, 2)
        self.assertTrue(all(c.args[5] == 4 for c in line.call_args_list))
        rect.assert_not_called()

    def test_display_reset_sits_directly_above_back(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        self.assertEqual(ui.DISPLAY_THEME_BOX[3] + 16,
                         ui.DISPLAY_SPECTRUM_BOX[1])
        self.assertEqual(ui.DISPLAY_RESET_BOX[3] + ui.LCD_NAV_GAP,
                         ui.lcd_drawer_back_box()[1])
        self.assertLess(ui.DISPLAY_THEME_BOX[3], ui.DISPLAY_RESET_BOX[1])
        self.assertEqual(ui.DISPLAY_THEME_BOX[2] - ui.DISPLAY_THEME_BOX[0], 236)
        self.assertEqual(ui.display_option_at(1150, (ui.DISPLAY_THEME_BOX[1] + ui.DISPLAY_THEME_BOX[3]) / 2),
                         ('theme', None))

    def test_display_drawer_draws_layout_and_speed_without_scope(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        seen = []
        with patch.object(ui, 'draw_lcd_audio_tile',
                          side_effect=lambda *_a, **_k: seen.append((_a[1], _a[2]))), \
             patch.object(ui, 'draw_display_slider_section'), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'draw_display_control') as controls, \
             patch.object(ui, 'draw_lcd_drawer_heading') as headings:
            ui.draw_display_setup_panel(None, -95, -20, 1, False, 'kiwi', True)
        self.assertIn((ui.DISPLAY_RESET_BOX, 'RESET DISPLAY'), seen)
        self.assertIn((ui.DISPLAY_THEME_BOX, 'THEMES'), seen)
        self.assertIn('LEFT', [entry.args[2] for entry in controls.call_args_list])
        self.assertIn('MIDDLE', [entry.args[2] for entry in controls.call_args_list])
        self.assertIn('RIGHT', [entry.args[2] for entry in controls.call_args_list])
        self.assertNotIn('DRAG', [entry.args[2] for entry in controls.call_args_list])
        self.assertIn('WATERFALL SPEED', [entry.args[3] for entry in headings.call_args_list])
        self.assertIn('WATERFALL THEME', [entry.args[3] for entry in headings.call_args_list])
        self.assertIn('FREQUENCY POSITION', [entry.args[3] for entry in headings.call_args_list])
        self.assertNotIn('SCOPE', [entry.args[3] for entry in headings.call_args_list])
        heading_y = {entry.args[3]: entry.args[2] for entry in headings.call_args_list}
        self.assertEqual(heading_y['WATERFALL THEME'] - 8
                         - ui.DISPLAY_CEIL_MINUS_BOX[3], 16)
        self.assertEqual(heading_y['WATERFALL SPEED'] - 8
                         - ui.DISPLAY_PALETTE_BOXES[0][1][3], 16)
        self.assertEqual(heading_y['FREQUENCY POSITION'] - 8
                         - ui.DISPLAY_RATE_BOXES[0][1][3], 16)
        self.assertEqual(ui.DISPLAY_THEME_BOX[3] + 16,
                         ui.DISPLAY_SPECTRUM_BOX[1])
        self.assertEqual(ui.DISPLAY_RESET_BOX[3] + ui.LCD_NAV_GAP,
                         ui.lcd_drawer_back_box()[1])
        self.assertLess(ui.DISPLAY_THEME_BOX[3], ui.DISPLAY_RESET_BOX[1])
        states = {entry.args[2]: entry.args[3] for entry in controls.call_args_list}
        self.assertFalse(states['LEFT'])
        self.assertTrue(states['MIDDLE'])
        self.assertFalse(states['RIGHT'])

    def test_display_drawer_options_fit_the_rail(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        rail_bottom = ui.lcd_drawer_back_box()[1]
        self.assertEqual(ui.DISPLAY_THEME_BOX[1] - ui.LCD_DRAWER_HEADER_H, 16)
        self.assertEqual(ui.DISPLAY_AUTO_BOX[1], ui.DISPLAY_SPECTRUM_BOX[1])
        boxes = [ui.DISPLAY_THEME_BOX, ui.DISPLAY_RESET_BOX, ui.DISPLAY_SPECTRUM_BOX, ui.DISPLAY_AUTO_BOX,
                 ui.DISPLAY_FLOOR_MINUS_BOX, ui.DISPLAY_CEIL_MINUS_BOX]
        boxes.extend(box for _layout, box in ui.DISPLAY_LAYOUT_BOXES)
        boxes.extend(box for _rate, box, _label in ui.DISPLAY_RATE_BOXES)
        boxes.extend(box for _name, box, _label in ui.DISPLAY_PALETTE_BOXES)
        for box in boxes:
            self.assertGreaterEqual(box[0], ui.LCD_NAV_X0)
            self.assertLessEqual(box[2], ui.LOGICAL_W)
            self.assertLess(box[3], rail_bottom, box)
        for layout, box in ui.DISPLAY_LAYOUT_BOXES:
            self.assertEqual(ui.display_option_at((box[0] + box[2]) / 2,
                                                  (box[1] + box[3]) / 2), ('layout', layout))
        back_x0, rail_bottom, back_x1, _back_bottom = ui.lcd_drawer_back_box()
        self.assertEqual(ui.DISPLAY_FLOOR_MINUS_BOX[::2], (back_x0, back_x1))
        self.assertEqual(ui.DISPLAY_CEIL_MINUS_BOX[::2], (back_x0, back_x1))
        for group in (
            (ui.DISPLAY_SPECTRUM_BOX, ui.DISPLAY_AUTO_BOX),
            tuple(box for _rate, box, _label in ui.DISPLAY_RATE_BOXES),
            tuple(box for _name, box, _label in ui.DISPLAY_PALETTE_BOXES),
            tuple(box for _layout, box in ui.DISPLAY_LAYOUT_BOXES),
        ):
            self.assertEqual((group[0][0], group[-1][2]), (back_x0, back_x1))
        self.assertEqual([box[3] - box[1] for _rate, box, _label in ui.DISPLAY_RATE_BOXES],
                         [31] * 3)
        self.assertEqual([position for position, _box in ui.DISPLAY_LAYOUT_BOXES],
                         ['left', 'middle', 'right'])
        self.assertEqual(
            [(box[0], box[2] - box[0], box[3] - box[1])
             for _position, box in ui.DISPLAY_LAYOUT_BOXES],
            [(box[0], box[2] - box[0], box[3] - box[1])
             for _rate, box, _label in ui.DISPLAY_RATE_BOXES],
        )
        self.assertEqual([(box[2] - box[0], box[3] - box[1])
                          for _name, box, _label in ui.DISPLAY_PALETTE_BOXES],
                         [(box[2] - box[0], box[3] - box[1])
                          for _rate, box, _label in ui.DISPLAY_RATE_BOXES])
        self.assertEqual(ui.DISPLAY_FLOOR_MINUS_BOX[1] - ui.DISPLAY_SPECTRUM_BOX[3], 16)
        self.assertEqual(ui.DISPLAY_CEIL_MINUS_BOX[1] - ui.DISPLAY_FLOOR_MINUS_BOX[3], 16)
        self.assertEqual(ui.DISPLAY_PALETTE_BOXES[0][1][1] - ui.DISPLAY_CEIL_MINUS_BOX[3], 40)
        self.assertEqual([name for name, _box, _label in ui.DISPLAY_PALETTE_BOXES],
                         ['classic', 'kiwi', 'gqrx'])
        for palette, box, _label in ui.DISPLAY_PALETTE_BOXES:
            self.assertEqual(ui.display_option_at((box[0] + box[2]) / 2,
                                                  (box[1] + box[3]) / 2),
                             ('palette', palette))
        self.assertEqual(ui.DISPLAY_THEME_BOX[3] + 16, ui.DISPLAY_SPECTRUM_BOX[1])
        self.assertEqual(rail_bottom - ui.DISPLAY_RESET_BOX[3], ui.LCD_NAV_GAP)
        self.assertLess(ui.DISPLAY_THEME_BOX[3], ui.DISPLAY_RESET_BOX[1])
        for earlier in boxes:
            if earlier != ui.DISPLAY_RESET_BOX:
                self.assertFalse(earlier[0] < ui.DISPLAY_RESET_BOX[2]
                                 and ui.DISPLAY_RESET_BOX[0] < earlier[2]
                                 and earlier[1] < ui.DISPLAY_RESET_BOX[3]
                                 and ui.DISPLAY_RESET_BOX[1] < earlier[3])

    def test_palette_choice_restores_both_contrast_sliders(self):
        state = ui.SharedState(
            'http://example.test:8073', 7075.0, 4, -95.0,
            142, 245, 3, 'am', True,
        )
        self.assertEqual(ui.WATERFALL_PALETTE_PRESETS['classic'], (160, 220))
        for palette in ('classic', 'kiwi', 'gqrx', 'classic'):
            state.set_waterfall(floor=80, ceil=250, auto=True)
            floor, ceiling, _speed, auto, selected, _generation = (
                ui.apply_waterfall_palette_preset(state, palette)
            )
            self.assertEqual((floor, ceiling), ui.WATERFALL_PALETTE_PRESETS[palette])
            self.assertFalse(auto)
            self.assertEqual(selected, palette)
            self.assertEqual(state.waterfall_snapshot()[:2], (floor, ceiling))

    def test_reset_display_restores_every_waterfall_and_spectrum_setting(self):
        state = ui.SharedState(
            'http://example.test:8073', 7075.0, 4, -95.0,
            142, 245, 3, 'am', True,
        )
        state.set_waterfall(floor=160, ceil=220, speed=2, auto=False, palette='classic')
        state.set_spectrum_enabled(False)
        state.set_spectrum_auto(False)
        previous_generation = state.waterfall_snapshot()[-1]

        reset_waterfall = ui.reset_display_view(state)

        self.assertEqual(reset_waterfall[:5], (
            ui.WATERFALL_DEFAULT_FLOOR,
            ui.WATERFALL_DEFAULT_CEIL,
            ui.WATERFALL_DEFAULT_SPEED,
            False,
            ui.WATERFALL_DEFAULT_PALETTE,
        ))
        self.assertEqual(state.waterfall_snapshot(), reset_waterfall)
        self.assertEqual(reset_waterfall[-1], previous_generation + 1)
        self.assertTrue(state.spectrum_enabled_snapshot())
        self.assertTrue(state.spectrum_auto_snapshot())

    def test_display_slider_section_renders_full_back_width(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        box = ui.DISPLAY_FLOOR_MINUS_BOX
        with patch.object(ui, 'draw_logical_rect') as rectangles, \
             patch.object(ui, 'draw_logical_line') as lines, \
             patch.object(ui, 'draw_text'):
            ui.draw_display_slider_section(None, box, 'FLOOR', 60, 180, '100', True)
        self.assertEqual(rectangles.call_args_list[0].args[:4], box)
        self.assertEqual(box[2] - box[0], 236)
        lines.assert_not_called()

    def test_gqrx_waterfall_has_dark_noise_and_warm_signal_peaks(self):
        red, green, blue = ui.waterfall_mapper('gqrx')
        self.assertEqual((len(red), len(green), len(blue)), (256, 256, 256))
        self.assertEqual((red[0], green[0], blue[0]), (0, 0, 0))
        self.assertEqual((red[100], green[100], blue[100]), (60, 125, 255))
        self.assertEqual((red[150], green[150], blue[150]), (255, 255, 0))
        self.assertEqual((red[249], green[249], blue[249]), (255, 3, 0))
        self.assertEqual((red[255], green[255], blue[255]), (255, 255, 255))
        self.assertNotEqual((red, green, blue), ui.waterfall_mapper('classic'))

    def test_kiwi_and_classic_preserve_their_original_palettes(self):
        self.assertEqual(ui.waterfall_mapper('kiwi'), ui.kiwi.make_waterfall_mapper())
        red, green, blue = ui.waterfall_mapper('classic')
        self.assertEqual((red[0], green[0], blue[0]), (1, 4, 14))
        self.assertEqual((red[160], green[160], blue[160]), (0, 226, 235))
        self.assertEqual((red[255], green[255], blue[255]), (245, 44, 36))

    def test_spectrum_and_auto_controls_leave_live_waterfall_unchanged(self):
        state = ui.SharedState(
            'http://example.test:8073', 7075.0, 4, -95.0,
            142, 245, 3, 'am', True,
        )
        ui.apply_waterfall_palette_preset(state, 'gqrx')
        waterfall_before = state.waterfall_snapshot()
        ui.toggle_display_spectrum_control(state, 'spectrum')
        self.assertFalse(state.spectrum_enabled_snapshot())
        self.assertEqual(state.waterfall_snapshot(), waterfall_before)
        ui.toggle_display_spectrum_control(state, 'auto')
        self.assertFalse(state.spectrum_auto_snapshot())
        self.assertEqual(state.waterfall_snapshot(), waterfall_before)
        ui.toggle_display_spectrum_control(state, 'auto')
        self.assertTrue(state.spectrum_auto_snapshot())
        self.assertEqual(state.waterfall_snapshot(), waterfall_before)

    def test_globe_view_selector_keeps_prior_choices_except_atlas(self):
        self.assertEqual(ui.GLOBE_DEFAULT_VIEW, 'satellite')
        self.assertEqual(ui.MAP_VIEWS, ('satellite_only', 'borders', 'satellite'))
        self.assertNotIn('atlas', ui.MAP_VIEWS)
        self.assertNotIn('ATLAS', ui.MAP_VIEW_LABELS.values())

    def test_navigation_tiles_match_home_button_spec(self):
        self.assertEqual((ui.LCD_NAV_TILE_W, ui.LCD_NAV_TILE_H), (114, 64))
        back = ui.lcd_drawer_back_box()
        self.assertEqual(
            2 * ui.LCD_NAV_TILE_W + ui.LCD_NAV_GAP,
            back[2] - back[0],
        )
        for items in (ui.MENU_ITEMS, ui.SETTINGS_MENU_ITEMS):
            has_back = items is ui.SETTINGS_MENU_ITEMS
            for index in range(len(items)):
                if has_back and index == len(items) - 1:
                    continue  # Back is the shared full-width return target.
                box = ui.lcd_nav_box(index, len(items), has_back)
                self.assertEqual(box[2] - box[0], ui.LCD_NAV_TILE_W)
                self.assertEqual(box[3] - box[1], ui.LCD_NAV_TILE_H if has_back else ui.LCD_HOME_NAV_TILE_H)
        # The Globe retains its four compact rail commands and full-width Back.
        ui.configure_output(True)
        ui.configure_popup_layout()
        for box in (ui.RADIOGARDEN_LIST_BOX, ui.RADIOGARDEN_VIEW_BOX,
                    ui.RADIOGARDEN_ZOOM_IN_BOX, ui.RADIOGARDEN_ZOOM_OUT_BOX):
            self.assertEqual(box[2] - box[0], ui.LCD_NAV_TILE_W)
            self.assertEqual(box[3] - box[1], ui.LCD_NAV_TILE_H)
        self.assertIs(ui.RADIOGARDEN_LIST_BOX, ui.PICKER_MAP_MODE_BOX)
        self.assertIs(ui.RADIOGARDEN_VIEW_BOX, ui.PICKER_SEARCH_BOX)
        self.assertIs(ui.RADIOGARDEN_ZOOM_IN_BOX, ui.PICKER_SORT_BOX)
        self.assertIs(ui.RADIOGARDEN_ZOOM_OUT_BOX, ui.PICKER_ROUTE_FAVORITES_BOX)
        self.assertEqual(ui.RADIOGARDEN_LIST_BOX[0], ui.RADIOGARDEN_EXIT_BOX[0])
        self.assertEqual(ui.RADIOGARDEN_VIEW_BOX[2], ui.RADIOGARDEN_EXIT_BOX[2])
        self.assertEqual(
            ui.RADIOGARDEN_EXIT_BOX[1] - max(
                ui.RADIOGARDEN_ZOOM_IN_BOX[3], ui.RADIOGARDEN_ZOOM_OUT_BOX[3],
            ),
            ui.LCD_NAV_GAP,
        )

    def test_globe_commands_all_live_in_the_right_rail(self):
        # Controls retain the familiar right-side geometry while floating over
        # a full-width Globe canvas.
        ui.configure_output(True)
        ui.configure_popup_layout()
        zoom_in, zoom_out = ui.receiver_map_zoom_boxes()
        rail_boxes = [zoom_in, zoom_out, ui.RADIOGARDEN_LIST_BOX,
                      ui.RADIOGARDEN_VIEW_BOX,
                      ui.RADIOGARDEN_EXIT_BOX]
        for box in rail_boxes:
            self.assertGreaterEqual(box[0], ui.LCD_NAV_X0)
            self.assertLessEqual(box[2], ui.LOGICAL_W)
        self.assertEqual(ui.PICKER_MAP_BOX, (0, 0, ui.LOGICAL_W, ui.LOGICAL_H))
        for index, first in enumerate(rail_boxes):
            for second in rail_boxes[index + 1:]:
                self.assertFalse(
                    first[0] < second[2] and second[0] < first[2]
                    and first[1] < second[3] and second[1] < first[3],
                    f"Globe rail controls overlap: {first} {second}",
                )

    def test_receiver_browser_opens_the_globe_not_a_map(self):
        labels = []
        with patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_receiver_action_button',
                          side_effect=lambda _c, _b, label, *_a, **_k: labels.append(str(label))), \
             patch.object(ui, 'draw_receiver_filter_button'), \
             patch.object(ui, 'draw_receiver_sidebar_header'), \
             patch.object(ui, 'draw_receiver_back_button'), patch.object(ui, 'draw_text'):
            ui.draw_station_picker(None, [], 0, "", "", "location", {}, None, None, "kiwi", None)
        self.assertIn("GLOBE", labels)
        self.assertNotIn("MAP", labels)

    def test_receiver_source_segments_resolve_to_their_source(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        for source, box in ui.receiver_source_segments():
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            self.assertEqual(ui.picker_source_segment_at(*center), source)

    def test_receiver_rail_tabs_and_commands_do_not_overlap(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        tabs = [box for _source, box in ui.receiver_source_segments()]
        commands = [ui.PICKER_MAP_MODE_BOX, ui.PICKER_SEARCH_BOX,
                    ui.PICKER_SORT_BOX, ui.PICKER_ROUTE_FAVORITES_BOX]
        back = ui.PICKER_EXIT_BOX
        self.assertEqual(commands, list(ui.receiver_picker_command_boxes()))
        self.assertTrue(all(box[3] - box[1] == 48 for box in tabs))
        self.assertTrue(all((box[0], box[2]) == (back[0], back[2]) for box in tabs))
        self.assertEqual(tabs[0][1], ui.LCD_DRAWER_HEADER_H + 16)
        self.assertTrue(all(tabs[index + 1][1] - tabs[index][3] == 14
                            for index in range(len(tabs) - 1)))
        self.assertLess(tabs[-1][3], min(box[1] for box in commands))
        self.assertLess(max(box[3] for box in commands), back[1])
        boxes = tabs + commands + [back]
        for index, first in enumerate(boxes):
            for second in boxes[index + 1:]:
                self.assertFalse(ui.boxes_overlap(first, second), (first, second))

    def test_frequency_drawer_uses_text_direction_buttons_and_lists_steps(self):
        texts = []
        readouts = []
        with patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'frequency_chevron_texture', return_value=(1, 10, 10)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_big_frequency',
                          side_effect=lambda _c, freq, *_a, **_k: readouts.append(freq)), \
             patch.object(ui, 'draw_text',
                          side_effect=lambda _c, _x, _y, text, *_a, **_k: texts.append(str(text))):
            ui.draw_frequency_drawer(
                None, 7075.0, 100, 'Oxanium', None, 'kiwi',
                entry_value='7.125', entry_replace_on_digit=False,
            )
        self.assertIn('UP', texts)
        self.assertIn('DOWN', texts)
        self.assertNotIn('MANUAL FREQUENCY', texts)
        self.assertNotIn('MHz', texts)
        self.assertNotIn('7.125', texts)
        self.assertEqual(readouts, [7125.0])
        self.assertNotIn('ENTER FREQUENCY', texts)
        self.assertIn('OK', texts)
        for step_hz in ui.frequency_tune_steps('kiwi'):
            self.assertIn(ui.format_tune_step(step_hz).upper(), texts)

    def test_home_instruments_sit_under_the_mode_buttons(self):
        # The passband and volume are painted after the mode surface, so in
        # both presentations they only need to clear that surface's real bottom
        # edge rather than the whole reserved annunciator block.
        for compact in (True, False):
            bandwidth = ui.lcd_home_bandwidth_box(compact)
            volume = ui.lcd_home_volume_box(compact)
            self.assertGreaterEqual(bandwidth[1], ui.lcd_annunciator_surface_bottom(compact))
            self.assertGreaterEqual(volume[1], bandwidth[3])
            self.assertLess(volume[3], ui.lcd_nav_top())
        # Expanded: the instruments sit directly under the mode buttons instead
        # of being pushed down by an oversized empty annunciator panel.
        self.assertEqual(
            ui.lcd_home_bandwidth_box(False)[1] - ui.lcd_home_mode_grid_bottom(False), 20)
        self.assertEqual(
            ui.lcd_annunciator_surface_bottom(False),
            ui.lcd_home_mode_grid_bottom(False) + ui.LCD_ANNUNCIATOR_EXPANDED_PAD)
        self.assertEqual(
            ui.lcd_annunciator_surface_bottom(True),
            ui.lcd_home_mode_grid_bottom(True) + ui.LCD_ANNUNCIATOR_COMPACT_PAD,
        )

    def test_compact_home_reserves_the_full_volume_control(self):
        compact_meter = ui.lcd_compact_smeter_box()
        compact_modes = tuple(box for _label, box in ui.lcd_home_mode_boxes(True))
        bandwidth = ui.lcd_home_bandwidth_box(True)
        volume = ui.lcd_home_volume_box(True)
        mute = ui.lcd_home_volume_mute_box(True)
        track = ui.lcd_home_volume_track_box(True)
        self.assertLess(compact_meter[3], min(box[1] for box in compact_modes))
        self.assertLessEqual(max(box[3] for box in compact_modes), bandwidth[1])
        self.assertEqual(volume[3] - volume[1], 72)
        self.assertGreaterEqual(mute[1], volume[1])
        self.assertLessEqual(mute[3], volume[3])
        self.assertGreaterEqual(track[1], volume[1])
        self.assertLessEqual(track[3], volume[3])
        self.assertLess(volume[3], ui.lcd_nav_top())

    def test_mode_hit_selects_before_drawer(self):
        for compact in (True,False):
            for label, box in ui.lcd_home_mode_boxes(compact):
                expected = 'NBFM' if label=='FM' else label
                state=ui.SharedState('http://kiwi.test',7075,8,-95,-125,-15,3,'lsb',True)
                selected=ui.engage_home_mode(state,(box[0]+box[2])/2,(box[1]+box[3])/2,compact)
                self.assertEqual(selected,expected)
                self.assertEqual(state.radio_snapshot()[0].upper(),expected)

    def test_large_smeter_moves_mode_hit_region_with_visible_buttons(self):
        ui.configure_output(True)
        with patch.dict(ui.theme_system.runtime_theme, {'smeter_style': 'bakelite_square'}):
            mode_boxes = tuple(box for _label, box in ui.lcd_home_mode_boxes(True))
            hit_box = ui.radio_toggle_box(None, 7075.0, True)
            self.assertGreater(max(box[3] for box in mode_boxes), ui.LCD_ANNUNCIATOR_BOX[3])
            for box in mode_boxes:
                center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                self.assertTrue(ui.contains(hit_box, *center))


class DualVfoHomeControlTests(unittest.TestCase):
    def test_receiver_list_selection_changes_only_the_requested_vfo(self):
        primary = ui.SharedState('http://a.test', 7075, 7, -95, 142, 245, 4, 'am', True)
        secondary = ui.SharedState('http://b.test', 7075, 7, -95, 142, 245, 4, 'lsb', True)
        sources = {
            'A': {'server': 'http://a.test', 'name': 'A'},
            'B': {'server': 'http://b.test', 'name': 'B'},
        }
        profiles = {'A': {'mode': 'AM'}, 'B': {'mode': 'LSB'}}
        station_b = ('New B', 'Location B', 'http://new-b.test', 0, 4)
        server_b, freq_b, zoom_b = ui.select_dual_vfo_receiver(
            primary, secondary, sources, profiles, 'B', station_b)
        self.assertEqual(server_b, 'http://new-b.test')
        self.assertEqual(primary.snapshot()[0], 'http://a.test')
        self.assertEqual(secondary.snapshot()[0], server_b)
        self.assertEqual(sources['B']['name'], 'New B')
        self.assertEqual(profiles['B']['mode'], 'LSB')
        self.assertEqual((profiles['B']['freq_khz'], profiles['B']['zoom']), (freq_b, zoom_b))

        station_a = ('New A', 'Location A', 'http://new-a.test', 1, 4)
        server_a, _freq_a, _zoom_a = ui.select_dual_vfo_receiver(
            primary, secondary, sources, profiles, 'A', station_a)
        self.assertEqual(primary.snapshot()[0], server_a)
        self.assertEqual(secondary.snapshot()[0], server_b)
        self.assertEqual(sources['A']['location'], 'Location A')
        self.assertEqual(sources['B']['server'], server_b)

    def test_zoom_buttons_match_home_and_audio_mix_sits_lower(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        layout = ui.dual_vfo_layout()
        for vfo in ('a', 'b'):
            waterfall = layout[f'{vfo}_waterfall']
            for label, home_box, key in (
                ('-', ui.ZOOM_MINUS_BOX, f'zoom_{vfo}_minus'),
                ('+', ui.ZOOM_PLUS_BOX, f'zoom_{vfo}_plus'),
            ):
                box = layout[key]
                self.assertEqual((box[0], box[2], box[3] - box[1]),
                                 (home_box[0], home_box[2], home_box[3] - home_box[1]))
                self.assertGreaterEqual(box[1], waterfall[1])
                self.assertLessEqual(box[3], waterfall[3])
                x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                self.assertEqual(ui.dual_vfo_action_at(x, y),
                                 f'zoom_{vfo.upper()}_{-1 if label == "-" else 1}')
            with patch.object(ui, 'draw_zoom_button') as draw_button:
                ui.draw_dual_vfo_zoom_controls(
                    None, layout[f'zoom_{vfo}_minus'], layout[f'zoom_{vfo}_plus'])
            self.assertEqual(draw_button.call_count, 2)
            draw_button.assert_any_call(None, layout[f'zoom_{vfo}_minus'], '-')
            draw_button.assert_any_call(None, layout[f'zoom_{vfo}_plus'], '+')

        mix = layout['mix_track']
        self.assertGreaterEqual(mix[1], layout['split'][1])
        self.assertGreaterEqual(mix[1] - layout['clone'][3], 16)
        self.assertLess(mix[3], layout['freq_b'][1])

    def test_each_vfo_has_home_sized_meter_and_matching_mode_grid(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        layout = ui.dual_vfo_layout()
        home_meter = ui.lcd_compact_smeter_box()
        home_modes = tuple(ui.lcd_home_mode_boxes(True))
        for vfo in ('A', 'B'):
            meter = layout[f'smeter_{vfo.lower()}']
            self.assertEqual((meter[0], meter[2]), (home_meter[0], home_meter[2]))
            self.assertEqual(meter[3] - meter[1], home_meter[3] - home_meter[1])
            modes = ui.dual_vfo_mode_boxes(vfo)
            self.assertEqual([label for label, _box in modes],
                             [label for label, _box in home_modes])
            for (label, box), (_home_label, home_box) in zip(modes, home_modes):
                self.assertEqual((box[0], box[2], box[3] - box[1]),
                                 (home_box[0], home_box[2], home_box[3] - home_box[1]))
                x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                self.assertEqual(ui.dual_vfo_action_at(x, y), f'mode_{vfo}_{label}')
            self.assertEqual(min(box[1] for _label, box in modes), layout[f'mode_{vfo.lower()}'][1])
            self.assertEqual(max(box[3] for _label, box in modes), layout[f'mode_{vfo.lower()}'][3])

    def test_dual_meter_forces_default_compact_face_and_mode_change_is_isolated(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        meter = ui.dual_vfo_layout()['smeter_a']
        with patch.dict(ui.theme_system.runtime_theme, {'smeter_style': 'bakelite_square'}), \
                patch.object(ui, 'draw_selected_smeter') as draw_meter:
            ui.draw_dual_vfo_smeter(None, meter, -95)
            self.assertEqual(ui.theme_system.runtime_theme['smeter_style'], 'bakelite_square')
        draw_meter.assert_called_once_with(
            None, meter, -95, style_id=ui.DEFAULT_METER_STYLE,
        )

        primary = ui.SharedState('http://a.test', 7075, 7, -95, 142, 245, 4, 'am', True)
        secondary = ui.SharedState('http://b.test', 7075, 7, -95, 142, 245, 4, 'lsb', True)
        profiles = {'A': {'mode': 'am'}, 'B': {'mode': 'LSB'}}
        ui.set_dual_vfo_mode(primary, secondary, profiles, 'B', 'NBFM')
        self.assertEqual(primary.radio_snapshot()[0], 'am')
        self.assertEqual(secondary.radio_snapshot()[0], 'nbfm')
        self.assertEqual(profiles['B']['mode'], 'NBFM')
        self.assertEqual(profiles['A']['mode'], 'am')
        ui.set_dual_vfo_mode(primary, secondary, profiles, 'A', 'CW')
        self.assertEqual(primary.radio_snapshot()[0], 'cw')
        self.assertEqual(secondary.radio_snapshot()[0], 'nbfm')
        self.assertEqual(profiles['A']['mode'], 'cw')
        self.assertEqual(profiles['B']['mode'], 'NBFM')


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
    def test_palette_change_does_not_restart_live_row_presentation(self):
        state = ui.SharedState(
            'http://example.test:8073', 7075.0, 4, -95.0,
            142, 245, 3, 'am', True,
        )
        rows = ui.queue.Queue()
        for value in range(3):
            rows.put(value)
        presenter = ui.WaterfallPresenter(reserve_seconds=0.10)
        key = ui.waterfall_stream_key(state.snapshot()[5], state.snapshot()[4], 'kiwi', False)
        self.assertEqual(presenter.take(rows, 1.0, 23.0, key), (0,))
        ui.apply_waterfall_palette_preset(state, 'gqrx')
        self.assertEqual(
            ui.waterfall_stream_key(state.snapshot()[5], state.snapshot()[4], 'kiwi', False),
            key,
        )
        self.assertEqual(presenter.take(rows, 1.05, 23.0, key), (1,))

    def test_presenter_builds_reserve_then_releases_at_source_cadence(self):
        rows = ui.queue.Queue()
        presenter = ui.WaterfallPresenter(reserve_seconds=0.26)
        for value in range(5):
            rows.put(value)

        # 23 fps needs six rows for the 260 ms reserve.
        self.assertEqual(presenter.take(rows, 10.0, 23.0, "stream"), ())
        rows.put(5)
        self.assertEqual(presenter.take(rows, 10.0, 23.0, "stream"), (0,))
        self.assertEqual(presenter.take(rows, 10.02, 23.0, "stream"), ())
        self.assertEqual(presenter.take(rows, 10.05, 23.0, "stream"), (1,))

    def test_presenter_rebuffers_after_a_real_underrun(self):
        rows = ui.queue.Queue()
        presenter = ui.WaterfallPresenter(reserve_seconds=0.10)
        for value in range(3):
            rows.put(value)
        self.assertEqual(presenter.take(rows, 1.0, 23.0, "stream"), (0,))
        self.assertEqual(presenter.take(rows, 1.1, 23.0, "stream"), (1, 2))
        self.assertEqual(presenter.take(rows, 1.2, 23.0, "stream"), ())
        rows.put(3)
        rows.put(4)
        self.assertEqual(presenter.take(rows, 1.3, 23.0, "stream"), ())
        rows.put(5)
        self.assertEqual(presenter.take(rows, 1.3, 23.0, "stream"), (3,))

    def test_fmdx_presenter_uses_audio_fft_cadence(self):
        self.assertAlmostEqual(
            ui.waterfall_presentation_fps("fmdx", 1),
            ui.fmdx.AUDIO_SAMPLE_RATE / 2048.0,
        )
        self.assertEqual(ui.waterfall_presentation_fps("kiwi", 4), 23.0)

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
                ui.draw_ui(None,7075,20,-95,-95,None,'LSB','DIG',100,instrument_layout='right',**kwargs)
                mocks['draw_lcd_mode_annunciators'].assert_not_called()

    def test_settings_back_uses_shared_renderer(self):
        with patch.object(ui,'draw_sidebar_header'), patch.object(ui,'draw_logical_rect'), patch.object(ui,'draw_logical_line'), \
             patch.object(ui,'draw_logical_rounded_rect'), \
             patch.object(ui,'lcd_nav_tile_background',return_value=(1,1,1)), \
             patch.object(ui,'menu_icon_texture',return_value=(1,1,1)), \
             patch.object(ui,'draw_textured_quad'), patch.object(ui,'draw_text'), patch.object(ui,'draw_radio_close_button') as back:
            ui.draw_lcd_navigation(None,settings_open=True)
        back.assert_called_once_with(None,ui.lcd_drawer_back_box())

class NavigationAndLandingBoundaryTests(unittest.TestCase):
    def test_touch_keyboards_keep_the_shared_back_target_reachable(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        back = ui.lcd_drawer_back_box()
        x = (back[0] + back[2]) / 2
        y = (back[1] + back[3]) / 2

        self.assertEqual(ui.keyboard_modal_back_box(), back)
        self.assertEqual(ui.deepgram_setup_action_at(x, y, "lower"), "CANCEL")
        self.assertEqual(ui.station_search_back_box(), back)
        self.assertTrue(ui.network_password_back_requested(x, y))
        self.assertIn(("CANCEL", back), ui.frequency_entry_layout()[2])

    def test_touch_keyboards_draw_the_shared_back_sidebar(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        with patch.object(ui, "draw_logical_rect"), \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_logical_rounded_rect"), \
                patch.object(ui, "draw_text"), \
                patch.object(ui, "draw_sidebar_header"), \
                patch.object(ui, "draw_radio_close_button"), \
                patch.object(ui, "draw_picker_button"), \
                patch.object(ui, "draw_network_password_eye"), \
                patch.object(ui, "fit_station_text", side_effect=lambda _cache, text, *_args, **_kwargs: text), \
                patch.object(ui, "draw_keyboard_modal_sidebar") as sidebar:
            ui.draw_deepgram_setup(None, "", "lower")
            ui.draw_network_password(None, "TEST", "", "lower", False, False, False)
            ui.draw_station_search(None, (), "", "location", "lower")

        self.assertEqual(
            sidebar.call_args_list,
            [
                call(None, "NETWORK", "WI-FI KEY"),
                call(None, "SEARCH", "RECEIVERS"),
            ],
        )

    def test_deepgram_keypad_uses_only_the_right_rail(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        for mode in ("lower", "upper", "digits"):
            boxes = ui.deepgram_sidebar_boxes(mode)
            self.assertEqual(boxes["panel"], (ui.LCD_NAV_X0, 0, ui.LOGICAL_W, ui.LOGICAL_H))
            self.assertEqual(ui.deepgram_setup_surface_box(), boxes["panel"])
            self.assertIsNone(ui.deepgram_setup_action_at(200, 100, mode))
            self.assertEqual(boxes["close"], ui.lcd_drawer_back_box())
            self.assertEqual(boxes["field"][2] - boxes["field"][0], 236)
            field = boxes["field"]
            self.assertEqual(ui.deepgram_setup_action_at((field[0] + field[2]) / 2,
                                                          (field[1] + field[3]) / 2, mode), "PASTE")
            for action, box in (*boxes["actions"].items(), *boxes["keys"]):
                self.assertGreaterEqual(box[0], ui.LCD_NAV_X0 + 10)
                self.assertLessEqual(box[2], ui.LOGICAL_W - 10)
                self.assertEqual((box[2] - box[0], box[3] - box[1]), (55, 31))
                self.assertEqual(ui.deepgram_setup_action_at((box[0] + box[2]) / 2,
                                                              (box[1] + box[3]) / 2, mode), action)
            self.assertLess(max(box[3] for _action, box in boxes["keys"]), boxes["close"][1])

        with patch.object(ui, "draw_logical_rect") as rect, \
                patch.object(ui, "draw_logical_line"), \
                patch.object(ui, "draw_text"), \
                patch.object(ui, "draw_sidebar_header"), \
                patch.object(ui, "draw_lcd_drawer_heading"), \
                patch.object(ui, "draw_styled_text_button"), \
                patch.object(ui, "draw_radio_close_button"):
            ui.draw_deepgram_setup(None, "secret", "lower")
        self.assertTrue(rect.call_args_list)
        self.assertTrue(all(call_args.args[0] >= ui.LCD_NAV_X0 for call_args in rect.call_args_list))

    def test_all_primary_back_targets_match_after_configuration(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        expected = ui.lcd_drawer_back_box()
        for box in (ui.TEST_BACK_BOX, ui.RADIOGARDEN_EXIT_BOX,
                    ui.RTL_LAB_BACK_BOX, ui.FONT_LAB_BACK_BOX, ui.WSPR_EXPANDED_LOG_BACK_BOX,
                    ui.network_panel_boxes()["back"]):
            self.assertEqual(box, expected)
        self.assertEqual(ui.PICKER_EXIT_BOX, ui.RECEIVER_PICKER_BACK_BOX)
        self.assertEqual(ui.PICKER_EXIT_BOX[1:], expected[1:])
        self.assertGreaterEqual(ui.PICKER_EXIT_BOX[0], ui.RECEIVER_PICKER_MAIN_W)
        for count in (2, 7, 8):
            for index in range(count - 1):
                self.assertLess(ui.lcd_nav_box(index, count, True)[3], expected[1])

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

    def test_passband_waits_for_receiver_data_and_hides_on_pause_or_switch(self):
        state = ui.SharedState('http://kiwi.test', 7075, 8, -95, 142, 245, 3, 'lsb', True)
        self.assertFalse(state.rf_stream_ready_snapshot())
        generation = state.snapshot()[-1]
        state.connection_ready(generation, 'waterfall')
        self.assertTrue(state.rf_stream_ready_snapshot())
        state.set_stream_paused(True)
        self.assertFalse(state.rf_stream_ready_snapshot())
        state.set_server('http://next.test')
        self.assertFalse(state.rf_stream_ready_snapshot())
        generation = state.snapshot()[-1]
        state.connection_ready(generation, 'audio')
        self.assertTrue(state.rf_stream_ready_snapshot())

class CapabilityControlTests(unittest.TestCase):
    def state(self, server='http://kiwi.test', freq=7075):
        return ui.SharedState(server, freq, 8, -95, 142, 245, 3, 'lsb', True)

    def record(self, server, protocol):
        return ui.receiver_catalog.normalize_receiver({'server': server, 'protocol': protocol})

    def test_unsupported_control_does_not_mutate_state(self):
        state = self.state('http://fm.test', 101700)
        state.set_server('http://fm.test', receiver_type='fmdx')
        before = state.radio_snapshot()
        decision = ui.apply_receiver_control(
            state, self.record('http://fm.test', 'fmdx'), 'passband', (-2400, 2400))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.message, 'Fixed passband on this receiver')
        self.assertEqual(state.radio_snapshot(), before)

    def test_fmdx_frequency_is_shared_and_blocked_by_default(self):
        state = self.state('http://fm.test', 101700)
        state.set_server('http://fm.test', receiver_type='fmdx')
        before = state.snapshot()[1]
        decision = ui.apply_receiver_control(
            state, self.record('http://fm.test', 'fmdx'), 'frequency', 101900.0)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.message,
                         'Shared tuner: changing frequency affects every listener')
        self.assertEqual(state.snapshot()[1], before)

    def test_supported_passband_control_mutates_state(self):
        state = self.state()
        before = state.radio_snapshot()
        decision = ui.apply_receiver_control(
            state, self.record('http://kiwi.test', 'kiwi'), 'passband', (-2400, 2400))
        self.assertTrue(decision.allowed)
        self.assertNotEqual(state.radio_snapshot(), before)

    def test_notice_lines_name_the_control_and_reason(self):
        record = self.record('http://fm.test', 'fmdx')
        decision = record.capabilities.decide('passband')
        self.assertEqual(ui.control_notice_lines(record, 'passband', decision),
                         ('PASSBAND', 'Fixed passband on this receiver'))


class ReceiverMapLegendTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        ui.receiver_map_reset_groups()

    def tearDown(self):
        ui.receiver_map_reset_groups()

    def receivers(self):
        return [
            {'name': 'A', 'location': '', 'server': 'http://a.kiwi:8073', 'lat': 0.0, 'lon': 0.0, 'receiver_type': 'kiwi'},
            {'name': 'B', 'location': '', 'server': 'owrxs://b.test', 'lat': 1.0, 'lon': 1.0, 'receiver_type': 'openwebrx'},
            {'name': 'C', 'location': '', 'server': ui.LOCAL_KIWI_SERVER, 'lat': 2.0, 'lon': 2.0, 'receiver_type': 'kiwi'},
            {'name': 'D', 'location': '', 'server': 'https://d.fmdx', 'lat': 3.0, 'lon': 3.0, 'receiver_type': 'fmdx'},
        ]

    def test_group_classifies_every_source(self):
        self.assertEqual(
            [ui.receiver_map_group(receiver) for receiver in self.receivers()],
            ['kiwi', 'openwebrx', 'local', 'fmdx'],
        )

    def test_globe_has_no_rail_background_at_any_zoom(self):
        """The map remains visible behind floating controls at every zoom."""
        for scale in (ui.RADIOGARDEN_ZOOM_MIN, ui.GLOBE_DEFAULT_SCALE,
                      20.5, ui.RADIOGARDEN_ZOOM_MAX):
            events = []
            with patch.object(
                    ui, 'draw_receiver_map_satellite',
                    side_effect=lambda *_a, **_k: events.append('map') or False,
                ), patch.object(
                    ui, 'draw_logical_rect',
                    side_effect=lambda *args: events.append(('rect', args)),
                ), patch.object(ui, 'draw_logical_line'), \
                 patch.object(ui, 'draw_logical_rounded_rect'), \
                 patch.object(ui, 'draw_logical_polyline'), \
                 patch.object(ui, 'draw_logical_circle'), \
                 patch.object(ui, 'draw_logical_points'), \
                 patch.object(ui, 'draw_text'), \
                 patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
                 patch.object(ui, 'draw_sidebar_header') as sidebar_header, \
                 patch.object(ui, 'draw_styled_text_button'), \
                 patch.object(ui, 'draw_picker_two_line_button'), \
                 patch.object(ui, 'draw_radio_close_button'):
                ui.draw_receiver_map(
                    None, self.receivers(), 0.0, 0.0, scale,
                    '', None, 'idle', {}, map_view='satellite_only',
                )
            rail_rects = [event for event in events if event[0] == 'rect'
                          and event[1][:4] == (ui.LCD_NAV_X0, 0, ui.LOGICAL_W, ui.LOGICAL_H)]
            self.assertEqual(rail_rects, [])
            sidebar_header.assert_not_called()

    def test_legend_lists_only_present_groups(self):
        entries = ui.receiver_map_legend_entries(self.receivers())
        self.assertEqual([group for group, _label, _color in entries],
                         ['kiwi', 'openwebrx', 'local', 'fmdx'])
        self.assertEqual(
            ui.receiver_map_legend_entries(self.receivers()[:1]),
            (('kiwi', 'KIWI', ui.RECEIVER_MAP_GROUP_COLORS['kiwi']),),
        )

    def test_openwebrx_has_its_blue_globe_identity_and_legend_button(self):
        self.assertEqual(ui.RECEIVER_MAP_GROUP_COLORS['openwebrx'], (41, 121, 255, 255))
        entries = ui.receiver_map_legend_entries(self.receivers())
        self.assertIn(
            ('openwebrx', 'OPENWEBRX', (41, 121, 255, 255)),
            entries,
        )

    def test_legend_uses_the_shared_gray_active_and_pressed_style(self):
        visual = ui.receiver_map_legend_visual('openwebrx', True)
        self.assertEqual(visual, ui.APP_UI_STYLE.button.resolve(active=True))
        self.assertEqual(visual, ui.receiver_map_legend_visual('kiwi', True))
        inactive = ui.receiver_map_legend_visual('openwebrx', False)
        self.assertEqual(inactive, ui.APP_UI_STYLE.button.resolve())
        pressed = ui.receiver_map_legend_visual('openwebrx', False, pressed=True)
        self.assertEqual(pressed, ui.APP_UI_STYLE.button.resolve(pressed=True))

    def test_legend_square_follows_receiver_dot_visibility(self):
        for group in ('kiwi', 'openwebrx', 'fmdx'):
            self.assertEqual(ui.receiver_map_legend_swatch_color(group, True),
                             ui.RECEIVER_MAP_GROUP_COLORS[group])
            self.assertEqual(ui.receiver_map_legend_swatch_color(group, False),
                             ui.APP_UI_STYLE.palette.secondary_text)

    def test_legend_draws_small_color_squares_before_labels(self):
        receivers = self.receivers()
        ui.receiver_map_toggle_group('fmdx')
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect') as rectangles, \
             patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline'), \
             patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_logical_points'), \
             patch.object(ui, 'draw_text'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'):
            ui.draw_receiver_map(None, receivers, 0.0, 0.0, 1.0,
                                 '', None, 'idle', {}, map_view='satellite_only')
        calls = [call.args for call in rectangles.call_args_list]
        for group, (x0, y0, x1, y1) in ui.receiver_map_legend_boxes(receivers):
            color = (ui.APP_UI_STYLE.palette.secondary_text if group == 'fmdx'
                     else ui.RECEIVER_MAP_GROUP_COLORS[group])
            self.assertIn((x0 + 12, (y0+y1)/2 - 6, x0 + 24, (y0+y1)/2 + 6, color), calls)

    def test_globe_zoom_reaches_1200x_and_uses_home_osd_panel(self):
        self.assertEqual(ui.RADIOGARDEN_ZOOM_MAX, 1200.0)
        scale = ui.GLOBE_DEFAULT_SCALE
        for _ in range(6):
            scale = ui.clamp(scale * ui.RADIOGARDEN_ZOOM_TAP_FACTOR,
                             ui.RADIOGARDEN_ZOOM_MIN, ui.RADIOGARDEN_ZOOM_MAX)
        self.assertEqual(scale, 1200.0)
        with patch.object(ui, 'draw_green_osd_panel') as panel, \
             patch.object(ui, 'draw_text') as text, \
             patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rect'):
            ui.draw_globe_zoom_osd(None, 1200.0)
        panel.assert_called_once_with(ui.ZOOM_OSD_BOX, 220)
        labels = [call.args[3] for call in text.call_args_list]
        self.assertIn('GLOBE ZOOM', labels)
        self.assertIn('1200x', labels)

    def test_globe_zoom_changes_map_projection_by_the_displayed_factor(self):
        box = (0, 0, 1024, 800)
        receiver = {'lat': 0.0, 'lon': 0.005}
        centre_x = (box[0] + box[2]) / 2
        half_zoom = ui.radiogarden_project(receiver, 0.0, 0.0, box, 600.0)
        full_zoom = ui.radiogarden_project(receiver, 0.0, 0.0, box, 1200.0)
        self.assertAlmostEqual(
            full_zoom[0] - centre_x, 2 * (half_zoom[0] - centre_x),
        )
        self.assertAlmostEqual(
            ui.radiogarden_radius(box, 1200.0),
            1200 * ui.radiogarden_radius(box, 1.0),
        )
        self.assertGreater(full_zoom[0] - centre_x, 50)

    def test_globe_pan_stays_screen_proportional_at_1200x(self):
        box = (0, 0, 1024, 800)
        receiver = {'lat': 0.0, 'lon': 0.0}
        yaw, pitch = ui.radiogarden_pan_angles(
            0.0, 0.0, 100.0, 0.0, box, 1200.0,
        )
        point = ui.radiogarden_project(receiver, yaw, pitch, box, 1200.0)
        self.assertAlmostEqual(point[0], 612.0, delta=1.0)

    def test_cm5_satellite_keeps_base_image_while_tiles_load(self):
        box = (0, 0, 1024, 800)
        with patch.object(ui, 'satellite_map_texture', return_value=1), \
             patch.object(ui, 'draw_receiver_map_satellite_tiles') as tiles, \
             patch.object(ui._globe_meshes, 'draw'), \
             patch.dict(ui.os.environ, {'ITUNER_GLOBE_HD_TILES': '1'}):
            self.assertTrue(ui.draw_receiver_map_satellite(
                None, 0.0, 0.0, box, 1200.0, interactive=False,
            ))
            tiles.assert_called_once()
        with patch.object(ui, 'satellite_map_texture', return_value=1), \
             patch.object(ui, 'draw_receiver_map_satellite_tiles') as tiles, \
             patch.object(ui._globe_meshes, 'draw'), \
             patch.dict(ui.os.environ, {'ITUNER_GLOBE_HD_TILES': '0'}):
            self.assertTrue(ui.draw_receiver_map_satellite(
                None, 0.0, 0.0, box, 1200.0, interactive=True,
            ))
            tiles.assert_not_called()

    def test_legend_label_names_the_action(self):
        # A lit chip offers to hide its group; a hidden chip offers to show it.
        self.assertEqual(ui.receiver_map_legend_label('kiwi', True), 'HIDE KIWI')
        self.assertEqual(ui.receiver_map_legend_label('fmdx', True), 'HIDE FM-DX')
        self.assertEqual(ui.receiver_map_legend_label('kiwi', False), 'SHOW KIWI')
        self.assertEqual(ui.receiver_map_legend_label('fmdx', False), 'SHOW FM-DX')

    def _legend_texts(self):
        texts = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline'), patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_text',
                          side_effect=lambda _c, _x, _y, text, *_a, **_k: texts.append(str(text))), \
             patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'radiogarden_project', return_value=(300.0, 200.0, 1.0)), \
             patch.object(ui, 'draw_logical_points'):
            ui.draw_receiver_map(
                None, self.receivers(), 0.0, 0.0, 1.0, '', None, 'idle', {},
                map_view='satellite_only',
            )
        return texts

    def test_legend_tiles_show_full_source_names(self):
        texts = self._legend_texts()
        self.assertIn('KIWI', texts)
        self.assertIn('OPENWEBRX', texts)
        self.assertIn('LAN', texts)
        self.assertIn('FM-DX', texts)
        ui.receiver_map_toggle_group('kiwi')
        texts = self._legend_texts()
        self.assertIn('KIWI', texts)

    def _legend_text_sizes(self):
        sizes = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline'), patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_text',
                          side_effect=lambda _c, _x, _y, text, _color, size, *_a, **_k: sizes.append((str(text), size))), \
             patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'radiogarden_project', return_value=(300.0, 200.0, 1.0)), \
             patch.object(ui, 'draw_logical_points'):
            ui.draw_receiver_map(
                None, self.receivers(), 0.0, 0.0, 1.0, '', None, 'idle', {},
                map_view='satellite_only',
            )
        return sizes

    def test_legend_rows_keep_the_receiver_category_font_size(self):
        sizes = [
            size for text, size in self._legend_text_sizes()
            if any(text in lines for lines in ui.RECEIVER_MAP_LEGEND_TEXT_LINES.values())
        ]
        self.assertTrue(sizes)
        self.assertTrue(all(size == ui.RECEIVER_LIST_THEME.label_size for size in sizes))

    def test_legend_text_is_left_aligned_after_its_color_square(self):
        labels = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline'), patch.object(ui, 'draw_logical_circle'), \
             patch.object(
                 ui, 'draw_text',
                 side_effect=lambda *args, **_kwargs: labels.append(args),
             ), patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'radiogarden_project', return_value=(300.0, 200.0, 1.0)), \
             patch.object(ui, 'draw_logical_points'):
            ui.draw_receiver_map(
                None, self.receivers(), 0.0, 0.0, 1.0, '', None, 'idle', {},
                map_view='satellite_only',
            )
        legend_boxes = dict(ui.receiver_map_legend_boxes(self.receivers()))
        for group, label in ui.RECEIVER_MAP_GROUP_LABELS.items():
            if group not in legend_boxes:
                continue
            call = next(args for args in labels if args[3] == label)
            self.assertEqual(call[8], 'lm')
            self.assertEqual(call[1], legend_boxes[group][0] + 34)

    def _draw_dots(self, scale):
        drawn = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline'), patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_text'), patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'radiogarden_project', return_value=(300.0, 200.0, 1.0)), \
             patch.object(ui, 'draw_logical_points',
                          side_effect=lambda points, color, size: drawn.append((tuple(color), size))):
            ui.draw_receiver_map(
                None, self.receivers(), 0.0, 0.0, scale, '', None, 'idle', {},
                map_view='satellite_only',
            )
        return drawn

    def test_dot_size_follows_actual_globe_scale(self):
        overview_scales = (0, 0.55, 1.0, 2.2, 4.0, 12.0, 20.49)
        self.assertTrue(all(
            ui.receiver_map_dot_pixels(scale) == ui.GLOBE_DOT_BASE_PIXELS
            for scale in overview_scales
        ))
        self.assertEqual(
            ui.receiver_map_dot_pixels(20.5),
            ui.GLOBE_DOT_GROW_START_PIXELS,
        )
        self.assertGreater(
            ui.receiver_map_dot_pixels(20.5 * ui.GLOBE_DOT_SCALE_STEP * 1.01),
            ui.receiver_map_dot_pixels(20.5),
        )
        self.assertEqual(ui.receiver_map_dot_pixels(999999), ui.GLOBE_DOT_MAX_PIXELS)

    def test_render_uses_scale_derived_dot_size(self):
        expected = sorted(
            tuple(ui.RECEIVER_MAP_GROUP_COLORS[group])
            for group in ('kiwi', 'openwebrx', 'local', 'fmdx')
        )
        for scale in (0.55, ui.GLOBE_DEFAULT_SCALE, 12.0, 20.5, 68.8):
            drawn = self._draw_dots(scale)
            self.assertEqual(sorted(color for color, _size in drawn), expected)
            expected_size = ui.receiver_map_dot_pixels(scale)
            self.assertTrue(all(actual == expected_size for _color, actual in drawn), scale)

    COASTLINE_COLOR = (94, 204, 188, 182)

    def _polyline_colors(self, map_view, scale=0.9, interactive=False):
        colors = []
        with patch.object(ui._globe_borders, 'draw',
                          side_effect=lambda _matrix, color: colors.append(tuple(color))), \
             patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline',
                          side_effect=lambda _points, color, *_a, **_k: colors.append(tuple(color))), \
             patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_text'), patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'radiogarden_project', return_value=(300.0, 200.0, 1.0)), \
             patch.object(ui, 'draw_logical_points'):
            ui.draw_receiver_map(
                None, self.receivers(), 0.0, 0.0, scale, '', None, 'idle', {},
                map_view=map_view, interactive=interactive,
            )
        return colors

    def test_no_view_draws_the_removed_clean_coastline_layer(self):
        # The CLEAN coastline layer is gone from every presentation.
        for view in ('borders', 'satellite_only', 'satellite'):
            self.assertNotIn(self.COASTLINE_COLOR, self._polyline_colors(view), view)

    def test_outline_views_still_draw_country_borders(self):
        for moving in (False, True):
            for view in ('borders', 'satellite'):
                colors = self._polyline_colors(view, interactive=moving)
                self.assertIn((160, 190, 180, 140), colors)
            self.assertNotIn((160, 190, 180, 140),
                             self._polyline_colors('satellite_only', interactive=moving))

    def test_legend_toggle_hides_and_shows_a_group(self):
        self.assertTrue(ui.receiver_map_group_visible('fmdx'))
        self.assertFalse(ui.receiver_map_toggle_group('fmdx'))
        self.assertFalse(ui.receiver_map_group_visible('fmdx'))
        self.assertTrue(ui.receiver_map_toggle_group('fmdx'))
        self.assertTrue(ui.receiver_map_group_visible('fmdx'))

    def test_legend_chips_are_hit_testable_and_do_not_overlap(self):
        receivers = self.receivers()
        boxes = ui.receiver_map_legend_boxes(receivers)
        self.assertEqual([group for group, _box in boxes],
                         ['kiwi', 'openwebrx', 'local', 'fmdx'])
        for group, box in boxes:
            # The legend lives in the Globe's right rail, not over the map.
            self.assertGreaterEqual(box[0], ui.LCD_NAV_X0)
            self.assertLessEqual(box[2], ui.LOGICAL_W)
            self.assertEqual(box[2] - box[0], 148)
            self.assertEqual(box[2], ui.LOGICAL_W - ui.RECEIVER_PICKER_MARGIN)
            self.assertEqual(box[3] - box[1], ui.RECEIVER_PICKER_CATEGORY_HEIGHT)
            self.assertEqual(box[1], ui.RECEIVER_MAP_LEGEND_RAIL_TOP +
                             list(ui.RECEIVER_MAP_GROUP_ORDER).index(group) *
                             (ui.RECEIVER_PICKER_CATEGORY_HEIGHT + ui.RECEIVER_PICKER_CATEGORY_GAP))
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            self.assertEqual(ui.receiver_map_legend_at(*center, receivers), group)
        for index, (_group, first) in enumerate(boxes):
            for _other, second in boxes[index + 1:]:
                self.assertFalse(first[0] < second[2] and second[0] < first[2]
                                 and first[1] < second[3] and second[1] < first[3])
        self.assertIsNone(ui.receiver_map_legend_at(boxes[-1][1][2] + 40, boxes[-1][1][1], receivers))

    def test_hidden_group_leaves_the_tap_surface(self):
        receivers = self.receivers()

        def project(receiver, *args, **kwargs):
            return (100.0 + receiver['lat'] * 1000.0, 120.0, 1.0)

        with patch.object(ui, 'radiogarden_project', side_effect=project):
            fmdx_x = 100.0 + 3.0 * 1000.0
            self.assertIsNotNone(ui.receiver_map_station_at(
                fmdx_x, 120, receivers, 0.0, 0.0, ui.PICKER_MAP_BOX, 1.0))
            ui.receiver_map_toggle_group('fmdx')
            self.assertIsNone(ui.receiver_map_station_at(
                fmdx_x, 120, receivers, 0.0, 0.0, ui.PICKER_MAP_BOX, 1.0))
            # The focus candidate also skips the hidden FM-DX receiver.
            self.assertNotEqual(
                ui.receiver_map_group(ui.receiver_map_center_candidate(receivers, 3.0, 3.0)),
                'fmdx',
            )

    def test_each_visible_receiver_draws_exactly_one_dot(self):
        receivers = self.receivers()
        drawn = []

        def record_points(points, color, size):
            drawn.append((len(points), size))

        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline'), patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_text'), patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'radiogarden_project', return_value=(300.0, 200.0, 1.0)), \
             patch.object(ui, 'draw_logical_points', side_effect=record_points):
            ui.draw_receiver_map(
                None, receivers, 0.0, 0.0, 1.0, '', None, 'idle', {},
                map_view='satellite_only',
            )
        # One point per receiver -- every marker shares the same current size.
        self.assertEqual(sum(count for count, _size in drawn), len(receivers))
        expected_size = ui.receiver_map_dot_pixels(1.0)
        self.assertTrue(all(size == expected_size for _count, size in drawn))
        # Each legend group has its own colour, so they batch into four calls.
        self.assertEqual(len(drawn), 4)

    def test_hidden_group_removes_its_dots_from_the_draw(self):
        receivers = self.receivers()
        ui.receiver_map_toggle_group('kiwi')
        ui.receiver_map_toggle_group('openwebrx')
        ui.receiver_map_toggle_group('local')
        drawn = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_logical_polyline'), patch.object(ui, 'draw_logical_circle'), \
             patch.object(ui, 'draw_text'), patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'fit_station_text', side_effect=lambda _c, text, *_a, **_k: text), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'radiogarden_project', return_value=(300.0, 200.0, 1.0)), \
             patch.object(ui, 'draw_logical_points',
                          side_effect=lambda points, color, size: drawn.append(len(points))):
            ui.draw_receiver_map(
                None, receivers, 0.0, 0.0, 1.0, '', None, 'idle', {},
                map_view='satellite_only',
            )
        # Only the still-visible FM-DX receiver is left on the globe.
        self.assertEqual(sum(drawn), 1)


class GlobeDefaultViewTests(unittest.TestCase):
    """The receiver browser's resting view is the operator's own location."""

    def test_resting_view_is_satellite_with_borders(self):
        self.assertEqual(ui.GLOBE_DEFAULT_VIEW, 'satellite')
        self.assertIn(ui.GLOBE_DEFAULT_VIEW, ui.MAP_VIEWS)

    def test_resting_scale_is_a_regional_close_up(self):
        self.assertEqual(ui.GLOBE_DEFAULT_SCALE, 2.2)
        self.assertGreaterEqual(ui.GLOBE_DEFAULT_SCALE, ui.RADIOGARDEN_ZOOM_MIN)
        self.assertLessEqual(ui.GLOBE_DEFAULT_SCALE, ui.RADIOGARDEN_ZOOM_MAX)

    def test_home_center_frames_the_fallback_location(self):
        home = ui.RECEIVER_HOME_FALLBACK
        self.assertEqual(
            ui.receiver_map_home_center(home),
            (math.radians(home['lon']), math.radians(home['lat'])),
        )

    def test_home_center_frames_a_saved_profile(self):
        profile = {'name': 'Testville', 'lat': -33.9, 'lon': 151.2, 'source': 'saved'}
        yaw, pitch = ui.receiver_map_home_center(profile)
        self.assertAlmostEqual(math.degrees(yaw), 151.2)
        self.assertAlmostEqual(math.degrees(pitch), -33.9)

    def test_home_center_rejects_invalid_profiles(self):
        self.assertIsNone(ui.receiver_map_home_center(None))
        self.assertIsNone(ui.receiver_map_home_center({'lat': 200.0, 'lon': 0.0}))
        self.assertIsNone(ui.receiver_map_home_center({'lat': 'north', 'lon': 0.0}))

    def test_selected_server_center_accepts_normalized_urls(self):
        receivers = [
            {'server': 'https://example.test/', 'lat': 45.75, 'lon': 21.23},
        ]
        yaw, pitch = ui.receiver_map_server_center(receivers, 'https://example.test')
        self.assertAlmostEqual(math.degrees(yaw), 21.23)
        self.assertAlmostEqual(math.degrees(pitch), 45.75)

    def test_selected_server_center_rejects_unknown_or_invalid_receivers(self):
        self.assertIsNone(ui.receiver_map_server_center([], 'https://missing.test'))
        self.assertIsNone(ui.receiver_map_server_center(
            [{'server': 'https://bad.test', 'lat': 100, 'lon': 0}],
            'https://bad.test',
        ))

    def test_globe_uses_the_live_receiver_and_home_only_as_fallback(self):
        import inspect
        source = inspect.getsource(ui)
        self.assertIn('def focus_receiver_map_on_home', source)
        self.assertIn('def focus_receiver_map_on_server', source)
        self.assertIn('def focus_receiver_map_on_active', source)
        self.assertIn('focus_receiver_map_on_server(active_server) or focus_receiver_map_on_home()', source)
        self.assertIn('picker_map_selected_server = target_server', source)


class SharedButtonPressFeedbackTests(unittest.TestCase):
    def setUp(self):
        ui.theme_system.apply_theme(ui.theme_system.DEFAULT_THEME)

    def tearDown(self):
        ui.set_ui_press_point()

    def test_press_point_only_activates_the_button_under_the_finger(self):
        ui.set_ui_press_point(25, 35)
        self.assertTrue(ui.ui_button_pressed((20, 30, 40, 50)))
        self.assertFalse(ui.ui_button_pressed((50, 50, 80, 80)))
        ui.set_ui_press_point()
        self.assertFalse(ui.ui_button_pressed((20, 30, 40, 50)))

    def test_shared_picker_button_uses_the_pressed_fill_and_text(self):
        box = (10, 20, 70, 80)
        fills = []
        colors = []
        ui.set_ui_press_point(40, 50)
        with patch.object(ui, 'draw_logical_rounded_rect', side_effect=lambda *_args: fills.append(_args[5])), \
             patch.object(ui, 'draw_text', side_effect=lambda _c, _x, _y, _label, color, *_a, **_k: colors.append(color)):
            ui.draw_picker_button(None, box, 'TEST')
        self.assertEqual(fills[0], ui.UI_PRESSED_FILL)
        self.assertEqual(colors[0], ui.UI_PRESSED_TEXT)

    def test_selected_picker_tab_uses_dark_fill_and_light_text(self):
        box = (10, 20, 246, 72)
        fills = []
        colors = []
        with patch.object(ui, 'draw_logical_rounded_rect', side_effect=lambda *_args: fills.append(_args[5])), \
             patch.object(ui, 'draw_text', side_effect=lambda _c, _x, _y, _label, color, *_a, **_k: colors.append(color)):
            ui.draw_picker_button(None, box, 'KIWI', selected=True)
        self.assertEqual(fills[0], ui.APP_UI_STYLE.palette.active_surface)
        self.assertEqual(colors[0], ui.APP_UI_STYLE.palette.text)

    def test_two_line_button_turns_title_and_subtitle_black_when_pressed(self):
        box = (10, 20, 104, 114)
        colors = []
        ui.set_ui_press_point(40, 50)
        with patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_text', side_effect=lambda _c, _x, _y, _label, color, *_a, **_k: colors.append(color)):
            ui.draw_picker_two_line_button(None, box, 'VIEW', 'SAT')
        self.assertEqual(colors, [ui.UI_PRESSED_TEXT, ui.UI_PRESSED_TEXT])

    def test_legacy_close_entry_point_draws_the_shared_text_back_button(self):
        box = (10, 20, 104, 114)
        with patch.object(ui, 'draw_styled_text_button') as draw:
            ui.draw_radio_close_button(None, box)
        draw.assert_called_once_with(
            None, box, 'BACK', size=ui.BACK_BUTTON_FONT_SIZE,
        )


class PassbandDrawerInteractionTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()

    def test_live_width_shift_order_matches_touch_regions(self):
        boxes = ui.lcd_filter_drawer_boxes()
        self.assertLess(boxes['visual'][3], boxes['width'][1])
        self.assertLess(boxes['width'][3], boxes['shift'][1])
        self.assertLess(boxes['shift'][3], boxes['presets'][0][2][1])

    def test_entire_visible_shift_and_width_controls_are_interactive(self):
        boxes = ui.lcd_filter_drawer_boxes()
        for name in ('shift', 'width'):
            x0, y0, x1, y1 = boxes[name]
            for point in (
                ((x0 + x1) / 2, y0 + 8),
                ((x0 + x1) / 2, (y0 + y1) / 2),
                ((x0 + x1) / 2, y1 - 8),
            ):
                self.assertEqual(ui.lcd_filter_drawer_action_at(*point), name)


class HomeRailInstrumentTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()

    def test_rail_renderer_leaves_instruments_to_the_compositor(self):
        # The passband and volume are painted by draw_ui after the mode
        # annunciators. If the rail renderer drew them first, the mode surface
        # would cover the expanded instruments sitting under the mode buttons.
        with patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_logical_rounded_rect'), \
             patch.object(ui, 'draw_nav_status_led'), \
             patch.object(ui, 'draw_sidebar_header'), patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'lcd_nav_tile_background', return_value=(1, 1, 1)), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), patch.object(ui, 'draw_text'), \
             patch.object(ui, 'draw_lcd_home_bandwidth') as bandwidth, \
             patch.object(ui, 'draw_lcd_home_volume_slider') as volume:
            ui.draw_lcd_navigation(None, volume=0.5, muted=False, low_cut=-2400, high_cut=2400)
        bandwidth.assert_not_called()
        volume.assert_not_called()

    def test_large_home_buttons_use_the_shared_black_button_style(self):
        normal = ui.APP_UI_STYLE.button.resolve()
        frames = []
        with patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_nav_status_led'), \
             patch.object(ui, 'draw_sidebar_header'), patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'draw_styled_button_frame', side_effect=lambda box, **kwargs: frames.append((box, kwargs)) or normal), \
             patch.object(ui, 'draw_text'):
            ui.draw_lcd_navigation(None)
        self.assertEqual(len(frames), len(ui.MENU_ITEMS))
        self.assertTrue(all(kwargs.get('active') is False for _box, kwargs in frames))
        self.assertTrue(all(kwargs.get('style') is ui.APP_UI_STYLE.button for _box, kwargs in frames))
        self.assertEqual(normal.fill, (0, 0, 0, 255))
        self.assertEqual(normal.border, ui.APP_UI_STYLE.palette.border)


class ReceiverBrowserEmptyStateTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()

    def test_station_selection_only_completes_on_a_real_change(self):
        # Re-selecting the already-live endpoint (the LOCAL tab's usual case)
        # is a no-op and must not dismiss the browser back to the main screen.
        self.assertFalse(ui.station_selection_changes_receiver(
            "http://kiwisdr.local:8073", "http://kiwisdr.local:8073/"))
        self.assertTrue(ui.station_selection_changes_receiver(
            "http://a.test:8073", "http://b.test:8073"))
        self.assertFalse(ui.station_selection_changes_receiver("", "http://a.test:8073"))
        self.assertFalse(ui.station_selection_changes_receiver("http://a.test:8073", ""))

    def test_empty_source_renders_the_shared_empty_text(self):
        texts = []
        with patch.object(ui, "draw_logical_rect"), patch.object(ui, "draw_logical_line"), \
             patch.object(ui, "draw_receiver_action_button"), \
             patch.object(ui, "draw_receiver_filter_button"), \
             patch.object(ui, "draw_receiver_sidebar_header"), \
             patch.object(ui, "draw_receiver_back_button"), \
             patch.object(ui, "draw_text",
                          side_effect=lambda _c, _x, _y, text, *_a, **_k: texts.append(str(text))):
            ui.draw_station_picker(None, [], 0, "", "", "location", {}, None, None, "local", None)
        self.assertIn("NO RECEIVERS IN THIS SOURCE", texts)

    def test_empty_local_list_is_actually_empty_when_the_seed_is_absent(self):
        # The empty text is driven by the filtered rows, so a source that
        # genuinely has no entries reaches it rather than a blank screen.
        rows = ui.filtered_stations([], "", "location", "local", set())
        self.assertEqual(rows, [])

    def test_local_remains_visible_without_availability_probes(self):
        server = ui.LOCAL_KIWI_SERVER
        for health in ({}, {server: {"checked": 1, "audio": False, "waterfall": False}}):
            rows = ui.filtered_stations(ui.STATIONS, "", "location", "local", set(), station_health=health)
            self.assertEqual([row[2] for row in rows], [server])

    def test_reachability_gate_leaves_other_sources_untouched(self):
        kiwi = ui.filtered_stations(ui.STATIONS, "", "location", "kiwi", set(), station_health={})
        self.assertTrue(kiwi)


if __name__ == '__main__':
    unittest.main()
