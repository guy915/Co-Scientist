"""Offline tests for the fail-closed same-process MCP server launcher."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tarfile
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import novelty_precise_rung_server_launcher as launcher


class ServerLauncherTests(unittest.TestCase):
    TEST_PYTHON = Path(
        os.environ.get(
            "NOVELTY_RUNG_TEST_PYTHON",
            "/Users/guy/Code/co-scientist/.venv-mcp/bin/python",
        )
    )
    PINNED_BUILDS = {
        "1ce3992ce0950b45979f7325fd66f7383f41afa0": "fbbf32866cf3d196772aafe6a94c2c01bdcd6f7f3bd405ae13b27d24e8306726",
        "8c91e5a9ed9661a37886c994f37083d75b41f8a5": "c22d34fa41daf7f06302731745bc761f51297eb0acb8ce8b8977fb20e2067673",
    }

    def _valid_source_root(self, root: Path) -> None:
        package = root / "engine" / "mcp_server"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('"""fixture"""\n')
        (package / "pubmed_client.py").write_text("# fixture client\n")
        (package / "server.py").write_text("# fixture server\n")

    def test_source_build_mismatch_stops_before_serving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "engine" / "mcp_server"
            package.mkdir(parents=True)
            (package / "pubmed_client.py").write_text("# wrong source\n")
            cache = root / "cache"
            receipt = root / "receipt.json"
            with (
                patch.dict(
                    os.environ,
                    {"COSCIENTIST_MCP_SHARED_SECRET": "s" * 48},
                    clear=False,
                ),
                patch.object(
                    launcher, "_serve", side_effect=AssertionError("must not serve")
                ),
            ):
                result = launcher.main(
                    [
                        "--source-root",
                        str(root),
                        "--expected-tree-sha256",
                        "0" * 64,
                        "--expected-source-sha256",
                        "0" * 64,
                        "--port",
                        "8898",
                        "--cache-dir",
                        str(cache),
                        "--receipt",
                        str(receipt),
                    ]
                )

            self.assertEqual(result, 2)
            self.assertFalse(receipt.exists())

    def test_extra_provider_credential_stops_before_import_or_serving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "source"
            root.mkdir()
            self._valid_source_root(root)
            cache = Path(directory) / "cache"
            receipt = Path(directory) / "receipt.json"
            with (
                patch.dict(
                    os.environ,
                    {
                        "COSCIENTIST_MCP_SHARED_SECRET": "s" * 48,
                        "OPENAI_API_KEY": "must-not-be-copied",
                    },
                    clear=True,
                ),
                patch.object(
                    launcher, "_serve", side_effect=AssertionError("must not serve")
                ),
            ):
                result = launcher.main(
                    [
                        "--source-root",
                        str(root),
                        "--expected-tree-sha256",
                        "6f149272de841a62ea449c0e649d221a0d8ea3d81c0de75da49a2e5086ec75b7",
                        "--expected-source-sha256",
                        "53dbc6ba3e99aa2bd6ba656cf3be446183f37316aa2c929ead4f5ca4d5b923aa",
                        "--port",
                        "8898",
                        "--cache-dir",
                        str(cache),
                        "--receipt",
                        str(receipt),
                    ]
                )

            self.assertEqual(result, 2)
            self.assertFalse(receipt.exists())

    def test_receipt_writer_never_serializes_the_mcp_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            secret = "s" * 48
            launcher._atomic_write_json(
                path,
                {"schema_version": launcher.SCHEMA_VERSION, "secret_free": True},
                secret,
            )

            payload = path.read_text(encoding="utf-8")
            self.assertNotIn(secret, payload)
            self.assertEqual(json.loads(payload)["secret_free"], True)

    def test_readiness_cleanup_removes_probe_cache_before_trials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            probe = cache / "pubmed" / "probe" / "runs" / "probe-run"
            probe.mkdir(parents=True)
            (probe / ".search-trace.json").write_text("{}")

            self.assertTrue(launcher._remove_readiness_cache(cache, "probe"))
            self.assertEqual(list(cache.iterdir()), [])

    def test_offline_guard_blocks_external_resolution_and_restores_patch(self) -> None:
        original = socket.getaddrinfo
        with ExitStack() as stack:
            blocked = launcher._guard_network(stack)
            with self.assertRaises(launcher.PreflightError):
                socket.getaddrinfo("eutils.ncbi.nlm.nih.gov", 443)
            self.assertEqual(blocked, ["dns"])

        self.assertIs(socket.getaddrinfo, original)

    def test_both_pinned_builds_pass_offline_probe_before_same_pid_serve(self) -> None:
        repository = Path(launcher.__file__).resolve().parents[3]
        launcher_dir = Path(launcher.__file__).resolve().parent
        child = """
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
import novelty_precise_rung_server_launcher as launcher

argv = sys.argv[1:]
receipt_path = Path(argv[argv.index('--receipt') + 1])
def fake_serve(app, host, port):
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    assert app is not None and host == '127.0.0.1'
    assert receipt['serving_pid'] == os.getpid()
    print(json.dumps({'serve_pid': os.getpid(), 'port': port}))
with patch.object(launcher, '_serve', fake_serve):
    raise SystemExit(launcher.main(argv))
"""
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            for index, (commit, expected_tree) in enumerate(self.PINNED_BUILDS.items()):
                build_root = temporary_root / f"build-{index}"
                build_root.mkdir()
                archive = subprocess.check_output(
                    ["git", "archive", "--format=tar", commit, "engine/mcp_server"],
                    cwd=repository,
                )
                with tarfile.open(fileobj=BytesIO(archive)) as source:
                    source.extractall(build_root, filter="data")
                source_file = build_root / "engine" / "mcp_server" / "pubmed_client.py"
                source_sha = hashlib.sha256(source_file.read_bytes()).hexdigest()
                cache = temporary_root / f"cache-{index}"
                receipt_path = temporary_root / f"receipt-{index}.json"
                environment = {
                    "COSCIENTIST_MCP_SHARED_SECRET": "offline-test-secret-" + "s" * 40,
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": os.pathsep.join(
                        (str(launcher_dir), str(build_root / "engine"))
                    ),
                }
                self.assertTrue(
                    self.TEST_PYTHON.is_file(),
                    f"offline MCP interpreter is missing: {self.TEST_PYTHON}",
                )
                result = subprocess.run(
                    [
                        str(self.TEST_PYTHON),
                        "-c",
                        child,
                        "--source-root",
                        str(build_root),
                        "--expected-tree-sha256",
                        expected_tree,
                        "--expected-source-sha256",
                        source_sha,
                        "--port",
                        str(8898 + index),
                        "--cache-dir",
                        str(cache),
                        "--receipt",
                        str(receipt_path),
                    ],
                    cwd=temporary_root,
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                serve = json.loads(result.stdout.strip().splitlines()[-1])
                receipt_bytes = receipt_path.read_bytes()
                receipt = json.loads(receipt_bytes)
                self.assertEqual(serve["serve_pid"], receipt["serving_pid"])
                self.assertEqual(receipt["schema_version"], launcher.SCHEMA_VERSION)
                self.assertEqual(receipt["status"], "passed")
                self.assertEqual(receipt["source_tree_sha256"], expected_tree)
                self.assertEqual(receipt["bind_host"], "127.0.0.1")
                self.assertEqual(receipt["max_workers"], 1)
                self.assertFalse(receipt["reload"])
                self.assertEqual(receipt["entrez"]["max_tries"], 1)
                self.assertEqual(receipt["entrez"]["sleep_between_tries"], 0)
                self.assertTrue(receipt["monkeypatches_restored"])
                trace = receipt["maintained_trace"]
                self.assertEqual(
                    trace["run_id"], f"m11_launcher_probe_{serve['serve_pid']}"
                )
                self.assertEqual(trace["slug"], trace["run_id"])
                self.assertEqual(trace["source_file_path"], str(source_file.resolve()))
                self.assertEqual(trace["server_build_id"], expected_tree)
                self.assertEqual(trace["process_id"], serve["serve_pid"])
                self.assertEqual(trace["sort"], "pub_date")
                self.assertEqual(trace["selected_ids"], trace["final_ids"])
                self.assertEqual(trace["final_ids"], trace["manifest_ids"])
                self.assertTrue(trace["validated"])
                self.assertTrue(trace["patches_restored"])
                self.assertTrue(trace["readiness_artifacts_removed"])
                self.assertTrue(trace["cache_empty_after_cleanup"])
                self.assertFalse(Path(trace["path"]).exists())
                transient = receipt["transient_probe"]
                self.assertEqual(transient["patch_target"], "Bio.Entrez.urlopen")
                self.assertEqual(transient["injected_status"], 503)
                self.assertEqual(transient["underlying_attempts"], 1)
                self.assertFalse(transient["external_traffic"])
                self.assertTrue(transient["restored"])
                self.assertEqual(list(cache.iterdir()), [])
                self.assertNotIn(
                    environment["COSCIENTIST_MCP_SHARED_SECRET"],
                    receipt_bytes.decode("utf-8"),
                )

    def test_transient_503_probe_counts_one_patched_urlopen_and_restores_it(
        self,
    ) -> None:
        try:
            from Bio import Entrez
        except ImportError as error:
            self.fail(f"Biopython is required for the real Entrez retry proof: {error}")

        original_max_tries = Entrez.max_tries
        original_sleep = Entrez.sleep_between_tries
        original_urlopen = Entrez.urlopen
        try:
            result = launcher._probe_transient_503(Entrez)
            self.assertEqual(result["underlying_attempts"], 1)
            self.assertFalse(result["external_traffic"])
            self.assertTrue(result["restored"])
            self.assertIs(Entrez.urlopen, original_urlopen)
            self.assertEqual(Entrez.max_tries, 1)
            self.assertEqual(Entrez.sleep_between_tries, 0)
        finally:
            Entrez.max_tries = original_max_tries
            Entrez.sleep_between_tries = original_sleep


if __name__ == "__main__":
    unittest.main()
