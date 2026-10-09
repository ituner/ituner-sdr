import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('whisper_install', Path(__file__).parents[1] / 'scripts/install-whisper.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class WhisperInstallTests(unittest.TestCase):
    def fixture(self, root):
        dest = root / 'whisper.cpp'
        binary = dest / 'build/bin/whisper-cli'
        model = dest / 'models/base.bin'
        binary.parent.mkdir(parents=True)
        model.parent.mkdir()
        binary.write_bytes(b'working binary'); binary.chmod(0o755)
        model.write_bytes(b'working model')
        manifest = dict(model_name='base.bin', model_sha256=installer.bootstrap.sha256(model))
        (dest / 'ituner-install.json').write_text(json.dumps(dict(
            manifest=manifest, binary_sha256=installer.bootstrap.sha256(binary))))
        return dest, manifest

    def test_verified_install_skips_network_and_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dest, manifest = self.fixture(root)
            with patch.object(installer.bootstrap, 'download', side_effect=AssertionError('network')), \
                 patch.object(installer.subprocess, 'run', side_effect=AssertionError('build')):
                installer.install(root, root / 'cache', manifest)
                installer.install(root, root / 'cache', manifest, verify_only=True)

    def test_corrupted_model_or_binary_is_rejected(self):
        for relative in ('models/base.bin', 'build/bin/whisper-cli'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); dest, manifest = self.fixture(root)
                (dest / relative).write_bytes(b'corrupt')
                self.assertFalse(installer.matches(dest, manifest))
                with self.assertRaisesRegex(RuntimeError, 'verification'):
                    installer.install(root, root / 'cache', manifest, verify_only=True)

    def test_failed_download_preserves_previous_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dest, manifest = self.fixture(root)
            manifest.update(source_url='https://example.invalid/source', source_sha256='0'*64)
            with patch.object(installer.bootstrap, 'download', side_effect=ValueError('Checksum mismatch')):
                with self.assertRaises(ValueError):installer.install(root, root / 'cache', manifest)
            self.assertEqual((dest / 'build/bin/whisper-cli').read_bytes(), b'working binary')
            self.assertEqual((dest / 'models/base.bin').read_bytes(), b'working model')


if __name__ == '__main__':unittest.main()
