import sys
import unittest
from pathlib import Path

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
            "home.png",
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

    def test_audio_icon_tracks_existing_muted_state(self):
        self.assertEqual(ui.menu_icon_filename("audio", muted=False), "audio.png")
        self.assertEqual(ui.menu_icon_filename("audio", muted=True), "audio-muted.png")
        self.assertEqual(ui.menu_icon_filename("tests", muted=True), "apps.png")


class DrawerGeometryTests(unittest.TestCase):
    def test_home_destinations_are_preserved_with_updated_mode_label(self):
        kinds = [kind for kind, _label in ui.MENU_ITEMS]
        self.assertEqual(
            kinds,
            ["local_rx", "rx", "audio", "digital", "dual", "settings"],
        )
        self.assertEqual(dict(ui.MENU_ITEMS)["digital"], "MODES")

    def test_settings_apps_and_back_labels_preserve_routes(self):
        labels = dict(ui.SETTINGS_MENU_ITEMS)
        self.assertEqual(labels["tests"], "APPS")
        self.assertEqual(labels["settings_back"], "BACK")

    def test_drawers_share_one_back_target(self):
        expected = ui.lcd_drawer_back_box()
        self.assertEqual(ui.lcd_radio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_display_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_audio_drawer_close_box(), expected)
        self.assertEqual(ui.lcd_filter_drawer_boxes()["close"], expected)
        self.assertEqual(ui.receiver_home_drawer_boxes()["close"], expected)
        self.assertEqual(ui.fan_curve_drawer_boxes()["close"], expected)

    def test_settings_back_tile_uses_shared_back_target(self):
        last = len(ui.SETTINGS_MENU_ITEMS) - 1
        self.assertEqual(
            ui.lcd_nav_box(last, len(ui.SETTINGS_MENU_ITEMS)),
            ui.lcd_drawer_back_box(),
        )


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


if __name__ == "__main__":
    unittest.main()
