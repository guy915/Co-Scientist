"""A child's title (R14-12), split out of test_evolve.py at the file cap.

Unlike the inherited fields in test_evolve_inheritance.py (introduction/
recent_findings/safety_and_toxicity, which the evolution LLM is never asked
to rewrite), title is asked for fresh on every evolution response -- the
same treatment as text/explanation/experiment -- since a refined mechanism
may no longer match the parent's name.
"""

import pytest

from co_scientist.agents.evolution import evolve
from co_scientist.agents.evolution.evolve import evolve_node
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_state
from tests.test_evolve import _RAPAMYCIN_RESPONSE, _children


async def test_evolution_child_takes_the_response_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canned response's title reaches the child, not the parent's."""
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        title="Quercetin Blockade of Aldolase",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(
        monkeypatch,
        evolve,
        {**_RAPAMYCIN_RESPONSE, "title": "Rapamycin-Driven mTOR Suppression"},
    )

    result = await evolve_node(state)

    child = _children(result)[0]
    assert child.title == "Rapamycin-Driven mTOR Suppression"
    assert original.title == "Quercetin Blockade of Aldolase"


async def test_evolution_child_title_is_none_when_response_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing title is left None, not inherited from the parent.

    The child's mechanism may have changed, so reusing the parent's
    (now possibly stale) title would misname it; the app's drain derives a
    fallback from the child's own refined text instead (R14-12).
    """
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        title="Quercetin Blockade of Aldolase",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    result = await evolve_node(state)

    child = _children(result)[0]
    assert child.title is None
