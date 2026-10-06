import json
from pathlib import Path
from typing import Any


def write_metadata_cache_file(metadata_file: Path, metadata: dict[str, Any]) -> None:
    with open(metadata_file, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream)


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
