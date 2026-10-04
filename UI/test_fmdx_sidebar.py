import unittest
from unittest.mock import patch
import kiwi_gl_display as ui

class FmdxSidebarTests(unittest.TestCase):
    def test_actions_are_below_status_and_above_steps(self):
        for stations in ((), ({'frequency_khz': 99500, 'name': 'TEST'},)):
            for scanning in (False, True):
                boxes = [box for _, box in ui.fmdx_control_layout(stations, scanning)]
                for box in boxes:
                    self.assertGreaterEqual(box[1], 240)
                    self.assertLessEqual(box[3], 410)
                for i, a in enumerate(boxes):
                    for b in boxes[i+1:]:
                        self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3])

    def test_fm_steps_match_touch_targets(self):
        ui.LCD_RADIO_DRAWER_PROGRESS = 1
        for step, box in ui.radio_step_options('fmdx'):
            self.assertIn(step, (50000, 100000, 200000))
            self.assertEqual(ui.radio_option_at((box[0]+box[2])/2, (box[1]+box[3])/2, receiver_type='fmdx'), ('step', step))

    def test_fm_step_does_not_depend_on_audio_waterfall_zoom(self):
        for zoom in (0, 8, 16):
            self.assertEqual(ui.receiver_tune_step_hz(zoom, 100, 'fmdx', 100000), 100000)
            self.assertEqual(ui.receiver_tune_step_hz(zoom, 100, 'kiwi', 100000), ui.finger_tune_step_hz(zoom,100))

    def test_fm_drag_uses_channel_step_instead_of_audio_span(self):
        for span in (5, 20, 100):
            self.assertEqual(ui.receiver_drag_span(span, 'fmdx', 100000), 100 * ui.rf_canvas_width() / 40)
            self.assertEqual(ui.receiver_drag_span(span, 'kiwi', 100000), span)


class FmdxRailRegressionTests(unittest.TestCase):
    def setUp(self):
        ui.configure_output(True)
        ui.configure_popup_layout()
        self.previous_progress = ui.LCD_RADIO_DRAWER_PROGRESS
        ui.LCD_RADIO_DRAWER_PROGRESS = 1.0
        self.addCleanup(setattr, ui, "LCD_RADIO_DRAWER_PROGRESS", self.previous_progress)

    def test_selected_fmdx_server_lights_only_fmdx(self):
        state = ui.SharedState("http://kiwi.test", 7075, 8, -95, -125, -15, 3, "am", True)
        state.set_server("https://fm.example/radio", receiver_type="fmdx")
        mode = ui.effective_receiver_mode(state.receiver_type_snapshot(), state.radio_snapshot()[0])
        labels = [label for label, _box in ui.lcd_home_mode_boxes(False, mode)]
        active = [label for label in labels if ui.mode_annunciator_active(label, mode, "IQ")]
        self.assertEqual(active, ["FMDX"])
        for mode in ("AM", "USB", "NBFM", ui.fmdx.MODE_LABEL):
            self.assertIn("FMDX", ui.home_mode_labels(mode))
            self.assertNotIn("NFM", ui.home_mode_labels(mode))
        self.assertTrue(ui.mode_annunciator_active("FMDX", "NBFM", "DIG"))

    def test_zoom_buttons_are_close_and_left_aligned(self):
        self.assertEqual(ui.ZOOM_PLUS_BOX[0] - ui.ZOOM_MINUS_BOX[2], 12)
        self.assertEqual(ui.ZOOM_MINUS_BOX[0], 24)
        self.assertLess(ui.ZOOM_PLUS_BOX[2], ui.rf_canvas_width() / 4)

    def test_fmdx_drawer_uses_shared_tiles_and_matches_tap_targets(self):
        stations = ({"frequency_khz": 99500, "name": "TEST"},)
        for shared in (False, True):
            with self.subTest(shared=shared), \
                 patch.object(ui, "draw_logical_rect"), \
                 patch.object(ui, "draw_logical_line"), \
                 patch.object(ui, "draw_text"), \
                 patch.object(ui, "draw_radio_close_button"), \
                 patch.object(ui, "draw_sidebar_header"), \
                 patch.object(ui, "fit_station_text", side_effect=lambda _c, label, *_a, **_kw: label), \
                 patch.object(ui, "draw_lcd_audio_tile") as tile:
                ui.draw_radio_setup_panel(None, "AM", "DIG", 100000,
                    receiver_type="fmdx", fmdx_stations=stations, fmdx_shared_control=shared)
                calls = tile.call_args_list
                self.assertEqual(calls[0].args[2:5], ("FMDX", "ON · FM RECEIVER", True))
                for action, box in ui.fmdx_control_layout(stations, shared_control=shared):
                    self.assertIn(box, [call.args[1] for call in calls])
                    self.assertEqual(ui.radio_option_at((box[0]+box[2])/2, (box[1]+box[3])/2,
                        receiver_type="fmdx", fmdx_stations=stations, fmdx_shared_control=shared),
                        ("fmdx_action", action))
                steps = [call for call in calls if call.args[2] == "TUNING STEP"]
                self.assertEqual(len(steps), 3 if shared else 0)
                if shared:
                    self.assertEqual([call.args[4] for call in steps], [False, True, False])
