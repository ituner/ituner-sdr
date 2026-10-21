"""On-demand application updates. No driver, OS, receiver, or model updates.

The Pi's privileged copy lives outside the application and only accepts fixed
operations against the official repository. Desktop workers run as the user.
"""
from __future__ import annotations
import argparse
import contextlib
try:
    import fcntl
except ImportError:  # Windows can run the SDR, but this installer targets Pi/Mac.
    fcntl = None
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'ituner/ituner-sdr'
API = 'https://api.github.com/repos/' + REPOSITORY
SHA = re.compile(r'^[0-9a-f]{40}$')
PROTOCOL = 1
MAX_DOWNLOAD = 80 * 1024 * 1024
MAX_EXPANDED = 200 * 1024 * 1024
HELPER = '/usr/local/sbin/ituner-update'
# Keep the existing helper protocol; the product has one update source: main.
UPDATE_CHANNEL = 'development'


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + str(os.getpid()))
    with temporary.open('w') as f:
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def config_path():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/iTuner/updates/config.json'
    return Path('/etc/ituner-update.json')


def load_config():
    if sys.platform not in ('linux', 'darwin'):
        raise RuntimeError('In-app installation currently supports Raspberry Pi and Mac.')
    cfg = read_json(config_path())
    if not cfg:
        raise RuntimeError('Updater is not installed. Run scripts/install-updater.py first.')
    if cfg.get('protocol') != PROTOCOL:
        raise RuntimeError('This update requires a newer updater installer.')
    return cfg


def installed(cfg):
    root = Path(cfg['root'])
    data = read_json(root / '.ituner-installed.json')
    if not data.get('version'):
        try:
            data['version'] = (root / 'VERSION').read_text().strip()
        except OSError:
            data['version'] = 'unversioned'
    if not data.get('commit') and cfg['platform'] == 'linux':
        try:
            data['commit'] = Path('/var/lib/ituner-sdr/installed-commit').read_text().strip()
        except OSError:
            pass
    return data


def request_json(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'ituner-updater/1', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        if (urllib.parse.urlparse(response.url).scheme != 'https' or
                urllib.parse.urlparse(response.url).hostname != 'api.github.com'):
            raise RuntimeError('Unexpected update server destination.')
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise RuntimeError('Update response is too large.')
        return json.loads(data)


def check_release(channel):
    if channel not in ('stable', 'development'):
        raise ValueError('Unknown update channel')
    if channel == 'stable':
        try:
            release = request_json(API + '/releases/latest')
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError('No stable release has been published yet. Try Development.') from exc
            raise
        if release.get('draft') or release.get('prerelease'):
            raise RuntimeError('The latest release is not a stable release.')
        tag = release['tag_name']
        commit = request_json(API + '/commits/' + urllib.parse.quote(tag, safe=''))
        name = tag
        notes = release.get('body') or 'No release notes supplied.'
    else:
        commit = request_json(API + '/commits/main')
        date = commit['commit'].get('committer', {}).get('date', '')[:10]
        name = 'Build ' + commit['sha'][:8] + (' · ' + date if date else '')
        notes = commit['commit']['message']
    sha = commit['sha']
    if not SHA.fullmatch(sha):
        raise RuntimeError('Invalid GitHub commit identifier.')
    return {'commit': sha, 'name': name, 'notes': notes[:12000], 'channel': channel}


def managed_name(name):
    """Only distributed application files; never hidden runtime/data folders."""
    p = PurePosixPath(name)
    if p.is_absolute() or not p.parts or any(x in ('', '.', '..') or x.startswith('.') for x in p.parts):
        return False
    if any(x in ('__pycache__', 'models', 'logs', 'recordings', 'downloads', 'venv') for x in p.parts):
        return False
    return str(p) in ('VERSION', 'app-update.json') or (
        len(p.parts) > 1 and p.parts[0] in ('UI', 'assets', 'licenses')
        and p.suffix != '.pyc')


def extract_application(archive, destination):
    destination = Path(destination)
    total = 0
    names = set()
    with tarfile.open(archive, 'r:gz') as tar:
        for index, member in enumerate(tar):
            if index > 20000:
                raise RuntimeError('Too many files in update.')
            parts = PurePosixPath(member.name).parts
            if len(parts) < 2:
                continue
            name = '/'.join(parts[1:])
            if '..' in parts or PurePosixPath(member.name).is_absolute():
                raise RuntimeError('Unsafe path in update archive.')
            if member.isdir() or not managed_name(name):
                continue
            if not member.isfile():
                raise RuntimeError('Links and special files are not allowed in application updates.')
            if name in names:
                raise RuntimeError('Duplicate file in update archive.')
            names.add(name)
            total += member.size
            if member.size > 32 * 1024 * 1024 or total > MAX_EXPANDED:
                raise RuntimeError('Expanded update exceeds size limit.')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)
    for required in ('UI/kiwi_gl_display.py', 'UI/app_update.py', 'VERSION', 'app-update.json'):
        if required not in names:
            raise RuntimeError('Release lacks updater support: ' + required)
    meta = read_json(destination / 'app-update.json')
    if meta.get('protocol') != PROTOCOL or meta.get('runtime') != 1:
        raise RuntimeError('Runtime/dependency upgrade required. Use the platform installer for this release.')
    return sorted(names)


def safe_target(root, name):
    if not managed_name(name):
        raise RuntimeError('Unmanaged update path: ' + name)
    root = Path(root)
    target = root / name
    if root.is_symlink():
        raise RuntimeError('Application root must not be a symlink.')
    current = target
    while current != root:
        if current.is_symlink():
            raise RuntimeError('Refusing to overwrite a symlink: ' + name)
        current = current.parent
    return target


def download(sha, target):
    if not SHA.fullmatch(sha):
        raise ValueError('Invalid commit')
    url = 'https://codeload.github.com/' + REPOSITORY + '/tar.gz/' + sha
    request = urllib.request.Request(url, headers={'User-Agent': 'ituner-updater/1'})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=30) as source, Path(target).open('wb') as output:
        parsed = urllib.parse.urlparse(source.url)
        if parsed.scheme != 'https' or parsed.hostname != 'codeload.github.com':
            raise RuntimeError('Unexpected download destination.')
        while True:
            chunk = source.read(128 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise RuntimeError('Download exceeds size limit.')
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def status(cfg, phase, message, **extra):
    atomic_json(Path(cfg['state']) / 'status.json',
                dict(phase=phase, message=message, time=time.time(), **extra))


def runtime_info(cfg):
    return read_json(cfg['runtime_info'])


def register_runtime():
    """Called after a presented frame; identifies the real running application."""
    try:
        cfg = load_config()
        if Path(__file__).resolve().parent.parent != Path(cfg['root']).resolve():
            return
        env = {k: v for k, v in os.environ.items() if k in (
            'PATH', 'LANG', 'LC_ALL', 'SDL_AUDIODRIVER', 'SDL_VIDEODRIVER',
            'ITUNER_SATELLITE_HOST', 'PYGAME_HIDE_SUPPORT_PROMPT', 'PYTHONUNBUFFERED')}
        atomic_json(cfg['runtime_info'], dict(pid=os.getpid(), python=sys.executable,
                    argv=sys.argv, cwd=os.getcwd(), env=env,
                    commit=installed(cfg).get('commit', ''), time=time.time()))
    except (OSError, RuntimeError, ValueError) as exc:
        print('application updater readiness:', exc, flush=True)


def process_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


class Platform:
    def __init__(self, cfg):
        self.cfg = cfg
        self.previous = runtime_info(cfg)
        self.child = None

    def stop(self):
        if self.cfg['platform'] == 'linux':
            subprocess.run(['systemctl', 'stop', 'ituner-sdr.service'], check=True, timeout=50)
        else:
            pid = self.previous.get('pid')
            if not process_alive(pid):
                return  # A failed new process must not prevent restoring its backup.
            # Do not signal a recycled PID belonging to an unrelated app.
            command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True)
            if 'kiwi_gl_display.py' not in command:
                raise RuntimeError('Desktop process identity changed. Reopen the app.')
            os.kill(pid, signal.SIGTERM)
            for _ in range(100):
                if not process_alive(pid):
                    break
                time.sleep(.2)
            else:
                raise RuntimeError('The app did not exit cleanly. No files were changed.')

    def start(self):
        if self.cfg['platform'] == 'linux':
            subprocess.run(['systemctl', 'reset-failed', 'ituner-sdr.service'], check=False)
            subprocess.run(['systemctl', 'start', 'ituner-sdr.service'], check=True, timeout=30)
        else:
            info = self.previous
            python = info.get('python', self.cfg['python'])
            args = info.get('argv', [str(Path(self.cfg['root']) / 'UI/kiwi_gl_display.py'), '--desktop'])
            # A Mac profile is user-owned; still limit relaunch to this app.
            args = [str(Path(self.cfg['root']) / 'UI/kiwi_gl_display.py')] + args[1:]
            env = dict(os.environ, **info.get('env', {}))
            with open(Path(self.cfg['state']) / 'application.log', 'ab') as log:
                self.child = subprocess.Popen([python, *args], cwd=self.cfg['root'], env=env,
                                               stdout=log, stderr=log, start_new_session=True)
            # Keep the existing desktop icon's singleton detection current.
            (Path.home() / 'Library/Application Support/iTuner/desktop.pid').write_text(str(self.child.pid))
            self.previous = dict(info, pid=self.child.pid)

    def healthy(self, since, commit, timeout=75, settle=8):
        deadline = time.monotonic() + timeout
        first = None
        while time.monotonic() < deadline:
            info = runtime_info(self.cfg)
            alive = process_alive(info.get('pid'))
            if self.cfg['platform'] == 'linux':
                current = subprocess.check_output(['systemctl', 'show', 'ituner-sdr.service',
                                                   '-p', 'MainPID', '--value'], text=True).strip()
                alive = alive and current == str(info.get('pid'))
            else:
                alive = alive and self.child is not None and self.child.poll() is None and info.get('pid') == self.child.pid
            valid = alive and info.get('time', 0) >= since and info.get('commit', '') == commit
            if valid:
                first = first or time.monotonic()
                if time.monotonic() - first >= settle:
                    return True
            else:
                first = None
            time.sleep(.5)
        return False


def preflight(cfg, stage):
    command = [cfg['python'], '-c',
               'import sys; sys.path.insert(0, sys.argv[1]); import kiwi_gl_display', str(stage / 'UI')]
    if cfg['platform'] == 'linux':
        command = ['runuser', '-u', cfg['user'], '--', *command]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, PYGAME_HIDE_SUPPORT_PROMPT='1', PYTHONDONTWRITEBYTECODE='1'))
    if result.returncode:
        raise RuntimeError('Dependency check failed; app unchanged. ' + (result.stderr or result.stdout)[-1200:])


def make_backup(cfg, names, folder):
    root = Path(cfg['root'])
    folder.mkdir(parents=True)
    records = {}
    for name in names:
        target = safe_target(root, name)
        records[name] = target.is_file()
        if target.exists() and not target.is_file():
            raise RuntimeError('Application path is not a regular file: ' + name)
        if records[name]:
            dest = folder / 'files' / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, dest)
    metadata = read_json(root / '.ituner-installed.json') or installed(cfg)
    atomic_json(folder / 'backup.json', {'files': records, 'installed': metadata})


def copy_atomic(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.update-tmp')
    if temp.is_symlink():
        raise RuntimeError('Unsafe temporary file.')
    shutil.copyfile(source, temp)
    temp.chmod(0o644)
    os.replace(temp, target)


def apply_files(cfg, stage, names, metadata):
    root = Path(cfg['root'])
    for name in names:
        copy_atomic(stage / name, safe_target(root, name))
    atomic_json(root / '.ituner-installed.json', metadata)
    if cfg['platform'] == 'linux':
        Path('/var/lib/ituner-sdr/installed-commit').write_text(metadata.get('commit', '') + '\n')


def restore_files(cfg, folder):
    data = read_json(folder / 'backup.json')
    if not data.get('files'):
        raise RuntimeError('No valid previous version is available.')
    for name, existed in data['files'].items():
        target = safe_target(cfg['root'], name)
        if existed:
            copy_atomic(folder / 'files' / name, target)
        else:
            target.unlink(missing_ok=True)
    atomic_json(Path(cfg['root']) / '.ituner-installed.json', data['installed'])
    if cfg['platform'] == 'linux':
        Path('/var/lib/ituner-sdr/installed-commit').write_text(data['installed'].get('commit', '') + '\n')
    return data['installed']


def recover_before_start(cfg):
    """Pi ExecStartPre: recover an interrupted write before importing the app."""
    state = Path(cfg['state'])
    with (state / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # A live update worker owns startup and validation.
        pending = state / 'pending'
        if (pending / 'backup.json').exists():
            restore_files(cfg, pending)
            shutil.rmtree(pending)
            status(cfg, 'complete', 'Interrupted update recovered; previous version restored.')
    return 0


def worker(cfg, operation, channel='stable', expected=''):
    state = Path(cfg['state']); state.mkdir(parents=True, exist_ok=True)
    with (state / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 2
        platform = Platform(cfg)
        pending = state / 'pending'
        previous = state / 'previous'
        stopped = False
        try:
            # A power interruption during a transaction is recovered before
            # attempting anything else. Backups stay outside the app tree.
            if (pending / 'backup.json').exists():
                status(cfg, 'installing', 'Recovering an interrupted update...')
                platform.stop(); stopped = True
                old = restore_files(cfg, pending)
                since = time.time(); platform.start(); stopped = False
                if not platform.healthy(since, old.get('commit', '')):
                    raise RuntimeError('Recovery needs attention; previous files restored.')
                shutil.rmtree(pending)
            if operation == 'rollback':
                status(cfg, 'installing', 'Restoring previous application version...')
                if not (previous / 'backup.json').exists():
                    raise RuntimeError('No previous version saved yet.')
                platform.stop(); stopped = True
                old = restore_files(cfg, previous)
                since = time.time(); platform.start(); stopped = False
                if not platform.healthy(since, old.get('commit', '')):
                    raise RuntimeError('Previous files restored, but the app did not become ready.')
                status(cfg, 'complete', 'Previous version restored.'); return 0
            status(cfg, 'downloading', 'Downloading and checking update; radio stays on...')
            release = check_release(channel)
            if release['commit'] != expected:
                raise RuntimeError('The release changed. Check for updates again before installing.')
            if installed(cfg).get('commit') == expected:
                status(cfg, 'complete', 'Already running this version.'); return 0
            if shutil.disk_usage(cfg['root']).free < 512 * 1024 * 1024:
                raise RuntimeError('At least 512 MB free storage is required.')
            with tempfile.TemporaryDirectory(prefix='ituner-update-', dir=state) as work:
                work = Path(work); work.chmod(0o755)
                archive = work / 'source.tar.gz'
                digest = download(expected, archive)
                stage = work / 'stage'; stage.mkdir(mode=0o755)
                names = extract_application(archive, stage)
                preflight(cfg, stage)
                status(cfg, 'installing', 'Restarting application with the new version...')
                if pending.exists():
                    shutil.rmtree(pending)
                # Stop before snapshotting to capture final settings writes.
                platform.stop(); stopped = True
                make_backup(cfg, names, pending)
                version = (stage / 'VERSION').read_text().strip()
                metadata = dict(version=version, commit=expected, channel=channel,
                                archive_sha256=digest, installed_at=time.time())
                apply_files(cfg, stage, names, metadata)
                since = time.time(); platform.start(); stopped = False
                if not platform.healthy(since, expected):
                    raise RuntimeError('New version failed the startup check.')
                if previous.exists():
                    shutil.rmtree(previous)
                pending.rename(previous)
                atomic_json(state / 'rollback.json', {'available': True,
                            'version': read_json(previous / 'backup.json')['installed'].get('version', '?')})
                status(cfg, 'complete', 'Update installed and interface verified.', commit=expected)
                return 0
        except Exception as exc:
            message = str(exc)
            if (pending / 'backup.json').exists():
                try:
                    platform.stop(); stopped = True
                    old = restore_files(cfg, pending)
                    since = time.time(); platform.start(); stopped = False
                    healthy = platform.healthy(since, old.get('commit', ''))
                    if healthy:
                        shutil.rmtree(pending)
                    message += ' Previous version restored' + (' and running.' if healthy else '; restart needs attention.')
                except Exception as recovery:
                    message += ' Recovery needs attention: ' + str(recovery)
            elif stopped:
                with contextlib.suppress(Exception):
                    platform.start()
            status(cfg, 'error', message[:1800])
            return 1


class UpdateController:
    """Render-thread facade: network and filesystem operations never block UI."""
    def __init__(self):
        self.open = False
        self.channel = UPDATE_CHANNEL
        self.release = None
        self.message = 'Check for the latest iTuner build on GitHub main.'
        self.phase = 'idle'
        self.recovery = False
        self.busy = False
        self.confirm = None
        self.notes_page = 0
        self.cfg = None
        self.last_status_time = 0
        try:
            self.cfg = load_config()
            # Ignore old completed jobs when opening this app; active jobs and
            # failures still need to be visible after a restart.
            state = read_json(Path(self.cfg['state']) / 'status.json')
            if state.get('phase') == 'complete':
                self.last_status_time = state.get('time', 0)
            else:
                self.poll()
        except RuntimeError as exc:
            self.phase = 'error'
            self.message = str(exc)

    def current(self):
        return installed(self.cfg) if self.cfg else {'version': 'updater not installed'}

    def poll(self):
        if not self.cfg:
            return
        state = read_json(Path(self.cfg['state']) / 'status.json')
        if state.get('time', 0) > self.last_status_time:
            self.last_status_time = state['time']
            self.message = state.get('message', '')
            self.phase = state.get('phase', 'idle')
            self.busy = self.phase in ('downloading', 'installing')

    def rollback_available(self):
        return bool(self.cfg and read_json(Path(self.cfg['state']) / 'rollback.json').get('available'))

    def check(self):
        if self.busy or not self.cfg:
            return
        self.poll()
        if self.busy:
            return
        self.busy = True; self.confirm = None; self.release = None
        self.recovery = False; self.phase = 'checking'
        self.message = 'Checking the latest build on GitHub main...'
        def task():
            try:
                self.release = check_release(UPDATE_CHANNEL)
                self.notes_page = 0
                current = self.release['commit'] == self.current().get('commit')
                self.phase = 'current' if current else 'available'
                self.message = ('You have the latest build on main.' if current
                                else 'A new build is available. Install it when you are ready.')
            except Exception as exc:
                self.phase = 'error'
                self.message = 'Could not check updates: ' + str(exc)
            finally:
                self.busy = False
        threading.Thread(target=task, daemon=True).start()

    def launch(self, operation):
        if self.busy or not self.cfg:
            return
        if operation not in ('install', 'rollback'):
            return
        if operation == 'install' and (not self.release or self.release['commit'] == self.current().get('commit')):
            return
        if operation == 'rollback' and not self.rollback_available():
            return
        self.poll()
        if self.busy:
            return
        channel = UPDATE_CHANNEL
        sha = self.release['commit'] if self.release else ''
        self.busy = True; self.confirm = None; self.recovery = False
        self.phase = 'starting'
        self.message = 'Starting update. The app will restart automatically...'
        def task():
            try:
                if self.cfg['platform'] == 'linux':
                    result = subprocess.run(['sudo', '-n', HELPER, operation, channel, sha],
                                            capture_output=True, text=True, timeout=15)
                    if result.returncode:
                        raise RuntimeError(result.stderr.strip() or 'Updater service could not start.')
                else:
                    log = Path(self.cfg['state']) / 'worker.log'
                    with log.open('ab') as out:
                        subprocess.Popen([self.cfg['python'], __file__, '--worker', operation, channel, sha],
                                         stdout=out, stderr=out, start_new_session=True,
                                         cwd=str(Path.home()))
                # Busy remains true until the worker reports a terminal state.
            except Exception as exc:
                self.phase = 'error'
                self.message = str(exc); self.busy = False
        threading.Thread(target=task, daemon=True).start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('operation', choices=['install', 'rollback', 'recover'])
    parser.add_argument('channel', choices=['stable', 'development'])
    parser.add_argument('commit', nargs='?', default='')
    args = parser.parse_args()
    if args.operation == 'install' and not SHA.fullmatch(args.commit):
        parser.error('Install requires an exact Git commit.')
    cfg = load_config()
    if cfg['platform'] == 'linux':
        if os.geteuid() != 0:
            parser.error('Use the installed sudo helper.')
        if args.operation == 'recover':
            return recover_before_start(cfg)
        if not args.worker:
            command = ['systemd-run', '--unit=ituner-app-update', '--collect',
                       '--property=Type=exec', '/usr/bin/python3', HELPER, '--worker',
                       args.operation, args.channel, args.commit]
            return subprocess.run(command).returncode
    return worker(cfg, args.operation, args.channel, args.commit)


if __name__ == '__main__':
    raise SystemExit(main())
