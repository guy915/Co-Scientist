"""Filesystem ownership and portable PubMed cache contracts."""

import subprocess
import sys
from pathlib import Path

from mcp_server.pubmed_storage import (
    has_proven_metadata_no_link,
    link_metadata_to_run,
    write_metadata_cache_file,
)


def test_storage_import_does_not_initialize_entrez() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules["Bio"] = None
import mcp_server.pubmed_storage
assert "mcp_server.entrez" not in sys.modules
assert "mcp_server.pubmed_client" not in sys.modules
assert "mcp_server.literature_review" not in sys.modules
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_metadata_and_empty_link_proof_survive_cache_relocation(
    tmp_path: Path,
) -> None:
    tree = tmp_path / "original"
    shared_dir = tree / "slug" / "shared"
    shared_dir.mkdir(parents=True)
    run_dir = tree / "slug" / "runs" / "run-id"
    run_dir.mkdir(parents=True)
    metadata_file = shared_dir / "101.metadata.json"
    metadata = {"title": "Paper \u03b2", "pmc_full_text_id": None}

    write_metadata_cache_file(metadata_file, metadata, successful_no_link=True)
    link_metadata_to_run(run_dir, "101")
    link_metadata_to_run(run_dir, "101")
    link_metadata_to_run(None, "101")
    assert metadata_file.read_text() == (
        '{"title": "Paper \\u03b2", "pmc_full_text_id": null}'
    )
    assert (run_dir / metadata_file.name).readlink() == Path(
        "../../shared/101.metadata.json"
    )

    relocated = tmp_path / "relocated"
    tree.rename(relocated)
    relocated_metadata = relocated / "slug" / "shared" / metadata_file.name
    run_link = relocated / "slug" / "runs" / "run-id" / metadata_file.name
    assert run_link.read_bytes() == relocated_metadata.read_bytes()
    assert has_proven_metadata_no_link(relocated_metadata)
    relocated_metadata.write_text('{"title": "changed"}')
    assert not has_proven_metadata_no_link(relocated_metadata)
