import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiwi_gl_display as ui  # noqa: E402


class MenuIconTests(unittest.TestCase):
    def test_decoder_tiles_have_eight_pixel_gaps_and_clear_back(self):
        count = len(ui.DIGITAL_MENU_ITEMS)
        offset = len(ui.SPECTRUM_MENU_ITEMS)
        for group in (ui.HF_DECODER_ITEMS, ui.VHF_UHF_DECODER_ITEMS, ui.WEB_APP_MENU_ITEMS):
            boxes = [ui.lcd_nav_box(offset + i, count, True) for i in range(len(group))]
            for i, box in enumerate(boxes):
                if i % 2:
                    self.assertEqual(box[0] - boxes[i - 1][2], 8)
                if i >= 2:
                    self.assertEqual(box[1] - boxes[i - 2][3], 8)
            offset += len(group)
        self.assertGreaterEqual(ui.lcd_drawer_back_box()[1] - boxes[-1][3], 8)

    def test_decoder_rail_starts_16_pixels_below_divider(self):
        box=ui.lcd_nav_box(0,len(ui.DIGITAL_MENU_ITEMS),True)
        self.assertEqual(box[1]-ui.LCD_DRAWER_HEADER_H,16)
        self.assertEqual(ui.lcd_nav_box(len(ui.DIGITAL_MENU_ITEMS)-1,len(ui.DIGITAL_MENU_ITEMS),True),ui.lcd_drawer_back_box())

    def test_cursor_hidden_only_on_touchscreen(self):
        with mock.patch.object(ui, 'pygame') as pygame, mock.patch.object(ui, 'GL'):
            pygame.OPENGL=1;pygame.NOFRAME=2;pygame.FULLSCREEN=4
            for desktop in (False, True):
                ui.setup_gl(desktop=desktop)
                pygame.mouse.set_visible.assert_called_with(desktop)

    def test_usb_probe_survives_missing_other_receiver_tool(self):
        def run(command, **kwargs):
            if command[0]=='airspyhf_info':
                raise FileNotFoundError('airspyhf_info')
            return mock.Mock(stdout='Found 1 device(s):\n  0: Nooelec, NESDR, SN: 123\nFound Rafael Micro R820T tuner',stderr='')
        def thread(**kwargs):
            return mock.Mock(start=kwargs['target'])
        with mock.patch.object(ui.subprocess,'run',side_effect=run), \
             mock.patch.object(ui.threading,'Thread',side_effect=thread):
            lab=ui.RTLSDRLab(mock.Mock(),mock.Mock(),mock.Mock())
            self.assertTrue(lab.snapshot()['present'])
            self.assertIn('Nooelec',lab.snapshot()['device'])
            lab.show('receivers')
            self.assertEqual(lab.navigation_parent,'receivers')
            self.assertFalse(lab.snapshot()['probing'])

    def test_network_retry_yields_to_usb_before_handoff_deadline(self):
        import threading
        state = ui.SharedState('http://example.test:8073', 7075.0, 4, -95.0, 142, 245, 3, 'am', True)
        for delay in (10.0, None):
            state.set_external_audio(False)
            stop = threading.Event()
            entered = threading.Event()
            finished = threading.Event()
            def retry():
                entered.set()
                ui.wait_for_audio_retry(stop, state, state.snapshot()[5], delay)
                finished.set()
            worker = threading.Thread(target=retry)
            worker.start()
            self.assertTrue(entered.wait(1))
            state.set_external_audio(True)
            try:
                self.assertTrue(finished.wait(0.5), 'USB must interrupt network retry and access-denied waits')
            finally:
                stop.set()
                worker.join(1)

    def test_usb_footer_identifies_device(self):
        footer = ui.usb_receiver_footer({
            'device': 'Realtek RTL2838, SN: 00000001',
            'capabilities': mock.Mock(label='RTL-SDR'),
            'preset': ('FM BROADCAST',),
        })
        self.assertEqual(footer, 'USB · Realtek RTL2838, SN: 00000001')

    def test_usb_receiver_survives_saved_preferences_round_trip(self):
        import tempfile
        for source, capabilities in ui.LOCAL_RECEIVER_CAPABILITIES.items():
            with self.subTest(source=source):
                state = ui.SharedState('http://example.test:8073',7075.,4,-95.,142,245,3,'am',True)
                with mock.patch.object(ui.RTLSDRLab,'probe'):
                    lab=ui.RTLSDRLab(mock.Mock(),state,mock.Mock())
                lab.source_inventory={source:dict(present=True,device=source)}
                lab.select_source(source)
                frequency=lab._presets()[0][1]/1000.
                with mock.patch.object(ui.threading,'Thread'):
                    self.assertTrue(lab.start(frequency,4))
                saved=lab.remembered_receiver()
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'receiver.json'
                    ui.save_remembered_view(path,'http://example.test:8073',7075.,4,'AM',True,{'usb_receiver':saved},'kiwi')
                    loaded=ui.load_remembered_view(path)
                self.assertEqual(loaded['freq_khz'],7075.)
                restored=ui.RTLSDRLab.validate_remembered_receiver(loaded['preferences']['usb_receiver'])
                self.assertEqual(restored['source_id'],source)
                lab.thread=None;lab.source_inventory={}
                self.assertFalse(lab.restore_receiver(restored))
                lab.source_inventory={source:dict(present=True,device=source)}
                with mock.patch.object(ui.threading,'Thread'):
                    self.assertTrue(lab.restore_receiver(restored))
                self.assertEqual(state.snapshot()[1],frequency)
                self.assertEqual(lab.demod_snapshot()[0],'am')

    def test_usb_selection_survives_worker_exit_until_explicit_stop(self):
        state = ui.SharedState('http://example.test:8073', 7075., 4, -95., 142, 245, 3, 'am', True)
        with mock.patch.object(ui.RTLSDRLab, 'probe'):
            lab = ui.RTLSDRLab(mock.Mock(), state, mock.Mock())
        lab.source_inventory = {'rtl-sdr': dict(present=True, device='RTL-SDR')}
        lab.select_source('rtl-sdr')
        with mock.patch.object(ui.threading, 'Thread'):
            self.assertTrue(lab.start(100100., 8))
        saved = lab.remembered_receiver()
        lab.thread.is_alive.return_value = False
        # Worker cleanup restores the network view before shutdown saves again.
        state.set_view(freq_khz=7075., zoom=4)
        self.assertEqual(lab.remembered_receiver(), saved)
        lab.stop()
        self.assertIsNone(lab.remembered_receiver())

    def test_invalid_saved_usb_receiver_is_ignored(self):
        for saved in (None,{},dict(source_id='invalid'),dict(source_id='rtl-sdr',freq_khz=float('nan'),zoom=4)):
            self.assertIsNone(ui.RTLSDRLab.validate_remembered_receiver(saved))

    def test_usb_screen_controls_match_back_size_and_have_working_hit_targets(self):
        from contextlib import ExitStack
        ui.configure_output(True);ui.configure_popup_layout()
        back = ui.RTL_LAB_BACK_BOX
        for box, action in ((ui.RTL_LAB_PROBE_BOX,'source'),(ui.RTL_LAB_PRESET_BOX,'preset'),
                            (ui.RTL_LAB_RUN_BOX,'run'),(back,'back')):
            self.assertEqual((box[2]-box[0],box[3]-box[1]),(back[2]-back[0],back[3]-back[1]))
            x,y=(box[0]+box[2])/2,(box[1]+box[3])/2
            self.assertTrue(ui.contains(ui.RTL_LAB_PANEL_BOX,x,y))
            self.assertEqual(ui.rtl_lab_option_at(x,y),action)
        snapshot=dict(preset=('AIR AM',118e6,'am',32000),running=False,status='READY',
                      capabilities=ui.RTL_SDR_CAPABILITIES,device='RTL-SDR V3',tuner='R820T',
                      probing=False,detail='Ready to listen')
        lab=mock.Mock();lab.snapshot.return_value=snapshot
        with ExitStack() as stack:
            for name in ('draw_logical_rect','draw_logical_rounded_rect','draw_settings_leaf_sidebar','draw_tests_button'):
                stack.enter_context(mock.patch.object(ui,name))
            text=stack.enter_context(mock.patch.object(ui,'draw_text'))
            stack.enter_context(mock.patch.object(ui,'fit_station_text',side_effect=lambda cache,value,*a,**k:value))
            ui.draw_rtl_lab_panel(mock.Mock(),lab)
            title=next(call for call in text.call_args_list if call.args[3]=='RTL-SDR')
            self.assertLess(title.args[2],ui.RTL_LAB_PROBE_BOX[1])

    def test_usb_start_defaults_decoder_and_home_mode_to_am(self):
        for capabilities in ui.LOCAL_RECEIVER_CAPABILITIES.values():
            with self.subTest(source=capabilities.source_id):
                state = ui.SharedState('http://example.test:8073', 7075., 4, -95., 142, 245, 3, 'usb', True)
                with mock.patch.object(ui.RTLSDRLab, 'probe'):
                    lab = ui.RTLSDRLab(mock.Mock(), state, mock.Mock())
                lab.source_id = capabilities.source_id
                lab.capabilities = capabilities
                lab.present = True
                for index, preset in enumerate(lab._presets()):
                    lab.thread = None
                    lab.preset_indices[lab.source_id] = index
                    with mock.patch.object(ui.threading, 'Thread'):
                        self.assertTrue(lab.start(preset[1] / 1000., 4))
                    self.assertEqual(lab.demod_snapshot()[0], 'am')
                    self.assertEqual(state.radio_snapshot()[0].upper(), 'AM')
                    self.assertEqual(lab.preferred_home_mode(preset), 'AM')

    def test_usb_category_hidden_geometry_matches_touch_targets(self):
        ui.configure_output(True)
        visible = ui.receiver_source_segments(True)
        hidden = ui.receiver_source_segments(False)
        self.assertEqual([source for source, _ in hidden], ['local', 'kiwi', 'openwebrx', 'fmdx', 'all'])
        self.assertEqual(hidden[0][1], visible[0][1])
        for source, (x0, y0, x1, y1) in hidden:
            self.assertEqual(ui.picker_source_segment_at((x0+x1)/2, (y0+y1)/2, False), source)
        self.assertEqual(ui.receiver_source_segments(True), visible)

    def test_usb_hotplug_rescans_only_when_topology_changes(self):
        import tempfile
        with mock.patch.object(ui.RTLSDRLab, 'probe'):
            lab = ui.RTLSDRLab(mock.Mock(), mock.Mock(), mock.Mock())
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(lab, 'probe', return_value=True) as probe:
            root = Path(directory)
            lab.refresh_usb_devices(now=1, usb_root=root)
            self.assertEqual(probe.call_count, 1)
            lab.refresh_usb_devices(now=2, usb_root=root)
            self.assertEqual(probe.call_count, 1)
            device = root / '1-1'
            device.mkdir()
            for name, value in (('idVendor', '0bda'), ('idProduct', '2838'), ('devnum', '2')):
                (device / name).write_text(value)
            lab.refresh_usb_devices(now=3, usb_root=root)
            self.assertEqual(probe.call_count, 2)
            lab.refresh_usb_devices(now=4, usb_root=root)
            self.assertEqual(probe.call_count, 2)
            for path in device.iterdir():
                path.unlink()
            device.rmdir()
            # Busy receivers defer the rescan until their worker releases it.
            probe.return_value = False
            lab.refresh_usb_devices(now=5, usb_root=root)
            probe.return_value = True
            lab.refresh_usb_devices(now=6, usb_root=root)
            self.assertEqual(probe.call_count, 4)

    def test_usb_waterfall_tap_preserves_window_and_signal_position(self):
        ui.configure_output(True)
        center = 100100.0
        span = 2400.0
        width = ui.rf_canvas_width()
        for fraction in (0.25, 0.75):
            target = ui.waterfall_tap_frequency_khz(width * fraction, center, span)
            state = ui.SharedState('http://example.test:8073', center, 4, -95., 142, 245, 3, 'am', True)
            state.set_view(freq_khz=target, waterfall_center_khz=center)
            view = ui.local_waterfall_center(state.snapshot()[1], state.waterfall_view_center_snapshot())
            self.assertEqual(view, center)
            # A signal at the new hardware center must remain under the tap,
            # rather than jumping to the middle of the spectrum.
            values = ui.np.zeros(1024)
            values[512] = 1.0
            remapped = ui.local_spectrum_in_view(values, target, view, span)
            self.assertEqual(int(ui.np.argmax(remapped)), int(1024 * fraction))
            self.assertAlmostEqual((target - view) / span + 0.5, fraction)
            state.set_view(freq_khz=target)
            self.assertEqual(ui.local_waterfall_center(target, state.waterfall_view_center_snapshot()), target)

    def test_usb_category_is_highlighted_and_draws_device_row(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(ui, 'LCD_800_MODE', True))
            draws = {}
            for name in ('draw_logical_rect', 'draw_receiver_action_button',
                         'draw_receiver_filter_button', 'draw_receiver_sidebar_header',
                         'draw_receiver_back_button', 'draw_picker_two_line_button',
                         'draw_station_list_frame', 'draw_text', 'draw_receiver_badge'):
                draws[name] = stack.enter_context(mock.patch.object(ui, name))
            cache = mock.Mock()
            cache.texture.return_value = (None, 80, 20)
            draws['draw_receiver_badge'].return_value = 60
            stack.enter_context(mock.patch.object(ui, 'ui_button_pressed', return_value=False))
            stack.enter_context(mock.patch.object(ui, 'fit_receiver_name', side_effect=lambda cache, name, *args: name))
            ui.draw_station_picker(cache, [('rtl-sdr', 'RTL-SDR V3', 'USB')],
                                   0, 'http://kiwisdr.local:8073', '', 'name_az', {},
                                   route_filter='usb')
            categories = draws['draw_receiver_filter_button'].call_args_list
            self.assertTrue(next(call.args[3] for call in categories if call.args[2] == 'USB'))
            self.assertFalse(next(call.args[3] for call in categories if call.args[2] == 'LAN'))
            draws['draw_picker_two_line_button'].assert_not_called()
            box = ui.station_tile(0, 0)
            self.assertEqual(draws['draw_station_list_frame'].call_args.args[0], box)
            title = next(call for call in draws['draw_text'].call_args_list if call.args[3] == 'RTL-SDR V3')
            self.assertEqual(title.args[1:3], (box[0] + 16, box[1] + 28))
            self.assertEqual(title.args[5], ui.RECEIVER_LIST_THEME.server_name_size)
            self.assertEqual(title.args[8], 'lm')
            badge = draws['draw_receiver_badge'].call_args.args
            self.assertEqual(badge[1:3], (box[0] + 16, box[1] + 52))
            self.assertEqual(badge[3].label, 'USB')

    def test_active_usb_row_uses_network_selection_style(self):
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(ui, 'LCD_800_MODE', True))
            draws = {}
            for name in ('draw_logical_rect', 'draw_receiver_action_button',
                         'draw_receiver_filter_button', 'draw_receiver_sidebar_header',
                         'draw_receiver_back_button', 'draw_station_list_frame',
                         'draw_logical_rounded_rect', 'draw_text', 'draw_receiver_badge'):
                draws[name] = stack.enter_context(mock.patch.object(ui, name))
            cache = mock.Mock()
            cache.texture.return_value = (None, 80, 20)
            draws['draw_receiver_badge'].return_value = 60
            stack.enter_context(mock.patch.object(ui, 'ui_button_pressed', return_value=False))
            stack.enter_context(mock.patch.object(ui, 'fit_receiver_name', side_effect=lambda cache, name, *args: name))
            server = 'http://kiwisdr.local:8073'
            def render(rows, route, active):
                ui.draw_station_picker(cache, rows, 0, server, '', 'name_az', {},
                                       route_filter=route, active_usb_source=active)
                return draws['draw_station_list_frame'].call_args.args[1:]
            network = [('Kiwi', '', server)]
            usb = [('rtl-sdr', 'RTL-SDR V3', 'USB')]
            selected_style = render(network, 'lan', None)
            self.assertEqual(render(usb, 'usb', 'rtl-sdr'), selected_style)
            inactive_style = render(usb, 'usb', None)
            self.assertNotEqual(inactive_style, selected_style)
            self.assertEqual(render(usb, 'usb', 'airspyhf'), inactive_style)
            self.assertEqual(render(network, 'lan', 'rtl-sdr'), inactive_style)

    def test_usb_browsing_does_not_require_starting_audio(self):
        with mock.patch.object(ui.RTLSDRLab, 'probe'):
            lab = ui.RTLSDRLab(mock.Mock(), mock.Mock(), mock.Mock())
        source = lab.source_id
        lab.source_inventory = {source: {'present': True, 'device': 'RTL-SDR V3'}}
        self.assertEqual(lab.receiver_rows()[0][1], 'RTL-SDR V3')
        self.assertTrue(lab.select_source(source))
        self.assertFalse(lab.is_running())
        with mock.patch.object(lab, 'probe'):
            lab.show('receivers')
        self.assertEqual(lab.navigation_parent, 'receivers')
        self.assertEqual(lab.receiver_rows()[0][1], 'RTL-SDR V3')
        lab.state.set_external_audio.assert_not_called()

    def test_required_runtime_icons_exist_in_both_asset_roots(self):
        required = {
            "apps.png",
            "audio-muted.png",
            "audio.png",
            "digi.png",
            "display.png",
            "dual.png",
            "frequency-chevron.png",
            "globe-network.png",
            "home.png",
            "info.png",
            "lan-home.png",
            "receivers.png",
            "rf.png",
            "settings.png",
            "stats.png",
        }
        repository = Path(__file__).resolve().parents[1]
        roots = (
            repository / "UI/assets/menu-icons",
            repository / "assets/menu-icons",
        )
        for root in roots:
            self.assertEqual(
                required - {path.name for path in root.glob("*.png")},
                set(),
            )
            for name in required:
                with Image.open(root / name) as image:
                    self.assertEqual(image.size, (64, 64))
                    self.assertIsNotNone(image.convert("RGBA").getchannel("A").getbbox())

    def test_audio_icon_tracks_existing_muted_state(self):
        self.assertEqual(ui.menu_icon_filename("audio", muted=False), "audio.png")
        self.assertEqual(ui.menu_icon_filename("audio", muted=True), "audio-muted.png")
        self.assertEqual(ui.menu_icon_filename("tests", muted=True), "apps.png")
        self.assertEqual(ui.menu_icon_filename("dual"), "dual.png")

    def test_receiver_globe_action_reuses_the_navigation_globe_asset(self):
        self.assertEqual(ui.RECEIVER_GLOBE_ICON, "globe-network.png")
        self.assertNotEqual(ui.RECEIVER_GLOBE_ICON, ui.menu_icon_filename("rx"))

    def test_lan_uses_the_requested_home_network_asset(self):
        self.assertEqual(ui.menu_icon_filename("local_rx"), "lan-home.png")

    def test_globe_list_action_uses_a_list_glyph(self):
        self.assertEqual(ui.GLOBE_LIST_ICON_KIND, "list")

    def test_dual_icon_has_requested_wide_low_profile(self):
        icon = Path(__file__).resolve().parent / "assets/menu-icons/dual.png"
        with Image.open(icon).convert("RGBA") as image:
            x0, y0, x1, y1 = image.getchannel("A").getbbox()
        self.assertGreater(x1 - x0, y1 - y0)
        self.assertLessEqual(y1 - y0, 42)


class DrawerGeometryTests(unittest.TestCase):
    @staticmethod
    def _center(box):
        return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2

    def _overlaps(self, a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    def test_frequency_entry_keypad_lives_in_the_side_rail(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        panel, entry, commands, keys = ui.frequency_entry_layout()
        # The manual keypad is a rail face, not a panel floating over the
        # waterfall beside it.
        self.assertEqual(panel, (ui.LCD_NAV_X0, 0, ui.LOGICAL_W, ui.lcd_rail_bottom()))
        boxes = [entry] + [box for _label, box in commands] + [box for _label, box in keys]
        for box in boxes:
            self.assertGreaterEqual(box[0], panel[0])
            self.assertGreaterEqual(box[1], panel[1])
            self.assertLessEqual(box[2], panel[2])
            self.assertLessEqual(box[3], panel[3])
        for index, box in enumerate(boxes):
            for other in boxes[index + 1:]:
                self.assertFalse(self._overlaps(box, other))
        for label, box in commands + keys:
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            self.assertEqual(ui.frequency_entry_action_at(*center), label)

    def test_home_destinations_match_text_only_layout(self):
        kinds = [kind for kind, _label in ui.MENU_ITEMS]
        self.assertEqual(
            kinds,
            ["rx", "dual", "audio", "display", "digital", "vosc", "tests", "settings"],
        )
        self.assertNotIn("display", dict(ui.SETTINGS_MENU_ITEMS))
        self.assertEqual(ui.LCD_NAV_TILE_W, 114)
        self.assertEqual(ui.LCD_NAV_TILE_H, 64)
        self.assertEqual(ui.LCD_NAV_GAP, 8)
        boxes = [ui.lcd_nav_box(i) for i in range(len(ui.MENU_ITEMS))]
        self.assertEqual(boxes[0], (1034, 488, 1148, 558))
        self.assertEqual(boxes[-1], (1156, 722, 1270, 792))

    def test_vosc_uses_right_rail_controls_and_shared_back(self):
        options = list(ui.vosc_sidebar_options())
        self.assertEqual(len(options), len(ui.ASR_ENGINES) + len(ui.CAPTION_MODES) + 1)
        back = ui.lcd_drawer_back_box()
        for kind, value, box in options:
            width = 236 if kind == "callsign" else 114
            self.assertEqual((box[2] - box[0], box[3] - box[1]), (width, 64))
            self.assertGreaterEqual(box[0], ui.LCD_NAV_X0 + 10)
            self.assertLessEqual(box[2], ui.LOGICAL_W - 10)
            self.assertLessEqual(box[3] + 8, back[1])
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            self.assertEqual(ui.asr_option_at(*center), (kind, value))
        self.assertEqual(options[-1][:2], ("callsign", None))
        self.assertLess(options[-2][2][3], options[-1][2][1])
        self.assertEqual(ui.asr_option_at((back[0] + back[2]) / 2,
                                          (back[1] + back[3]) / 2), ("back", None))

    def test_vosc_callsign_button_shows_its_live_state(self):
        ui.configure_output(True)
        with mock.patch.object(ui, "draw_logical_rect"), \
             mock.patch.object(ui, "draw_logical_line"), \
             mock.patch.object(ui, "draw_sidebar_header"), \
             mock.patch.object(ui, "draw_text"), \
             mock.patch.object(ui, "draw_styled_button_frame", return_value=mock.Mock(text=(255, 255, 255))), \
             mock.patch.object(ui, "draw_radio_close_button"), \
             mock.patch.object(ui, "draw_styled_two_line_button") as callsign_button:
            ui.draw_asr_panel(None, "vosk", callsign_enabled=True)
        callsign_button.assert_called_once_with(
            None, list(ui.vosc_sidebar_options())[-1][2], "CALLSIGN", "ON", active=True,
        )

    def test_footer_places_larger_clock_before_buffer_and_system_stats_on_right(self):
        cache = mock.Mock()
        cache.font.return_value.size.return_value = (90, 13)
        with mock.patch.object(ui, "draw_logical_rect"), \
             mock.patch.object(ui, "fit_station_text", return_value="TEST RECEIVER"), \
             mock.patch.object(ui, "read_process_ram_mb", return_value=120), \
             mock.patch.object(ui, "draw_text") as draw_text:
            ui.draw_lower_status(cache, 15, 50, 712, 800,
                                 station_name="TEST RECEIVER", audio_jitter_depth=7)
        rendered = [(call.args[1], call.args[2], call.args[3]) for call in draw_text.call_args_list]
        self.assertEqual(rendered[0], (18, 739, "TEST RECEIVER"))
        self.assertEqual(rendered[1][0:2], (18, 771))
        self.assertIn("UTC", rendered[1][2])
        self.assertEqual(rendered[2], (124, 771, "BUFFER Q7/T6"))
        self.assertEqual(rendered[3], (1006, 739, "CPU 15%   RAM 120 MB"))
        self.assertEqual(rendered[4], (1006, 771, "TEMP 50 C"))
        self.assertTrue(all(call.args[5] == 18 for call in draw_text.call_args_list))

    def test_digi_rail_retains_all_decoder_destinations(self):
        self.assertEqual({kind for kind, _ in ui.DIGITAL_MENU_ITEMS},
                         {"spectrum", "wspr", "sstv", "hell", "qrss", "cw", "adsb", "ais", "aprs", "ism", "meteor", "cubesat", "sonde", "groundstation", "satvisor", "digital_back"})
        self.assertIs(ui.lcd_nav_items(digital_open=True), ui.DIGITAL_MENU_ITEMS)

    def test_decoder_sections_keep_hf_and_vhf_targets_separate(self):
        ui.configure_output(True)
        self.assertEqual({kind for kind, _ in ui.HF_DECODER_ITEMS}, {"wspr", "sstv", "hell", "qrss", "cw"})
        self.assertEqual({k for k,_ in ui.VHF_UHF_DECODER_ITEMS}, {"adsb", "ais", "aprs", "ism", "meteor", "cubesat", "sonde"})
        boxes = [ui.lcd_nav_box(i, len(ui.DIGITAL_MENU_ITEMS), True) for i in range(len(ui.DIGITAL_MENU_ITEMS))]
        for i, box in enumerate(boxes):
            center = ((box[0]+box[2])/2, (box[1]+box[3])/2)
            self.assertEqual(ui.lcd_nav_item_at(*center, ui.DIGITAL_MENU_ITEMS), i)
        self.assertEqual(ui.DIGITAL_MENU_ITEMS[0], ('spectrum', 'SPECTRUM ANALYZER'))
        first_hf=len(ui.SPECTRUM_MENU_ITEMS);first_vhf=first_hf+len(ui.HF_DECODER_ITEMS)
        self.assertLess(boxes[0][3], boxes[first_hf][1])
        self.assertLess(max(box[3] for box in boxes[first_hf:first_vhf]), boxes[first_vhf][1])
        self.assertLess(max(box[3] for box in boxes[first_vhf:-1]), boxes[-1][1])
        for i,box in enumerate(boxes):
            for other in boxes[i+1:]: self.assertFalse(self._overlaps(box,other))

    def test_digi_rail_marks_only_decoders_with_enabled_sessions(self):
        ui.configure_output(True)
        groups = (
            [{"paused": False}, {"paused": False}], [{"paused": True}],
            [{"paused": False}], [], [{"paused": True}, {"paused": False}],
        )
        counts = ui.digital_decoder_session_counts(*groups)
        self.assertEqual(counts, {"wspr": 2, "sstv": 0, "hell": 1,
                                  "qrss": 0, "cw": 1})
        active = ui.active_digital_decoder_kinds(*groups)
        self.assertEqual(active, {"wspr", "hell", "cw"})
        with mock.patch.object(ui, "draw_logical_rect"), \
             mock.patch.object(ui, "draw_logical_line"), \
             mock.patch.object(ui, "draw_sidebar_header"), \
             mock.patch.object(ui, "draw_text"), \
             mock.patch.object(ui, "draw_radio_close_button"), \
             mock.patch.object(ui, "draw_logical_circle") as circles, \
             mock.patch.object(ui, "draw_styled_text_button") as buttons:
            ui.draw_lcd_navigation(
                None, digital_open=True, active_decoders=active,
                decoder_counts=counts,
            )
        self.assertEqual(
            [call.args[2] for call in buttons.call_args_list],
            ["SPECTRUM ANALYZER", "2 WSPR", "SSTV", "1 Hell RX", "QRSS", "1 CW MORSE", "ADS-B", "AIS", "APRS", "rtl_433", "Meteor-M", "CubeSat", "Radiosonde", "Ground Stn", "Satvisor"],
        )
        dots = [call.args for call in circles.call_args_list]
        self.assertEqual(len(dots), 6)
        for kind in active:
            index = next(i for i, item in enumerate(ui.DIGITAL_MENU_ITEMS)
                         if item[0] == kind)
            x0, y0, x1, _y1 = ui.lcd_nav_box(
                index, len(ui.DIGITAL_MENU_ITEMS), True,
            )
            self.assertIn((round(x1 - 10), round(y0 + 10), ui.NAV_STATUS_LED_RADIUS,
                           ui.APP_UI_STYLE.palette.ready), dots)
        active_rims = [call for call in circles.call_args_list
                       if call.kwargs.get("outline")]
        self.assertEqual(len(active_rims), 3)
        self.assertTrue(all(call.args[2] == ui.NAV_STATUS_LED_RADIUS
                            for call in circles.call_args_list))
        self.assertEqual(ui.NAV_STATUS_LED_RADIUS * 2, 7)

    def test_home_digi_button_keeps_mode_count_separate_from_running_sessions(self):
        ui.configure_output(True)
        groups = (
            [{"paused": False}, {"paused": False}],
            [{"paused": True}], [{"paused": False}], [],
            [{"paused": False}, {"paused": True}],
        )
        self.assertEqual(sum(ui.digital_decoder_session_counts(*groups).values()), 4)
        self.assertEqual(sum(ui.digital_decoder_session_counts([], [], [], [], []).values()), 0)
        with mock.patch.object(ui, "draw_logical_rect"), \
             mock.patch.object(ui, "draw_logical_line"), \
             mock.patch.object(ui, "draw_logical_circle"), \
             mock.patch.object(ui, "draw_navigation_button") as buttons:
            ui.draw_lcd_navigation(None, running_decoder_count=4)
        digi_calls = [call.args for call in buttons.call_args_list
                      if call.args[2] == "DIGITAL"]
        self.assertEqual(len(digi_calls), 1)
        self.assertEqual(digi_calls[0][3], "13 MODES")
        with mock.patch.object(ui, "draw_logical_rect"), \
             mock.patch.object(ui, "draw_logical_line"), \
             mock.patch.object(ui, "draw_logical_circle"), \
             mock.patch.object(ui, "draw_navigation_button") as zero_buttons:
            ui.draw_lcd_navigation(None, running_decoder_count=0)
        zero_digi_calls = [call.args for call in zero_buttons.call_args_list
                           if call.args[2] == "DIGITAL"]
        self.assertEqual(zero_digi_calls[0][3], "13 MODES")

    def test_home_digi_title_stays_compact_with_many_running_sessions(self):
        ui.configure_output(True)
        with mock.patch.object(ui, "draw_logical_rect"), \
             mock.patch.object(ui, "draw_logical_line"), \
             mock.patch.object(ui, "draw_logical_circle"), \
             mock.patch.object(ui, "draw_navigation_button") as buttons:
            ui.draw_lcd_navigation(None, running_decoder_count=100)
        digi = next(call.args for call in buttons.call_args_list
                    if call.args[2] == "DIGITAL")
        self.assertEqual(digi[3], "13 MODES")
        cache = ui.TextCache()
        font = cache.font(ui.APP_UI_STYLE.button.title_size, bold=True,
                          family=ui.APP_UI_STYLE.button.font_family)
        label_cache = mock.Mock()
        label_cache.texture.side_effect = lambda text, *_args, **_kwargs: (
            None, font.size(text)[0], font.size(text)[1]
        )
        visible = ui.button_label_for_box(
            label_cache, digi[2], digi[1], size=ui.APP_UI_STYLE.button.title_size,
        )
        self.assertLessEqual(font.size(visible)[0], digi[1][2] - digi[1][0] - 8)
        if visible != digi[2]:
            self.assertTrue(visible.endswith("…"))

    def test_home_status_leds_follow_receiver_decoder_and_asr_state(self):
        ui.configure_output(True)
        with mock.patch.object(ui, "draw_logical_rect"), \
             mock.patch.object(ui, "draw_logical_line"), \
             mock.patch.object(ui, "draw_navigation_button"), \
             mock.patch.object(ui, "draw_logical_circle") as circles:
            ui.draw_lcd_navigation(
                None, receiver_playing=True, running_decoder_count=2,
                captions_running=True,
            )
        fills = [item.args[3] for item in circles.call_args_list if not item.kwargs.get("outline")]
        self.assertEqual(fills, [ui.APP_UI_STYLE.palette.ready] * 3)
        with mock.patch.object(ui, "draw_logical_rect"), \
             mock.patch.object(ui, "draw_logical_line"), \
             mock.patch.object(ui, "draw_navigation_button"), \
             mock.patch.object(ui, "draw_logical_circle") as idle_circles:
            ui.draw_lcd_navigation(None)
        idle_fills = [item.args[3] for item in idle_circles.call_args_list
                      if not item.kwargs.get("outline")]
        self.assertEqual(idle_fills, [(18, 24, 22, 255)] * 3)

    def test_apps_no_longer_contains_dual_vfo_action(self):
        cx = (ui.TEST_DUAL_BOX[0] + ui.TEST_DUAL_BOX[2]) / 2
        cy = (ui.TEST_DUAL_BOX[1] + ui.TEST_DUAL_BOX[3]) / 2
        self.assertIsNone(ui.tests_option_at(cx, cy))

    def test_lan_and_network_use_distinct_drawn_icons(self):
        surface = mock.Mock()
        monochrome = (1, 2, 3)
        with mock.patch.object(ui.pygame.draw, "rect") as draw_rect, \
             mock.patch.object(ui.pygame.draw, "line") as draw_line, \
             mock.patch.object(ui.pygame.draw, "lines") as draw_lines, \
             mock.patch.object(ui.pygame.draw, "circle") as draw_circle:
            ui.draw_menu_icon(surface, "local_rx", 50, 50, monochrome, (4, 5, 6))
            lan_calls = (
                draw_rect.call_count,
                draw_line.call_count,
                draw_lines.call_count,
                draw_circle.call_count,
            )
            self.assertTrue(all(call.args[1] == monochrome for call in draw_line.call_args_list))
            self.assertTrue(all(call.args[1] == monochrome for call in draw_lines.call_args_list))
            self.assertTrue(all(
                call.args[4] == ui.APP_ACTION_ICON_STROKE
                for call in draw_line.call_args_list
            ))
            self.assertTrue(all(
                call.args[4] == ui.APP_ACTION_ICON_STROKE
                for call in draw_lines.call_args_list
            ))
            draw_rect.reset_mock()
            draw_line.reset_mock()
            draw_lines.reset_mock()
            draw_circle.reset_mock()
            ui.draw_menu_icon(surface, "network", 50, 50, monochrome, (4, 5, 6))
            network_calls = (
                draw_rect.call_count,
                draw_line.call_count,
                draw_lines.call_count,
                draw_circle.call_count,
            )
            self.assertTrue(all(call.args[1] == monochrome for call in draw_lines.call_args_list))
            self.assertTrue(all(call.args[1] == monochrome for call in draw_circle.call_args_list))
        self.assertNotEqual(lan_calls, network_calls)

    def test_list_glyph_has_three_monochrome_rows(self):
        surface = mock.Mock()
        color = (11, 22, 33)
        with mock.patch.object(ui.pygame.draw, "line") as draw_line, \
             mock.patch.object(ui.pygame.draw, "circle") as draw_circle:
            ui.draw_menu_icon(surface, "list", 50, 50, color, (4, 5, 6))
        self.assertEqual(draw_line.call_count, 3)
        self.assertEqual(draw_circle.call_count, 3)
        self.assertTrue(all(call.args[1] == color for call in draw_line.call_args_list))
        self.assertTrue(all(call.args[1] == color for call in draw_circle.call_args_list))
        self.assertTrue(all(
            call.args[4] == ui.APP_ACTION_ICON_STROKE
            for call in draw_line.call_args_list
        ))

    def test_settings_uses_info_and_has_no_duplicate_kiwi_route(self):
        labels = dict(ui.SETTINGS_MENU_ITEMS)
        self.assertEqual(labels["tests"], "TOOLS")
        self.assertEqual(labels["system"], "SYSTEM")
        self.assertEqual(labels["settings_back"], "BACK")
        self.assertNotIn("kiwi", labels)
        self.assertEqual(ui.menu_icon_filename("system"), "info.png")

    def test_home_and_settings_tiles_use_requested_copy_and_full_subtitles(self):
        self.assertEqual(dict(ui.MENU_ITEMS), {
            "rx": "RECEIVERS", "audio": "AUDIO", "digital": "DIGITAL",
            "vosc": "CAPTIONS", "display": "DISPLAY", "dual": "DUAL RX",
            "settings": "SYSTEM", "tests": "APPS",
        })
        self.assertEqual(ui.menu_subtitle("digital"), "13 MODES")
        self.assertEqual(ui.HOME_MENU_SUBTITLES["vosc"], "TRANSCRIBE")
        self.assertNotIn("theme", dict(ui.SETTINGS_MENU_ITEMS))
        self.assertNotIn("theme", ui.SETTINGS_MENU_SUBTITLES)
        self.assertEqual(ui.navigation_back_surface("display"), "display")
        self.assertEqual((ui.APP_UI_STYLE.button.title_size,
                          ui.APP_UI_STYLE.button.subtitle_size), (14, 12))

        cache = mock.Mock()
        cache.texture.side_effect = lambda text, *_args, **_kwargs: (
            None, 117 if text == "COLORS & LAYOUT" else 50, 14,
        )
        box = (1034, 512, 1148, 576)
        with mock.patch.object(ui, "draw_styled_button_frame",
                               return_value=ui.APP_UI_STYLE.button.resolve()), \
             mock.patch.object(ui, "draw_text") as drawn, \
             mock.patch.object(ui, "draw_text_scaled_x") as scaled:
            ui.draw_styled_two_line_button(
                cache, box, "THEME", "COLORS & LAYOUT", fit_full_subtitle=True,
            )
        self.assertEqual((drawn.call_args.args[3], drawn.call_args.args[5]),
                         ("THEME", 14))
        self.assertEqual((scaled.call_args.args[3], scaled.call_args.args[5]),
                         ("COLORS & LAYOUT", 12))
        self.assertLess(scaled.call_args.args[6], 1)

    def test_drawers_share_one_back_target(self):
        expected = ui.lcd_drawer_back_box()
        self.assertEqual(ui.lcd_radio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_display_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_audio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_filter_drawer_boxes()["close"], expected)
        self.assertEqual(ui.receiver_home_drawer_boxes()["close"], expected)
        self.assertEqual(ui.fan_curve_drawer_boxes()["close"], expected)
        self.assertEqual(ui.compact_font_review_boxes()["exit"], expected)

    def test_font_review_owns_the_full_rail_without_covering_back(self):
        boxes = ui.compact_font_review_boxes()
        self.assertEqual(
            boxes["panel"],
            (ui.LCD_NAV_X0, 0, ui.LOGICAL_W, ui.LOGICAL_H),
        )
        back = boxes["exit"]
        self.assertLess(boxes["preview"][3], boxes["previous"][1])
        for name in ("previous", "next", "like", "delete", "use"):
            control = boxes[name]
            self.assertLessEqual(control[3], back[1])

    def test_settings_back_tile_uses_shared_back_target(self):
        last = len(ui.SETTINGS_MENU_ITEMS) - 1
        self.assertEqual(
            ui.lcd_nav_box(last, len(ui.SETTINGS_MENU_ITEMS), True),
            ui.lcd_drawer_back_box(),
        )

    def test_modes_drawer_contains_families_wspr_and_back_without_overlap(self):
        ui.LCD_RADIO_DRAWER_PROGRESS = 1.0
        mode_boxes = [box for _family, _modes, box in ui.radio_mode_layout()]
        step_boxes = [box for _step, box in ui.radio_step_options("kiwi")]
        back_box = ui.lcd_radio_drawer_close_box()
        for row in range(0, len(mode_boxes), 2):
            left, right = mode_boxes[row:row + 2]
            self.assertEqual(left[0], back_box[0])
            self.assertEqual(right[2], back_box[2])
            self.assertEqual(right[0] - left[2], 8)
        self.assertEqual([step for step, _box in ui.radio_step_options("kiwi")],
                         [10, 100, 1000, 5000])
        self.assertEqual(len(step_boxes), 4)
        frequency_boxes = [box for _step, box in ui.frequency_drawer_step_boxes("kiwi")]
        for (step, box), frequency_box in zip(ui.radio_step_options("kiwi"), frequency_boxes):
            self.assertEqual(ui.radio_option_at(*self._center(box)), ("step", step))
            self.assertEqual((box[0], box[2], box[3] - box[1]),
                             (frequency_box[0], frequency_box[2], 31))
        self.assertEqual(len({box[1] for box in step_boxes}), 1)
        self.assertIsNone(ui.radio_option_at(step_boxes[0][0] + 4, step_boxes[0][1] - 18))
        self.assertEqual(ui.radio_option_at(*self._center(
            next(box for step, box in ui.radio_step_options("fmdx") if step == 100_000)
        ), receiver_type="fmdx", fmdx_shared_control=True), ("step", 100_000))
        self.assertIsNone(ui.radio_option_at(*self._center(
            next(box for step, box in ui.radio_step_options("fmdx") if step == 100_000)
        ), receiver_type="fmdx", fmdx_shared_control=False))
        decoders = ui.radio_decoder_boxes()
        self.assertEqual({kind for kind, _ in decoders}, {"wspr", "sstv", "hell", "qrss", "cw"})
        overlaps = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
        for index, (kind, box) in enumerate(decoders):
            for other in (*mode_boxes, *step_boxes, back_box, *(b for _, b in decoders[index+1:])):
                self.assertFalse(overlaps(box, other), kind)
            x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
            self.assertEqual(ui.radio_option_at(x, y), ("workspace", kind))
            self.assertNotEqual(ui.radio_option_at(x, y, receiver_type="openwebrx"), ("workspace", kind))
            self.assertNotEqual(ui.radio_option_at(x, y, receiver_type="fmdx"), ("workspace", kind))

    def test_modes_drawer_highlights_the_selected_step_in_four_button_row(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        previous_progress = ui.LCD_RADIO_DRAWER_PROGRESS
        ui.LCD_RADIO_DRAWER_PROGRESS = 1.0
        try:
            with mock.patch.object(ui, 'draw_logical_rect'), \
                 mock.patch.object(ui, 'draw_sidebar_header'), \
                 mock.patch.object(ui, 'draw_radio_close_button'), \
                 mock.patch.object(ui, 'draw_radio_family_option'), \
                 mock.patch.object(ui, 'draw_lcd_drawer_heading'), \
                 mock.patch.object(ui, 'draw_radio_option'), \
                 mock.patch.object(ui, 'draw_picker_button') as buttons:
                ui.draw_radio_setup_panel(None, 'AM', 'DIG', 100,
                                          receiver_type='kiwi')
        finally:
            ui.LCD_RADIO_DRAWER_PROGRESS = previous_progress
        self.assertEqual([entry.args[2] for entry in buttons.call_args_list],
                         ['10 Hz', '100 Hz', '1 kHz', '5 kHz'])
        self.assertEqual([entry.args[4] for entry in buttons.call_args_list],
                         [False, True, False, False])

    def test_stats_close_target_is_inside_graph_header(self):
        graph = (120, 90, 900, 420)
        close = ui.cpu_utilization_graph_close_box(graph)
        self.assertGreaterEqual(close[0], graph[0])
        self.assertGreaterEqual(close[1], graph[1])
        self.assertLessEqual(close[2], graph[2])
        self.assertLess(close[3], graph[1] + 44)

    def test_live_pcm_uses_the_stats_close_button(self):
        graph = (120, 90, 900, 420)
        close = ui.audio_transport_graph_close_box(graph)
        self.assertEqual(close, ui.cpu_utilization_graph_close_box(graph))
        text_cache = object()
        with mock.patch.object(ui, 'draw_logical_rect'), \
             mock.patch.object(ui, 'draw_logical_line'), \
             mock.patch.object(ui, 'draw_text'), \
             mock.patch.object(ui, 'draw_styled_text_button') as button:
            ui.draw_audio_transport_graph(text_cache, (), graph)
        button.assert_called_once_with(text_cache, close, 'CLOSE', size=12)

    def test_frequency_drawer_controls_are_bounded_and_disjoint(self):
        boxes = ui.frequency_drawer_boxes()
        panel = boxes["panel"]
        controls = [boxes[name] for name in ("readout", "down", "up", "step_heading", "close")]
        controls += [box for _key, box in ui.frequency_drawer_key_boxes()]
        controls += [box for _step, box in ui.frequency_drawer_step_boxes("kiwi")]
        overlaps = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
        for box in controls:
            self.assertGreaterEqual(box[0], panel[0])
            self.assertGreaterEqual(box[1], panel[1])
            self.assertLessEqual(box[2], panel[2])
            self.assertLessEqual(box[3], panel[3])
        for index, box in enumerate(controls):
            for other in controls[index + 1:]:
                self.assertFalse(overlaps(box, other))
        for name in ("down", "up", "close"):
            box = boxes[name]
            self.assertEqual(ui.frequency_drawer_action_at((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), name)

    def test_frequency_drawer_direction_buttons_match_rail_tiles(self):
        boxes = ui.frequency_drawer_boxes()
        for name in ("down", "up"):
            x0, y0, x1, y1 = boxes[name]
            self.assertEqual((x1 - x0, y1 - y0),
                             (ui.LCD_NAV_TILE_W, ui.LCD_NAV_TILE_H))
        self.assertEqual(boxes["down"][1], boxes["up"][1])
        self.assertEqual(boxes["down"][3], boxes["up"][3])
        self.assertEqual(boxes["down"][1] - boxes["readout"][3], 16)
        self.assertEqual(ui.frequency_drawer_key_boxes()[0][1][1] - boxes["down"][3], 16)
        self.assertEqual(
            boxes["step_heading"][1] - max(box[3] for _key, box in ui.frequency_drawer_key_boxes()),
            16,
        )
        self.assertEqual(ui.frequency_drawer_step_boxes()[0][1][1] - boxes["step_heading"][3], 8)
        self.assertNotIn("entry", boxes)

    def test_frequency_drawer_no_longer_exposes_a_font_setting(self):
        # The big-frequency typeface is fixed to the enabled face, so the rail
        # must not offer a control to change it.
        boxes = ui.frequency_drawer_boxes()
        self.assertNotIn("font", boxes)
        for _step, box in ui.frequency_drawer_step_boxes("kiwi"):
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            self.assertNotEqual(ui.frequency_drawer_action_at(*center), "font")

    def test_frequency_drawer_lists_tune_steps_inline(self):
        # Tapping a step selects it in the frequency rail itself instead of
        # linking away to the Radio drawer's step screen.
        kiwi = ui.frequency_drawer_step_boxes("kiwi")
        self.assertEqual([step for step, _box in kiwi],
                         [step for step, _box in ui.RADIO_STEP_OPTIONS])
        fmdx = ui.frequency_drawer_step_boxes("fmdx")
        self.assertEqual([step for step, _box in fmdx], list(ui.FMDX_TUNE_STEPS_HZ))
        for step, box in kiwi + fmdx:
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            self.assertEqual(
                ui.frequency_drawer_action_at(*center, receiver_type="fmdx" if step in ui.FMDX_TUNE_STEPS_HZ else "kiwi"),
                f"step_{int(step)}",
            )
        self.assertEqual(len({box[1] for _step, box in kiwi}), 1)
        self.assertTrue(all((box[2] - box[0], box[3] - box[1]) == (55, 31)
                            for _step, box in kiwi))
        keys = ui.frequency_drawer_key_boxes()
        self.assertEqual(len(keys), 15)
        self.assertEqual([len(row) for row in ui.FREQUENCY_KEY_LABELS], [3] * 5)
        self.assertTrue(all((box[2] - box[0], box[3] - box[1]) == (72, 48)
                            for _key, box in keys))
        row_tops = sorted({box[1] for _key, box in keys})
        self.assertEqual([b - a for a, b in zip(row_tops, row_tops[1:])], [56] * 4)
        for key, box in keys:
            self.assertEqual(ui.frequency_drawer_action_at(*self._center(box)), f"key_{key}")

    def test_frequency_step_uses_hz_increment_and_receiver_bounds(self):
        self.assertEqual(ui.frequency_step_target(7075.0, 1, 100, 0, 30000), 7075.1)
        self.assertEqual(ui.frequency_step_target(10.0, -1, 100_000, 0, 108000), 0.0)
        self.assertEqual(ui.frequency_step_target(7075.05, 1, 100, 0, 30000), 7075.1)
        self.assertEqual(ui.frequency_step_target(7075.05, -1, 100, 0, 30000), 7075.0)
        self.assertEqual(ui.configured_tune_step_hz("kiwi", 500, 100_000), 500)
        self.assertEqual(ui.configured_tune_step_hz("fmdx", 500, 50_000), 50_000)
        self.assertEqual(ui.format_frequency_digits(7075.794), "007.075.794")
        self.assertEqual(ui.format_tune_step(100_000), "100 kHz")
        self.assertEqual(ui.format_small_tune_step(100_000), "100K")
        self.assertEqual(ui.edit_frequency_entry("7.075000", "1", True), ("1", False))
        self.assertEqual(ui.edit_frequency_entry("7.", "."), ("7.", False))
        self.assertEqual(ui.edit_frequency_entry("7.", "000"), ("7.000", False))
        self.assertEqual(ui.edit_frequency_entry("7.000", "DEL"), ("7.00", False))
        self.assertEqual(ui.edit_frequency_entry("7.000", "CLR"), ("", False))
        self.assertEqual(ui.edit_frequency_entry("", "1"), ("1", False))
        self.assertEqual(ui.edit_frequency_entry("0", "1"), ("1", False))
        self.assertEqual(ui.edit_frequency_entry("", "00"), ("0", False))
        self.assertEqual(ui.edit_frequency_entry("", "."), ("0.", False))
        self.assertEqual(ui.frequency_entry_preview_khz("7.125", 7075.0, False), 7125.0)
        self.assertEqual(ui.frequency_entry_preview_khz("", 7075.0, False), 0.0)
        self.assertEqual(ui.frequency_entry_preview_khz("7.125", 7075.0, True), 7075.0)
        self.assertEqual(
            [ui.next_radio_tune_step(step) for step in (10, 100, 1000, 5000)],
            [100, 1000, 5000, 10],
        )

    def test_frequency_arrow_hold_accelerates_and_cancels_cleanly(self):
        receiver = ("receiver", 1, "kiwi")
        hold = ui.FrequencyArrowHold()
        hold.begin("up", 10.0, receiver)
        self.assertIsNone(hold.tick(10.49, "up", receiver))
        self.assertEqual(hold.tick(10.50, "up", receiver), "up")
        first_interval = hold.next_at - 10.50
        self.assertEqual(hold.tick(13.0, "up", receiver), "up")
        self.assertLess(hold.next_at - 13.0, first_interval)
        self.assertFalse(hold.release("up", receiver))

        hold.begin("down", 20.0, receiver)
        self.assertTrue(hold.release("down", receiver))
        hold.begin("up", 30.0, receiver)
        self.assertIsNone(hold.tick(30.2, None, receiver))
        self.assertFalse(hold.release("up", receiver))
        hold.begin("up", 40.0, receiver)
        self.assertIsNone(hold.tick(40.5, "up", ("another receiver", 2, "kiwi")))
        self.assertFalse(hold.release("up", receiver))

    def test_entire_compact_frequency_area_opens_tuning_target(self):
        compact = ui.compact_frequency_touch_box()
        measured = (compact[0] + 40, compact[1] + 10, compact[2] - 40, compact[3] - 10)
        self.assertTrue(ui.is_frequency_readout_touch(compact[0] + 2, compact[1] + 2, measured, compact=True))
        self.assertFalse(ui.is_frequency_readout_touch(compact[0] + 2, compact[1] + 2, measured, compact=False))
        self.assertFalse(ui.is_frequency_readout_touch(
            compact[0] + 2, compact[1] + 2, measured,
            compact=True, home_available=False,
        ))

    def test_sidebar_headers_use_one_centered_compact_style(self):
        with mock.patch.object(ui, "draw_logical_rect") as draw_rect, mock.patch.object(ui, "draw_logical_line") as draw_line, mock.patch.object(ui, "draw_text") as draw_text:
            ui.draw_sidebar_header(object(), "SETTINGS")
        args = draw_text.call_args.args
        self.assertEqual(args[1], (ui.LCD_NAV_X0 + ui.LOGICAL_W) / 2)
        self.assertEqual(args[5], 15)
        self.assertTrue(args[6])
        self.assertEqual(args[8], "cm")
        self.assertEqual(draw_line.call_args.args[:4],
                         (ui.LCD_NAV_X0 + 10, ui.LCD_DRAWER_HEADER_H,
                          ui.LOGICAL_W - 10, ui.LCD_DRAWER_HEADER_H))
        self.assertEqual(draw_rect.call_args.args[-1], (0, 0, 0, 255))


class ParentNavigationTests(unittest.TestCase):
    def test_shared_destination_records_the_surface_that_opened_it(self):
        self.assertEqual(ui.navigation_parent(ui.MENU_ITEMS, "rx"), "home")
        self.assertEqual(ui.navigation_parent(ui.MENU_ITEMS, "display"), "home")
        self.assertEqual(ui.navigation_parent(ui.MENU_ITEMS, "dual"), "home")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "tests"), "settings")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "settings_back"), "home")

    def test_unknown_parent_falls_back_to_home(self):
        self.assertEqual(ui.navigation_back_surface("digi"), "digi")
        self.assertEqual(ui.navigation_back_surface("settings"), "settings")
        self.assertEqual(ui.navigation_back_surface("home"), "home")
        self.assertEqual(ui.navigation_back_surface("unexpected"), "home")

    def test_nested_back_returns_to_the_immediate_previous_screen(self):
        self.assertEqual(ui.navigation_previous_surface("receiver_map", "home"), "receivers")
        self.assertEqual(ui.navigation_previous_surface("fan_curve", "settings"), "info")
        self.assertEqual(ui.navigation_previous_surface("font_review", "frequency"), "frequency")
        self.assertEqual(ui.navigation_previous_surface("display", "settings"), "settings")

    def test_known_leaf_surfaces_can_be_restored(self):
        for surface in ("settings", "receivers", "info", "apps", "audio", "frequency", "modes", "wspr"):
            self.assertEqual(ui.navigation_back_surface(surface), surface)

    def test_stats_keeps_settings_surface_when_launched_from_settings(self):
        self.assertTrue(ui.stats_keeps_settings_sidebar("settings"))
        self.assertFalse(ui.stats_keeps_settings_sidebar("home"))


class ReceiverBrowserTests(unittest.TestCase):
    def records(self):
        catalog = ui.receiver_catalog
        return catalog.merge_catalogs(
            (catalog.normalize_receiver({
                "id": "kiwi:a", "protocol": "kiwi", "endpoint": "https://kiwi-a.test",
                "name": "Kiwi A", "location": "Alabama", "favorite": True,
            }),),
            (catalog.normalize_receiver({
                "id": "openwebrx:o", "protocol": "openwebrx", "endpoint": "owrxs://owrx.test",
                "name": "OpenWebRX O", "location": "Finland",
            }),),
            (catalog.normalize_receiver({
                "id": "local:l", "protocol": "kiwi", "source_group": "local",
                "endpoint": "http://kiwisdr.local:8073", "name": "Local KiwiSDR", "location": "LAN",
            }),),
            (catalog.normalize_receiver({
                "id": "fmdx:f", "protocol": "fmdx", "endpoint": "https://fm.test",
                "name": "FM A", "location": "FM land",
            }),),
        )

    def test_receiver_browser_defaults_to_kiwi_list(self):
        state = ui.ReceiverBrowserState()
        self.assertEqual((state.view, state.source), ("list", "kiwi"))
        self.assertFalse(state.favorites_only)

    def test_source_segments_are_single_select_and_in_priority_order(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        segments = ui.receiver_source_segments()
        self.assertEqual([source for source, _box in segments],
                         ["usb", "local", "kiwi", "openwebrx", "fmdx", "all"])
        for box in (box for _source, box in segments):
            self.assertEqual((box[0], box[2]),
                             (ui.PICKER_EXIT_BOX[0], ui.PICKER_EXIT_BOX[2]))
            self.assertGreater(box[2] - box[0], box[3] - box[1])
            self.assertEqual(box[3] - box[1], 48)
        for index, (_name, a) in enumerate(segments):
            for _other, b in segments[index + 1:]:
                self.assertFalse(ui.boxes_overlap(a, b))
        self.assertEqual(segments[0][1][1], ui.LCD_DRAWER_HEADER_H + 16)
        self.assertTrue(all(
            segments[index + 1][1][1] - segments[index][1][3] == 14
            for index in range(len(segments) - 1)
        ))
        self.assertLess(segments[-1][1][3], ui.PICKER_MAP_MODE_BOX[1])
        self.assertEqual(ui.PICKER_HEADER_H, 0)

    def test_list_and_map_use_the_same_filtered_records(self):
        state = ui.ReceiverBrowserState(source="openwebrx")
        records = self.records()
        self.assertEqual(ui.browser_records(records, state, "list"),
                         ui.browser_records(records, state, "map"))
        self.assertEqual([record.protocol for record in ui.browser_records(records, state, "list")],
                         ["openwebrx"])

    def test_source_switch_resets_browser_not_view(self):
        state = ui.ReceiverBrowserState(view="map", source="kiwi", query="kiwi", favorites_only=True)
        switched = state.with_source("fmdx")
        self.assertEqual((switched.view, switched.source), ("map", "fmdx"))
        self.assertEqual((switched.query, switched.favorites_only), ("kiwi", True))
        self.assertEqual(switched.with_view("list").view, "list")
        self.assertEqual(switched.with_source("nonsense").source, "fmdx")

    def test_local_segment_keeps_kiwi_transport(self):
        records = self.records()
        local = ui.browser_records(records, ui.ReceiverBrowserState(source="local"), "list")
        self.assertEqual([record.protocol for record in local], ["kiwi"])

    def test_openwebrx_segment_has_seeded_receivers(self):
        openwebrx = [record for record in ui.RECEIVER_CATALOG if record.protocol == "openwebrx"]
        self.assertTrue(openwebrx)
        self.assertEqual({record.source_group for record in openwebrx}, {"openwebrx"})
        rows = ui.filtered_stations(ui.STATIONS, "", "name", "openwebrx", set())
        self.assertTrue(rows)

    def test_globe_refresh_cannot_erase_openwebrx_catalog_rows(self):
        globe_only = ((
            "Globe Kiwi", "London", "http://kiwi-map.test:8073",
            1, 8, 51.5, -0.1, "kiwi",
        ),)
        combined = ui.merge_station_rows(globe_only, ui.STATIONS)
        openwebrx = ui.filtered_stations(
            combined, "", "name", "openwebrx", set(), {},
        )
        self.assertTrue(openwebrx)
        self.assertTrue(all(ui.station_receiver_type(row) == "openwebrx" for row in openwebrx))

    def test_kiwi_and_local_segments_are_exclusive(self):
        kiwi = ui.filtered_stations(ui.STATIONS, "", "name", "kiwi", set())
        local = ui.filtered_stations(ui.STATIONS, "", "name", "local", set())
        self.assertTrue(local)
        self.assertEqual(set(row[2] for row in kiwi) & set(row[2] for row in local), set())

    def test_favorites_only_filters_across_sources(self):
        records = self.records()
        favorites = ui.browser_records(
            records, ui.ReceiverBrowserState(source="all", favorites_only=True), "list")
        self.assertEqual([record.id for record in favorites], ["kiwi:a"])

    def test_receiver_sort_cycles_through_four_states_and_wraps(self):
        modes = []
        mode = ui.RECEIVER_SORT_MODES[0]
        for _ in range(4):
            modes.append(mode)
            mode = ui.next_receiver_sort_mode(mode)
        self.assertEqual(tuple(modes), ui.RECEIVER_SORT_MODES)
        self.assertEqual(mode, ui.RECEIVER_SORT_MODES[0])
        self.assertEqual(
            [ui.receiver_sort_label(value) for value in modes],
            ["NEAREST FIRST", "FARTHEST FIRST", "NAME A-Z", "NAME Z-A"],
        )

    def test_receiver_distance_and_name_sort_orders_are_exact(self):
        stations = (
            ("Bravo", "B", "http://bravo.test", 0, 4, 0.0, 10.0, "kiwi"),
            ("Alpha", "A", "http://alpha.test", 0, 4, 0.0, 1.0, "kiwi"),
            ("Charlie", "C", "http://charlie.test", 0, 4, None, None, "kiwi"),
        )
        home = {"lat": 0.0, "lon": 0.0}

        def names(mode):
            return [row[0] for row in ui.filtered_stations(
                stations, "", mode, "all", set(), {}, home,
            )]

        self.assertEqual(names("distance_near"), ["Alpha", "Bravo", "Charlie"])
        self.assertEqual(names("distance_far"), ["Bravo", "Alpha", "Charlie"])
        self.assertEqual(names("name_az"), ["Alpha", "Bravo", "Charlie"])
        self.assertEqual(names("name_za"), ["Charlie", "Bravo", "Alpha"])

    def test_health_badges_do_not_override_selected_sort_order(self):
        stations = (
            ("Alpha", "", "http://alpha.test"),
            ("Bravo", "", "http://bravo.test"),
        )
        health = {
            "http://alpha.test": {"audio": False, "waterfall": False, "checked": ui.time.time()},
            "http://bravo.test": {"audio": True, "waterfall": True, "checked": ui.time.time()},
        }
        self.assertEqual(ui.health_prioritized_stations(stations, health, "name_az"), list(stations))

    def test_active_receiver_centers_in_its_category_and_all(self):
        stations = tuple(
            (f"Receiver {index}", "", f"http://rx{index}.test", 0, 4)
            for index in range(10)
        )
        active = "http://rx5.test/"
        expected = ui.centered_receiver_scroll(stations, active)
        self.assertEqual(expected, 3)
        self.assertEqual(
            ui.active_receiver_scroll_for_source(
                stations, active, "kiwi", "kiwi",
            ),
            expected,
        )
        self.assertEqual(
            ui.active_receiver_scroll_for_source(
                stations, active, "all", "kiwi",
            ),
            expected,
        )

    def test_active_receiver_near_list_end_stays_third_without_losing_tail_rows(self):
        stations = tuple(
            (f"Receiver {index}", "", f"http://rx{index}.test", 0, 4)
            for index in range(10)
        )
        focused = ui.focused_receiver_rows_for_source(
            stations, "http://rx9.test/", "kiwi", "kiwi",
        )
        self.assertEqual([row[0] for row in focused[:6]], [
            "Receiver 7", "Receiver 8", "Receiver 9",
            "Receiver 0", "Receiver 1", "Receiver 2",
        ])
        self.assertEqual(len(focused), len(stations))
        self.assertEqual(set(focused), set(stations))
        active_box = ui.station_tile(2, 0)
        third_box = ui.station_tile(2, 0)
        self.assertIsNotNone(active_box)
        self.assertEqual(active_box[1:], third_box[1:])
        self.assertLessEqual(
            ui.centered_receiver_scroll(stations, "http://rx9.test/"),
            ui.station_page_max(stations),
        )

    def test_fmdx_notice_offset_still_places_active_receiver_third(self):
        stations = tuple(
            (f"Receiver {index}", "", f"http://rx{index}.test", 0, 4)
            for index in range(6)
        )
        focused = ui.focused_receiver_rows_for_source(
            stations, "http://rx5.test/", "fmdx", "fmdx", leading_rows=1,
        )
        self.assertEqual(focused[1][0], "Receiver 5")
        active_box = ui.station_tile(1 + 1, 0)
        third_box = ui.station_tile(2, 0)
        self.assertEqual(active_box[1:], third_box[1:])

    def test_unrelated_category_starts_at_top_instead_of_centering_active(self):
        stations = tuple(
            (f"Receiver {index}", "", f"http://rx{index}.test", 0, 4)
            for index in range(10)
        )
        self.assertEqual(
            ui.active_receiver_scroll_for_source(
                stations, "http://rx5.test", "openwebrx", "kiwi",
            ),
            0,
        )


class WorkspaceLayoutTests(unittest.TestCase):
    def test_settings_center_workspace_stays_outside_sidebar(self):
        x0, y0, x1, y1 = ui.settings_center_workspace_box()
        self.assertGreaterEqual(x0, 0)
        self.assertEqual(x1, ui.LCD_NAV_X0)
        self.assertGreater(y1, y0)
        self.assertLessEqual(y1, ui.LOGICAL_H)



class AllScreenLayoutTests(unittest.TestCase):
    """Every drawer/workspace layout must stay on-screen and not collide.

    This is the durable guard behind an audit that walked every screen one
    by one: touch targets belong inside the 1280x800 logical display, and two
    sibling controls must never partially overlap (a control fully nested in
    a container, such as the reveal eye inside a password field, is fine).
    """

    PARENTS = {"panel", "readout"}
    _EXTRA_ARGS = {
        "networks": [],
        "receivers": [],
        "page": 1,
        "tile_count": 4,
        "item_count": 4,
        "scroll_y": 0.0,
    }

    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()

    def _iter_layout_functions(self):
        for name, func in sorted(vars(ui).items()):
            if name.endswith("_boxes") and callable(func):
                yield name, func

    def _arguments(self, func):
        import inspect

        args = []
        for parameter in inspect.signature(func).parameters.values():
            if parameter.default is not inspect.Parameter.empty:
                args.append(parameter.default)
            elif parameter.name in self._EXTRA_ARGS:
                args.append(self._EXTRA_ARGS[parameter.name])
            else:
                return None
        return args

    def _walk(self, value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from self._walk(item, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            if len(value) == 4 and all(isinstance(v, (int, float)) for v in value):
                yield path, tuple(value)
            else:
                for index, item in enumerate(value):
                    yield from self._walk(item, f"{path}[{index}]")

    @staticmethod
    def _overlaps(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    @staticmethod
    def _contains(outer, inner):
        return (
            outer[0] <= inner[0]
            and outer[1] <= inner[1]
            and outer[2] >= inner[2]
            and outer[3] >= inner[3]
        )

    def test_every_layout_is_bounded_and_collision_free(self):
        scanned = 0
        for name, func in self._iter_layout_functions():
            args = self._arguments(func)
            if args is None:
                continue
            layout = func(*args)
            if layout is None:
                continue
            scanned += 1
            controls = []
            for path, box in self._walk(layout, name):
                if path.rsplit(".", 1)[-1].split("[")[0] in self.PARENTS:
                    continue
                x0, y0, x1, y1 = box
                if (x0, y0, x1, y1) == (0, 0, 0, 0):
                    continue
                self.assertLess(x0, x1, f"{path} inverted width {box}")
                self.assertLess(y0, y1, f"{path} inverted height {box}")
                self.assertGreaterEqual(x0, 0, f"{path} left of display {box}")
                self.assertGreaterEqual(y0, 0, f"{path} above display {box}")
                self.assertLessEqual(x1, ui.LOGICAL_W, f"{path} right of display {box}")
                self.assertLessEqual(y1, ui.LOGICAL_H, f"{path} below display {box}")
                controls.append((path, box))
            for index, (path_a, box_a) in enumerate(controls):
                for path_b, box_b in controls[index + 1:]:
                    if not self._overlaps(box_a, box_b):
                        continue
                    if self._contains(box_a, box_b) or self._contains(box_b, box_a):
                        continue
                    self.fail(f"{name}: {path_a}{box_a} collides with {path_b}{box_b}")
        self.assertGreaterEqual(scanned, 15)


class BigFrequencyStyleTests(unittest.TestCase):
    """The large readout and the compact Home rail keep their intended sizes."""

    def test_one_shared_face_size_and_colour(self):
        self.assertEqual(ui.BIG_FREQUENCY_SIZE, 58)
        self.assertEqual(ui.COMPACT_FREQUENCY_SIZE, 36)
        self.assertEqual(ui.BIG_FREQUENCY_COLOR, ui.VFO_NEON_COLOR)

    def test_helper_draws_the_shared_style(self):
        calls = []
        cache = mock.Mock()
        cache.font.return_value = mock.Mock(size=lambda text: (100, 30))
        with mock.patch.object(ui, "draw_text_scaled_x", side_effect=lambda *a, **k: calls.append((a, k))):
            ui.draw_big_frequency(cache, 7075.794, 500, 40, 300, family="Oxanium")
            ui.draw_big_frequency(cache, 0, 500, 40, 300, display_text="0")
        self.assertEqual(len(calls), 2)
        args, kwargs = calls[0]
        self.assertEqual(args[3], ui.sdr_ui.format_freq(7075.794))
        self.assertEqual(args[4], ui.BIG_FREQUENCY_COLOR)
        self.assertEqual(args[5], ui.BIG_FREQUENCY_SIZE)
        self.assertEqual(kwargs.get("family"), "Oxanium")
        self.assertTrue(kwargs.get("bold"))
        self.assertEqual(kwargs.get("anchor"), "rm")
        self.assertEqual(calls[1][0][3], "0")

    def test_frequency_rail_readout_uses_the_shared_helper(self):
        calls = []
        with mock.patch.object(ui, "draw_big_frequency", side_effect=lambda *a, **k: calls.append((a, k))), \
                mock.patch.object(ui, "draw_logical_rect") as rect, \
                mock.patch.object(ui, "draw_logical_line"), \
                mock.patch.object(ui, "draw_logical_rounded_rect"), \
                mock.patch.object(ui, "draw_sidebar_header"), \
                mock.patch.object(ui, "draw_text"), \
                mock.patch.object(ui, "draw_picker_button"), \
                mock.patch.object(ui, "draw_radio_close_button"), \
                mock.patch.object(ui, "frequency_chevron_texture", return_value=(0, 10, 10)), \
                mock.patch.object(ui, "draw_textured_quad"):
            ui.draw_frequency_drawer(object(), 7075.794, 100, "Oxanium")
            ui.draw_frequency_drawer(
                object(), 7075.794, 100, "Oxanium", entry_value="7.125",
                entry_replace_on_digit=False,
            )
            ui.draw_frequency_drawer(
                object(), 7075.794, 100, "Oxanium", entry_value="",
                entry_replace_on_digit=False,
            )
            ui.draw_frequency_drawer(
                object(), 7075.794, 100, "Oxanium", entry_value="1",
                entry_replace_on_digit=False,
            )
            ui.draw_frequency_drawer(
                object(), 7075.794, 100, "Oxanium", entry_value="999999",
                entry_invalid=True, entry_replace_on_digit=False,
            )
        self.assertEqual(len(calls), 5)
        args, kwargs = calls[0]
        self.assertEqual(args[1], 7075.794)
        self.assertEqual(kwargs.get("family"), "Oxanium")
        self.assertEqual(calls[1][0][1], 7125.0)
        self.assertEqual(calls[1][1]["display_text"], "7.125")
        self.assertEqual(calls[2][0][1], 0.0)
        self.assertEqual(calls[2][1]["display_text"], "0")
        self.assertEqual(calls[3][1]["display_text"], "1")
        self.assertIn(
            mock.call(*ui.frequency_drawer_boxes()["readout"],
                      ui.APP_UI_STYLE.palette.top_instrument_band),
            rect.call_args_list,
        )
        self.assertIn(
            mock.call(*ui.frequency_drawer_boxes()["readout"],
                      ui.APP_UI_STYLE.palette.danger),
            rect.call_args_list,
        )


class FmdxDisclaimerTests(unittest.TestCase):
    def test_disclaimer_uses_first_receiver_row_without_an_action(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        boxes = ui.fmdx_disclaimer_boxes()
        self.assertEqual(boxes["panel"], ui.station_tile(0, 0))
        self.assertEqual(set(boxes), {"panel"})

    def test_notice_offsets_real_receiver_rows(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        stations = [("A", "Somewhere", "http://a.test:8073")]
        first_receiver = ui.station_tile(1, 0)
        center = ((first_receiver[0] + first_receiver[2]) / 2,
                  (first_receiver[1] + first_receiver[3]) / 2)
        self.assertEqual(ui.station_at(*center, stations, 0, leading_rows=1), 0)
        notice = ui.station_tile(0, 0)
        notice_center = ((notice[0] + notice[2]) / 2, (notice[1] + notice[3]) / 2)
        self.assertIsNone(ui.station_at(*notice_center, stations, 0, leading_rows=1))

    def test_notice_reuses_server_row_frame_and_stacks_subtitle_under_title(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        boxes = ui.fmdx_disclaimer_boxes()
        cache = object()
        text_calls = []
        with mock.patch.object(ui, "draw_station_list_frame") as frame, \
                mock.patch.object(ui, "draw_logical_circle"), \
                mock.patch.object(ui, "draw_text", side_effect=lambda *a, **k: text_calls.append((a, k))), \
                mock.patch.object(ui, "fit_station_text", side_effect=lambda _c, text, *_a, **_k: text), \
                mock.patch.object(ui, "draw_radio_option") as option:
            ui.draw_fmdx_disclaimer(cache)
        frame.assert_called_once_with(
            boxes["panel"], ui.STATION_LIST_FILL, ui.FMDX_DISCLAIMER_OUTLINE, 2,
        )
        option.assert_not_called()
        self.assertEqual([call[0][3] for call in text_calls], [
            ui.FMDX_DISCLAIMER_TITLE,
            *ui.FMDX_DISCLAIMER_SUBTITLE_LINES,
        ])
        self.assertLess(text_calls[0][0][2], text_calls[1][0][2])
        self.assertLess(text_calls[1][0][2], text_calls[2][0][2])

    def test_notice_is_shown_once_per_process_and_resets_on_restart(self):
        visible, shown = ui.fmdx_disclaimer_transition("fmdx", False, False)
        self.assertEqual((visible, shown), (True, True))
        # Re-selecting FM-DX does not recreate or toggle the row.
        self.assertEqual(ui.fmdx_disclaimer_transition("fmdx", visible, shown), (True, True))
        visible = False  # Leaving the FM-DX view dismisses it.
        visible, shown = ui.fmdx_disclaimer_transition("kiwi", visible, shown)
        self.assertEqual((visible, shown), (False, True))
        self.assertEqual(ui.fmdx_disclaimer_transition("fmdx", visible, shown), (False, True))
        # A new process initializes both flags to False.
        self.assertEqual(ui.fmdx_disclaimer_transition("fmdx", False, False), (True, True))


class ReceiverListStyleTests(unittest.TestCase):
    class Cache:
        @staticmethod
        def texture(text, _size, _color, **_kwargs):
            return 0, len(str(text)) * 10, 14

    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()

    def test_receiver_browser_uses_the_standard_1024_256_split(self):
        self.assertEqual(ui.PICKER_BOX, (0, 0, 1024, 800))
        self.assertEqual(ui.LOGICAL_W - ui.PICKER_BOX[2], 256)
        self.assertTrue(all(box[0] >= 1024 for _source, box in ui.PICKER_SOURCE_SEGMENT_BOXES))

    def test_theme_uses_exact_receiver_palette_and_type_scale(self):
        theme = ui.RECEIVER_LIST_THEME
        self.assertEqual(theme.main_background, (18, 18, 18, 255))
        self.assertEqual(theme.sidebar_background, (0, 0, 0, 255))
        self.assertEqual(theme.primary_text, (255, 255, 255))
        self.assertEqual(theme.secondary_text, (160, 160, 160))
        self.assertEqual(theme.focus, (0, 229, 255, 255))
        self.assertEqual((theme.label_size, theme.server_name_size), (13, 18))

    def test_badges_share_labels_and_exact_state_colors(self):
        theme = ui.RECEIVER_LIST_THEME
        ready = ui.receiver_health_badge("AUDIO", {"audio": True}, "audio", True)
        inactive = ui.receiver_health_badge("WATERFALL", {"waterfall": False}, "waterfall", True)
        untested = ui.receiver_health_badge("AUDIO", {}, "audio", False)
        waiting = ui.receiver_health_badge("WATERFALL", {}, "waterfall", False, pending=True)
        self.assertEqual((ready.label, ready.fill), ("AUDIO", theme.ready))
        self.assertEqual((inactive.label, inactive.fill, inactive.text),
                         ("WATERFALL", theme.secondary_text, theme.secondary_text))
        self.assertEqual((untested.label, untested.fill, untested.text),
                         ("AUDIO", theme.secondary_text, theme.secondary_text))
        self.assertEqual((waiting.label, waiting.fill), ("WATERFALL", theme.waiting))
        self.assertEqual(ui.receiver_source_badge("kiwi").fill, theme.kiwi)
        self.assertEqual(theme.kiwi, (0, 229, 255, 255))
        self.assertEqual(ui.receiver_source_badge("openwebrx").fill, theme.openwebrx)
        self.assertEqual(ui.receiver_source_badge("fmdx").fill, theme.fmdx)
        self.assertEqual(ui.receiver_source_badge("kiwi", True).label, "LAN")

    def test_receiver_badges_are_outlined_in_their_state_color(self):
        badge = ui.receiver_source_badge("openwebrx")
        with mock.patch.object(ui, "draw_logical_rounded_rect") as rounded, \
                mock.patch.object(ui, "draw_text") as text:
            ui.draw_receiver_badge(
                self.Cache(), 10, 20, badge, background=(30, 30, 30, 255),
            )
        args = rounded.call_args.args
        self.assertEqual(args[5], (30, 30, 30, 255))
        self.assertEqual(args[6], badge.fill)
        self.assertEqual(args[7], 2)
        self.assertEqual(text.call_args.args[4], badge.fill[:3])

    def test_long_server_names_use_three_dot_elision(self):
        fitted = ui.fit_receiver_name(self.Cache(), "A very long receiver server name", 105)
        self.assertTrue(fitted.endswith("..."))
        self.assertLessEqual(len(fitted) * 10, 105)

    def test_selected_filter_has_dark_gray_fill_and_light_gray_border(self):
        box = (1090, 76, 1270, 128)
        with mock.patch.object(ui, "draw_logical_rounded_rect") as rounded, \
                mock.patch.object(ui, "draw_text") as text:
            ui.draw_receiver_filter_button(self.Cache(), box, "LAN", True)
        rounded.assert_called_once_with(
            *box, ui.APP_UI_STYLE.button.radius,
            ui.APP_UI_STYLE.palette.active_surface, ui.APP_UI_STYLE.palette.active_border, 2,
        )
        self.assertEqual(text.call_args.args[4], ui.APP_UI_STYLE.palette.text)

    def test_receiver_rows_are_six_complete_with_balanced_padding(self):
        boxes = [ui.station_tile(index, 0) for index in range(6)]
        self.assertTrue(all(box is not None for box in boxes))
        self.assertTrue(all(box[3] - box[1] == ui.RECEIVER_PICKER_ROW_HEIGHT for box in boxes))
        self.assertEqual(boxes[0][1] - ui.PICKER_HEADER_H, ui.RECEIVER_PICKER_ROW_INSET)
        self.assertEqual(ui.LOGICAL_H - boxes[-1][3], ui.RECEIVER_PICKER_ROW_INSET)

    def test_sorted_rows_keep_selected_receiver_in_natural_order(self):
        stations = [
            (f"Receiver {index}", "", f"http://rx{index}.test", 0, 4)
            for index in range(10)
        ]
        focused = ui.receiver_rows_for_display(
            stations, "http://rx9.test", "kiwi", "kiwi", True,
        )
        sorted_rows = ui.receiver_rows_for_display(
            stations, "http://rx9.test", "kiwi", "kiwi", False,
        )
        self.assertEqual(focused[2][0], "Receiver 9")
        self.assertEqual(sorted_rows, stations)

    def test_sort_notice_uses_zoom_green_osd_typography(self):
        with mock.patch.object(ui, "draw_green_osd_panel") as panel, \
                mock.patch.object(ui, "draw_text") as text, \
                mock.patch.object(ui, "draw_logical_polyline") as chevron:
            ui.draw_receiver_sort_notice(
                self.Cache(), "SORTED BY FARTHEST FIRST", 220, "distance_far",
            )
        panel.assert_called_once_with(ui.receiver_list_notice_box(), 220)
        labels = [call.args[3] for call in text.call_args_list]
        self.assertEqual(labels, ["SORTED BY", "FARTHEST FIRST"])
        x0, y0, x1, _y1 = ui.ZOOM_OSD_BOX
        self.assertEqual(text.call_args_list[0].args[1:3], (x0 + 18, y0 + 22))
        self.assertEqual(chevron.call_args.args[0],
                         ui.sort_chevron_points(ui.ZOOM_OSD_BOX, "distance_far"))
        self.assertEqual(chevron.call_args.args[1:], ((72, 255, 122, 220), 5))
        for call in text.call_args_list:
            self.assertEqual(call.args[4:9], ((72, 255, 122), 28, True, True, "lm"))
            self.assertEqual(call.kwargs["alpha"], 220 / 255.0)

    def test_sort_chevron_points_match_ascending_and_descending_modes(self):
        box = ui.ZOOM_OSD_BOX
        for mode in ("distance_near", "name_az"):
            left, tip, right = ui.sort_chevron_points(box, mode)
            self.assertLess(tip[1], left[1])
            self.assertEqual(left[1], right[1])
            self.assertEqual(right[0], box[2] - 21)
        for mode in ("distance_far", "name_za"):
            left, tip, right = ui.sort_chevron_points(box, mode)
            self.assertGreater(tip[1], left[1])
            self.assertEqual(left[1], right[1])
            self.assertEqual(right[0], box[2] - 21)

    def test_active_receiver_selects_its_source_tab(self):
        stations = (
            ("Kiwi", "NL", "http://kiwi.test:8073", 0, 4, 1.0, 2.0, "kiwi"),
            ("OpenWebRX", "DE", "owrxs://owrx.test", 0, 4, 3.0, 4.0, "openwebrx"),
            ("FM-DX", "FR", "http://fmdx.test", 0, 4, 5.0, 6.0, "fmdx"),
        )
        self.assertEqual(
            ui.active_receiver_source(stations, "owrxs://owrx.test/", "kiwi"),
            "openwebrx",
        )
        self.assertEqual(
            ui.active_receiver_source(stations, "http://fmdx.test", "fmdx"),
            "fmdx",
        )

    def test_active_receiver_is_scrolled_to_the_middle_row(self):
        stations = tuple(
            (f"Receiver {index}", "", f"http://rx{index}.test", 0, 4)
            for index in range(10)
        )
        scroll = ui.centered_receiver_scroll(stations, "http://rx4.test/")
        self.assertEqual(scroll, 2)
        selected_box = ui.station_tile(4, scroll)
        middle_box = ui.station_tile(2, 0)
        self.assertEqual(selected_box[1:], middle_box[1:])

    def test_openwebrx_catalog_coordinates_become_globe_points(self):
        stations = (
            ("OWRX", "Berlin", "owrxs://owrx.test", 1, 4, 52.52, 13.405, "openwebrx"),
        )
        points = ui.merge_receiver_map_stations([], stations)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["receiver_type"], "openwebrx")
        self.assertEqual(
            ui.receiver_map_server_center(points, "owrxs://owrx.test/"),
            (ui.math.radians(13.405), ui.math.radians(52.52)),
        )

    def test_receiver_actions_use_the_lower_wide_rail_grid(self):
        boxes = ui.receiver_picker_command_boxes()
        self.assertEqual(len(boxes), 4)
        self.assertGreaterEqual(min(box[1] for box in boxes), 466)
        self.assertTrue(all(box[2] <= ui.LOGICAL_W for box in boxes))
        self.assertTrue(all(box[2] - box[0] == ui.LCD_NAV_TILE_W and
                            box[3] - box[1] == ui.LCD_NAV_TILE_H for box in boxes))
        self.assertEqual(ui.RECEIVER_PICKER_ACTION_SIZE, ui.LCD_NAV_TILE_W)
        self.assertEqual(ui.RECEIVER_PICKER_ACTION_GAP, ui.LCD_NAV_GAP)
        back = ui.RECEIVER_PICKER_BACK_BOX
        self.assertEqual(min(box[0] for box in boxes), back[0])
        self.assertEqual(max(box[2] for box in boxes), back[2])
        self.assertEqual(back[1] - max(box[3] for box in boxes), ui.RECEIVER_PICKER_ACTION_GAP)

    def test_receiver_action_icons_match_home_menu_scale(self):
        self.assertEqual(ui.RECEIVER_ACTION_ICON_SIZE, ui.APP_ACTION_ICON_SIZE)
        with mock.patch.object(ui, "draw_logical_circle") as circle, \
                mock.patch.object(ui, "draw_logical_line") as line:
            ui.draw_receiver_action_icon(
                self.Cache(), ui.PICKER_SEARCH_BOX, "search", (255, 255, 255, 255),
            )
        self.assertEqual(circle.call_args.args[2], 15)
        self.assertEqual(circle.call_args.kwargs["width"], ui.APP_ACTION_ICON_STROKE)
        self.assertEqual(line.call_args.args[5], ui.APP_ACTION_ICON_STROKE)

    def test_receiver_globe_icon_is_larger_than_other_action_icons(self):
        self.assertGreater(ui.RECEIVER_GLOBE_ICON_SIZE, ui.RECEIVER_ACTION_ICON_SIZE)
        self.assertLess(ui.RECEIVER_GLOBE_ICON_SIZE, ui.RECEIVER_PICKER_ACTION_SIZE)

    def test_sort_icon_uses_three_balanced_lines_with_shared_stroke(self):
        lines = []
        with mock.patch.object(
            ui, "draw_logical_line", side_effect=lambda *args: lines.append(args),
        ):
            ui.draw_receiver_action_icon(
                self.Cache(), ui.PICKER_SORT_BOX, "sort", (255, 255, 255, 255),
            )
        self.assertEqual(len(lines), 3)
        self.assertEqual([line[2] - line[0] for line in lines], [42, 28, 14])
        self.assertTrue(all(line[5] == ui.APP_ACTION_ICON_STROKE for line in lines))

    def test_receiver_back_label_is_centered_plain_text(self):
        with mock.patch.object(ui, "draw_styled_text_button") as draw:
            ui.draw_receiver_back_button(self.Cache(), ui.PICKER_EXIT_BOX)
        self.assertEqual(draw.call_args.args[2], "BACK")

    def test_sort_button_has_no_persistent_sort_subtitle(self):
        texts = []
        with mock.patch.object(ui, "draw_styled_button_frame",
                               return_value=ui.APP_UI_STYLE.button.resolve()), \
                mock.patch.object(ui, "draw_receiver_action_icon"), \
                mock.patch.object(ui, "draw_text",
                                  side_effect=lambda *args, **_kwargs: texts.append(args[3])):
            ui.draw_receiver_action_button(
                self.Cache(), ui.PICKER_SORT_BOX, "SORT", "sort",
            )
        self.assertEqual(texts, ["SORT"])

    def test_sort_notice_uses_exact_zoom_osd_box(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        self.assertEqual(ui.receiver_list_notice_box(), ui.ZOOM_OSD_BOX)
        self.assertLessEqual(ui.ZOOM_OSD_BOX[2], ui.PICKER_BOX[2])

    def test_vosc_overlays_have_separate_close_and_translation_targets(self):
        box = (16, 360, 1008, 500)
        close = ui.compact_header_close_box(box)
        translation = ui.caption_translation_toggle_box(box)
        self.assertLessEqual(translation[2], close[0])
        with mock.patch.object(ui, "draw_logical_rect"), \
                mock.patch.object(ui, "draw_text"), \
                mock.patch.object(ui, "fit_station_text", side_effect=lambda _cache, label, *_args, **_kwargs: label), \
                mock.patch.object(ui, "draw_styled_text_button") as button:
            ui.draw_vosk_captions(None, (), (), "", "LISTENING", box=box, engine="vosk")
            ui.draw_callsign_captions(None, True, "", (), "", "LISTENING", box)
        self.assertEqual(button.call_count, 2)
        self.assertTrue(all(call.args[1:] == (close, "CLOSE") for call in button.call_args_list))

    def test_callsign_and_transcription_share_live_popup_geometry_and_type(self):
        ui.configure_output(True)
        box = ui.caption_box_for_waterfall(250, 712, "middle")
        self.assertEqual(box, ui.callsign_box_for_waterfall(250, 712, "middle"))
        with mock.patch.object(ui, "draw_vosc_live_popup_frame") as frame, \
                mock.patch.object(ui, "draw_text") as draw, \
                mock.patch.object(ui, "wrap_caption_lines", return_value=["CQ TEST"]), \
                mock.patch.object(ui, "fit_station_text", side_effect=lambda _cache, label, *_args, **_kwargs: label):
            ui.draw_vosk_captions(None, ("CQ TEST",), (), "", "LISTENING", box=box, engine="vosk")
            ui.draw_callsign_captions(None, True, "G4ZFE", ("G4ZFE",), "", "HEARD", box)
        self.assertEqual([call.args[1] for call in frame.call_args_list], [box, box])
        body = {call.args[3]: call.args for call in draw.call_args_list}
        self.assertEqual(body["CQ TEST"][4:8], body["G4ZFE"][4:8])
        self.assertEqual(body["G4ZFE"][4:8],
                         (ui.APP_UI_STYLE.palette.text, 26, True, False))

    def test_vosc_errors_remain_in_live_popups_even_with_old_text(self):
        box = (16, 360, 1008, 500)
        with mock.patch.object(ui, "draw_vosc_live_popup_frame"), \
                mock.patch.object(ui, "draw_vosc_live_popup_error") as error, \
                mock.patch.object(ui, "draw_text"):
            ui.draw_vosk_captions(None, ("OLD WORDS",), (), "", "DEEP ERROR", box=box, engine="vosk")
            ui.draw_callsign_captions(None, True, "G4ZFE", ("G4ZFE",), "", "ERROR", box)
        self.assertEqual([call.args[2] for call in error.call_args_list], ["DEEP ERROR", "VOSK ERROR"])

    def test_vosc_live_popup_error_uses_dimmed_color(self):
        with mock.patch.object(ui, "draw_text") as draw:
            ui.draw_vosc_live_popup_error(None, (16, 360, 1008, 500), "error")
        self.assertEqual(draw.call_args.args[3], "ERROR")
        self.assertEqual(draw.call_args.args[4], ui.APP_UI_STYLE.palette.secondary_text)

    def test_deepgram_key_error_remains_visible_in_shared_keyboard(self):
        ui.configure_output(True)
        with mock.patch.object(ui, "draw_logical_rect"), \
                mock.patch.object(ui, "draw_logical_line"), \
                mock.patch.object(ui, "draw_network_button"), \
                mock.patch.object(ui, "fit_station_text", side_effect=lambda _cache, text, *_args: text), \
                mock.patch.object(ui, "draw_text") as draw:
            ui.draw_deepgram_setup(None, "short", "lower", "enter the complete API key")
        labels = [call.args[3] for call in draw.call_args_list]
        self.assertIn("enter the complete API key", labels)
        self.assertNotIn("short", labels)
        self.assertIn("•••••", labels)

    def test_bottom_vosc_popup_owns_covered_zoom_buttons_until_moved(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        caption_bottom = ui.caption_box_for_waterfall(250, 712, "bottom")
        caption_middle = ui.caption_box_for_waterfall(250, 712, "middle")
        callsign_bottom = ui.callsign_box_for_waterfall(250, 712, "bottom")
        for zoom in (ui.ZOOM_MINUS_BOX, ui.ZOOM_PLUS_BOX):
            zoom_x = (zoom[0] + zoom[2]) / 2
            zoom_y = (zoom[1] + zoom[3]) / 2
            self.assertEqual(
                ui.vosc_popup_action_at(zoom_x, zoom_y, caption_bottom, None, True, False),
                "caption_readonly",
            )
            self.assertEqual(
                ui.vosc_popup_action_at(zoom_x, zoom_y, None, callsign_bottom, False, True),
                "callsign_caption",
            )
            self.assertIsNone(
                ui.vosc_popup_action_at(zoom_x, zoom_y, caption_middle, None, True, False)
            )
        close = ui.compact_header_close_box(caption_bottom)
        self.assertEqual(
            ui.vosc_popup_action_at((close[0] + close[2]) / 2, (close[1] + close[3]) / 2,
                                    caption_bottom, None, True, False),
            "caption_close",
        )

    def test_vosc_error_notice_uses_zoom_panel_and_green_type(self):
        with mock.patch.object(ui, "draw_green_osd_panel") as panel, \
                mock.patch.object(ui, "fit_station_text", return_value="API KEY") as fit, \
                mock.patch.object(ui, "draw_text") as draw:
            ui.draw_vosc_error_osd(None, "api key", 220)
        panel.assert_called_once_with(ui.ZOOM_OSD_BOX, 220)
        fit.assert_called_once()
        self.assertEqual([call.args[3] for call in draw.call_args_list], ["ERROR", "API KEY"])
        self.assertTrue(all(call.args[4:6] == ((72, 255, 122), 28) for call in draw.call_args_list))

    def test_rc28_mode_notice_uses_zoom_panel_and_green_type(self):
        with mock.patch.object(ui, "draw_green_osd_panel") as panel, \
                mock.patch.object(ui, "draw_text") as draw:
            ui.draw_rc28_mode_osd(None, "WIDTH", 220)
        panel.assert_called_once_with(ui.ZOOM_OSD_BOX, 220)
        self.assertEqual([call.args[3] for call in draw.call_args_list], ["RC-28", "WIDTH"])
        self.assertTrue(all(call.args[4:6] == ((72, 255, 122), 28) for call in draw.call_args_list))
        self.assertEqual([call.args[8] for call in draw.call_args_list], ["lm", "rm"])

    def test_favorite_star_is_closed_and_mathematically_regular(self):
        points = ui.regular_star_points(0, 0, 23)
        self.assertEqual(len(points), 11)
        self.assertEqual(points[0], points[-1])
        outer = (points[0][0] ** 2 + points[0][1] ** 2) ** 0.5
        inner = (points[1][0] ** 2 + points[1][1] ** 2) ** 0.5
        self.assertAlmostEqual(inner / outer, 0.38196601125)

    def test_shared_button_style_separates_inactive_active_and_pressed_states(self):
        ui.theme_system.apply_theme(ui.theme_system.DEFAULT_THEME)
        normal = ui.APP_UI_STYLE.button.resolve()
        active = ui.APP_UI_STYLE.button.resolve(active=True)
        pressed = ui.APP_UI_STYLE.button.resolve(pressed=True)
        self.assertEqual(normal.fill, (0, 0, 0, 255))
        self.assertEqual(normal.border, (46, 46, 46, 255))
        self.assertEqual(active.fill, (30, 30, 30, 255))
        self.assertEqual(active.border, (96, 96, 96, 255))
        self.assertEqual(active.text, (255, 255, 255))
        self.assertEqual(pressed.fill, (0, 229, 255, 255))
        self.assertEqual(pressed.border, (0, 229, 255, 255))
        self.assertEqual(pressed.text, (0, 0, 0))

    def test_pressed_two_line_button_uses_black_title_and_subtitle(self):
        pressed = ui.APP_UI_STYLE.button.resolve(pressed=True)
        with mock.patch.object(ui, "ui_button_pressed", return_value=True), \
                mock.patch.object(ui, "draw_styled_button_frame", return_value=pressed), \
                mock.patch.object(ui, "draw_text") as text:
            ui.draw_styled_two_line_button(None, (10, 20, 124, 84), "TITLE", "SUBTITLE")
        self.assertEqual([call.args[4] for call in text.call_args_list],
                         [(0, 0, 0), (0, 0, 0)])

    def test_home_favorite_uses_shared_active_style_without_gold_fill(self):
        active = ui.APP_UI_STYLE.button.resolve(active=True)
        with mock.patch.object(ui, "ui_button_pressed", return_value=False), \
                mock.patch.object(ui, "draw_styled_button_frame", return_value=active) as frame, \
                mock.patch.object(ui, "draw_favorite_star") as star, \
                mock.patch.object(ui, "draw_logical_circle") as gold_fill:
            ui.draw_favorite_waterfall_button(True)
        self.assertTrue(frame.call_args.kwargs["active"])
        self.assertEqual(star.call_args.args[3], active.text)
        self.assertTrue(star.call_args.kwargs["filled"])
        gold_fill.assert_not_called()

    def test_distance_follows_the_badges_under_the_server_name(self):
        station = ("Receiver", "Location", "owrx://example.test", None, None, 1.0, 2.0, "openwebrx")
        drawn_text = []
        badge_calls = []

        def badge(_cache, x, y, badge, _theme, **_kwargs):
            badge_calls.append((x, y, badge.label))
            return 70

        with mock.patch.object(ui, "draw_logical_rect"), \
                mock.patch.object(ui, "draw_logical_rounded_rect"), \
                mock.patch.object(ui, "draw_receiver_action_button"), \
                mock.patch.object(ui, "draw_receiver_filter_button"), \
                mock.patch.object(ui, "draw_receiver_sidebar_header"), \
                mock.patch.object(ui, "draw_receiver_back_button"), \
                mock.patch.object(ui, "draw_receiver_badge", side_effect=badge), \
                mock.patch.object(ui, "draw_text", side_effect=lambda *args, **_kwargs: drawn_text.append(args)):
            ui.draw_station_picker(
                self.Cache(), [station], 0, "", "", "name", {},
                route_filter="openwebrx", home_profile={"latitude": 0.0, "longitude": 0.0},
            )

        name_call = next(call for call in drawn_text if call[3] == "Receiver · Location")
        distance_call = next(call for call in drawn_text if str(call[3]).startswith("DISTANCE:"))
        self.assertEqual([b[2] for b in badge_calls], ["OPENWEBRX"])
        self.assertGreater(badge_calls[0][1], name_call[2])
        self.assertGreater(distance_call[1], badge_calls[-1][0])


class OpenWebRxScopeTests(unittest.TestCase):
    class State:
        def __init__(self, enabled):
            self.enabled = enabled
            self.update = None

        def spectrum_enabled_snapshot(self):
            return self.enabled

        def update_spectrum(self, samples, floor, ceiling):
            self.update = (samples, floor, ceiling)

    def test_openwebrx_fft_feeds_the_shared_scope(self):
        state = self.State(True)
        self.assertTrue(ui.update_openwebrx_scope(state, (42, 77), 20, 100))
        self.assertEqual(state.update, ((42, 77), 20, 100))

    def test_disabled_scope_skips_openwebrx_fft_work(self):
        state = self.State(False)
        self.assertFalse(ui.update_openwebrx_scope(state, (42, 77), 20, 100))
        self.assertIsNone(state.update)


if __name__ == "__main__":
    unittest.main()
