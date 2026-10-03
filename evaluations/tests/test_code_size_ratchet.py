"""Ratchets git-tracked first-party production source lines downward."""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Starting count at be6105ab. Lower with each reduction; never raise.
CODE_SIZE_CEILING = 161_285
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".css"}
EXCLUDED_DIRECTORIES = {
    "vendor",
    "references",
    "tests",
    "test",
    "e2e",
    "__tests__",
}


def _is_production_source(path: Path) -> bool:
    return (
        path.suffix in SOURCE_SUFFIXES
        and not EXCLUDED_DIRECTORIES.intersection(path.parts)
        and ".test." not in path.name
        and ".spec." not in path.name
        and not (path.suffix == ".py" and path.name.startswith("test_"))
    )


def _production_line_count(repo: Path) -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo)
    total = 0
    for name in tracked.decode().split("\0"):
        path = Path(name)
        if name and _is_production_source(path):
            with (repo / path).open("rb") as source:
                total += sum(1 for _ in source)
    return total


def test_code_size_ratchet() -> None:
    count = _production_line_count(REPO_ROOT)
    assert count <= CODE_SIZE_CEILING, (
        f"Production code size: {count:,} lines; "
        f"ceiling: {CODE_SIZE_CEILING:,}. Remove code and lower the ceiling "
        "in the same PR; never raise it or compress code to meet it."
    )


@pytest.mark.parametrize(
    "name",
    [
        "vendor/library.py",
        "references/example.ts",
        "app/tests/helper.py",
        "engine/test/helper.py",
        "e2e/support/client.ts",
        "app/frontend/__tests__/helper.tsx",
        "app/frontend/widget.test.tsx",
        "engine/example.spec.py",
        "app/test_helpers.py",
        "README.md",
    ],
)
def test_excluded_sources(name: str) -> None:
    assert not _is_production_source(Path(name))


def test_counts_only_tracked_sources_and_unterminated_lines(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name in ("backend.py", "client.ts", "widget.tsx", "theme.css"):
        (tmp_path / name).write_text("first\nsecond", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "test_kept.py").write_text("ignored\n", encoding="utf-8")
    subprocess.run(
        [
            "git",
            "add",
            "backend.py",
            "client.ts",
            "widget.tsx",
            "theme.css",
            "test_kept.py",
        ],
        cwd=tmp_path,
        check=True,
    )
    assert _production_line_count(tmp_path) == 8
