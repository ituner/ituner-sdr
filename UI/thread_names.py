"""Publish Python worker names to Linux once, when each thread starts.

Installed only by the native UI entry point. No profiler, trace hook, polling,
new thread or per-frame work. Native-library threads retain library names.
"""
import re
import sys
import threading
from pathlib import Path


def set_os_thread_name(name):
    if not sys.platform.startswith('linux'):
        return
    # Linux comm allows 15 UTF-8 bytes plus its terminating NUL.
    encoded = str(name).replace('\n', '-').encode('utf-8')[:15]
    encoded = encoded.decode('utf-8', errors='ignore').encode('utf-8')
    try:
        Path(f'/proc/self/task/{threading.get_native_id()}/comm').write_bytes(encoded)
    except OSError:
        # Naming is diagnostic only and must never stop a worker.
        pass


def worker_name(thread):
    name = thread.name
    if re.match(r'^Thread-\d+(?: |$)', name):
        target = getattr(thread, '_target', None)
        # Qualnames distinguish otherwise anonymous self._run methods.
        name = getattr(target, '__qualname__', name).replace('.<locals>.', '.')
        name = name.replace('_', '-').strip('-')
    return name


def install_thread_names():
    """Wrap standard Thread.run once; preserve targets and exception handling.

    Explicit Thread subclasses overriding run and native-created threads are
    outside this hook. The application's standard Thread/ThreadPool workers
    use it. Python versions that already set OS names are harmlessly updated.
    """
    set_os_thread_name('ui-main')
    if getattr(threading.Thread.run, '_ituner_names', False):
        return
    original = threading.Thread.run

    def named_run(self):
        set_os_thread_name(worker_name(self))
        return original(self)

    named_run._ituner_names = True
    threading.Thread.run = named_run
