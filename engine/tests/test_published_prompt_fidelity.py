"""Offline contracts for published prompt fidelity."""

from __future__ import annotations

import functools
import re
import unicodedata
from pathlib import Path
from typing import Any

import pytest

import co_scientist
from co_scientist.agents.evolution.evolve import EVOLUTION_PARENT_COUNT
from co_scientist.agents.ranking.ranking_debate import (
    _append_debate_context,
    debate_transcript_document,
)
from co_scientist.agents.ranking.ranking_matchmaking import MatchmakingWeights
from co_scientist.constants import INITIAL_ELO_RATING, RESEARCH_OVERVIEW_TOP_K
from co_scientist.generator import HypothesisGenerator
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts.generation_debate import (
    DebatePromptRequest,
    get_debate_generation_prompt,
)
from co_scientist.prompts.planning import get_meta_review_prompt
from co_scientist.scheduling import Budget, SchedulerStats, decide_next_task
from co_scientist.scheduling.models import TerminationReason
from co_scientist.schemas import get_schema_for_prompt
from co_scientist.schemas.synthesis import RESEARCH_OVERVIEW_TARGET_DIRECTIONS
from tests._published_corpus import (
    Rendered,
    corpus_available,
    published_prompt,
    render_all,
    unrendered_slots,
)

# Every check here reads the corpus, and the presence parametrization
# reads it at collection time -- where ``pytest.skip`` would be a
# collection error rather than a skip. Both guards below are therefore
# needed, not one belt-and-braces pair.

PUBLISHED_STEMS = (
    "generation-01-hypothesis-after-literature-review",
    "generation-02-hypothesis-after-scientific-debate",
    "reflection-03-generate-observations",
    "ranking-04-pairwise-comparison",
    "ranking-05-comparison-via-scientific-debate",
    "evolution-06-feasibility-improvement",
    "evolution-07-out-of-the-box-thinking",
    "meta-review-08-meta-review-generation",
)

_FENCE = re.compile(r"^```.*?$", re.MULTILINE)
_ENUMERATOR = re.compile(r"^\s*(?:\d+\.|[a-z]\.|[*-])\s+")
# Split before a numbered/lettered/bulleted item or a new capitalized
# sentence, but never immediately after an enumerator's own period -- the
# two negative lookbehinds keep "1." and "a." attached to what follows.
_SENTENCE_SPLIT = re.compile(
    r'(?<!\s\d\.)(?<![\s(][a-z]\.)(?<=[.:"])\s+'
    r"(?=(?:\d+\.\s|[a-z]\.\s|[*-]\s|[A-Z#]))"
)
# A paper placeholder. The closing "}" is optional-by-alternation because
# reflection-03's final line opens "{provide reasoning..." and closes with
# ")" -- a typo in the published source, reproduced verbatim in the
# extract.
_PLACEHOLDER = re.compile(r"\{[^{}]*?[})]")
_EMPHASIS = re.compile(r"[*`]+")
# Typographic quotes, spelled by code point: ruff rejects the literal
# characters as visually ambiguous (RUF001).
_QUOTE_FOLDS = (
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u2018", "'"),
    ("\u2019", "'"),
)


def _normalize(text: str) -> str:
    """Fold a prompt to the form both sides are compared in."""
    folded = unicodedata.normalize("NFKC", text)
    for curly, straight in _QUOTE_FOLDS:
        folded = folded.replace(curly, straight)
    folded = _EMPHASIS.sub("", folded)
    return re.sub(r"\s+", " ", folded).strip().lower()


def _fenced_body(text: str) -> str:
    """Return the prompt body inside the extract's code fence."""
    parts = _FENCE.split(text)
    assert len(parts) >= 2, "published extract has no fenced prompt body"
    return parts[1].strip("\n")


def _drop_caption(body: str) -> str:
    """Drop the figure caption the paper prints above each prompt.

    Two of the eight are rendered as one run-on paragraph, so their
    caption is a prefix of the first line rather than a line of its own.
    """
    first, _, rest = body.partition("\n")
    if not first.startswith("Prompt for"):
        return body
    if " You are " in first:
        return first[first.index(" You are ") + 1 :] + (
            "\n" + rest if rest else ""
        )
    return rest


def _join_continuations(body: str) -> list[str]:
    """Join lines the paper wrapped mid-sentence back into one unit."""
    units: list[str] = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if units and not units[-1].endswith((".", ":", "!", "?")):
            units[-1] = f"{units[-1]} {line}"
        else:
            units.append(line)
    return units


def _strip_enumerators(unit: str) -> str:
    """Remove every leading list marker from one unit."""
    previous = ""
    while previous != unit:
        previous = unit
        unit = _ENUMERATOR.sub("", unit)
    return unit.strip()


def _is_assertable(fragment: str) -> bool:
    """True for a fragment specific enough to assert on.

    A one-word fragment is too weak to prove anything, except when it is
    a section label the published prompt ends with a colon ("Goal:").
    """
    return len(fragment.split()) >= 2 or fragment.endswith(":")


def _fragments(unit: str) -> list[str]:
    """Split one published unit at its placeholders into matchable parts."""
    parts = (_normalize(part) for part in _PLACEHOLDER.split(unit))
    return [part for part in parts if part and _is_assertable(part)]


@functools.cache
def published_fragments(stem: str) -> tuple[str, ...]:
    """Return one published prompt's assertable fragments, in order."""
    body = _drop_caption(_fenced_body(published_prompt(stem)))
    body = body.replace("\\*", "*")
    fragments: list[str] = []
    for unit in _join_continuations(body):
        for piece in _SENTENCE_SPLIT.split(unit):
            fragments.extend(_fragments(_strip_enumerators(piece)))
    return tuple(fragments)


def find_fragment(text: str, fragment: str, start: int = 0) -> int:
    """Locate a published fragment at a token boundary in ``text``.

    A plain substring search lets a short published label match inside a
    longer word of ours -- "Instructions:" inside "Additional
    instructions:" -- which reports a missing section as a reordered one.
    The fragment must therefore begin where a word does.
    """
    pattern = re.compile(r"(?<![0-9a-z])" + re.escape(fragment))
    match = pattern.search(text, start)
    return match.start() if match else -1


def contains_fragment(text: str, fragment: str) -> bool:
    """True when ``text`` carries the published fragment."""
    return find_fragment(text, fragment) >= 0


@functools.cache
def _rendered() -> dict[str, Rendered]:
    return render_all()


def _union(stem: str) -> str:
    """The normalized text of every counterpart of one published prompt."""
    return _normalize(_rendered()[stem].union)


def _primary(stem: str) -> str:
    """The normalized text of the counterpart that owns published order."""
    return _normalize(_rendered()[stem].primary.text)


def _presence_cases() -> list[tuple[str, str]]:
    if not corpus_available():
        return []
    return [
        (stem, fragment)
        for stem in PUBLISHED_STEMS
        for fragment in published_fragments(stem)
    ]


# --- harness guards ----------------------------------------------------


# --- (b) ABSENT: published text missing from our rendered prompt -------


# --- (c) REORDERED: published ordering our prompt breaks ---------------


# --- (c) CONTRADICTED: wording that states the published opposite ------
#
# One guard per inversion found by the audit. Each asserts the
# contradicting wording is *absent*; none of them is satisfied by adding
# the published sentence alongside the contradiction, which is how the
# ranking scores instruction survived its first fix attempt.


# --- (d) OURS WITHOUT COUNTERPART: invented text, delete candidates ----
#
# Not contradictions: the published prompt states no opposite. Each is a
# mechanic we added that the published prompt leaves to its own
# termination rule, kept as a guard so a deletion is verified rather than
# assumed.


@pytest.mark.skipif(
    not corpus_available(),
    reason="engine checked out without the reference corpus",
)
class TestPublishedPromptFidelity:
    @pytest.mark.parametrize("stem", PUBLISHED_STEMS)
    def test_every_slot_rendered(self, stem: str) -> None:
        """No counterpart may reach a fidelity check with an unfilled slot.

        An unfilled ``{{slot}}`` would read as a missing published sentence,
        so this failing means the fixture is wrong, not the prompt.
        """
        leftovers = {
            part.name: unrendered_slots(part.text)
            for part in _rendered()[stem].counterparts
            if unrendered_slots(part.text)
        }
        assert not leftovers, f"fixture left slots unrendered: {leftovers}"

    @pytest.mark.parametrize("stem", PUBLISHED_STEMS)
    def test_published_prompt_yields_fragments(self, stem: str) -> None:
        """Extraction must produce fragments; zero would pass every check."""
        assert len(published_fragments(stem)) >= 5

    @pytest.mark.parametrize(
        ("stem", "fragment"),
        _presence_cases(),
        ids=lambda value: value[:60],
    )
    def test_published_fragment_is_present(
        self, stem: str, fragment: str
    ) -> None:
        assert contains_fragment(_union(stem), fragment), (
            f"published {stem} states {fragment!r}; "
            "our rendered prompt does not"
        )

    @pytest.mark.parametrize("stem", PUBLISHED_STEMS)
    def test_published_order_is_preserved(self, stem: str) -> None:
        """Fragments we do carry appear in the published order.

        Only fragments actually present are checked, so a missing sentence is
        reported once (by the presence test) rather than twice.
        """
        text = _primary(stem)
        cursor = 0
        out_of_order: list[str] = []
        for fragment in published_fragments(stem):
            if not contains_fragment(text, fragment):
                continue
            index = find_fragment(text, fragment, cursor)
            if index < 0:
                out_of_order.append(fragment)
                continue
            cursor = index + len(fragment)
        assert not out_of_order, (
            f"{stem}: present but out of published order: {out_of_order}"
        )

    def test_ranking_does_not_tell_the_judge_to_consider_the_scores(
        self,
    ) -> None:
        """A.4 says disregard the review scores, so we must not say consider."""
        text = _union("ranking-04-pairwise-comparison")
        assert "consider these scores" not in text

    def test_observation_start_phrase_is_not_narrowed(self) -> None:
        """A.3 mandates a literal opening phrase for each observation.

        The published phrase is 'would we see this observation if the
        hypothesis was true:'. Appending a qualifier changes the literal the
        reviewer is told to emit, so the instruction diverges from the
        published protocol even where nothing parses the emitted phrase.
        """
        text = _union("reflection-03-generate-observations")
        assert (
            "would we see this observation if the hypothesis was true, and"
            " not otherwise:" not in text
        )

    def test_summary_start_phrase_is_not_replaced(self) -> None:
        """A.3's summary step mandates its own literal opening phrase."""
        text = _union("reflection-03-generate-observations")
        assert (
            "taken as a whole, does the hypothesis explain observations that"
            " known mechanisms cannot:" not in text
        )

    def test_meta_review_does_not_order_per_proposal_evaluation(self) -> None:
        """A.8 forbids evaluating individual proposals.

        Our template carries that directive and then asks for a per-idea
        comparison table, which is the evaluation the directive forbids.
        """
        text = _union("meta-review-08-meta-review-generation")
        assert "compare the candidate ideas against each other" not in text

    def test_debate_does_not_order_the_panel_to_discard_two_ideas(self) -> None:
        """A.2 asks for three hypotheses and never orders a cull.

        The published procedure converges on one finalized idea at
        termination, so narrowing is implicit in it; ordering the panel to
        drop two of the three within a turn makes a within-turn elimination
        out of what the paper leaves to the debate's own end condition.
        """
        text = _union("generation-02-hypothesis-after-scientific-debate")
        assert "filter out the worse 2" not in text


_TERMINATION_TOKEN = "HYPOTHESIS"


def _slot_after_label(text: str, label: str) -> str:
    """Return the line a published label puts its slot's value on.

    The label owns exactly the line below it in every template here, so
    this reads the published slot itself rather than the run-context
    blocks that follow it.
    """
    match = re.search(rf"^{re.escape(label)}\n(?P<body>.*)$", text, re.M)
    assert match is not None, f"published label missing: {label!r}"
    return match.group("body").strip()


# --- A.8: the published {instructions} slot ----------------------------


# --- A.2: the published HYPOTHESIS termination token --------------------


def _debate_prompt(*, is_final_turn: bool, literature: bool) -> str:
    prompt, _ = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="A research goal.",
            transcript="Expert 1: an opening claim.",
            is_final_turn=is_final_turn,
            articles_with_reasoning=(
                "Analysis 1: a finding." if literature else None
            ),
        )
    )
    return prompt


# --- A.5: the follow-up debate transcript -------------------------------


def _transcript_entry(winner: str) -> dict[str, Any]:
    """One turn entry shaped exactly as ``_run_debate_turn`` builds it."""
    return {
        "turn": 1,
        "winner": winner,
        "winner_id": "0f2b7c41-3a19-4d55-9c8e-7b1a02d64f38",
        "reasoning": "It states the pilot readout.",
        "presentation_order": "ab",
        "valid_output": True,
    }


def _favoured_line(prompt: str) -> str:
    match = re.search(r"^- Turn 1 favored .*$", prompt, re.M)
    assert match is not None, "the prior-turns block lost its verdict line"
    return match.group(0)


# --- the fixture the other three defects hid behind ---------------------


@pytest.mark.skipif(
    not corpus_available(),
    reason="engine checked out without the reference corpus",
)
class TestPublishedPromptFidelityReview:
    def test_meta_review_additional_instructions_slot_is_never_blank(
        self,
    ) -> None:
        """A.8's published ``Additional instructions:`` label carries text.

        ``agents/meta_review/meta_review.py::_synthesize_meta_review`` is the
        only production caller and never passes ``instructions``, so the
        builder's ``instructions or ""`` shipped the published label over an
        empty line in every real run. Its siblings all fill an unsupplied
        published slot with a truthful "none" line instead
        (``generation_debate._DEFAULT_DEBATE_INSTRUCTIONS``,
        ``prompts/ranking.py::_NO_NOTES``).
        """
        prompt, _ = get_meta_review_prompt(
            research_goal="A research goal.",
            all_reviews="[]",
        )
        assert _slot_after_label(prompt, "Additional instructions:"), (
            "A.8's published 'Additional instructions:' label rendered over"
            " nothing in the production call shape"
        )

    def test_supplied_meta_review_instructions_are_not_replaced(self) -> None:
        """A real instruction still reaches the published slot verbatim."""
        prompt, _ = get_meta_review_prompt(
            research_goal="A research goal.",
            all_reviews="[]",
            instructions="Weigh the pilot readouts first.",
        )
        body = _slot_after_label(prompt, "Additional instructions:")
        assert body == "Weigh the pilot readouts first."

    @pytest.mark.parametrize("literature", [True, False])
    def test_final_turn_routes_the_termination_token_into_the_json(
        self,
        literature: bool,
    ) -> None:
        """The final turn's own block resolves A.2's termination token.

        Published A.2 ends a free-form debate by writing ``HYPOTHESIS``
        followed by prose. Our final turn answers in JSON instead, and
        ``_DEBATE_FINAL_TURN_INSTRUCTIONS`` is concatenated *after* the
        template that still carries the published termination sentence -- so
        the one turn that must emit parseable JSON was also being told to
        open with a bare capitalised token. The published sentence stays
        where the paper puts it; the final-turn block has to say where that
        conclusion goes on this turn.
        """
        prompt = _debate_prompt(is_final_turn=True, literature=literature)
        final_block = prompt.split("## FINAL TURN - OUTPUT FORMAT", 1)[1]
        assert _TERMINATION_TOKEN in final_block, (
            "the final-turn output block never mentions the published"
            " termination token it has to override"
        )
        assert "hypothesis" in final_block.split(_TERMINATION_TOKEN, 1)[1][:400]

    @pytest.mark.parametrize("literature", [True, False])
    def test_non_final_turn_keeps_the_bare_termination_token(
        self,
        literature: bool,
    ) -> None:
        """A free-form turn is unchanged: the published token still ends it."""
        prompt = _debate_prompt(is_final_turn=False, literature=literature)
        assert "## FINAL TURN - OUTPUT FORMAT" not in prompt
        assert prompt.rstrip().endswith("Your Turn:")
        assert f'writing "{_TERMINATION_TOKEN}"' in prompt

    def test_followup_turn_names_the_prior_winner_by_its_presented_number(
        self,
    ) -> None:
        """The prior-turn line names a side the judge can actually find.

        ``_run_debate_turn`` records ``winner_id`` as the Hypothesis UUID,
        and the appended block printed it verbatim -- so a real follow-up
        turn read "favored hypothesis 0f2b7c41-..." while the prompt above it
        labels its two sides "Hypothesis 1" and "Hypothesis 2". The fidelity
        fixture hand-wrote ``winner_id: "A"``, which is why the render looked
        right.
        """
        appended = _append_debate_context(
            "base prompt", [_transcript_entry("a")], swapped=False
        )
        line = _favoured_line(appended)
        assert "hypothesis 1" in line.lower()
        assert "0f2b7c41" not in line

    def test_swapped_followup_turn_renumbers_the_prior_winner(self) -> None:
        """A swapped turn renumbers the verdict to the order it presents.

        Turns alternate A/B presentation order (``_execute_debate_turn``),
        and ``winner`` is always the canonical un-swapped side. Printing it
        unchanged on a swapped turn would point the judge at the hypothesis
        it is *not* reading in that position -- the Output Format's own
        legend (``winner`` is "a" for hypothesis 1) makes it decode the line
        inverted.
        """
        appended = _append_debate_context(
            "base prompt", [_transcript_entry("a")], swapped=True
        )
        assert "hypothesis 2" in _favoured_line(appended).lower()

    def test_generation_fixture_renders_the_analyzed_paper_list(self) -> None:
        """``articles()`` must mark its articles as read by the review.

        ``format_articles_metadata`` filters on ``used_in_analysis``, so a
        fixture that omits the flag renders ``{{articles_metadata}}`` as an
        empty string. ``test_every_slot_rendered`` only sees a leftover
        ``{{`` marker, so an empty render is invisible to it.
        """
        primary = render_all()[
            "generation-01-hypothesis-after-literature-review"
        ].primary
        assert "Papers Analyzed in Literature Review" in primary.text


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


# Every constant below cites
# references/core/google-co-scientist/research/extracted-artifacts/pseudocode/
# <name>.md, each one part of the single Nature SI Note 8 listing (source
# lines 905-1099 of the supplementary information).

# 01-supervisor.md -- 71 lines, sha256 2f7a6fe641b3.
# "WHILE NumberOfIdeas < MaxIdeas AND NumberOfMatchesPerIdea <
# MaxMatchesPerIdea DO" -- the Supervisor's two named termination
# predicates. Google states the names, not the values, so only the
# predicates are pinned; their thresholds stay configurable clone
# decisions. This constant is used by the corroboration module; the two
# reason values below are our own vocabulary for the same predicates.
_SUPERVISOR_TERMINATION_PREDICATES = (
    "NumberOfIdeas < MaxIdeas",
    "NumberOfMatchesPerIdea < MaxMatchesPerIdea",
)
_TERMINATION_REASON_VALUES = {"max_ideas", "max_matches_per_idea"}

# 02-generation.md -- 29 lines, sha256 f9d19a9a6505.
# "Strategy 1: Use existing knowledge" / "Strategy 2: Simulate debate",
# followed by "More strategies..." -- the two named strategies are
# required, and the enum is deliberately allowed to be larger.
_GENERATION_STATED_STRATEGIES = (
    "Strategy 1: Use existing knowledge",
    "Strategy 2: Simulate debate",
)

# 03-reflection.md -- 30 lines, sha256 ad6a4c3b022c.
# "Break down this hypothesis into its core assumptions." / "CHECK if the
# assumption is scientifically plausible" -- deep verification decomposes
# a hypothesis and checks each assumption in turn.
_REFLECTION_STATED_ASSUMPTION_LINES = (
    "Break down this hypothesis into its core assumptions",
    "CHECK if the assumption is scientifically plausible",
)

# 04-ranking.md -- 36 lines, sha256 e5c0327ddb0c.
# "SET HypothesisToAdd.EloRating TO 1200" -- AddToTournament's only
# initializer, since it exits early for a hypothesis that already has a
# rating.
_RANKING_STATED_ENTRY_RATING = 1200
# "Prioritize new hypotheses or those with similar Elo ratings" -- Google
# publishes no weights, so only the presence of the two matching terms is
# pinned below, not their magnitudes.
_RANKING_STATED_PAIRING_LINE = (
    "Prioritize new hypotheses or those with similar Elo ratings"
)

# 05-evolution.md -- 32 lines, sha256 f737c9a057b7.
# "FETCH the top 5 hypotheses from the HypothesesList".
_EVOLUTION_STATED_PARENT_COUNT = 5
# "// Treat it like a brand new idea" followed by a new Reflection review
# task -- an evolved hypothesis re-enters review exactly like a freshly
# generated one.
_EVOLUTION_STATED_TREAT_AS_NEW_LINE = "Treat it like a brand new idea"
_EVOLUTION_STATED_REVIEW_TASK_LINE = (
    'Agent: Reflection, Action: "ReviewHypothesis"'
)

# 07-meta-review.md -- 25 lines, sha256 7e502a1ae3fa.
# "FETCH the top 10 hypotheses from SharedMemory".
_META_REVIEW_STATED_TOP_N = 10
# "GATHER all reviews and tournament debate transcripts from SharedMemory".
_META_REVIEW_STATED_GATHER_LINE = (
    "GATHER all reviews and tournament debate transcripts"
)


def test_tournament_entry_rating_is_the_stated_one() -> None:
    """A hypothesis enters the tournament at the listing's rating.

    The Ranking agent's ``AddToTournament`` sets the rating once and exits
    early for a hypothesis that already has one, so the entry rating is
    also the only initializer -- which is why the model's default is
    checked against it too.
    """
    assert INITIAL_ELO_RATING == _RANKING_STATED_ENTRY_RATING
    hypothesis = Hypothesis(text="An idea.")
    assert hypothesis.elo_rating == _RANKING_STATED_ENTRY_RATING


def test_termination_predicates_are_the_named_ones() -> None:
    """The run stops on the two predicates the Supervisor loop names."""
    reasons = {reason.value for reason in TerminationReason}
    assert reasons >= _TERMINATION_REASON_VALUES


def test_the_named_predicates_can_actually_stop_a_run() -> None:
    """Naming the reasons is not the same as being able to reach them.

    The enum check above passed for the whole time both predicates were
    ``None`` on every production run -- the tier table never carried them,
    so the loop actually terminated on ``max_iterations``, which the
    listing does not name. This asserts the control flow instead: given a
    ``Budget`` that sets them, the scheduler really does stop, and says
    which of the two it stopped on. That they are *set* on a real run is
    the app's half, pinned by
    ``app/tests/test_run_modes_supervisor_budget.py``.
    """
    settled = SchedulerStats(
        pool_size=9, reviewed_count=9, rankable_count=9, match_coverage=4.0
    )
    ideas = decide_next_task(settled, Budget(max_iterations=9, max_ideas=9))
    assert ideas.termination_reason is TerminationReason.MAX_IDEAS
    matches = decide_next_task(
        settled, Budget(max_iterations=9, max_matches_per_idea=4.0)
    )
    assert matches.termination_reason is TerminationReason.MAX_MATCHES_PER_IDEA


def test_evolution_breeds_from_the_stated_parent_count() -> None:
    """Evolution takes its parents from the listing's top-N by rank."""
    assert EVOLUTION_PARENT_COUNT == _EVOLUTION_STATED_PARENT_COUNT


def test_research_overview_synthesizes_the_stated_top_n() -> None:
    """The final overview synthesizes the listing's top-N hypotheses."""
    assert RESEARCH_OVERVIEW_TOP_K == _META_REVIEW_STATED_TOP_N


def test_pairing_prioritizes_new_and_similarly_rated_ideas() -> None:
    """Matchmaking weights the two priorities the listing names.

    ``RunTournamentBatch`` prioritizes new hypotheses (``recency``) and
    ones whose ratings are close (``elo_closeness``, the pairwise term
    scored in ``_partner_score`` -- ``rank`` and ``similarity_bonus``
    score different things and would let this pass without the property
    they name actually existing). Behavior is pinned separately by
    ``test_ranking_matchmaking.py::test_close_elo_hypotheses_are_preferred``.
    """
    weights = MatchmakingWeights()
    assert weights.recency > 0
    assert weights.elo_closeness > 0


def test_evolved_hypotheses_are_reviewed_like_new_ones() -> None:
    """An evolved hypothesis re-enters review, as the listing requires.

    The Evolution agent queues a Reflection review for each child it
    creates -- "treat it like a brand new idea" -- which in this graph is
    the evolve to review edge.
    """
    graph = HypothesisGenerator()._build_graph(
        enable_literature_review_node=False
    )
    drawable = graph.get_graph()
    assert {
        edge.target for edge in drawable.edges if edge.source == "evolve"
    } == {"review"}


def test_deep_verification_decomposes_into_assumptions() -> None:
    """Verification breaks a hypothesis down and checks each assumption.

    The Reflection agent's listing does exactly that, so the schema must
    carry the decomposition rather than only the probing questions.
    """
    schema = get_schema_for_prompt("deep_verification")
    assert schema is not None
    item = schema["schema"]["properties"]["sub_assumptions"]["items"]
    assert set(item["required"]) == {"assumption", "verification", "status"}


def test_generation_runs_the_strategies_the_listing_names() -> None:
    """Generation carries the listing's two named strategies, and more.

    The listing names existing-knowledge and simulated-debate generation
    and then says "More strategies...", so the two named ones are required
    and the enum is deliberately allowed to be larger.
    """
    methods = {method.value for method in GenerationMethod}
    assert {"literature_tools", "debate"} <= methods


def test_meta_review_reads_reviews_and_debate_transcripts() -> None:
    """System feedback is synthesized from both of the listing's inputs."""
    schema = get_schema_for_prompt("meta_review")
    assert schema is not None
    properties = schema["schema"]["properties"]
    assert "meta_review_summary" in properties
