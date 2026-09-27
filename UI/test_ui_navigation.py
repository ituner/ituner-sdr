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


if __name__ == "__main__":
    unittest.main()
