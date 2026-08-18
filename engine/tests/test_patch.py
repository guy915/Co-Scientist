"""Tests for context-anchored patch parsing and application.

Three properties carry the weight, and each has a test that fails
against a plausible wrong implementation:

* a stale patch must fail rather than apply somewhere else,
* a failing patch must leave the tree untouched,
* repeated identical blocks must resolve in order, not by "best match".
"""

from pathlib import Path

import pytest

from co_scientist.patch import (
    Patch,
    PatchError,
    UpdateFile,
    apply_patch,
    parse_patch,
    seek_anchor,
)


def _envelope(*body: str) -> str:
    """Wraps operation lines in the patch envelope."""
    return "\n".join(["*** Begin Patch", *body, "*** End Patch"])


def _apply(text: str, root: Path) -> Patch:
    """Parses and applies a patch, returning the parsed form."""
    patch = parse_patch(text)
    apply_patch(patch, root)
    return patch


# --- parsing --------------------------------------------------------------


def test_envelope_markers_are_required() -> None:
    with pytest.raises(PatchError, match="must start with"):
        parse_patch("*** Update File: a.py\n+x\n*** End Patch")
    with pytest.raises(PatchError, match="must end with"):
        parse_patch("*** Begin Patch\n*** Update File: a.py\n")


def test_an_empty_patch_is_rejected() -> None:
    with pytest.raises(PatchError, match="no file operations"):
        parse_patch(_envelope())


def test_an_unrecognized_hunk_line_is_rejected() -> None:
    with pytest.raises(PatchError, match="unrecognized line"):
        parse_patch(_envelope("*** Update File: a.py", "@@", "?bad marker"))


def test_a_blank_line_in_a_hunk_reads_as_blank_context() -> None:
    """A blank context line is ' ', which gets whitespace-stripped en route."""
    patch = parse_patch(
        _envelope("*** Update File: a.py", "@@", " keep", "", "-drop")
    )
    update = patch.operations[0]
    assert isinstance(update, UpdateFile)
    assert update.hunks[0].anchor == ("keep", "", "drop")


def test_multiple_files_parse_into_one_envelope() -> None:
    patch = parse_patch(
        _envelope(
            "*** Add File: new.py",
            "+print(1)",
            "*** Delete File: gone.py",
            "*** Update File: kept.py",
            "@@",
            " context",
            "-old",
            "+new",
        )
    )
    assert patch.paths == ("new.py", "gone.py", "kept.py")


# --- seeking --------------------------------------------------------------


def test_repeated_blocks_resolve_in_order_not_by_best_match() -> None:
    """The monotonic cursor.

    A scoring matcher would return the same "best" occurrence twice.
    """
    lines = ["x", "dup", "y", "dup", "z"]
    first = seek_anchor(lines, ("dup",), 0)
    assert first is not None and first.start == 1
    second = seek_anchor(lines, ("dup",), first.end)
    assert second is not None and second.start == 3


def test_the_ladder_prefers_an_exact_match_anywhere() -> None:
    """Rung-major search: an exact match later beats a fuzzy one earlier."""
    lines = ["value ", "value"]
    found = seek_anchor(lines, ("value",), 0)
    assert found is not None
    assert found.start == 1
    assert found.rung == "exact"


def test_trailing_whitespace_differences_still_match() -> None:
    found = seek_anchor(["  code  "], ("  code",), 0)
    assert found is not None
    assert found.rung == "trailing-whitespace"


def test_smart_quotes_still_match() -> None:
    """A quote that changed shape in transit must not fail an edit."""
    found = seek_anchor(['x = "a"'], ("x = “a”",), 0)
    assert found is not None
    assert found.rung == "unicode-punctuation"


def test_a_missing_anchor_returns_nothing() -> None:
    assert seek_anchor(["a", "b"], ("absent",), 0) is None


# --- applying -------------------------------------------------------------


def test_update_replaces_the_anchored_lines(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("before\nold\nafter\n")

    _apply(
        _envelope(
            "*** Update File: a.py",
            "@@",
            " before",
            "-old",
            "+new",
            " after",
        ),
        tmp_path,
    )

    assert target.read_text() == "before\nnew\nafter\n"


def test_add_creates_a_file(tmp_path: Path) -> None:
    _apply(
        _envelope("*** Add File: sub/new.py", "+print(1)"),
        tmp_path,
    )
    assert (tmp_path / "sub" / "new.py").read_text() == "print(1)\n"


def test_add_refuses_to_clobber(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("existing\n")
    with pytest.raises(PatchError, match="already exists"):
        _apply(_envelope("*** Add File: a.py", "+new"), tmp_path)
    assert (tmp_path / "a.py").read_text() == "existing\n"


def test_delete_removes_a_file(tmp_path: Path) -> None:
    (tmp_path / "gone.py").write_text("x\n")
    _apply(_envelope("*** Delete File: gone.py"), tmp_path)
    assert not (tmp_path / "gone.py").exists()


def test_move_renames_and_edits(tmp_path: Path) -> None:
    (tmp_path / "old.py").write_text("keep\nold\n")
    _apply(
        _envelope(
            "*** Update File: old.py",
            "*** Move to: new.py",
            "@@",
            " keep",
            "-old",
            "+new",
        ),
        tmp_path,
    )
    assert not (tmp_path / "old.py").exists()
    assert (tmp_path / "new.py").read_text() == "keep\nnew\n"


def test_a_stale_context_fails_rather_than_applying_elsewhere(
    tmp_path: Path,
) -> None:
    """The central property.

    A line-addressed editor would happily write at the numbered line,
    which now holds something else.
    """
    target = tmp_path / "a.py"
    target.write_text("completely\ndifferent\ncontent\n")

    with pytest.raises(PatchError, match="did not match"):
        _apply(
            _envelope(
                "*** Update File: a.py", "@@", " expected", "-old", "+new"
            ),
            tmp_path,
        )
    assert target.read_text() == "completely\ndifferent\ncontent\n"


def test_a_failing_patch_leaves_every_file_untouched(
    tmp_path: Path,
) -> None:
    """All-or-nothing across files.

    The first operation is valid; the second is not. Without the
    plan-then-commit split, the first would already be on disk and the
    tree would be in a state nobody asked for.
    """
    good = tmp_path / "good.py"
    good.write_text("old\n")

    with pytest.raises(PatchError, match="does not exist"):
        _apply(
            _envelope(
                "*** Update File: good.py",
                "@@",
                "-old",
                "+new",
                "*** Update File: missing.py",
                "@@",
                "-a",
                "+b",
            ),
            tmp_path,
        )

    assert good.read_text() == "old\n"


def test_hunks_apply_in_order_within_one_file(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("dup\nmiddle\ndup\n")

    _apply(
        _envelope(
            "*** Update File: a.py",
            "@@",
            "-dup",
            "+first",
            "@@",
            "-dup",
            "+second",
        ),
        tmp_path,
    )

    assert target.read_text() == "first\nmiddle\nsecond\n"


# --- containment ----------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["../escape.py", "sub/../../escape.py", "/etc/passwd"]
)
def test_paths_outside_the_root_are_refused(tmp_path: Path, path: str) -> None:
    with pytest.raises(PatchError, match=r"relative|outside"):
        _apply(_envelope(f"*** Add File: {path}", "+x"), tmp_path)


def test_a_symlinked_escape_is_refused(tmp_path: Path) -> None:
    """Containment is checked after resolution, so a link cannot step out."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside)

    with pytest.raises(PatchError, match="outside"):
        _apply(_envelope("*** Add File: link/escape.py", "+x"), root)
