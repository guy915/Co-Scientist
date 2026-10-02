"""Evolution guard, multi-parent, partner, and grounding tests.

Split out of ``test_evolve.py`` to keep that module within the size cap.
"""

from typing import Any

import pytest

from co_scientist.agents.evolution import EvolutionContext, evolve
from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
)
from co_scientist.agents.evolution.evolve import (
    evolve_single_hypothesis,
)
from co_scientist.agents.evolution.evolve_prompt import (
    _EvolutionOperation,
)
from co_scientist.agents.evolution.evolve_results import (
    _apply_evolution_result,
)
from co_scientist.models import Hypothesis
from tests._state import make_article, make_hypothesis, make_state
from tests.test_evolve import _RAPAMYCIN_RESPONSE


def _observation(
    child_text: str,
    parent: Hypothesis,
    peers: list[Hypothesis],
    proximity_graph: dict[str, Any] | None = None,
    combination_partner: Hypothesis | None = None,
) -> tuple[Hypothesis | None, dict[str, Any] | None]:
    """Apply one canned refinement through the acceptance guard."""
    partners: tuple[Hypothesis, ...] = ()
    if combination_partner is not None:
        partners = (combination_partner,)
    operator = (
        EvolutionOperator.COMBINATION
        if partners
        else EvolutionOperator.ENHANCEMENT
    )
    context = EvolutionContext(
        model_name="fake/model",
        meta_review={},
        removed_duplicates=[],
        proximity_graph=proximity_graph,
    )
    operation = _EvolutionOperation(operator=operator, partners=partners)
    response: dict[str, Any] = {
        "hypothesis": child_text,
        "refinement_summary": "refined",
        "_evolution_operator": operator.value,
    }
    if partners:
        response["combined_partners"] = [1]
    return _apply_evolution_result(parent, response, peers, context, operation)


def test_guard_rejects_on_weight_one_proximity_edge() -> None:
    """A weight-1.0 parent-neighbor edge rejects even disjoint wording.

    The persisted graph's LLM-judged similarity outranks the lexical
    estimate: the refinement of a parent the proximity pass already judged
    highly similar to a peer converges on that peer.
    """
    parent = make_hypothesis(text="parent mechanism about kinase signaling")
    peer = make_hypothesis(text="a disjoint wording entirely")
    graph = {
        "edges": [{"source": parent.id, "target": peer.id, "similarity": 1.0}]
    }

    child, detail = _observation(
        "novel child wording sharing nothing lexically", parent, [peer], graph
    )

    assert child is None and detail is None


def test_guard_accepts_below_threshold_proximity_edge() -> None:
    """Medium/low proximity edges (dedup survivors) do not reject."""
    parent = make_hypothesis(text="parent mechanism about kinase signaling")
    peer = make_hypothesis(text="a disjoint wording entirely")
    graph = {
        "edges": [{"source": parent.id, "target": peer.id, "similarity": 0.6}]
    }

    child, detail = _observation(
        "novel child wording sharing nothing lexically", parent, [peer], graph
    )

    assert child is not None and detail is not None


def test_guard_coverage_fallback_rejects_near_verbatim_child() -> None:
    """Without a graph, near-total token coverage still rejects."""
    parent = make_hypothesis(text="parent mechanism about kinase signaling")
    peer_text = "rapamycin suppresses mtor signaling downstream of the kinase"
    peer = make_hypothesis(text=peer_text)

    child, _ = _observation(
        "rapamycin suppresses mtor signaling downstream", parent, [peer]
    )

    assert child is None


def test_guard_coverage_is_not_dominated_by_a_short_peer() -> None:
    """A refinement expanding a short peer is not its duplicate.

    Union-based Jaccard penalized exactly this asymmetry; coverage divides
    by the child's own tokens, so a long refinement that merely contains a
    short peer's wording passes.
    """
    parent = make_hypothesis(text="parent mechanism about kinase signaling")
    peer = make_hypothesis(text="rapamycin suppresses mtor")
    long_child = (
        "rapamycin suppresses mtor while an orthogonal readout of "
        "autophagic flux distinguishes cytostatic from cytotoxic "
        "responses across a dose matrix in patient-derived organoids"
    )

    child, detail = _observation(long_child, parent, [peer])

    assert child is not None and detail is not None


def test_guard_exempts_resolved_combination_partners() -> None:
    """A faithful merge may resemble the partners it combined.

    The rejection set is every idea the refinement was NOT deliberately
    merging; holding the merge to stay distinct from its own parents would
    reject combination's intended output.
    """
    parent = make_hypothesis(text="parent mechanism about kinase signaling")
    partner = make_hypothesis(text="partner mechanism about proteolysis")
    outsider = make_hypothesis(text="an unrelated third idea altogether")

    child, detail = _observation(
        partner.text,  # verbatim partner text: the harshest possible merge
        parent,
        [partner, outsider],
        combination_partner=partner,
    )

    assert child is not None
    assert detail is not None


def test_combination_records_every_parent() -> None:
    """A combination child keeps parent_id primary and parent_ids all."""
    parent = make_hypothesis(text="parent mechanism about kinase signaling")
    partner = make_hypothesis(
        text="partner mechanism about proteolysis",
        explanation="partner explanation",
        experiment="partner experiment",
    )
    response = {
        "hypothesis": "a merged mechanism covering both signaling routes",
        "refinement_summary": "combined",
        "_evolution_operator": "combination",
        "combined_partners": [1],
    }

    child, detail = _apply_evolution_result(
        parent,
        response,
        [],
        EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        _EvolutionOperation(
            operator=EvolutionOperator.COMBINATION, partners=(partner,)
        ),
    )

    assert child is not None and detail is not None
    assert child.parent_id == parent.id
    assert child.parent_ids == [parent.id, partner.id]
    assert detail["parent_id"] == parent.id
    assert detail["parent_ids"] == [parent.id, partner.id]


def test_combination_invalid_indices_degrade_to_single_parent() -> None:
    """Unresolvable partner indices mint a single-parent child, not none."""
    parent = make_hypothesis(text="parent mechanism about kinase signaling")
    partner = make_hypothesis(text="partner mechanism about proteolysis")

    child, detail = _apply_evolution_result(
        parent,
        {
            "hypothesis": "a refined mechanism with no usable partner",
            "refinement_summary": "combined",
            "_evolution_operator": "combination",
            "combined_partners": [99],
        },
        [],
        EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        _EvolutionOperation(
            operator=EvolutionOperator.COMBINATION, partners=(partner,)
        ),
    )

    assert child is not None and detail is not None
    assert child.parent_id == parent.id
    assert child.parent_ids == [parent.id]


async def test_partner_selection_flows_from_ranked_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Combination tasks offer the top-ranked peers as partners, whole."""
    observed_prompt = ""

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return {
            "hypothesis": "a merged mechanism with a distinct readout",
            "refinement_summary": "combined",
            "combined_partners": [1],
        }

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis(text="parent idea", elo_rating=1500)
    partner = make_hypothesis(
        text="strongest peer idea",
        elo_rating=1400,
        explanation="peer explanation",
        experiment="peer experiment",
    )

    child, detail = await evolve_single_hypothesis(
        parent,
        other_hypotheses=[partner],
        context=EvolutionContext(
            model_name="fake/model", meta_review={}, removed_duplicates=[]
        ),
        operation=_EvolutionOperation(
            operator=EvolutionOperator.COMBINATION, partners=(partner,)
        ),
    )

    assert "## Combination Partners" in observed_prompt
    assert "strongest peer idea" in observed_prompt
    assert "peer experiment" in observed_prompt
    assert child is not None
    assert detail is not None
    assert child.parent_ids == [parent.id, partner.id]
    assert detail["operator"] == "combination"


# --- enhancement grounding (E6) ----------------------------------------------


async def test_enhancement_grounding_falls_back_to_run_articles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without MCP the enhancement prompt carries the run's own articles."""
    observed_prompt = ""

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return dict(_RAPAMYCIN_RESPONSE)

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis(text="parent idea about oxidative stress")
    article = make_article(title="A run-accumulated evidence source")
    state = make_state(hypotheses=[parent], articles=[article])

    child, _ = await evolve_single_hypothesis(
        parent,
        other_hypotheses=[],
        context=EvolutionContext(
            model_name="fake/model",
            meta_review={},
            removed_duplicates=[],
            state=state,
        ),
    )

    assert child is not None
    assert "A run-accumulated evidence source" in observed_prompt


async def test_enhancement_grounding_placeholder_without_any_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No MCP and no run articles renders an explicit no-evidence note."""
    observed_prompt = ""

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return dict(_RAPAMYCIN_RESPONSE)

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis(text="parent idea about oxidative stress")
    state = make_state(hypotheses=[parent])

    await evolve_single_hypothesis(
        parent,
        other_hypotheses=[],
        context=EvolutionContext(
            model_name="fake/model",
            meta_review={},
            removed_duplicates=[],
            state=state,
        ),
    )

    assert "No retrieved evidence is available" in observed_prompt


async def test_enhancement_grounding_retrieves_when_mcp_is_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With MCP up the operator performs a live, parent-targeted retrieval."""
    from co_scientist.agents.evolution import evolve_grounding

    observed_prompt = ""
    observed_queries: list[str] = []

    async def fake_query_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        return {"queries": ["mtor", "rapamycin resistance"]}

    async def fake_retrieval(
        state: Any, queries: list[str]
    ) -> tuple[list[Any], list[str]]:
        observed_queries.extend(queries)
        return [make_article(title="Freshly retrieved grounding source")], []

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return dict(_RAPAMYCIN_RESPONSE)

    monkeypatch.setattr(evolve_grounding, "call_llm_json", fake_query_llm)
    monkeypatch.setattr(
        evolve_grounding, "_retrieve_probe_evidence", fake_retrieval
    )
    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis(text="parent idea about oxidative stress")
    state = make_state(hypotheses=[parent], mcp_available=True)

    child, _ = await evolve_single_hypothesis(
        parent,
        other_hypotheses=[],
        context=EvolutionContext(
            model_name="fake/model",
            meta_review={},
            removed_duplicates=[],
            state=state,
        ),
    )

    assert child is not None
    assert observed_queries == ["mtor", "rapamycin resistance"]
    assert "Freshly retrieved grounding source" in observed_prompt


async def test_non_enhancement_operators_perform_no_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live grounding is the enhancement brief; others never search."""
    from co_scientist.agents.evolution import evolve_grounding

    async def never_called(*_: Any, **__: Any) -> Any:
        raise AssertionError("retrieval helpers must not run")

    monkeypatch.setattr(evolve_grounding, "call_llm_json", never_called)
    monkeypatch.setattr(
        evolve_grounding, "_retrieve_probe_evidence", never_called
    )

    async def fake_llm(**_: Any) -> dict[str, Any]:
        return dict(_RAPAMYCIN_RESPONSE)

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis(text="parent idea about oxidative stress")
    state = make_state(hypotheses=[parent], mcp_available=True)

    child, _ = await evolve_single_hypothesis(
        parent,
        other_hypotheses=[],
        context=EvolutionContext(
            model_name="fake/model",
            meta_review={},
            removed_duplicates=[],
            state=state,
        ),
        operation=_EvolutionOperation(
            operator=EvolutionOperator.SIMPLIFICATION
        ),
    )

    assert child is not None


def test_grounding_metrics_extra_counts_only_live_enhancements() -> None:
    """Query-generation calls are metered only when the MCP server is up."""
    from co_scientist.agents.evolution.evolve_grounding import (
        grounding_metrics_extra,
    )

    operators = ["enhancement", "combination", "enhancement"]
    assert (
        grounding_metrics_extra(make_state(mcp_available=True), operators) == 2
    )
    assert (
        grounding_metrics_extra(make_state(mcp_available=False), operators) == 0
    )


# --- falsified-assumption feedback (audit K9, evolution half) ----------------


async def test_evolution_prompt_splices_falsified_assumptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A weakened hypothesis's falsified assumptions reach the refinement.

    Audit K9: deep verification already found a non-fundamental assumption
    wrong; evolution must not rebuild on that broken ground, so the prompt
    carries the run's verified-wrong assumption block.
    """
    observed_prompt = ""

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return dict(_RAPAMYCIN_RESPONSE)

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis(text="parent idea about oxidative stress")
    weakened = make_hypothesis(
        text="a weakened leader idea",
        deep_verification_verdict="weakened",
        deep_verification_probes=[
            {
                "question": "Is the cofactor present at all?",
                "answer": "No; it is absent in the relevant tissue.",
                "reasoning": "Measurements show no cofactor.",
                "assumption_is_fundamental": False,
            }
        ],
    )
    state = make_state(hypotheses=[parent, weakened])

    child, _ = await evolve_single_hypothesis(
        parent,
        other_hypotheses=[weakened],
        context=EvolutionContext(
            model_name="fake/model",
            meta_review={},
            removed_duplicates=[],
            state=state,
        ),
    )

    assert child is not None
    assert "Assumptions Verified Incorrect" in observed_prompt
    assert "Is the cofactor present at all?" in observed_prompt


async def test_evolution_prompt_omits_falsified_block_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no falsified assumption yet, the block renders nothing."""
    observed_prompt = ""

    async def fake_llm(*, prompt: str, **_: Any) -> dict[str, Any]:
        nonlocal observed_prompt
        observed_prompt = prompt
        return dict(_RAPAMYCIN_RESPONSE)

    monkeypatch.setattr(evolve, "call_llm_json", fake_llm)
    parent = make_hypothesis(text="parent idea about oxidative stress")
    state = make_state(hypotheses=[parent])

    await evolve_single_hypothesis(
        parent,
        other_hypotheses=[],
        context=EvolutionContext(
            model_name="fake/model",
            meta_review={},
            removed_duplicates=[],
            state=state,
        ),
    )

    assert "Assumptions Verified Incorrect" not in observed_prompt
