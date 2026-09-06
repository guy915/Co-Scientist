"""Defects an independent review found behind the presence/order contract.

``test_published_prompt_fidelity.py`` asserts that every published
sentence is *present* and in *published order*. Three classes of defect
survive that contract, and one instance of each is pinned here:

* a published placeholder whose only production caller never fills it,
  so the published label ships over an empty line in every real run
  (A.8's ``Additional instructions:``);
* a published termination phrase left as a bare free-text ending on the
  one turn that must answer in JSON, where it contradicts the output
  contract appended right below it (A.2's ``HYPOTHESIS`` token);
* a published input slot carrying data of the wrong kind -- a hypothesis
  UUID where the prompt labels its two sides "Hypothesis 1" and
  "Hypothesis 2" (A.5's follow-up debate transcript).

Each was invisible to the presence checks for the same reason: the
fidelity fixture is deliberately rich, so it fills by hand what
production leaves empty or fakes what production computes. The last test
here guards the fixture itself, since an empty render is not something
``test_every_slot_rendered`` can see.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from co_scientist.agents.ranking.ranking_debate_turns import (
    _append_debate_context,
)
from co_scientist.prompts.generation_debate import (
    DebatePromptRequest,
    get_debate_generation_prompt,
)
from co_scientist.prompts.planning import get_meta_review_prompt
from tests._published_corpus import corpus_available
from tests._published_prompt_renders import render_all

pytestmark = pytest.mark.skipif(
    not corpus_available(),
    reason="engine checked out without the reference corpus",
)

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


def test_meta_review_additional_instructions_slot_is_never_blank() -> None:
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


def test_supplied_meta_review_instructions_are_not_replaced() -> None:
    """A real instruction still reaches the published slot verbatim."""
    prompt, _ = get_meta_review_prompt(
        research_goal="A research goal.",
        all_reviews="[]",
        instructions="Weigh the pilot readouts first.",
    )
    body = _slot_after_label(prompt, "Additional instructions:")
    assert body == "Weigh the pilot readouts first."


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


@pytest.mark.parametrize("literature", [True, False])
def test_final_turn_routes_the_termination_token_into_the_json(
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
    literature: bool,
) -> None:
    """A free-form turn is unchanged: the published token still ends it."""
    prompt = _debate_prompt(is_final_turn=False, literature=literature)
    assert "## FINAL TURN - OUTPUT FORMAT" not in prompt
    assert prompt.rstrip().endswith("Your Turn:")
    assert f'writing "{_TERMINATION_TOKEN}"' in prompt


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


def test_followup_turn_names_the_prior_winner_by_its_presented_number() -> None:
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


def test_swapped_followup_turn_renumbers_the_prior_winner() -> None:
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


# --- the fixture the other three defects hid behind ---------------------


def test_generation_fixture_renders_the_analyzed_paper_list() -> None:
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
