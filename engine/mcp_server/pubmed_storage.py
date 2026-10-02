"""PubMed cache persistence and portable links into per-run directories.

Both metadata retrieval paths and PMC downloads use this filesystem layer.
It depends only on the standard library, without fetching or parsing papers.
"""

import hashlib
import json
from pathlib import Path
from typing import Any


def metadata_no_link_sidecar(metadata_file: Path) -> Path:
    """Return the digest sidecar proving a successful empty PMC lookup."""
    return metadata_file.with_name(f".{metadata_file.stem}.no-link.sha256")


def has_proven_metadata_no_link(metadata_file: Path) -> bool:
    """Check that the empty-link proof matches the current metadata bytes."""
    try:
        expected = metadata_no_link_sidecar(metadata_file).read_text(
            encoding="ascii"
        )
        actual = hashlib.sha256(metadata_file.read_bytes()).hexdigest()
    except (OSError, UnicodeError):
        return False
    return expected == actual


def write_metadata_cache_file(
    metadata_file: Path,
    metadata: dict[str, Any],
    *,
    successful_no_link: bool = False,
) -> None:
    """Write metadata and retain empty-link proof only for successful calls."""
    sidecar = metadata_no_link_sidecar(metadata_file)
    # Failed legacy lookups can rewrite identical JSON. Expire the old proof.
    sidecar.unlink(missing_ok=True)
    with open(metadata_file, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream)
    if successful_no_link:
        digest = hashlib.sha256(metadata_file.read_bytes()).hexdigest()
        sidecar.write_text(digest, encoding="ascii")


def link_shared_file_to_run(run_dir: Path, filename: str) -> None:
    """Link a shared-pool file into a per-run directory idempotently.

    Args:
        run_dir: Per-run directory that should hold the symlink.
        filename: Basename of the file under ``<slug>/shared/`` to link to.
    """
    symlink = run_dir / filename
    if not symlink.exists():
        # Relative symlink: run_dir is <slug>/runs/<run_id>/, so two levels
        # up reaches <slug>/, from which "shared/<filename>" resolves. Kept
        # relative so the whole <slug> tree stays portable if moved/copied.
        symlink.symlink_to(f"../../shared/{filename}")


def link_metadata_to_run(run_dir: Path | None, paper_id: str) -> None:
    """Link shared metadata into a run, skipping searches without run IDs."""
    # No-op without a run_id: metadata still lands in the shared pool, it
    # just is not exposed under a per-run directory.
    if not run_dir:
        return
    link_shared_file_to_run(run_dir, f"{paper_id}.metadata.json")
