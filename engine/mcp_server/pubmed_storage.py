import hashlib
import json
from pathlib import Path
from typing import Any


def metadata_no_link_sidecar(metadata_file: Path) -> Path:
    return metadata_file.with_name(f".{metadata_file.stem}.no-link.sha256")


def has_proven_metadata_no_link(metadata_file: Path) -> bool:
    """The empty-link proof is valid only for the current metadata bytes."""
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
    sidecar = metadata_no_link_sidecar(metadata_file)
    # Failed legacy lookups can rewrite identical JSON. Expire the old proof.
    sidecar.unlink(missing_ok=True)
    with open(metadata_file, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream)
    if successful_no_link:
        digest = hashlib.sha256(metadata_file.read_bytes()).hexdigest()
        sidecar.write_text(digest, encoding="ascii")


def link_shared_file_to_run(run_dir: Path, filename: str) -> None:
    symlink = run_dir / filename
    if not symlink.exists():
        # Relative links keep the whole slug literature tree portable when
        # moved.
        symlink.symlink_to(f"../../shared/{filename}")


def link_metadata_to_run(run_dir: Path | None, paper_id: str) -> None:
    if not run_dir:
        return
    link_shared_file_to_run(run_dir, f"{paper_id}.metadata.json")
