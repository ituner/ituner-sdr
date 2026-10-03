"""CM5 1280x800 regression coverage for board_v1."""
import time
import unittest
from unittest.mock import patch
import kiwi_gl_display as ui

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
             patch.object(ui, 'draw_logical_disc_points'):
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

        def record_discs(points, color, radius, segments=10):
            drawn.append((len(points), radius))

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
             patch.object(ui, 'draw_logical_disc_points', side_effect=record_discs):
            ui.draw_receiver_map(
                None, receivers, 0.0, 0.0, 1.0, '', None, 'idle', {},
                map_view='satellite_only',
            )
        # One filled disc per receiver -- no separate halo disc stacked on top.
        self.assertEqual(sum(count for count, _radius in drawn), len(receivers))
        self.assertTrue(all(radius <= 7.2 for _count, radius in drawn))
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
             patch.object(ui, 'draw_logical_disc_points',
                          side_effect=lambda points, color, radius, segments=10: drawn.append(len(points))):
            ui.draw_receiver_map(
                None, receivers, 0.0, 0.0, 1.0, '', None, 'idle', {},
                map_view='satellite_only',
            )
        # Only the still-visible FM-DX receiver is left on the globe.
        self.assertEqual(sum(drawn), 1)


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
