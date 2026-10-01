"""A child's own proposal sections, split out of test_evolve.py.

``_build_evolution_child`` used to carry the mechanism (``literature_
grounding``), the scene-setting fields (MO-6) and the proposer's own safety
assessment (MO-10) straight from the primary parent, on the rationale that
the evolution LLM was never asked to rewrite them. Production extended run
bc77950f (2026-09-08) showed what that costs once an operator diverges: all
seven children carried their parent's mechanism and safety text
byte-identically, so a verteporfin/YAP-TEAD child published a palbociclib/
CDK4-6 mechanism paragraph, and the six categorical claims the gate
harvests from ``literature_grounding`` named a molecule the child does not
propose. EVOLUTION_SCHEMA now asks for those four sections, and a child
that is not given them carries none rather than its parent's. The prompt
assertions at the end of this file cover what funds that ask: all three
evolution templates now show the run's ``[C*]`` reference list, so a
refinement's own grounding paragraph has keys to cite.
"""

from typing import Any

import pytest

from co_scientist.agents.evolution import evolve
from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
)
from co_scientist.agents.evolution.evolve import evolve_node
from co_scientist.agents.evolution.evolve_prompt import (
    _build_evolution_prompt,
    _EvolutionContext,
    _EvolutionOperation,
)
from co_scientist.agents.generation.citations import ReferenceIndex
from co_scientist.offline.llm import (
    DEFAULT_OFFLINE_MODEL,
    install_offline_router,
)
from tests._llm_fake import disable_llm_cache, stub_call_llm_json
from tests._offline_helpers import isolate_offline_router
from tests._state import make_article, make_hypothesis, make_state
from tests.test_evolve import _RAPAMYCIN_RESPONSE, _children

# The parent's own sections, all naming the molecule the parent proposes.
_PARENT_SECTIONS: dict[str, Any] = {
    "introduction": "Metabolic disease remains a major cause of morbidity.",
    "recent_findings": "Aldolase inhibitors have shown early promise [C1].",
    "literature_grounding": (
        "Quercetin depletes aldolase activity in hepatocytes [C1]."
    ),
    "safety_and_toxicity": (
        "Quercetin is well tolerated at dietary doses in humans."
    ),
}

# The same four sections as an evolution response would carry them, each
# describing the child's own molecule rather than the parent's.
_CHILD_SECTIONS: dict[str, Any] = {
    "introduction": "Growth signaling drives proliferative disease.",
    "recent_findings": "Kinase inhibitors reshaped the field [C2].",
    "literature_grounding": (
        "Rapamycin suppresses mtor signaling in mammalian cells [C2]."
    ),
    "safety_and_toxicity": (
        "Rapamycin carries immunosuppression risk at chronic doses."
    ),
}


def _evolved_parent() -> Any:
    """The parent every test here evolves, with all four sections set."""
    return make_hypothesis(
        text="quercetin inhibits aldolase activity",
        citation_map={"C1": {"type": "paper", "title": "Aldolase"}},
        **_PARENT_SECTIONS,
    )


def _prompt_context(**overrides: Any) -> _EvolutionContext:
    """A minimal evolution context for the prompt-render assertions."""
    return _EvolutionContext(
        model_name="test-model",
        meta_review={},
        removed_duplicates=[],
        state=make_state(),
        **overrides,
    )


async def test_child_sections_come_from_the_evolution_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response's own sections reach the child, replacing the parent's."""
    original = _evolved_parent()
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(
        monkeypatch, evolve, {**_RAPAMYCIN_RESPONSE, **_CHILD_SECTIONS}
    )

    child = _children(await evolve_node(state))[0]

    assert child.introduction == _CHILD_SECTIONS["introduction"]
    assert child.recent_findings == _CHILD_SECTIONS["recent_findings"]
    assert (
        child.literature_grounding == (_CHILD_SECTIONS["literature_grounding"])
    )
    assert child.safety_and_toxicity == (_CHILD_SECTIONS["safety_and_toxicity"])


async def test_child_never_inherits_the_parent_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production shape: a response that omits them yields none.

    An empty section publishes nothing; the parent's section publishes a
    mechanism and a safety profile for a molecule the child does not
    propose, and the claim gate then reports its categorical claims as
    unsupported because no retrieval can ever support them.
    """
    original = _evolved_parent()
    state = make_state(hypotheses=[original], evolution_max_count=1)
    stub_call_llm_json(monkeypatch, evolve, _RAPAMYCIN_RESPONSE)

    child = _children(await evolve_node(state))[0]

    assert child.literature_grounding is None
    assert child.safety_and_toxicity is None
    assert child.introduction is None
    assert child.recent_findings is None


async def test_blank_sections_do_not_become_the_parents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The json_object downgrade backfills "" for a missing required key."""
    original = _evolved_parent()
    state = make_state(hypotheses=[original], evolution_max_count=1)
    blanks = dict.fromkeys(_CHILD_SECTIONS, "   ")
    stub_call_llm_json(monkeypatch, evolve, {**_RAPAMYCIN_RESPONSE, **blanks})

    child = _children(await evolve_node(state))[0]

    assert child.literature_grounding is None
    assert child.safety_and_toxicity is None


async def test_child_citation_map_resolves_its_own_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The child's map resolves the keys the child cites, not the parent's.

    The parent's map is keyed to the grounding paragraph the parent wrote,
    so carrying it forward beside a rewritten paragraph leaves the child
    citing [C2] while its map explains [C1].
    """
    original = _evolved_parent()
    state = make_state(
        hypotheses=[original],
        evolution_max_count=1,
        articles=[
            make_article("Aldolase depletion", used_in_analysis=True),
            make_article("mTOR suppression", used_in_analysis=True),
        ],
    )
    stub_call_llm_json(
        monkeypatch, evolve, {**_RAPAMYCIN_RESPONSE, **_CHILD_SECTIONS}
    )

    child = _children(await evolve_node(state))[0]

    assert list(child.citation_map) == ["C2"]
    assert child.citation_map["C2"]["title"] == "mTOR suppression"


async def test_offline_backend_produces_a_populated_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deterministic offline backend fills the four new sections.

    The schema filler answers every declared field, so an offline run's
    child is well-formed rather than a hypothesis with an empty mechanism
    -- and, since the sections are now the response's, distinct from its
    parent's.
    """
    isolate_offline_router(monkeypatch)
    disable_llm_cache(monkeypatch)
    install_offline_router()
    original = _evolved_parent()
    state = make_state(
        hypotheses=[original],
        evolution_max_count=1,
        model_name=DEFAULT_OFFLINE_MODEL,
    )

    child = _children(await evolve_node(state))[0]

    assert child.text
    for section in _PARENT_SECTIONS:
        value = getattr(child, section)
        assert value, f"offline child has no {section}"
        assert value != _PARENT_SECTIONS[section]


@pytest.mark.parametrize(
    "operator",
    [
        EvolutionOperator.ENHANCEMENT,
        EvolutionOperator.COHERENCE_FEASIBILITY,
        EvolutionOperator.OUT_OF_BOX,
    ],
)
def test_evolution_prompt_carries_the_citation_reference_list(
    operator: EvolutionOperator,
) -> None:
    """Every evolution template shows the [C*] keys its answer may cite.

    The refinement is now asked for its own ``literature_grounding``, and
    that field's instruction is to cite only the supplied bracketed keys.
    Without the list in the prompt a child either disclaims its grounding
    or invents keys that resolve to nothing, so all three templates carry
    the slot -- not just the one that renders evolution.md.
    """
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        ["a peer hypothesis"],
        _prompt_context(
            reference_index=ReferenceIndex(
                text="[C1] Smith et al., 2023 - Aldolase inhibition",
                sources={"C1": {"type": "paper", "title": "Aldolase"}},
            )
        ),
        _EvolutionOperation(operator=operator),
    )

    assert "[C1] Smith et al., 2023" in prompt
    assert "Literature Grounding (required)" in prompt
    assert "Safety and Toxicity (required)" in prompt
    assert "{{MISSING" not in prompt


def test_evolution_prompt_omits_citations_without_a_reference_index() -> None:
    """A run with no analyzed sources sees no citation instructions."""
    prompt, _ = _build_evolution_prompt(
        make_hypothesis(text="the parent hypothesis"),
        [],
        _prompt_context(),
        _EvolutionOperation(),
    )

    assert "Citation Reference List" not in prompt
    assert "{{MISSING" not in prompt
