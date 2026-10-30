import contextlib
import io
from pathlib import Path
import sys
import threading
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'UI'))
from directory_refresh import (DailyDirectoryRefresh, DIRECTORY_REFRESH_SECONDS,
                               checked_refresh, directory_age_label)


class DailyRefreshTests(unittest.TestCase):
    def test_manual_refresh_starts_early_without_overlapping_and_resets_daily_deadline(self):
        now = [30.0]
        started = threading.Event()
        release = threading.Event()
        def job():
            started.set()
            release.wait(2)
        timer = DailyDirectoryRefresh([job], lambda: now[0])
        now[0] = 100.0
        try:
            self.assertTrue(timer.request())
            self.assertTrue(started.wait(1))
            self.assertFalse(timer.request())
            self.assertTrue(timer.busy)
        finally:
            release.set()
            timer.worker.join(2)
        self.assertFalse(timer.busy)
        self.assertEqual(timer.completed, 1)
        self.assertEqual(timer.next_at, 100.0 + DIRECTORY_REFRESH_SECONDS)
        self.assertEqual(timer.result_message(), 'DIRECTORY UPDATED')

    def test_cached_fallback_is_not_reported_as_successful_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / 'directory.json'
            cache.write_text('saved')
            self.assertFalse(checked_refresh(lambda: ['cached rows'], cache))
            self.assertEqual(cache.read_text(), 'saved')
            self.assertTrue(checked_refresh(lambda: cache.write_text('fresh directory'), cache))
            self.assertTrue(directory_age_label(cache).startswith('Updated'))
            self.assertEqual(directory_age_label(cache, now=cache.stat().st_mtime + 120),
                             'Updated 2 min ago')

    def test_manual_refresh_failure_keeps_other_jobs_and_reports_partial_update(self):
        timer = DailyDirectoryRefresh([lambda: False, lambda: True])
        self.assertTrue(timer.request())
        timer.worker.join(2)
        self.assertEqual(timer.results, (False, True))
        self.assertIn('SOME SOURCES UNAVAILABLE', timer.result_message())
        timer = DailyDirectoryRefresh([lambda: False])
        timer.request()
        timer.worker.join(2)
        self.assertEqual(timer.result_message(), 'UPDATE UNAVAILABLE; SAVED LIST KEPT')

    def test_refresh_touch_target_fits_cm5_rail_without_covering_existing_actions(self):
        import ast
        source = (Path(__file__).resolve().parents[1] / 'UI/kiwi_gl_display.py').read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == 'receiver_directory_refresh_box')
        env = {'LCD_800_MODE': True, 'RECEIVER_PICKER_BACK_BOX': (1034, 728, 1270, 792)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<refresh-geometry>', 'exec'), env)
        x0, y0, x1, y1 = env['receiver_directory_refresh_box']()
        self.assertEqual((x0, x1), (1034, 1270))
        self.assertGreaterEqual(y1 - y0, 56)
        self.assertLess(y1, 584)  # First existing command row.
        self.assertGreater(y0, 376)  # Last source-category row.

    def test_tapping_refresh_uses_background_worker_and_sets_feedback(self):
        import ast
        import time
        from types import SimpleNamespace
        source = (Path(__file__).resolve().parents[1] / 'UI/kiwi_gl_display.py').read_text()
        handler = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.If)
                       and isinstance(n.test, ast.BoolOp)
                       and any(isinstance(child, ast.Constant) and child.value == 'picker_directory_refresh'
                               for child in ast.walk(n.test)))
        called = threading.Event()
        timer = DailyDirectoryRefresh([called.set])
        env = dict(touch_started=True, gesture='picker_directory_refresh', x=1100, y=530,
                   start_x=1100, start_y=530, args=SimpleNamespace(tap_px=12),
                   daily_directories=timer, time=time, manual_directory_refresh=False,
                   wake_controls=lambda: None)
        code = compile(ast.Module(body=handler.body, type_ignores=[]), '<refresh-touch>', 'exec')
        exec(code, env)
        timer.worker.join(2)
        self.assertTrue(called.is_set())
        self.assertTrue(env['manual_directory_refresh'])
        self.assertEqual(env['picker_map_notice'], 'UPDATING DIRECTORY')
        self.assertEqual(env['picker_list_notice'], 'UPDATING DIRECTORY')

    def test_startup_is_not_duplicated_then_runs_once_per_day(self):
        now=[0.0];calls=[]
        timer=DailyDirectoryRefresh([lambda:calls.append('directory')],lambda:now[0])
        self.assertEqual(DIRECTORY_REFRESH_SECONDS,86400)
        self.assertFalse(timer.poll())
        now[0]=86399
        self.assertFalse(timer.poll())
        now[0]=86400
        self.assertTrue(timer.poll());timer.worker.join(2)
        self.assertEqual(calls,['directory'])
        self.assertFalse(timer.poll())
        now[0]=172800
        self.assertTrue(timer.poll());timer.worker.join(2)
        self.assertEqual(calls,['directory','directory'])

    def test_no_overlap_or_catchup_burst_after_long_pause(self):
        now=[0.0];release=threading.Event();started=threading.Event();calls=[]
        def job():
            calls.append(1);started.set();release.wait(2)
        timer=DailyDirectoryRefresh([job],lambda:now[0])
        try:
            now[0]=10*86400
            self.assertTrue(timer.poll());self.assertTrue(started.wait(1))
            now[0]+=2*86400
            self.assertFalse(timer.poll())
        finally:
            release.set();timer.worker.join(2)
        self.assertTrue(timer.poll());timer.worker.join(2)
        self.assertEqual(calls,[1,1])
        self.assertFalse(timer.poll())

    def test_failed_feed_does_not_retry_rapidly_or_skip_other_feeds(self):
        now=[0.0];calls=[]
        def failed():raise OSError('offline')
        timer=DailyDirectoryRefresh([failed,lambda:calls.append(1)],lambda:now[0])
        now[0]=86400
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(timer.poll());timer.worker.join(2)
        self.assertEqual(calls,[1]);self.assertFalse(timer.poll())

    def test_main_loop_directory_queues_are_wired_to_initialized_queues(self):
        import ast
        import queue
        source = (Path(__file__).resolve().parents[1]/'UI/kiwi_gl_display.py').read_text()
        tree = ast.parse(source)
        # Exercise the actual main-loop dispatch with the two startup queues.
        # Empty queues are the normal state before background downloads finish.
        loop = next(n for n in ast.walk(tree) if isinstance(n, ast.For)
                    and isinstance(n.target, ast.Tuple)
                    and [getattr(x, 'id', '') for x in n.target.elts]
                    == ['directory_label', 'directory_queue'])
        env = dict(queue=queue, public_result_queue=queue.Queue(),
                   openwebrx_result_queue=queue.Queue())
        exec(compile(ast.Module(body=[loop], type_ignores=[]), 'directory-loop', 'exec'), env)


if __name__=='__main__':unittest.main()
