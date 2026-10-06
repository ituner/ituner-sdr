import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiwi_gl_display as ui  # noqa: E402


class MenuIconTests(unittest.TestCase):
    def test_required_runtime_icons_exist_in_both_asset_roots(self):
        required = {
            "apps.png",
            "audio-muted.png",
            "audio.png",
            "digi.png",
            "display.png",
            "dual.png",
            "frequency-chevron.png",
            "home.png",
            "info.png",
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
        self.assertEqual(ui.RECEIVER_GLOBE_ICON, ui.menu_icon_filename("rx"))

    def test_dual_icon_has_requested_wide_low_profile(self):
        icon = Path(__file__).resolve().parent / "assets/menu-icons/dual.png"
        with Image.open(icon).convert("RGBA") as image:
            x0, y0, x1, y1 = image.getchannel("A").getbbox()
        self.assertGreater(x1 - x0, y1 - y0)
        self.assertLessEqual(y1 - y0, 42)


class DrawerGeometryTests(unittest.TestCase):
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

    def test_home_destinations_are_preserved_with_updated_mode_label(self):
        kinds = [kind for kind, _label in ui.MENU_ITEMS]
        self.assertEqual(
            kinds,
            ["local_rx", "rx", "audio", "digital", "dual", "settings"],
        )
        self.assertEqual(dict(ui.MENU_ITEMS)["digital"], "MODES")

    def test_settings_uses_info_and_has_no_duplicate_kiwi_route(self):
        labels = dict(ui.SETTINGS_MENU_ITEMS)
        self.assertEqual(labels["tests"], "APPS")
        self.assertEqual(labels["system"], "INFO")
        self.assertEqual(labels["settings_back"], "BACK")
        self.assertNotIn("kiwi", labels)
        self.assertEqual(ui.menu_icon_filename("system"), "info.png")

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
        wspr_box = ui.radio_wspr_box()
        back_box = ui.lcd_radio_drawer_close_box()
        overlaps = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
        for box in (*mode_boxes, *step_boxes):
            self.assertFalse(overlaps(box, wspr_box))
        self.assertFalse(overlaps(wspr_box, back_box))
        x = (wspr_box[0] + wspr_box[2]) / 2
        y = (wspr_box[1] + wspr_box[3]) / 2
        self.assertEqual(ui.radio_option_at(x, y), ("workspace", "wspr"))

    def test_stats_close_target_is_inside_graph_header(self):
        graph = (120, 90, 900, 420)
        close = ui.cpu_utilization_graph_close_box(graph)
        self.assertGreaterEqual(close[0], graph[0])
        self.assertGreaterEqual(close[1], graph[1])
        self.assertLessEqual(close[2], graph[2])
        self.assertLess(close[3], graph[1] + 44)

    def test_frequency_drawer_controls_are_bounded_and_disjoint(self):
        boxes = ui.frequency_drawer_boxes()
        panel = boxes["panel"]
        controls = [boxes[name] for name in ("readout", "down", "up", "manual", "step_heading", "close")]
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
        for name in ("down", "up", "manual", "close"):
            box = boxes[name]
            self.assertEqual(ui.frequency_drawer_action_at((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), name)

    def test_frequency_drawer_arrows_are_square(self):
        boxes = ui.frequency_drawer_boxes()
        for name in ("down", "up"):
            x0, y0, x1, y1 = boxes[name]
            self.assertAlmostEqual(x1 - x0, y1 - y0, msg=f"{name} is not square")
        self.assertEqual(boxes["down"][1], boxes["up"][1])
        self.assertEqual(boxes["down"][3], boxes["up"][3])

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

    def test_frequency_step_uses_hz_increment_and_receiver_bounds(self):
        self.assertEqual(ui.frequency_step_target(7075.0, 1, 100, 0, 30000), 7075.1)
        self.assertEqual(ui.frequency_step_target(10.0, -1, 100_000, 0, 108000), 0.0)
        self.assertEqual(ui.frequency_step_target(7075.05, 1, 100, 0, 30000), 7075.1)
        self.assertEqual(ui.frequency_step_target(7075.05, -1, 100, 0, 30000), 7075.0)
        self.assertEqual(ui.configured_tune_step_hz("kiwi", 500, 100_000), 500)
        self.assertEqual(ui.configured_tune_step_hz("fmdx", 500, 50_000), 50_000)
        self.assertEqual(ui.format_frequency_digits(7075.794), "007.075.794")
        self.assertEqual(ui.format_tune_step(100_000), "100 kHz")

    def test_entire_compact_frequency_area_opens_tuning_target(self):
        compact = ui.compact_frequency_touch_box()
        measured = (compact[0] + 40, compact[1] + 10, compact[2] - 40, compact[3] - 10)
        self.assertTrue(ui.is_frequency_readout_touch(compact[0] + 2, compact[1] + 2, measured, compact=True))
        self.assertFalse(ui.is_frequency_readout_touch(compact[0] + 2, compact[1] + 2, measured, compact=False))

    def test_sidebar_headers_use_one_centered_compact_style(self):
        with mock.patch.object(ui, "draw_logical_rect"), mock.patch.object(ui, "draw_logical_line"), mock.patch.object(ui, "draw_text") as draw_text:
            ui.draw_sidebar_header(object(), "SETTINGS")
        args = draw_text.call_args.args
        self.assertEqual(args[1], (ui.LCD_NAV_X0 + ui.LOGICAL_W) / 2)
        self.assertEqual(args[5], 15)
        self.assertTrue(args[6])
        self.assertEqual(args[8], "cm")


class ParentNavigationTests(unittest.TestCase):
    def test_shared_destination_records_the_surface_that_opened_it(self):
        self.assertEqual(ui.navigation_parent(ui.MENU_ITEMS, "rx"), "home")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "display"), "settings")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "tests"), "settings")
        self.assertEqual(ui.navigation_parent(ui.SETTINGS_MENU_ITEMS, "settings_back"), "home")

    def test_unknown_parent_falls_back_to_home(self):
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
                         ["local", "kiwi", "openwebrx", "fmdx", "all"])
        for box in (box for _source, box in segments):
            self.assertGreaterEqual(box[0], ui.LCD_NAV_X0)
            self.assertLessEqual(box[2], ui.LOGICAL_W)
            self.assertGreater(box[2] - box[0], box[3] - box[1])
        for index, (_name, a) in enumerate(segments):
            for _other, b in segments[index + 1:]:
                self.assertFalse(ui.boxes_overlap(a, b))
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


class WorkspaceLayoutTests(unittest.TestCase):
    def test_settings_center_workspace_stays_outside_sidebar(self):
        x0, y0, x1, y1 = ui.settings_center_workspace_box()
        self.assertGreaterEqual(x0, 0)
        self.assertEqual(x1, ui.LCD_NAV_X0)
        self.assertGreater(y1, y0)
        self.assertLessEqual(y1, ui.LOGICAL_H)

    def test_constellation_layout_fits_current_display(self):
        layout = ui.constellation_layout()
        for box in layout.values():
            x0, y0, x1, y1 = box
            self.assertGreaterEqual(x0, 0)
            self.assertGreaterEqual(y0, 0)
            self.assertLessEqual(x1, ui.LOGICAL_W)
            self.assertLessEqual(y1, ui.LOGICAL_H)
            self.assertGreater(x1, x0)
            self.assertGreater(y1, y0)
        self.assertLessEqual(layout["map"][2], ui.LCD_NAV_X0)
        self.assertGreaterEqual(layout["sidebar"][0], ui.LCD_NAV_X0)


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
    """The large readout must look identical wherever it is drawn."""

    def test_one_shared_face_size_and_colour(self):
        self.assertEqual(ui.BIG_FREQUENCY_SIZE, 58)
        self.assertEqual(ui.BIG_FREQUENCY_COLOR, ui.VFO_NEON_COLOR)

    def test_helper_draws_the_shared_style(self):
        calls = []
        cache = mock.Mock()
        cache.font.return_value = mock.Mock(size=lambda text: (100, 30))
        with mock.patch.object(ui, "draw_text_scaled_x", side_effect=lambda *a, **k: calls.append((a, k))):
            ui.draw_big_frequency(cache, 7075.794, 500, 40, 300, family="Oxanium")
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[3], ui.sdr_ui.format_freq(7075.794))
        self.assertEqual(args[4], ui.BIG_FREQUENCY_COLOR)
        self.assertEqual(args[5], ui.BIG_FREQUENCY_SIZE)
        self.assertEqual(kwargs.get("family"), "Oxanium")
        self.assertTrue(kwargs.get("bold"))
        self.assertEqual(kwargs.get("anchor"), "rm")

    def test_frequency_rail_readout_uses_the_shared_helper(self):
        calls = []
        with mock.patch.object(ui, "draw_big_frequency", side_effect=lambda *a, **k: calls.append((a, k))), \
                mock.patch.object(ui, "draw_logical_rect"), \
                mock.patch.object(ui, "draw_logical_line"), \
                mock.patch.object(ui, "draw_logical_rounded_rect"), \
                mock.patch.object(ui, "draw_sidebar_header"), \
                mock.patch.object(ui, "draw_text"), \
                mock.patch.object(ui, "draw_picker_button"), \
                mock.patch.object(ui, "draw_radio_close_button"), \
                mock.patch.object(ui, "frequency_chevron_texture", return_value=(0, 10, 10)), \
                mock.patch.object(ui, "draw_textured_quad"):
            ui.draw_frequency_drawer(object(), 7075.794, 100, "Oxanium")
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(args[1], 7075.794)
        self.assertEqual(kwargs.get("family"), "Oxanium")


class FmdxDisclaimerTests(unittest.TestCase):
    def test_disclaimer_uses_first_receiver_row_with_an_ok_button(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        boxes = ui.fmdx_disclaimer_boxes()
        x0, y0, x1, y1 = boxes["panel"]
        self.assertEqual(boxes["panel"], ui.station_tile(0, 0))
        self.assertLessEqual(x1, ui.PICKER_BOX[2])
        ok = boxes["ok"]
        self.assertTrue(x0 <= ok[0] and ok[2] <= x1 and y0 <= ok[1] and ok[3] <= y1)
        self.assertEqual(ui.fmdx_disclaimer_action_at((ok[0] + ok[2]) / 2, (ok[1] + ok[3]) / 2), "ok")

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

    def test_notice_reuses_server_row_frame_and_free_slot_lane_for_ok(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        boxes = ui.fmdx_disclaimer_boxes()
        cache = object()
        with mock.patch.object(ui, "draw_station_list_frame") as frame, \
                mock.patch.object(ui, "draw_logical_circle"), \
                mock.patch.object(ui, "draw_text"), \
                mock.patch.object(ui, "fit_station_text", side_effect=lambda _c, text, *_a, **_k: text), \
                mock.patch.object(ui, "draw_radio_option") as option:
            ui.draw_fmdx_disclaimer(cache)
        frame.assert_called_once_with(
            boxes["panel"], ui.STATION_LIST_FILL, ui.FMDX_DISCLAIMER_OUTLINE, 2,
        )
        option.assert_called_once_with(cache, boxes["ok"], "OK", False)

    def test_notice_is_shown_once_per_process_and_resets_on_restart(self):
        visible, shown = ui.fmdx_disclaimer_transition("fmdx", False, False)
        self.assertEqual((visible, shown), (True, True))
        # Re-selecting FM-DX does not recreate or toggle the row.
        self.assertEqual(ui.fmdx_disclaimer_transition("fmdx", visible, shown), (True, True))
        visible = False  # OK dismissed it.
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
        self.assertEqual(theme.sidebar_background, (26, 26, 26, 255))
        self.assertEqual(theme.primary_text, (255, 255, 255))
        self.assertEqual(theme.secondary_text, (160, 160, 160))
        self.assertEqual(theme.focus, (0, 229, 255, 255))
        self.assertEqual((theme.label_size, theme.server_name_size), (14, 18))

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

    def test_selected_filter_is_cyan_with_dark_text(self):
        box = (1090, 76, 1270, 128)
        with mock.patch.object(ui, "draw_logical_rounded_rect") as rounded, \
                mock.patch.object(ui, "draw_text") as text:
            ui.draw_receiver_filter_button(self.Cache(), box, "LAN", True)
        rounded.assert_called_once_with(
            *box, ui.APP_UI_STYLE.button.radius,
            ui.RECEIVER_LIST_THEME.focus, ui.RECEIVER_LIST_THEME.focus, 2,
        )
        self.assertEqual(text.call_args.args[4], (18, 18, 18))

    def test_receiver_rows_show_five_complete_and_a_sixth_teaser(self):
        boxes = [ui.station_tile(index, 0) for index in range(6)]
        self.assertTrue(all(box is not None for box in boxes))
        self.assertTrue(all(box[3] - box[1] == ui.RECEIVER_PICKER_ROW_HEIGHT for box in boxes))
        self.assertLess(boxes[-1][1], ui.LOGICAL_H)
        self.assertGreater(boxes[-1][3], ui.LOGICAL_H)

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
        self.assertTrue(all(box[2] - box[0] == box[3] - box[1] for box in boxes))
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

    def test_favorite_star_is_closed_and_mathematically_regular(self):
        points = ui.regular_star_points(0, 0, 23)
        self.assertEqual(len(points), 11)
        self.assertEqual(points[0], points[-1])
        outer = (points[0][0] ** 2 + points[0][1] ** 2) ** 0.5
        inner = (points[1][0] ** 2 + points[1][1] ** 2) ** 0.5
        self.assertAlmostEqual(inner / outer, 0.38196601125)

    def test_shared_button_style_uses_cyan_active_state_everywhere(self):
        normal = ui.APP_UI_STYLE.button.resolve()
        active = ui.APP_UI_STYLE.button.resolve(active=True)
        pressed = ui.APP_UI_STYLE.button.resolve(pressed=True)
        self.assertEqual(normal.fill, (38, 38, 38, 255))
        self.assertEqual(active.fill, (0, 229, 255, 255))
        self.assertEqual(active.text, (18, 18, 18))
        self.assertEqual(pressed, active)

    def test_home_favorite_uses_shared_active_style_without_gold_fill(self):
        active = ui.APP_UI_STYLE.button.resolve(active=True)
        with mock.patch.object(ui, "ui_button_pressed", return_value=False), \
                mock.patch.object(ui, "draw_styled_button_frame", return_value=active) as frame, \
                mock.patch.object(ui, "draw_logical_polyline") as star, \
                mock.patch.object(ui, "draw_logical_circle") as gold_fill:
            ui.draw_favorite_waterfall_button(True)
        self.assertTrue(frame.call_args.kwargs["active"])
        self.assertEqual(star.call_args.args[1], active.text)
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
