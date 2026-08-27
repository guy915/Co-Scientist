"""Pins our output shapes against the artifacts Google actually published.

Every other parity test reads a *description* of Google's behavior -- the
paper's prose, or the local consolidation under ``references/core/``, which
the fidelity audit found to be part clone-invented. The four artifacts here
are different: the papers print complete worked examples of them, so the
required shape can be read off the exemplar instead of paraphrased. These
tests derive the field vocabulary from those files and assert our schemas
and prompts carry it, so renaming a schema key fails against the exemplar
that names it.

``tests._published_corpus`` locates them, and says what happens when the
corpus is absent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

import co_scientist
from co_scientist.schemas import get_schema_for_prompt
from tests._published_corpus import published_output

# The NIH Specific Aims page, as all three published exemplars render it:
# a three-block preamble, the numbered aims, and a closing pilot study.
# Values are the schema keys that must carry each block.
_AIMS_PAGE_BLOCKS = {
    "disease description": "disease_description",
    "unmet need": "unmet_need",
    "proposed solution": "proposed_solution",
    "pilot evaluation": "pilot_evaluation",
}
_AIMS_PER_AIM_BLOCKS = {
    "overarching goal": "overarching_goal",
    "hypothesis": "hypothesis",
    "reasoning": "reasoning",
}
# Two exemplars append the paper's own apparatus after the artifact ends.
# Neither is part of what the Meta-review agent produced.
_AIMS_PAPER_APPARATUS = {"articles", "expert rating"}


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


def _aims_schema() -> dict[str, Any]:
    """Return the ``nih_specific_aims`` node of the research-overview schema."""
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    body = schema.get("schema", schema)
    assert "nih_specific_aims" in body["required"]
    aims: dict[str, Any] = body["properties"]["nih_specific_aims"]
    return aims


@pytest.mark.parametrize(
    "exemplar",
    [
        "specific-aims/givosiran-aml.md",
        "specific-aims/lapatinib-colon-cancer.md",
        "specific-aims/selinexor-colon-cancer.md",
    ],
)
def test_specific_aims_schema_matches_published_exemplars(
    exemplar: str,
) -> None:
    """Our aims page must carry every block the exemplars print.

    All three exemplars share one heading vocabulary, so the schema is
    checked against each of them rather than against a single sample.
    """
    labels = _heading_labels(published_output(exemplar), 4)
    labels -= _AIMS_PAPER_APPARATUS
    assert labels == set(_AIMS_PAGE_BLOCKS) | set(_AIMS_PER_AIM_BLOCKS)

    aims = _aims_schema()
    properties = aims["properties"]
    required = set(aims["required"])
    assert isinstance(properties, dict)
    for label, key in _AIMS_PAGE_BLOCKS.items():
        assert key in required, f"exemplar block '{label}' has no schema key"
    # The aims themselves are the one block the exemplars repeat, so they
    # are an array rather than a fourth prose field.
    assert "aims" in required
    aim_item = properties["aims"]["items"]
    assert set(aim_item["required"]) == set(_AIMS_PER_AIM_BLOCKS.values())


def test_specific_aims_schema_adds_nothing_the_exemplars_lack() -> None:
    """The page must not grow sections Google's exemplars do not have.

    An addition here reads as a richer grant page and is a fidelity
    violation: the previous shape carried an ``introduction`` and an
    ``impact`` statement that no published exemplar prints, in place of
    the three-block preamble that all three do.
    """
    required = set(_aims_schema()["required"])
    assert required == set(_AIMS_PAGE_BLOCKS.values()) | {"aims"}


def test_deep_verification_probe_matches_published_exemplar() -> None:
    """A probe must carry the exemplar's question/answer/reasoning triple.

    Figure A.15 labels its probe with exactly those three, in that order;
    the schema's remaining probe keys are routing metadata that never
    reaches a reader.
    """
    exemplar = published_output(
        "reviews/reparixin-deep-verification-probing.md"
    )
    text = exemplar.read_text(encoding="utf-8")
    labels = [
        label.lower()
        for label in re.findall(r"^(Question|Answer|Reasoning):", text, re.M)
    ]
    assert labels == ["question", "answer", "reasoning"]

    schema = get_schema_for_prompt("deep_verification")
    assert schema is not None
    probe = schema["schema"]["properties"]["probes"]["items"]
    assert set(probe["required"]) >= set(labels)


def test_ranking_debate_verdict_matches_published_exemplar() -> None:
    """The tournament judge must end on the exemplar's verdict line.

    Figure A.17 is a multi-turn exchange between named experts that closes
    with a single ``Better idea: <n>`` line -- the token the parser reads
    back as the match result.
    """
    exemplar = published_output("ranking-tournament/als-tournament-debate.md")
    text = exemplar.read_text(encoding="utf-8")
    turns = re.findall(r"^Expert \d+:", text, re.MULTILINE)
    assert len(turns) > 2, "exemplar is a multi-turn debate"
    verdict = re.search(r"^Better idea: *\d+\s*$", text, re.MULTILINE)
    assert verdict is not None

    template = (
        Path(co_scientist.__file__).parent / "prompts/templates/ranking.md"
    ).read_text(encoding="utf-8")
    assert "better idea:" in template.lower()

    schema = get_schema_for_prompt("ranking")
    assert schema is not None
    assert "decision_summary" in schema["schema"]["properties"]


def test_research_overview_sections_match_published_exemplar() -> None:
    """Each research direction must argue why it matters and what to do.

    The overview exemplar develops every direction under two questions,
    which are the two per-direction fields the schema requires beside the
    direction's title.
    """
    exemplar = published_output(
        "research-overviews/cf-pici-research-overview.md"
    )
    questions = _heading_labels(exemplar, 4)
    assert questions == {
        "● why research this area?",
        "● what to research in this area?",
    }

    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    overview = schema["schema"]["properties"]["overview"]
    assert set(overview["required"]) == {"summary", "research_directions"}
    direction = overview["properties"]["research_directions"]["items"]
    assert set(direction["required"]) == {
        "title",
        "importance",
        "suggested_experiments",
    }
