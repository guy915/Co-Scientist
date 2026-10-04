import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
# Lower the production ceiling after reductions; never raise it.
CODE_SIZE_CEILING = 137_847
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


def _line_counts(repo: Path) -> dict[str, int]:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo)
    totals = dict.fromkeys(("production", "test", "doc"), 0)
    for name in tracked.decode().split("\0"):
        path = Path(name)
        if (
            not name
            or {"vendor", "references"}.intersection(path.parts)
            or (repo / path).is_symlink()
        ):
            continue
        if path.suffix in SOURCE_SUFFIXES:
            category = "production" if _is_production_source(path) else "test"
        elif path.suffix == ".md" and not path.is_relative_to(
            "engine/src/co_scientist/prompts/templates"
        ):
            category = "doc"
        else:
            continue
        with (repo / path).open("rb") as source:
            totals[category] += sum(1 for _ in source)
    return totals


def test_code_size_ratchet() -> None:
    totals = _line_counts(REPO_ROOT)
    print("; ".join(f"{key}: {value:,} lines" for key, value in totals.items()))
    count = totals["production"]
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
    assert _line_counts(tmp_path) == {"production": 8, "test": 1, "doc": 0}


def test_doc_counts_exclude_runtime_templates_vendor_and_symlinks(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name in (
        "README.md",
        "engine/src/co_scientist/tools/README.md",
        "engine/src/co_scientist/prompts/templates/review.md",
        "vendor/README.md",
        "references/README.md",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("first\nsecond", encoding="utf-8")
    (tmp_path / "CLAUDE.md").symlink_to("README.md")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    assert _line_counts(tmp_path) == {"production": 0, "test": 0, "doc": 4}
