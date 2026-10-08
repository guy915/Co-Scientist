import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from .secret_scan import scan


class PinnedToolTests(unittest.TestCase):
    def test_secret_in_pr_additions_fails_and_secret_removed_by_pr_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", directory, *args], text=True
                ).strip()

            git("init", "-q")
            git("config", "user.name", "Test Developer")
            git("config", "user.email", "test@example.com")
            (root / "README.md").write_text("Base\n")
            git("add", ".")
            git("commit", "-qm", "test(ci): create base")
            base = git("rev-parse", "HEAD")
            # Assemble a synthetic fixture so the proof does not itself publish a key-shaped value.
            sentinel = "AKIA" + "QWERTYUIOPASDFGH"
            (root / "credentials.txt").write_text(f"aws_access_key_id = {sentinel}\n")
            git("add", ".")
            git("commit", "-qm", "test(ci): add sentinel")
            leaked = git("rev-parse", "HEAD")
            binary = Path(os.environ["GITLEAKS_BIN"])
            self.assertEqual(scan(root, base, leaked, binary), 1)
            (root / "credentials.txt").unlink()
            git("add", "-u")
            git("commit", "-qm", "test(ci): remove sentinel")
            self.assertEqual(scan(root, leaked, git("rev-parse", "HEAD"), binary), 0)

    def test_workflow_typo_and_untrusted_expression_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "unsafe.yml"
            workflow.write_text(
                "name: Proof\non: pull_request\npermissions: {}\njobs:\n  proof:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo '${{ github.event.pull_request.title }}'\n"
            )
            result = subprocess.run(
                [
                    os.environ["ZIZMOR_BIN"],
                    "--offline",
                    "--no-progress",
                    "--no-config",
                    str(workflow),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("template-injection", result.stdout + result.stderr)
            workflow.write_text(
                "name: Proof\non: pull_request\njobs:\n  proof:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo '${{ github.missing_property }}'\n"
            )
            result = subprocess.run(
                [
                    os.environ["ACTIONLINT_BIN"],
                    "-shellcheck=",
                    "-pyflakes=",
                    str(workflow),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing_property", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
