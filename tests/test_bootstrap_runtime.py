import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location("bootstrap", Path(__file__).parents[1] / "scripts/bootstrap-runtime.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapSafetyTests(unittest.TestCase):
    def test_zip_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "evil.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("../escape", "untrusted")
            with self.assertRaises(ValueError):
                bootstrap.extract_archive(archive, root / "stage")
            self.assertFalse((root / "escape").exists())

    def test_tar_link_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "evil.tar"
            with tarfile.open(archive, "w") as t:
                member = tarfile.TarInfo("model/link")
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                t.addfile(member)
            with self.assertRaises(ValueError):
                bootstrap.extract_archive(archive, root / "stage")

    def test_bad_download_never_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = {"id": "test", "url": "https://example.invalid/model.zip", "archive_sha256": "0" * 64}
            with patch.object(bootstrap.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")):
                with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                    bootstrap.download(model, Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_failed_model_validation_preserves_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vendor = root / "vendor"
            old = vendor / "model"
            old.mkdir(parents=True)
            (old / "weights").write_bytes(b"working")
            archive = root / "model.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("model/weights", b"wrong")
            model = {"id": "model", "files": {"weights": hashlib.sha256(b"expected").hexdigest()}}
            with patch.object(bootstrap, "download", return_value=archive):
                with self.assertRaisesRegex(ValueError, "failed verification"):
                    bootstrap.install_model(model, vendor, root / "cache")
            self.assertEqual((old / "weights").read_bytes(), b"working")

    def test_verified_model_skips_network_and_preserves_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            vendor = Path(tmp)
            old = vendor / "model"
            old.mkdir()
            weights = old / "weights"
            weights.write_bytes(b"working")
            before = weights.stat().st_mtime_ns
            model = {"id": "model", "files": {"weights": bootstrap.sha256(weights)}}
            with patch.object(bootstrap, "download", side_effect=AssertionError("network called")):
                bootstrap.install_model(model, vendor, vendor / "cache")
            self.assertEqual(weights.stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
