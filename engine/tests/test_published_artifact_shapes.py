"""Pins our output shapes against the artifacts Google actually published.

Every other parity test reads a *description* of Google's behavior -- the
paper's prose, or the local consolidation under ``references/core/``, which
the fidelity audit found to be part clone-invented. The artifacts cited
below are different: the papers print complete worked examples of them, so
the required shape can be read off the exemplar instead of paraphrased.

Each exemplar's shape-defining vocabulary is transcribed once, below, as a
cited module-level constant, and every test in this module checks our
schemas and prompts against those constants directly -- so none of it
touches disk and none of it can skip. That is the half of the pin that must
keep guarding once ``references/`` is gone.
``test_published_artifact_shapes_corroboration.py`` re-reads the same
exemplars and asserts the transcription still matches; that module is the
one allowed to skip when the corpus is absent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import co_scientist
from co_scientist.schemas import get_schema_for_prompt

# references/core/google-co-scientist/research/extracted-artifacts/outputs/
# specific-aims/givosiran-aml.md -- 74 lines, sha256 e37cd65c356d.
# specific-aims/lapatinib-colon-cancer.md -- 118 lines, sha256 ba876c0d0bae.
# specific-aims/selinexor-colon-cancer.md -- 97 lines, sha256 fdddea2c0d52.
# All three render one NIH Specific Aims page: a three-block preamble, the
# numbered aims, and a closing pilot study. Values are the schema keys that
# must carry each block.
_AIMS_EXEMPLARS = (
    "specific-aims/givosiran-aml.md",
    "specific-aims/lapatinib-colon-cancer.md",
    "specific-aims/selinexor-colon-cancer.md",
)
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

# outputs/reviews/reparixin-deep-verification-probing.md -- 41 lines,
# sha256 e133f842f15a. Figure A.15 labels its probe with exactly this
# triple, in this order; the schema's remaining probe keys are routing
# metadata that never reaches a reader.
_PROBE_EXEMPLAR_LABELS = ("question", "answer", "reasoning")

# outputs/ranking-tournament/als-tournament-debate.md -- 22 lines,
# sha256 29679d639c25. Figure A.17: a five-turn exchange between named
# experts that closes with a single verdict line.
_DEBATE_EXEMPLAR_TURN_COUNT = 5
_DEBATE_EXEMPLAR_VERDICT = "Better idea: 1"

# outputs/research-overviews/cf-pici-research-overview.md -- 91 lines,
# sha256 748950658a5d. Direction #1's two per-direction question headings.
_OVERVIEW_EXEMPLAR_QUESTION_HEADINGS = {
    "● why research this area?",
    "● what to research in this area?",
}

# The same exemplar's "What to Research in This Area?" answer is itself a
# list of named sub-topics ("Topic 1: Characterization of the cf-PICI
# Integrase" through "Topic 4: Episomal Maintenance", consistently 4 per
# direction across all 6 directions), each carrying its own "Why research
# this topic?", an "Example idea" (what to investigate), and a "Specific
# questions" list of 4 -- MO-1, the nested sub-topic layer our schema
# used to flatten away entirely.
_OVERVIEW_SUB_TOPIC_REQUIRED = {"title", "why", "what", "specific_questions"}

_OVERVIEW_DIRECTION_REQUIRED = {
    "title",
    "importance",
    "suggested_experiments",
    "sub_topics",
}


def _aims_schema() -> dict[str, Any]:
    """Return the research-overview schema's ``nih_specific_aims`` node."""
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    body = schema.get("schema", schema)
    assert "nih_specific_aims" in body["required"]
    aims: dict[str, Any] = body["properties"]["nih_specific_aims"]
    return aims


def test_specific_aims_schema_carries_published_heading_vocabulary() -> None:
    """Our aims page must carry every block the published exemplars print.

    All three exemplars share one heading vocabulary (cited above), so it
    is checked once rather than once per exemplar; the corroboration
    module still re-derives each exemplar's own labels from disk and
    checks all three separately.
    """
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

    Figure A.15 (cited above) labels its probe with exactly those three,
    in that order; the schema's remaining probe keys are routing metadata
    that never reaches a reader.
    """
    schema = get_schema_for_prompt("deep_verification")
    assert schema is not None
    probe = schema["schema"]["properties"]["probes"]["items"]
    assert set(probe["required"]) >= set(_PROBE_EXEMPLAR_LABELS)


def test_ranking_debate_verdict_matches_published_exemplar() -> None:
    """The tournament judge must end on the exemplar's verdict line.

    Figure A.17 (cited above) is a multi-turn exchange between named
    experts that closes with a single ``Better idea: <n>`` line -- the
    token the parser reads back as the match result.
    """
    template = (
        Path(co_scientist.__file__).parent / "prompts/templates/ranking.md"
    ).read_text(encoding="utf-8")
    assert "better idea:" in template.lower()

    schema = get_schema_for_prompt("ranking")
    assert schema is not None
    assert "decision_summary" in schema["schema"]["properties"]


def test_research_overview_sections_match_published_exemplar() -> None:
    """Each research direction must argue why it matters and what to do.

    The overview exemplar (cited above) develops every direction under
    two questions, which are the two per-direction fields the schema
    requires beside the direction's title -- plus, since MO-1, the
    nested sub_topics layer both exemplars carry under their own
    vocabulary for "what to research".
    """
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    overview = schema["schema"]["properties"]["overview"]
    assert set(overview["required"]) == {"summary", "research_directions"}
    direction = overview["properties"]["research_directions"]["items"]
    assert set(direction["required"]) == _OVERVIEW_DIRECTION_REQUIRED


def test_research_direction_sub_topics_match_published_exemplar() -> None:
    """Each sub-topic must carry the exemplars' why/what/specific-questions.

    Both exemplars nest a named sub-topic one level below the direction
    (MO-1); this checks the sub-topic item's own required shape.
    """
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    overview = schema["schema"]["properties"]["overview"]
    direction = overview["properties"]["research_directions"]["items"]
    sub_topic = direction["properties"]["sub_topics"]["items"]
    assert set(sub_topic["required"]) == _OVERVIEW_SUB_TOPIC_REQUIRED
