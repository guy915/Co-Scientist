"""Locates the Google artifacts published alongside the papers.

The papers and the Nature supplement print more than prose: complete worked
outputs (paper §A.3, §A.5.3) and the agents' pseudo-code (SI Note 8). Both
are extracted verbatim under ``references/core/``, which makes them a
primary requirement source the tests can read, rather than one paraphrased
through the local consolidation the fidelity audit found to be part
clone-invented.

That corpus lives outside ``engine/``, which is independently installable.
An engine extracted on its own has no ``references/`` tree at all and skips;
a ``references/`` tree that exists but has lost one of these files is a move
or a deletion, and fails.

The engine's two published-value pin modules -- ``pseudocode_invariants``
and ``artifact_shapes`` -- carry their pinned values inline as cited module
constants and no longer import this module at all, so they cannot skip.
Only their ``_corroboration`` siblings do: they re-read the corpus through
the functions here and check the inlined constants still match what is on
disk, which is exactly the check this module's skip-or-fail split exists
for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REFERENCES = Path(__file__).resolve().parents[2] / "references"
_ARTIFACTS = (
    _REFERENCES / "core/google-co-scientist/research/extracted-artifacts"
)


def corpus_available() -> bool:
    """True when the reference corpus is checked out beside the engine.

    Callers that read the corpus at *collection* time need this: a
    ``pytest.skip`` raised while a parametrization is being built is a
    collection error, not a skip, so the engine-alone checkout this
    module exists to tolerate would go red instead of quiet.

    Returns:
        Whether the ``references/`` tree is present.
    """
    return _REFERENCES.is_dir()


def _require(path: Path) -> Path:
    """Return a published artifact, skipping only outside the repo.

    Args:
        path: The artifact's absolute path.

    Returns:
        The same path, once it is known to exist.
    """
    if not _REFERENCES.is_dir():
        pytest.skip("engine checked out without the reference corpus")
    assert path.is_file(), f"published artifact moved or deleted: {path}"
    return path


def published_output(relative: str) -> Path:
    """Return one of the outputs the papers print in full.

    Args:
        relative: Path under the extracted ``outputs/`` directory.

    Returns:
        The exemplar's path.
    """
    return _require(_ARTIFACTS / "outputs" / relative)


def published_pseudocode(name: str) -> str:
    """Return one agent's pseudo-code from Nature SI Note 8.

    Args:
        name: The file's stem, e.g. ``04-ranking``.

    Returns:
        The file's text, header comment included.
    """
    path = _require(_ARTIFACTS / "pseudocode" / f"{name}.md")
    return path.read_text(encoding="utf-8")


def published_prompt(name: str) -> str:
    """Return one of the eight prompts the papers publish in full.

    Args:
        name: The file's stem, e.g. ``ranking-04-pairwise-comparison``.

    Returns:
        The file's text, header comment included.
    """
    path = _require(_ARTIFACTS / "prompts" / f"{name}.md")
    return path.read_text(encoding="utf-8")
