"""Keep the newest caption row visible and distinct from its history."""
import unittest
from unittest import mock
import kiwi_gl_display as ui


class CaptionReadingFocusTests(unittest.TestCase):
    def test_newest_row_is_bright_for_final_and_partial_text(self):
        for partial in ('', 'new words'):
            with self.subTest(partial=partial), \
                    mock.patch.object(ui, 'draw_vosc_live_popup_frame'), \
                    mock.patch.object(ui, 'wrap_caption_lines', return_value=['old line', 'new line']), \
                    mock.patch.object(ui, 'draw_text') as draw:
                ui.draw_vosk_captions(None, ('old words',), (), partial, 'LISTENING')
                rows = [call.args for call in draw.call_args_list]
                self.assertEqual(rows[0][4], ui.APP_UI_STYLE.palette.secondary_text)
                self.assertEqual(rows[1][4], ui.APP_UI_STYLE.palette.text)

    def test_wrapping_keeps_newest_row_when_history_exceeds_panel(self):
        cache = mock.Mock()
        cache.texture.return_value = (None, 10, 10)
        self.assertEqual(ui.wrap_caption_lines(
            cache, 'one two three four five six', 100, 26,
            max_rows=4, max_characters=5), ['three', 'four', 'five', 'six'])


if __name__ == '__main__':
    unittest.main()
