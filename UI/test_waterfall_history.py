import unittest
from types import SimpleNamespace
from unittest.mock import patch

from waterfall_history import CompactRow, WaterfallHistory, WaterfallPixels

GRAY = (bytes(range(256)),) * 3


def row(at, width=4, value=42):
    return CompactRow(bytes([value]) * width, GRAY, at)


class HistoryTests(unittest.TestCase):
    def test_adaptive_playback_keeps_captures_and_idle_live_during_review(self):
        import queue
        from waterfall_presenter import WaterfallPresenter

        history = WaterfallHistory(4)
        presenter = WaterfallPresenter()
        pending = queue.Queue()
        for i in range(20):
            history.append(row(i), 7100, 20, i)
        history.scroll(5, 4, now=20)
        anchor = history.window(4)
        resumed = False
        for frame in range(181):
            now = 20 + frame / 30
            if frame % 6 == 0:
                pending.put(row(now))
            for compact in presenter.take(pending, now, 23, 'receiver'):
                history.append(compact, 7200, 20, now)
            if now < 25:
                self.assertEqual(history.window(4), anchor)
            resumed = history.resume_if_idle(now) or resumed
        self.assertTrue(resumed)
        self.assertFalse(history.reviewing)
        self.assertGreater(history.window(4)[0].compact.captured_at, 25)
        self.assertEqual(history.window(4)[0].center_khz, 7200)

    def test_idle_resume_waits_five_seconds_and_touch_restarts_timer(self):
        history = WaterfallHistory(4)
        for i in range(20):
            history.append(row(i), 7100, 20, i)
        history.scroll(5, 4, now=20)
        self.assertFalse(history.resume_if_idle(24.99))
        self.assertFalse(history.resume_if_idle(25, touching=True))
        self.assertFalse(history.resume_if_idle(29.99))
        self.assertTrue(history.resume_if_idle(30))
        self.assertFalse(history.reviewing)
        self.assertFalse(history.resume_if_idle(35))

    def test_live_rows_do_not_reset_idle_timer_but_another_scroll_does(self):
        history = WaterfallHistory(4)
        for i in range(20):
            history.append(row(i), 7100, 20, i)
        history.scroll(5, 4, now=20)
        history.append(row(24), 7100, 20, 24)
        history.scroll(1, 4, now=24)
        self.assertFalse(history.resume_if_idle(25))
        self.assertTrue(history.resume_if_idle(29))
        history.scroll(1, 4, now=30)
        history.clear()
        self.assertFalse(history.resume_if_idle(40))

    def test_five_minutes_and_memory_are_bounded_at_high_input_rates(self):
        history = WaterfallHistory(4)
        for i in range(36001):
            now = i / 100
            history.append(row(now), 7100, 20, now)
        rows = history.window(20000)
        self.assertGreater(len(rows), 8900)
        self.assertLessEqual(len(rows), 9001)
        self.assertGreaterEqual(rows[-1].compact.captured_at, 60)
        self.assertEqual(sum(len(r.compact.pixels) for r in rows), len(rows) * 4)

    def test_review_anchor_does_not_follow_new_rows(self):
        history = WaterfallHistory(4)
        for i in range(20):
            history.append(row(i, value=i), 7100 + i, 20, i)
        history.scroll(5, 4)
        before = history.window(4)
        for i in range(20, 25):
            history.append(row(i), 9000, 40, i)
        self.assertEqual(history.window(4), before)
        self.assertEqual([r.center_khz for r in before], [7114, 7113, 7112, 7111])
        history.live()
        self.assertFalse(history.reviewing)
        self.assertEqual(history.window(4)[0].center_khz, 9000)

    def test_expiry_clamps_oldest_view_even_without_new_data(self):
        history = WaterfallHistory(4, seconds=10)
        for i in range(11):
            history.append(row(i), 7100, 20, i)
        history.scroll(1000, 4)
        history.expire(15)
        self.assertEqual([r.compact.captured_at for r in history.window(4)], [8, 7, 6, 5])
        history.expire(21)
        self.assertFalse(history.reviewing)
        self.assertEqual(history.window(4), ())
        self.assertTrue(all(r is None for r in history.rows))

    def test_scroll_to_latest_resumes_live_and_short_history_clamps(self):
        history = WaterfallHistory(4)
        for i in range(10):
            history.append(row(i), 7100, 20, i)
        history.scroll(50, 4)
        self.assertEqual(history.top(4), 3)
        history.scroll(-500, 4)
        self.assertFalse(history.reviewing)
        history.scroll(1, 800)
        self.assertFalse(history.reviewing)

    def test_duplicate_display_rows_and_late_packets_are_not_retained_twice(self):
        history = WaterfallHistory(4)
        self.assertTrue(history.append(row(1), 7100, 20, 1))
        self.assertFalse(history.append(row(1), 7100, 20, 1))
        self.assertFalse(history.append(row(.5), 7100, 20, 1))
        self.assertFalse(history.append(row(2, width=5), 7100, 20, 2))
        self.assertFalse(history.append(row(2), 7100, 20, 400))

    def test_rgba_roundtrip_preserves_palette_and_alpha(self):
        palette = (bytes(range(256)), bytes(reversed(range(256))), bytes([123]) * 256)
        compact = CompactRow(bytes([0, 128, 255]), palette, 0)
        self.assertEqual(compact.rgba(), bytes([0, 255, 123, 255, 128, 127, 123, 255, 255, 0, 123, 255]))
        wrapped = WaterfallPixels(compact.rgba(), compact)
        self.assertIsInstance(wrapped, bytes)
        self.assertIs(wrapped.compact, compact)

    def test_clear_releases_history_and_anchor(self):
        history = WaterfallHistory(4)
        for i in range(10):
            history.append(row(i), 7100, 20, i)
        history.scroll(3, 2)
        history.clear()
        self.assertEqual(history.window(4), ())
        self.assertFalse(history.reviewing)
        self.assertEqual(history.next, 0)


class HistoryDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import kiwi_gl_display as ui
        cls.ui = ui

    def test_actions_remain_drawable_but_are_inert_while_reviewing(self):
        ui = self.ui
        state = SimpleNamespace(smart_seek_available=lambda: True)
        with patch.object(ui, 'carrier_button_visible', return_value=True):
            for action in ('TUNE', 'SCAN'):
                self.assertTrue(ui.waterfall_action_enabled(state, action))
                self.assertFalse(ui.waterfall_action_enabled(state, action, reviewing=True))
        with patch.object(ui, 'draw_styled_two_line_button') as disabled, \
                patch.object(ui, 'draw_styled_text_button') as enabled:
            for action, box in (('TUNE', ui.carrier_waterfall_box()), ('SCAN', ui.smart_seek_waterfall_box())):
                ui.draw_waterfall_text_button(None, box, action, enabled=False)
                self.assertEqual(disabled.call_args.args[1:3], (box, action))
                self.assertFalse(disabled.call_args.kwargs['enabled'])
            enabled.assert_not_called()

    def test_live_notice_reuses_zoom_panel_and_notice_color(self):
        ui = self.ui
        with patch.object(ui, 'draw_green_osd_panel') as panel, patch.object(ui, 'draw_text') as text:
            ui.draw_waterfall_live_osd(None, 180)
            panel.assert_called_once_with(ui.ZOOM_OSD_BOX, 180)
            self.assertEqual(text.call_args.args[3], 'LIVE ENABLED')
            self.assertEqual(text.call_args.args[4], ui.APP_UI_STYLE.palette.notice)
            panel.reset_mock()
            ui.draw_waterfall_live_osd(None, 0)
            panel.assert_not_called()

    def test_source_pixels_roundtrip_for_all_display_palettes(self):
        ui = self.ui
        for palette in ('classic', 'kiwi', 'gqrx'):
            image = ui.kiwi.waterfall_line(bytes(range(256)), ui.waterfall_mapper(palette),
                                         31, 210, width=1024, retain_compact=True)
            compact = image.info['waterfall_compact']
            self.assertEqual(compact.rgba(), image.convert('RGBA').tobytes())
            self.assertEqual(len(compact.pixels), 1024)

    def test_gesture_directions_do_not_overlap_or_accept_jitter(self):
        ui = self.ui
        args = SimpleNamespace(swipe_start_px=12)
        for x, y, vertical, horizontal in ((2, -60, True, False), (60, 2, False, True),
                                          (4, 3, False, False), (40, 40, False, False)):
            self.assertEqual(ui.is_waterfall_history_drag(0, 0, x, y, args), vertical)
            self.assertEqual(ui.is_deliberate_waterfall_drag(0, 0, x, y, args), horizontal)

    def test_live_control_is_guarded_when_hidden_or_covered(self):
        ui = self.ui
        ui.configure_output(True)
        x0, y0, x1, y1 = ui.waterfall_live_box()
        x, y = (x0 + x1) / 2, (y0 + y1) / 2
        self.assertGreaterEqual(x0, 0)
        self.assertGreaterEqual(x1 - x0, 48)
        self.assertFalse(ui.waterfall_history_touch(x, y, False))
        self.assertFalse(ui.waterfall_history_touch(x, y, True, modal_open=True))
        self.assertTrue(ui.waterfall_history_touch(x, y, True))
        self.assertLess(x1, ui.carrier_waterfall_box()[0])

    def test_anchored_view_uploads_only_after_scroll_or_theme_change(self):
        ui = self.ui
        with patch.object(ui, 'GL') as gl, patch.object(ui, 'WF_TEX_W', 4), \
                patch.object(ui, 'WF_TEX_H', 4), patch.object(ui, 'time') as clock, \
                patch.object(ui, 'draw_logical_rect'), \
                patch.object(ui.WaterfallTexture, '_draw_frequency_aligned'):
            clock.monotonic.return_value = 20
            texture = ui.WaterfallTexture(retain_history=True)
            for i in range(20):
                compact = row(i)
                texture.push_line(WaterfallPixels(compact.rgba(), compact), 7100, 20)
            texture.history.scroll(5, 4)
            gl.glTexSubImage2D.reset_mock()
            texture.draw(0, 0, 4, 4, 7100, 20)
            self.assertEqual(gl.glTexSubImage2D.call_count, 1)
            texture.draw(0, 0, 4, 4, 7100, 20)
            self.assertEqual(gl.glTexSubImage2D.call_count, 1)
            compact = row(20)
            texture.push_line(WaterfallPixels(compact.rgba(), compact), 7100, 20)
            gl.glTexSubImage2D.reset_mock()
            texture.draw(0, 0, 4, 4, 7100, 20)
            gl.glTexSubImage2D.assert_not_called()
            texture.history.scroll(1, 4)
            texture.draw(0, 0, 4, 4, 7100, 20)
            gl.glTexSubImage2D.assert_not_called()
            clock.monotonic.return_value += .04
            texture.draw(0, 0, 4, 4, 7100, 20)
            self.assertEqual(gl.glTexSubImage2D.call_count, 1)
            with patch.object(ui, 'waterfall_theme_signature', return_value=('changed',)):
                texture.draw(0, 0, 4, 4, 7100, 20)
            self.assertEqual(gl.glTexSubImage2D.call_count, 2)
            texture.clear()
            self.assertFalse(texture.history.reviewing)
            self.assertIsNone(texture.history_view_key)


if __name__ == '__main__':
    unittest.main()
