import contextlib
import io
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'UI'))
from directory_refresh import DailyDirectoryRefresh, DIRECTORY_REFRESH_SECONDS


class DailyRefreshTests(unittest.TestCase):
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
