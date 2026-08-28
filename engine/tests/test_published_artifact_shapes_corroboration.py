"""Corroborates the transcription pinned in the sibling shapes module.

``test_published_artifact_shapes.py`` checks our schemas and prompts
against literals transcribed from Google's published exemplars and cited
there to the extracted file they came from. This module re-reads those
same exemplars and asserts the transcription still matches what is on disk.

Every test here goes through ``tests._published_corpus``, which skips
outright when ``references/`` is absent and fails when only one file
under it has moved or been deleted. Losing this module on ``references/``
deletion is expected and safe: the values it exists to corroborate are
already guarded, without disk access, by the sibling pin module.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._published_corpus import published_output
from tests.test_published_artifact_shapes import (
    _AIMS_EXEMPLARS,
    _AIMS_PAGE_BLOCKS,
    _AIMS_PAPER_APPARATUS,
    _AIMS_PER_AIM_BLOCKS,
    _DEBATE_EXEMPLAR_TURN_COUNT,
    _DEBATE_EXEMPLAR_VERDICT,
    _OVERVIEW_EXEMPLAR_QUESTION_HEADINGS,
    _PROBE_EXEMPLAR_LABELS,
)


def _heading_labels(path: Path, level: int) -> set[str]:
    """Return an exemplar's headings at one level, normalized for matching.

    Args:
        path: The exemplar to read.
        level: Heading depth, as a count of leading ``#``.

    Returns:
        Lowercased heading text with any trailing colon removed.
    """
    pattern = re.compile(rf"^#{{{level}}} +(.+?)\s*$", re.MULTILINE)
    return {
        match.rstrip(":").strip().lower()
        for match in pattern.findall(path.read_text(encoding="utf-8"))
    }


@pytest.mark.parametrize("exemplar", _AIMS_EXEMPLARS)
def test_specific_aims_schema_matches_published_exemplars(
    exemplar: str,
) -> None:
    """Each exemplar's own headings still match the pinned vocabulary."""
    labels = _heading_labels(published_output(exemplar), 4)
    labels -= _AIMS_PAPER_APPARATUS
    assert labels == set(_AIMS_PAGE_BLOCKS) | set(_AIMS_PER_AIM_BLOCKS)


def test_probe_exemplar_still_prints_the_pinned_labels() -> None:
    """The Reparixin probe exemplar still labels question/answer/reasoning."""
    exemplar = published_output(
        "reviews/reparixin-deep-verification-probing.md"
    )
    text = exemplar.read_text(encoding="utf-8")
    labels = [
        label.lower()
        for label in re.findall(r"^(Question|Answer|Reasoning):", text, re.M)
    ]
    assert labels == list(_PROBE_EXEMPLAR_LABELS)


def test_debate_exemplar_still_matches_the_pinned_shape() -> None:
    """The ALS debate exemplar still has the pinned turn count and verdict."""
    exemplar = published_output("ranking-tournament/als-tournament-debate.md")
    text = exemplar.read_text(encoding="utf-8")
    turns = re.findall(r"^Expert \d+:", text, re.MULTILINE)
    assert len(turns) == _DEBATE_EXEMPLAR_TURN_COUNT

    verdict = re.search(r"^Better idea: *\d+\s*$", text, re.MULTILINE)
    assert verdict is not None
    assert verdict.group(0).strip() == _DEBATE_EXEMPLAR_VERDICT


def test_overview_exemplar_still_prints_the_pinned_headings() -> None:
    """The cf-PICI overview exemplar still asks the pinned two questions."""
    exemplar = published_output(
        "research-overviews/cf-pici-research-overview.md"
    )
    questions = _heading_labels(exemplar, 4)
    assert questions == _OVERVIEW_EXEMPLAR_QUESTION_HEADINGS
