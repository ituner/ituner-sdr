import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from UI import thread_names as names


class ThreadNameTests(unittest.TestCase):
    def test_hook_runs_target_once_and_is_idempotent(self):
        original = threading.Thread.run
        seen = []
        try:
            with patch.object(names, 'set_os_thread_name') as publish:
                names.install_thread_names()
                hook = threading.Thread.run
                names.install_thread_names()
                self.assertIs(threading.Thread.run, hook)
                worker = threading.Thread(target=lambda: seen.append('done'), name='waterfall-rx')
                worker.start()
                worker.join()
                self.assertEqual(seen, ['done'])
                publish.assert_any_call('waterfall-rx')
        finally:
            threading.Thread.run = original

    def test_utf8_limit_and_missing_proc_are_safe(self):
        with patch.object(sys, 'platform', 'linux'), patch.object(Path, 'write_bytes') as write:
            names.set_os_thread_name('é' * 20)
            value = write.call_args.args[0]
            self.assertLessEqual(len(value), 15)
            value.decode('utf-8')
            write.side_effect = OSError('unavailable')
            names.set_os_thread_name('audio-rx')

    def test_default_name_uses_target_role(self):
        def receiver_worker():
            pass
        name = names.worker_name(threading.Thread(target=receiver_worker))
        self.assertIn('receiver-worker', name)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'requires Linux procfs')
    def test_live_kernel_name(self):
        original = threading.Thread.run
        seen = []
        try:
            names.install_thread_names()
            def read_name():
                seen.append(Path(f'/proc/self/task/{threading.get_native_id()}/comm').read_text().strip())
            worker = threading.Thread(target=read_name, name='waterfall-rx')
            worker.start()
            worker.join()
            self.assertEqual(seen, ['waterfall-rx'])
        finally:
            threading.Thread.run = original
