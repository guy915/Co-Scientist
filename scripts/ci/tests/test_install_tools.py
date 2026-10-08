import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.ci.install_tools import extract_verified


class InstallToolsTests(unittest.TestCase):
    def archive(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            member = tarfile.TarInfo("gitleaks")
            member.size = 6
            archive.addfile(member, io.BytesIO(b"binary"))
        return data.getvalue()

    def test_checksum_mismatch_fails_before_writing_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gitleaks"
            with self.assertRaisesRegex(ValueError, "checksum"):
                extract_verified(self.archive(), "0" * 64, "gitleaks", path)
            self.assertFalse(path.exists())

    def test_verified_binary_alone_is_extracted_and_executable(self):
        archive = self.archive()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gitleaks"
            extract_verified(
                archive, hashlib.sha256(archive).hexdigest(), "gitleaks", path
            )
            self.assertEqual(path.read_bytes(), b"binary")
            self.assertTrue(path.stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
