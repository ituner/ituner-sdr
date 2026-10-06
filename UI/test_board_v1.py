"""CM5 1280x800 regression coverage for board_v1."""
import math
import time
import unittest
from unittest.mock import patch
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

    def test_globe_rail_zooms_are_glyph_only(self):
        # The zoom buttons carry just the + / − symbol, with no caption text.
        receivers = [
            {'name': 'A', 'location': '', 'server': 'http://a.kiwi:8073', 'lat': 0.0, 'lon': 0.0, 'receiver_type': 'kiwi'},
            {'name': 'C', 'location': '', 'server': ui.LOCAL_KIWI_SERVER, 'lat': 2.0, 'lon': 2.0, 'receiver_type': 'kiwi'},
            {'name': 'D', 'location': '', 'server': 'https://d.fmdx', 'lat': 3.0, 'lon': 3.0, 'receiver_type': 'fmdx'},
        ]
        texts = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
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
        self.assertNotIn('ZOOM +', texts)
        self.assertNotIn('ZOOM −', texts)
        self.assertIn('+', texts)
        self.assertIn('−', texts)

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

    def test_waterfall_zoom_pressed_palette_is_opaque_shared_feedback(self):
        fill, border, icon = ui.zoom_button_palette(active=True, pressed=True)
        self.assertEqual(fill, ui.UI_PRESSED_FILL)
        self.assertEqual(fill[3], 255)
        self.assertEqual(border, ui.UI_PRESSED_EDGE)
        self.assertEqual(icon, (*ui.UI_PRESSED_TEXT, 255))

    def test_display_drawer_exposes_the_scope_drag_action(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        box = ui.DISPLAY_SCOPE_BOX
        center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        self.assertEqual(ui.display_option_at(*center), ('scope', None))
        # It shares its row with Instruments without overlapping it.
        self.assertFalse(
            ui.DISPLAY_INSTRUMENTS_BOX[0] < ui.DISPLAY_SCOPE_BOX[2]
            and ui.DISPLAY_SCOPE_BOX[0] < ui.DISPLAY_INSTRUMENTS_BOX[2]
        )

    def test_display_drawer_draws_scope_and_short_layout_tile(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        seen = []
        with patch.object(ui, 'draw_lcd_audio_tile',
                          side_effect=lambda *_a, **_k: seen.append((_a[1], _a[2]))), \
             patch.object(ui, 'draw_lcd_audio_slider_tile'), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'draw_sidebar_header'), patch.object(ui, 'draw_display_control'):
            ui.draw_display_setup_panel(None, -95, -20, 1, False, 'kiwi', True)
        titles = [title for _box, title in seen]
        self.assertIn((ui.DISPLAY_SCOPE_BOX, 'SCOPE'), seen)
        # The too-long INSTRUMENTS tile was renamed so it fits half a rail.
        self.assertIn('LAYOUT', titles)
        self.assertNotIn('INSTRUMENTS', titles)

    def test_display_drawer_options_fit_the_rail(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        rail_bottom = ui.lcd_drawer_back_box()[1]
        boxes = [ui.DISPLAY_RESET_BOX, ui.DISPLAY_SPECTRUM_BOX, ui.DISPLAY_AUTO_BOX,
                 ui.DISPLAY_FLOOR_MINUS_BOX, ui.DISPLAY_CEIL_MINUS_BOX,
                 ui.DISPLAY_INSTRUMENTS_BOX, ui.DISPLAY_SCOPE_BOX]
        boxes.extend(box for _rate, box, _label in ui.DISPLAY_RATE_BOXES)
        boxes.extend(box for _name, box, _label in ui.DISPLAY_PALETTE_BOXES)
        for box in boxes:
            self.assertGreaterEqual(box[0], ui.LCD_NAV_X0)
            self.assertLessEqual(box[2], ui.LOGICAL_W)
            self.assertLess(box[3], rail_bottom, box)
        # LAYOUT and SCOPE share one compact row without overlapping.
        self.assertEqual(ui.DISPLAY_INSTRUMENTS_BOX[3], ui.DISPLAY_SCOPE_BOX[3])
        self.assertLess(ui.DISPLAY_INSTRUMENTS_BOX[2], ui.DISPLAY_SCOPE_BOX[0])

    def test_map_view_no_longer_offers_clean(self):
        # CLEAN hid the geographic context and read as an empty globe; it is
        # gone from the VIEW cycle entirely.
        self.assertNotIn('clean', ui.MAP_VIEWS)
        self.assertNotIn('CLEAN', ui.MAP_VIEW_LABELS.values())
        views = set()
        view = 'satellite_only'
        for _ in range(len(ui.MAP_VIEWS)):
            views.add(view)
            view = ui.MAP_VIEWS[(ui.MAP_VIEWS.index(view) + 1) % len(ui.MAP_VIEWS)]
        self.assertEqual(views, set(ui.MAP_VIEWS))
        self.assertNotIn('clean', views)

    def test_navigation_tiles_are_equal_squares(self):
        self.assertEqual(ui.LCD_NAV_TILE_W, ui.LCD_NAV_TILE_H)
        for items in (ui.MENU_ITEMS, ui.SETTINGS_MENU_ITEMS):
            has_back = items is ui.SETTINGS_MENU_ITEMS
            for index in range(len(items)):
                if has_back and index == len(items) - 1:
                    continue  # Back is the shared full-width return target.
                box = ui.lcd_nav_box(index, len(items), has_back)
                self.assertEqual(box[2] - box[0], ui.LCD_NAV_TILE_W)
                self.assertEqual(box[3] - box[1], ui.LCD_NAV_TILE_H)
        # Every Globe rail command reuses the same square launcher tile.
        ui.configure_output(True)
        ui.configure_popup_layout()
        for box in (ui.RADIOGARDEN_LIST_BOX, ui.RADIOGARDEN_VIEW_BOX,
                    ui.RADIOGARDEN_ZOOM_IN_BOX, ui.RADIOGARDEN_ZOOM_OUT_BOX):
            self.assertEqual(box[2] - box[0], ui.LCD_NAV_TILE_W)
            self.assertEqual(box[3] - box[1], ui.LCD_NAV_TILE_H)

    def test_globe_commands_all_live_in_the_right_rail(self):
        # The Globe's controls (including zoom) belong to the rail, never
        # floating over the map canvas where they could swallow a drag.
        ui.configure_output(True)
        ui.configure_popup_layout()
        zoom_in, zoom_out = ui.receiver_map_zoom_boxes()
        rail_boxes = [zoom_in, zoom_out, ui.RADIOGARDEN_LIST_BOX,
                      ui.RADIOGARDEN_VIEW_BOX, ui.RADIOGARDEN_EXIT_BOX]
        for box in rail_boxes:
            self.assertGreaterEqual(box[0], ui.LCD_NAV_X0)
            self.assertLessEqual(box[2], ui.LOGICAL_W)
        map_box = ui.PICKER_MAP_BOX
        for box in (zoom_in, zoom_out):
            self.assertFalse(
                box[0] < map_box[2] and map_box[0] < box[2]
                and box[1] < map_box[3] and map_box[1] < box[3],
                f"Globe zoom control floats over the map: {box}",
            )
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
             patch.object(ui, 'draw_picker_button',
                          side_effect=lambda _c, _b, label, *_a, **_k: labels.append(str(label))), \
             patch.object(ui, 'draw_picker_two_line_button'), \
             patch.object(ui, 'draw_radio_close_button'), patch.object(ui, 'draw_text'), \
             patch.object(ui, 'draw_station_health_icons'):
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
        self.assertEqual(commands, [ui.lcd_nav_box(index, 5, True) for index in range(4)])
        self.assertTrue(all(box[0] == tabs[0][0] and box[2] == tabs[0][2] for box in tabs))
        self.assertTrue(all(box[2] - box[0] > box[3] - box[1] for box in tabs))
        self.assertLess(tabs[-1][3], min(box[1] for box in commands))
        self.assertLess(max(box[3] for box in commands), back[1])
        boxes = tabs + commands + [back]
        for index, first in enumerate(boxes):
            for second in boxes[index + 1:]:
                self.assertFalse(ui.boxes_overlap(first, second), (first, second))

    def test_frequency_drawer_lists_steps_without_up_down_captions(self):
        texts = []
        with patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_sidebar_header'), \
             patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'frequency_chevron_texture', return_value=(1, 10, 10)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_big_frequency'), \
             patch.object(ui, 'draw_text',
                          side_effect=lambda _c, _x, _y, text, *_a, **_k: texts.append(str(text))):
            ui.draw_frequency_drawer(None, 7075.0, 100, 'Oxanium', None, 'kiwi')
        # The arrow icons carry no UP/DOWN caption any more.
        self.assertNotIn('UP', texts)
        self.assertNotIn('DOWN', texts)
        for step_hz in ui.frequency_tune_steps('kiwi'):
            self.assertIn(ui.format_tune_step(step_hz), texts)

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
        self.assertEqual(ui.lcd_annunciator_surface_bottom(True), ui.LCD_ANNUNCIATOR_BOX[3])

    def test_mode_hit_selects_before_drawer(self):
        for compact in (True,False):
            for label, box in ui.lcd_home_mode_boxes(compact):
                expected = 'NBFM' if label=='FMDX' else label
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
                ui.draw_ui(None,7075,20,-95,-95,None,'LSB','DIG',100,instrument_layout='compact',**kwargs)
                mocks['draw_lcd_mode_annunciators'].assert_not_called()

    def test_settings_back_uses_shared_renderer(self):
        with patch.object(ui,'draw_sidebar_header'), patch.object(ui,'draw_logical_rect'), patch.object(ui,'draw_logical_line'), \
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

    def test_legend_lists_only_present_groups(self):
        entries = ui.receiver_map_legend_entries(self.receivers())
        self.assertEqual([group for group, _label, _color in entries],
                         ['kiwi', 'openwebrx', 'local', 'fmdx'])
        self.assertEqual(
            ui.receiver_map_legend_entries(self.receivers()[:1]),
            (('kiwi', 'KIWI', ui.RECEIVER_MAP_GROUP_COLORS['kiwi']),),
        )

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
        self.assertIn('OPEN', texts)
        self.assertIn('WEBRX', texts)
        self.assertIn('LOCAL', texts)
        self.assertIn('FM-DX', texts)
        ui.receiver_map_toggle_group('kiwi')
        texts = self._legend_texts()
        self.assertIn('KIWI', texts)

    def _legend_text_sizes(self):
        sizes = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
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

    def test_legend_square_keeps_the_normal_button_font_size(self):
        sizes = [
            size for text, size in self._legend_text_sizes()
            if any(text in lines for lines in ui.RECEIVER_MAP_LEGEND_TEXT_LINES.values())
        ]
        self.assertTrue(sizes)
        self.assertTrue(all(size == ui.RECEIVER_MAP_LEGEND_FONT_SIZE for size in sizes))
        self.assertEqual(ui.RECEIVER_MAP_LEGEND_FONT_SIZE, 18)

    def _draw_dots(self, scale):
        drawn = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
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
            ui.receiver_map_dot_pixels(68.8),
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

    def _polyline_colors(self, map_view, scale=0.9):
        colors = []
        with patch.object(ui, 'draw_receiver_map_satellite', return_value=False), \
             patch.object(ui, 'draw_logical_rect'), patch.object(ui, 'draw_logical_line'), \
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
                map_view=map_view,
            )
        return colors

    def test_no_view_draws_the_removed_clean_coastline_layer(self):
        # The CLEAN coastline layer is gone from every presentation.
        for view in ('borders', 'atlas', 'satellite_only', 'satellite'):
            self.assertNotIn(self.COASTLINE_COLOR, self._polyline_colors(view), view)

    def test_outline_views_still_draw_country_borders(self):
        for view in ('borders', 'atlas', 'satellite'):
            colors = self._polyline_colors(view)
            self.assertTrue(
                any(color in ((177, 203, 201, 196), (207, 222, 211, 150)) for color in colors),
                view,
            )

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
            self.assertEqual(box[2] - box[0], ui.LCD_NAV_TILE_W)
            self.assertEqual(box[3] - box[1], ui.LCD_NAV_TILE_H)
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
        self.assertEqual(ui.MAP_VIEW_LABELS[ui.GLOBE_DEFAULT_VIEW], 'SAT')

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

    def test_globe_uses_home_once_then_selected_receiver(self):
        import inspect
        source = inspect.getsource(ui)
        self.assertIn('def focus_receiver_map_on_home', source)
        self.assertIn('def focus_receiver_map_on_server', source)
        self.assertIn('picker_map_has_opened', source)
        self.assertIn('picker_map_selected_server = target_server', source)


class SharedButtonPressFeedbackTests(unittest.TestCase):
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
        with patch.object(ui, 'draw_logical_rect', side_effect=lambda *_args: fills.append(_args[-1])), \
             patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_text', side_effect=lambda _c, _x, _y, _label, color, *_a, **_k: colors.append(color)):
            ui.draw_picker_button(None, box, 'TEST')
        self.assertEqual(fills[0], ui.UI_PRESSED_FILL)
        self.assertEqual(colors[0], ui.UI_PRESSED_TEXT)

    def test_selected_picker_tab_uses_cyan_fill_and_dark_text(self):
        box = (10, 20, 246, 72)
        fills = []
        colors = []
        with patch.object(ui, 'draw_logical_rect', side_effect=lambda *_args: fills.append(_args[-1])), \
             patch.object(ui, 'draw_logical_line'), \
             patch.object(ui, 'draw_text', side_effect=lambda _c, _x, _y, _label, color, *_a, **_k: colors.append(color)):
            ui.draw_picker_button(None, box, 'KIWI', selected=True)
        self.assertEqual(fills[0], ui.UI_PRESSED_FILL)
        self.assertEqual(colors[0], ui.UI_PRESSED_TEXT)

    def test_two_line_button_inverts_both_labels_while_pressed(self):
        box = (10, 20, 104, 114)
        colors = []
        ui.set_ui_press_point(40, 50)
        with patch.object(ui, 'draw_picker_button'), \
             patch.object(ui, 'draw_text', side_effect=lambda _c, _x, _y, _label, color, *_a, **_k: colors.append(color)):
            ui.draw_picker_two_line_button(None, box, 'VIEW', 'SAT')
        self.assertEqual(colors, [ui.UI_PRESSED_TEXT, ui.UI_PRESSED_TEXT])

    def test_pressed_close_button_supplies_rgba_to_opengl_primitives(self):
        box = (10, 20, 104, 114)
        primitive_colors = []
        ui.set_ui_press_point(40, 50)

        def record_line(_x0, _y0, _x1, _y1, color, _width):
            primitive_colors.append(color)
            if len(ui.rgba(color)) != 4:
                raise TypeError("OpenGL color must contain RGBA")

        with patch.object(ui, 'draw_logical_rect'), \
             patch.object(ui, 'draw_logical_line', side_effect=record_line):
            ui.draw_radio_close_button(None, box)

        self.assertTrue(primitive_colors)


class PassbandDrawerInteractionTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()

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
             patch.object(ui, 'draw_sidebar_header'), patch.object(ui, 'draw_radio_close_button'), \
             patch.object(ui, 'lcd_nav_tile_background', return_value=(1, 1, 1)), \
             patch.object(ui, 'menu_icon_texture', return_value=(1, 1, 1)), \
             patch.object(ui, 'draw_textured_quad'), \
             patch.object(ui, 'draw_lcd_home_bandwidth') as bandwidth, \
             patch.object(ui, 'draw_lcd_home_volume_slider') as volume:
            ui.draw_lcd_navigation(None, volume=0.5, muted=False, low_cut=-2400, high_cut=2400)
        bandwidth.assert_not_called()
        volume.assert_not_called()


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
             patch.object(ui, "draw_picker_button"), \
             patch.object(ui, "draw_picker_two_line_button"), \
             patch.object(ui, "draw_radio_close_button"), \
             patch.object(ui, "draw_text",
                          side_effect=lambda _c, _x, _y, text, *_a, **_k: texts.append(str(text))):
            ui.draw_station_picker(None, [], 0, "", "", "location", {}, None, None, "local", None)
        self.assertIn("NO RECEIVERS IN THIS SOURCE", texts)

    def test_empty_local_list_is_actually_empty_when_the_seed_is_absent(self):
        # The empty text is driven by the filtered rows, so a source that
        # genuinely has no entries reaches it rather than a blank screen.
        rows = ui.filtered_stations([], "", "location", "local", set())
        self.assertEqual(rows, [])

    def test_local_hides_the_builtin_kiwi_until_it_is_reachable(self):
        server = ui.LOCAL_KIWI_SERVER
        # No health record yet: LOCAL is genuinely empty, so it shows the
        # shared no-receivers message instead of a phantom placeholder.
        self.assertEqual(
            ui.filtered_stations(ui.STATIONS, "", "location", "local", set(), station_health={}),
            [],
        )
        now = time.time()
        healthy = {server: {"checked": now, "audio": True, "waterfall": True}}
        reachable = ui.filtered_stations(ui.STATIONS, "", "location", "local", set(), station_health=healthy)
        self.assertEqual([row[2] for row in reachable], [server])
        stale = {server: {"checked": now - 90000, "audio": True, "waterfall": True}}
        self.assertEqual(
            ui.filtered_stations(ui.STATIONS, "", "location", "local", set(), station_health=stale),
            [],
        )
        offline = {server: {"checked": now, "audio": False, "waterfall": False}}
        self.assertEqual(
            ui.filtered_stations(ui.STATIONS, "", "location", "local", set(), station_health=offline),
            [],
        )

    def test_reachability_gate_leaves_other_sources_untouched(self):
        kiwi = ui.filtered_stations(ui.STATIONS, "", "location", "kiwi", set(), station_health={})
        self.assertTrue(kiwi)


if __name__ == '__main__':
    unittest.main()
