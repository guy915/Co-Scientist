import json
import re
from pathlib import Path
from typing import Any

_CACHE_COMPONENT = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PUBMED_ID = re.compile(r"^[0-9]{1,16}$")
_CACHE_FILENAME = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


def validate_cache_identifier(value: str, *, label: str, numeric: bool = False) -> str:
    pattern = _PUBMED_ID if numeric else _CACHE_COMPONENT
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def confined_path(root: Path, *parts: str) -> Path:
    base = root.resolve()
    candidate = base.joinpath(*parts)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("literature cache path escapes its root") from exc
    return candidate


def write_metadata_cache_file(metadata_file: Path, metadata: dict[str, Any]) -> None:
    if metadata_file.is_symlink():
        raise ValueError("metadata cache file must not be a symlink")
    with open(metadata_file, "w", encoding="utf-8") as stream:
        json.dump(metadata, stream)


def link_shared_file_to_run(run_dir: Path, filename: str) -> None:
    if not _CACHE_FILENAME.fullmatch(filename) or filename in {".", ".."}:
        raise ValueError("invalid literature cache filename")
    root = run_dir.parents[2]
    slug = run_dir.parent.parent.name
    validate_cache_identifier(slug, label="slug")
    symlink = confined_path(root, run_dir.parent.parent.name, "runs", run_dir.name, filename)
    confined_path(root, slug, "shared", filename)
    if symlink.is_symlink():
        confined_path(root, run_dir.parent.parent.name, "runs", run_dir.name, filename)
        return
    if not symlink.exists():
        # Relative links keep the whole slug literature tree portable when
        # moved.
        symlink.symlink_to(f"../../shared/{filename}")


def link_metadata_to_run(run_dir: Path | None, paper_id: str) -> None:
    validate_cache_identifier(paper_id, label="PubMed ID", numeric=True)
    if not run_dir:
        return
    link_shared_file_to_run(run_dir, f"{paper_id}.metadata.json")
