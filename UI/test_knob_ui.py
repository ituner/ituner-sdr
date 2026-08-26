import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiwi_gl_display as ui  # noqa: E402


class KnobUiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ui.configure_output(True)
        ui.configure_popup_layout()

    def test_main_context_matches_visible_home_rail_order(self):
        context = ui.active_knob_context(ui.KnobUiFlags())

        self.assertEqual(context.screen_id, "main")
        self.assertEqual(
            tuple(control.control_id for control in context.controls),
            ("local_rx", "receivers", "audio", "digital", "dual", "settings"),
        )

    def test_search_does_not_focus_picker_controls_covered_by_keyboard(self):
        context = ui.active_knob_context(
            ui.KnobUiFlags(picker_open=True, search_open=True),
            receiver_row_count=5,
        )

        self.assertEqual(context.screen_id, "receiver_search")
        self.assertEqual(tuple(control.control_id for control in context.controls), ("back",))

    def test_receiver_rows_are_marked_for_page_control(self):
        context = ui.active_knob_context(
            ui.KnobUiFlags(picker_open=True), receiver_row_count=3,
        )

        rows = [control for control in context.controls if control.category == "receiver"]
        self.assertEqual(
            tuple(row.control_id for row in rows),
            ("receiver_row:0", "receiver_row:1", "receiver_row:2"),
        )

    def test_nested_workspace_never_falls_through_to_hidden_home_controls(self):
        context = ui.active_knob_context(ui.KnobUiFlags(network_panel_open=True))

        self.assertEqual(context.screen_id, "network")
        self.assertEqual(tuple(control.control_id for control in context.controls), ("back",))

    def test_font_lab_never_falls_through_to_hidden_home_controls(self):
        context = ui.active_knob_context(ui.KnobUiFlags(font_lab_open=True))

        self.assertEqual(context.screen_id, "font_lab")
        self.assertEqual(tuple(control.control_id for control in context.controls), ("back",))

    def test_constellation_back_focus_uses_visible_back_button(self):
        flags = ui.KnobUiFlags(globe_open=True)

        self.assertEqual(ui.knob_focus_box("back", flags), ui.GLOBE_BACK_BOX)

    def test_font_lab_back_focus_uses_visible_back_button(self):
        flags = ui.KnobUiFlags(font_lab_open=True)

        self.assertEqual(ui.knob_focus_box("back", flags), ui.FONT_LAB_BACK_BOX)

    def test_tuning_uses_exact_steps_and_clamps(self):
        self.assertAlmostEqual(ui.knob_tune_frequency(1000.0, 3, 1, 100), 1000.3)
        self.assertEqual(ui.knob_tune_frequency(29999.0, 2, 12, 100), 29999.0)

    def test_overlay_reports_view_step_and_acceleration(self):
        lines = ui.knob_overlay_lines(ui.KnobController().snapshot(), 100)

        self.assertEqual(lines, ("VIEW ZOOM", "TUNE STEP 100 Hz", "TUNE x1"))


if __name__ == "__main__":
    unittest.main()
