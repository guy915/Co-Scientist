"""A child's inherited (not LLM-rewritten) fields, split out of test_evolve.py.

``_build_evolution_child`` carries several fields straight from the primary
parent because the evolution LLM is never asked to rewrite them --
literature_grounding is the original example; the scene-setting fields
(MO-6) get the same treatment. Split out to keep ``test_evolve.py`` within
the module-size cap.
"""

import pytest

from co_scientist.agents.evolution import evolve
from co_scientist.agents.evolution.evolve import evolve_node
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_state
from tests.test_evolve import _RAPAMYCIN_RESPONSE, _children


async def test_evolution_child_inherits_scene_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child inherits the parent's Introduction/Recent findings (MO-6).

    The evolution LLM is not asked to rewrite these scene-setting fields
    (unlike text/explanation/experiment), so the child carries the primary
    parent's values unchanged -- the same treatment as literature_grounding.
    """
    original = make_hypothesis(
        text="quercetin inhibits aldolase activity",
        introduction="Metabolic disease remains a major cause of morbidity.",
        recent_findings="Aldolase inhibitors have shown early promise.",
    )
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    result = await evolve_node(state)

    child = _children(result)[0]
    assert child.introduction == original.introduction
    assert child.recent_findings == original.recent_findings
