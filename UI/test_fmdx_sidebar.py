import unittest
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
