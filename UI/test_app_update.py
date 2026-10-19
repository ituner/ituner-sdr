import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock
import app_update as u


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'app'; self.root.mkdir()
        self.state = self.base / 'state'; self.state.mkdir()
        self.cfg = dict(root=str(self.root), state=str(self.state), platform='darwin',
                        runtime_info=str(self.base / 'runtime.json'), python='python3')
        (self.root / 'UI').mkdir()
        (self.root / 'UI/kiwi_gl_display.py').write_text('old')
        (self.root / 'VERSION').write_text('0.1.1')
        u.atomic_json(self.root / '.ituner-installed.json', dict(version='0.1.1', commit='a'*40))

    def archive(self, extras=None):
        data = {'source/UI/kiwi_gl_display.py': b'new', 'source/UI/app_update.py': b'helper',
                'source/VERSION': b'0.1.2', 'source/app-update.json': b'{"protocol":1,"runtime":1}',
                'source/config/display.txt': b'NEVER INSTALL', 'source/UI/.venv/bin/python': b'preserve'}
        data.update(extras or {})
        archive = self.base / 'source.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for name, value in data.items():
                member = tarfile.TarInfo(name)
                if value is None:
                    member.type = tarfile.SYMTYPE; member.linkname = '/etc/passwd'
                    tar.addfile(member)
                else:
                    member.size = len(value); tar.addfile(member, io.BytesIO(value))
        return archive

    def test_archive_limits_scope_preserves_drivers_runtime(self):
        stage = self.base / 'stage'
        names = u.extract_application(self.archive(), stage)
        self.assertNotIn('config/display.txt', names)
        self.assertNotIn('UI/.venv/bin/python', names)
        self.assertIn('UI/app_update.py', names)

    def test_traversal_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsafe path'):
            u.extract_application(self.archive({'source/../escape': b'oops'}), self.base / 'stage')

    def test_archive_symlink_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Links'):
            u.extract_application(self.archive({'source/UI/a.py': None}), self.base / 'stage')

    def test_existing_symlink_rejected(self):
        (self.root / 'UI/link.py').symlink_to('/tmp')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            u.safe_target(self.root, 'UI/link.py')

    def test_manifest_dependency_change_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Runtime/dependency'):
            u.extract_application(self.archive({'source/app-update.json': b'{"protocol":1,"runtime":2}'}), self.base / 'stage')

    def test_backup_restore_preserves_unmanaged_files(self):
        (self.root / 'UI/my-recording.wav').write_bytes(b'audio')
        stage = self.base / 'stage'; names = u.extract_application(self.archive(), stage)
        backup = self.state / 'previous'
        u.make_backup(self.cfg, names, backup)
        u.apply_files(self.cfg, stage, names, dict(version='0.1.2',commit='b'*40))
        self.assertEqual((self.root / 'UI/kiwi_gl_display.py').read_text(), 'new')
        u.restore_files(self.cfg, backup)
        self.assertEqual((self.root / 'UI/kiwi_gl_display.py').read_text(), 'old')
        self.assertFalse((self.root / 'UI/app_update.py').exists())
        self.assertEqual((self.root / 'UI/my-recording.wav').read_bytes(), b'audio')
        self.assertEqual(u.installed(self.cfg)['commit'], 'a'*40)

    def run_worker(self, healthy):
        archive = self.archive()
        release = dict(commit='b'*40, channel='stable', name='v0.1.2', notes='test')
        def download(sha, target):
            import shutil
            shutil.copyfile(archive, target)
            return 'digest'
        platform = mock.Mock(); platform.healthy.side_effect = healthy
        with mock.patch.object(u, 'Platform', return_value=platform), \
             mock.patch.object(u, 'check_release', return_value=release), \
             mock.patch.object(u, 'download', side_effect=download), \
             mock.patch.object(u, 'preflight'):
            result = u.worker(self.cfg, 'install', 'stable', 'b'*40)
        return result, platform

    def test_success_keeps_previous_for_rollback(self):
        result, platform = self.run_worker([True])
        self.assertEqual(result, 0)
        self.assertTrue((self.state / 'previous/backup.json').exists())
        self.assertFalse((self.state / 'pending').exists())
        self.assertEqual(u.installed(self.cfg)['commit'], 'b'*40)
        self.assertEqual(u.read_json(self.state / 'status.json')['phase'], 'complete')
        platform.stop.assert_called_once()

    def test_failed_start_automatically_restores(self):
        result, platform = self.run_worker([False, True])
        self.assertEqual(result, 1)
        self.assertEqual((self.root / 'UI/kiwi_gl_display.py').read_text(), 'old')
        self.assertEqual(u.installed(self.cfg)['commit'], 'a'*40)
        self.assertIn('Previous version restored and running', u.read_json(self.state / 'status.json')['message'])
        self.assertEqual(platform.start.call_count, 2)

    def test_failed_download_never_stops_app(self):
        with mock.patch.object(u, 'Platform') as platform, \
             mock.patch.object(u, 'check_release', side_effect=OSError('offline')):
            self.assertEqual(u.worker(self.cfg, 'install', 'stable', 'b'*40), 1)
        platform.return_value.stop.assert_not_called()
        self.assertEqual((self.root / 'UI/kiwi_gl_display.py').read_text(), 'old')

    def test_release_changed_requires_recheck(self):
        with mock.patch.object(u, 'Platform') as platform, mock.patch.object(u, 'check_release', return_value={'commit': 'c'*40}):
            self.assertEqual(u.worker(self.cfg, 'install', 'stable', 'b'*40), 1)
        platform.return_value.stop.assert_not_called()
        self.assertIn('release changed', u.read_json(self.state / 'status.json')['message'])

    def test_manual_rollback(self):
        self.run_worker([True])
        with mock.patch.object(u, 'Platform') as platform:
            platform.return_value.healthy.return_value = True
            self.assertEqual(u.worker(self.cfg, 'rollback'), 0)
        self.assertEqual(u.installed(self.cfg)['commit'], 'a'*40)

    def test_check_uses_github_only_and_pins_sha(self):
        with mock.patch.object(u, 'request_json', side_effect=[
            {'tag_name':'v0.1.2','body':'Changes'}, {'sha':'b'*40}]) as request:
            release = u.check_release('stable')
        self.assertEqual(release['commit'], 'b'*40)
        self.assertTrue(all(c.args[0].startswith(u.API) for c in request.call_args_list))

    def test_bad_sha_rejected(self):
        with mock.patch.object(u, 'request_json', return_value={'sha':'bad','commit':{'message':'test'}}):
            with self.assertRaises(RuntimeError):
                u.check_release('development')

    def test_controller_does_not_check_on_open(self):
        with mock.patch.object(u, 'load_config', return_value=self.cfg), mock.patch.object(u,'check_release') as check:
            controller = u.UpdateController(); controller.open = True; controller.poll()
            check.assert_not_called()

    def test_dead_mac_process_does_not_block_restore(self):
        platform = u.Platform(self.cfg)
        with mock.patch.object(u, 'process_alive', return_value=False), mock.patch.object(u.os, 'kill') as kill:
            platform.stop()
        kill.assert_not_called()

    def test_boot_recovers_pending_files_without_starting_service(self):
        stage = self.base / 'stage'
        names = u.extract_application(self.archive(), stage)
        u.make_backup(self.cfg, names, self.state / 'pending')
        u.apply_files(self.cfg, stage, names, {'version':'0.1.2','commit':'b'*40})
        self.assertEqual(u.recover_before_start(self.cfg), 0)
        self.assertEqual(u.installed(self.cfg)['commit'], 'a'*40)
        self.assertFalse((self.state / 'pending').exists())

    def test_stale_readiness_is_rejected(self):
        platform = u.Platform(self.cfg)
        platform.child = mock.Mock(pid=123)
        platform.child.poll.return_value = None
        u.atomic_json(self.cfg['runtime_info'], dict(pid=123,commit='b'*40,time=1))
        with mock.patch.object(u, 'process_alive', return_value=True):
            self.assertFalse(platform.healthy(2,'b'*40, timeout=.01, settle=0))


if __name__ == '__main__':
    unittest.main()
