"""Pins our output shapes against the artifacts Google actually published.

Every other parity test reads a *description* of Google's behavior -- the
paper's prose, or the local consolidation the fidelity audit found to be
part clone-invented. The artifacts cited below are different: the papers
print complete worked examples of them, reproduced in
``docs/CORPUS-EXTRACTION.md`` Appendix C, so
the required shape can be read off the exemplar instead of paraphrased.

Each exemplar's shape-defining vocabulary is transcribed once, below, as a
cited module-level constant, and every test in this module checks our
schemas and prompts against those constants directly -- so none of it
touches disk and none of it can skip. That is the pin that kept guarding
once ``references/`` was removed. Its ``_corroboration`` sibling, which
re-read the raw exemplar files, was removed with that tree; the values
transcribed here are cited to their reproduction in
``docs/CORPUS-EXTRACTION.md`` (Appendix C).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import co_scientist
from co_scientist.agents.ranking.ranking_debate_turns import (
    debate_transcript_document,
)
from co_scientist.schemas import get_schema_for_prompt
from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_TARGET_DIRECTIONS

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
# this topic?", an "Example idea" (a worked illustration of how the topic
# would actually be attacked), and a "Specific questions" list of 4 --
# MO-1, the nested sub-topic layer our schema used to flatten away
# entirely. F7 adds ``example_idea``: the exemplar's own third block,
# which ``what`` (the topic statement) does not stand in for.
_OVERVIEW_SUB_TOPIC_REQUIRED = {
    "title",
    "why",
    "what",
    "example_idea",
    "specific_questions",
}

# The same exemplar enumerates SIX main research directions. We ask for
# fewer (see RESEARCH_OVERVIEW_TARGET_DIRECTIONS) because this node's
# budget is measured, not aspirational, but the exemplar's own count is
# what bounds the array.
_OVERVIEW_EXEMPLAR_DIRECTION_COUNT = 6

# outputs/research-overviews/als-research-overview-and-contact.md -- 84
# lines, sha256 6d2997eaeec0. Each direction opens with "Rationale:" /
# "Recent Findings:" before its own "Areas of Research:" sub-topic list
# (the same nesting as cf-PICI, under ALS's own Why/What/Example-Idea
# vocabulary). ALS's "Recent Findings" is the "what is already known"
# slot cf-PICI folds into a bullet under "Why Research This Area?"
# rather than naming as its own section -- MO-12. We already mirror
# cf-PICI's Why/What pair (importance / suggested_experiments, pinned
# below); recent_findings adds ALS's third slot rather than switching
# vocabularies.
_OVERVIEW_DIRECTION_REQUIRED = {
    "title",
    "importance",
    "suggested_experiments",
    "recent_findings",
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
    is checked once rather than once per exemplar.
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
        Path(co_scientist.__file__).parent
        / "prompts/templates/ranking_debate.md"
    ).read_text(encoding="utf-8")
    assert "better idea:" in template.lower()

    schema = get_schema_for_prompt("ranking_debate")
    assert schema is not None
    assert "decision_summary" in schema["schema"]["properties"]


def test_debate_transcript_matches_the_published_exemplar_shape() -> None:
    """A judged debate projects onto turns plus one closing verdict line.

    Figure A.17 prints its exchange turn by turn and states the verdict
    exactly once, at the end. Our judge answers *every* turn with its own
    verdict line, numbered in that turn's presentation order -- which the
    loop alternates -- so the projection has to strip them and restate the
    match's own verdict once, or the rendered debate argues for a
    different number every turn.
    """
    transcript = [
        {
            "turn": turn,
            "winner": "a",
            "reasoning": f"Turn {turn}. better idea: 1",
        }
        for turn in range(1, _DEBATE_EXEMPLAR_TURN_COUNT + 1)
    ]

    document = debate_transcript_document(transcript, "1")

    assert len(document["turns"]) == _DEBATE_EXEMPLAR_TURN_COUNT
    assert f"Better idea: {document['verdict']}" == _DEBATE_EXEMPLAR_VERDICT
    assert not any(
        "better idea" in turn["text"].lower() for turn in document["turns"]
    )


def test_research_overview_sections_match_published_exemplar() -> None:
    """Each research direction must argue why it matters and what to do.

    The overview exemplar (cited above) develops every direction under
    two questions, which are the two per-direction fields the schema
    requires beside the direction's title -- plus, since MO-1/MO-12,
    the nested sub_topics layer both exemplars carry under their own
    vocabulary for "what to research", and ALS's recent_findings slot
    for "what is already known".
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


def _research_directions_node() -> dict[str, Any]:
    """Return the schema's ``overview.research_directions`` array node."""
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    overview = schema["schema"]["properties"]["overview"]
    directions: dict[str, Any] = overview["properties"]["research_directions"]
    return directions


def test_research_directions_ask_for_more_than_one_direction() -> None:
    """The prompt must name a direction count, bounded by the exemplar's.

    The published overview enumerates six directions and our runs settled
    on three, because nothing asked for a number at all. The ask is now
    explicit and sized against this node's measured output budget
    (RESEARCH_OVERVIEW_MAX_TOKENS is already the escalation ladder's own
    ceiling, so an over-ask cannot be answered by escalating), and the
    array is capped at the exemplar's own six.
    """
    directions = _research_directions_node()
    assert directions["maxItems"] == _OVERVIEW_EXEMPLAR_DIRECTION_COUNT
    assert RESEARCH_OVERVIEW_TARGET_DIRECTIONS > 1
    assert (
        RESEARCH_OVERVIEW_TARGET_DIRECTIONS
        <= _OVERVIEW_EXEMPLAR_DIRECTION_COUNT
    )
    template = _overview_template()
    # The phrase, not the digit: "4" already appears in several other
    # counts in this prompt, so a bare substring check would pass for any
    # value of the constant and bind nothing.
    assert (
        f"exactly {RESEARCH_OVERVIEW_TARGET_DIRECTIONS} major directions"
        in template
    )


def test_overview_schema_never_echoes_the_hypothesis_pool_back() -> None:
    """Neither new field may make output scale with the input pool.

    The trap this guards is the one proximity clustering hit: a schema
    that names pool items by repeating their text makes the response grow
    with the pool and truncate identically on every retry. Both fields
    added for F5/F7 are bounded and authored -- the directions array by
    ``maxItems``, ``example_idea`` by being a plain authored string -- and
    the prompt says so in as many words.
    """
    directions = _research_directions_node()
    assert "maxItems" in directions
    sub_topic = directions["items"]["properties"]["sub_topics"]["items"]
    example_idea = sub_topic["properties"]["example_idea"]
    assert example_idea["type"] == "string"
    description = example_idea.get("description", "").lower()
    for banned in ("copy", "verbatim", "repeat", "quote"):
        assert banned not in description
    # The anti-echo instruction travels with the field it governs: the
    # sub-topics are written by the per-direction call, not the draft.
    assert (
        "not by echoing the hypotheses or evidence text back"
        in _direction_template()
    )


def _direction_template() -> str:
    """Return the per-direction prompt template's raw text."""
    return (
        Path(co_scientist.__file__).parent
        / "prompts/templates/research_overview_direction.md"
    ).read_text(encoding="utf-8")


def _overview_template() -> str:
    """Return the research-overview prompt template's raw text."""
    return (
        Path(co_scientist.__file__).parent
        / "prompts/templates/research_overview.md"
    ).read_text(encoding="utf-8")
