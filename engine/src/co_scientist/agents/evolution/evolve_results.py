"""Applying evolution LLM responses and building the evolve state delta."""

import dataclasses
import logging
from typing import Any

from co_scientist.agents.evolution.evolve_context import find_nearest_peer
from co_scientist.agents.evolution.evolve_prompt import (
    _EvolutionContext,
    _EvolutionOperation,
)
from co_scientist.agents.generation.citations import resolve_citation_keys
from co_scientist.agents.generation.experiment_plan import (
    format_experiment_plan,
)
from co_scientist.constants import (
    DUPLICATE_SIMILARITY_THRESHOLD,
    INITIAL_ELO_RATING,
)
from co_scientist.models import (
    Hypothesis,
    HypothesisOrigin,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.state import AppendHypotheses

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _RefinedFields:
    """The refined content an evolution LLM response yields for a child.

    The four proposal sections default to ``None`` because a response that
    does not carry one leaves the child without it -- never with its
    parent's. See ``_section_or_none``.
    """

    refined_text: str
    title: str | None
    explanation: str | None
    experiment: str | None
    refinement_summary: str
    introduction: str | None = None
    recent_findings: str | None = None
    literature_grounding: str | None = None
    safety_and_toxicity: str | None = None


def _section_or_none(response: dict[str, Any], key: str) -> str | None:
    """One proposal section from the response, or None if it has none.

    Blank counts as absent: under the json_object downgrade
    ``llm_json._backfill_required_fields`` inserts ``""`` for a missing
    required string, and an empty mechanism must read as "this child has
    no mechanism section" rather than fall back to the parent's.
    """
    value = response.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _extract_evolution_fields(
    hypothesis: Hypothesis, response: dict[str, Any]
) -> _RefinedFields:
    """Extracts the refined fields from an evolution LLM response.

    Args:
        hypothesis: Hypothesis being evolved; supplies fallback values for
            fields the response omits.
        response: Parsed JSON response from the evolution LLM call.

    Returns:
        The refined text, explanation, experiment, refinement summary, and
        the child's own four proposal sections.
    """
    # Prefer the canonical "hypothesis" key; fall back to the legacy
    # "refined_hypothesis_text" name, and finally to the pre-evolution text
    # if the LLM response omits both (defensive against malformed output).
    refined_text = response.get("hypothesis") or response.get(
        "refined_hypothesis_text", hypothesis.text
    )
    # R14-20: the response's "experiment" is EVOLUTION_SCHEMA's structured
    # pilot-plan object -- ordered steps plus separately bolded Go/No-Go
    # criteria (or a degraded shape under the json_object downgrade);
    # format_experiment_plan renders it back to the plain-string prose
    # _RefinedFields.experiment expects, falling back to the
    # pre-evolution experiment when the response has nothing usable.
    #
    # R14-12: "title" is carried through unvalidated, same as citations.py's
    # hypothesis_from_llm_output -- a missing/malformed/empty value is left
    # None here rather than inheriting the parent's (now possibly stale)
    # title, since the app's drain derives a fresh fallback from the
    # child's own refined_text when title is absent.
    return _RefinedFields(
        refined_text=refined_text,
        title=response.get("title"),
        explanation=response.get("explanation", hypothesis.explanation),
        experiment=format_experiment_plan(
            response.get("experiment"), fallback=hypothesis.experiment
        ),
        refinement_summary=response.get(
            "refinement_summary", "no refinement summary provided"
        ),
        introduction=_section_or_none(response, "introduction"),
        recent_findings=_section_or_none(response, "recent_findings"),
        literature_grounding=_section_or_none(response, "literature_grounding"),
        safety_and_toxicity=_section_or_none(response, "safety_and_toxicity"),
    )


def _resolve_parents(
    hypothesis: Hypothesis,
    response: dict[str, Any],
    partners: tuple[Hypothesis, ...],
) -> list[Hypothesis]:
    """The child's parent list: the primary parent plus combined partners.

    Combination identifies the partners it merged by the positional index
    the prompt assigned (never by echoed text), so the response schema stays
    bounded whatever the partners' length. Invalid indices are dropped and
    an unresolvable response degrades to the single primary parent -- a
    combination that names no partner is still a valid refinement.
    """
    if not partners or response.get("_evolution_operator") != "combination":
        return [hypothesis]
    merged = _merged_partners(hypothesis, response, partners)
    return [hypothesis, *merged]


def _merged_partners(
    hypothesis: Hypothesis,
    response: dict[str, Any],
    partners: tuple[Hypothesis, ...],
) -> list[Hypothesis]:
    """Resolve a combination response's partner indices, in order, deduped."""
    resolved: list[Hypothesis] = []
    seen: set[str] = set()
    for raw in response.get("combined_partners") or []:
        partner = _partner_at(partners, raw)
        if partner is None or partner.id == hypothesis.id:
            continue
        if partner.id not in seen:
            seen.add(partner.id)
            resolved.append(partner)
    return resolved


def _partner_at(
    partners: tuple[Hypothesis, ...], raw: Any
) -> Hypothesis | None:
    """Resolve one response index to its partner, or None if invalid.

    Indices are the 1-based positions the prompt assigned; anything else
    (a non-int, or an out-of-range value) is dropped rather than raising.
    """
    if not isinstance(raw, int) or isinstance(raw, bool):
        return None
    if not 1 <= raw <= len(partners):
        return None
    return partners[raw - 1]


def _build_evolution_child(
    parents: list[Hypothesis],
    fields: _RefinedFields,
    creation_iteration: int | None,
    citation_sources: dict[str, dict[str, Any]] | None = None,
) -> Hypothesis:
    """Construct an immutable evolution child from an accepted refinement.

    Paper invariant (SSR §4, §12; TE §5): the Evolution agent *generates a new
    hypothesis*; it never modifies or replaces its parent. The child therefore
    gets a fresh id, points at its parents, increments the generation depth,
    resets Elo to the initial rating with zero matches, and starts with no
    reviews or deep-verification state so it must be reviewed before it can be
    ranked. The parents are not touched.

    Lineage for a multi-parent combination: ``parent_id`` keeps the primary
    parent (the hypothesis that was evolved) so existing lineage consumers
    are unchanged, while ``parent_ids`` records every parent merged.

    ``citation_sources`` is the run's ``[C*]`` reference index, against
    which the child's own grounding paragraph is resolved. The parent's
    ``citation_map`` is deliberately not carried over: it was resolved from
    the paragraph the parent wrote, so beside a rewritten paragraph it
    explains keys the child never cites and omits the ones it does.

    Returns:
        A new child ``Hypothesis`` linked to ``parents``.
    """
    primary = parents[0]
    return Hypothesis(
        text=fields.refined_text,
        title=fields.title,
        parent_id=primary.id,
        parent_ids=[parent.id for parent in parents],
        generation=primary.generation + 1,
        origin=HypothesisOrigin.EVOLUTION,
        creation_iteration=creation_iteration,
        category=primary.category,
        # Scene-setting, mechanism and safety (MO-6, MO-10) are the child's
        # own: EVOLUTION_SCHEMA asks the refinement for all four, and a
        # response that carries none leaves the child with none rather than
        # publishing its parent's under the child's name (see
        # schemas/evolution.py for the production run that forced this).
        introduction=fields.introduction,
        recent_findings=fields.recent_findings,
        safety_and_toxicity=fields.safety_and_toxicity,
        explanation=fields.explanation,
        experiment=fields.experiment,
        literature_grounding=fields.literature_grounding,
        citation_map=resolve_citation_keys(
            fields.literature_grounding, citation_sources or {}
        ),
        # Fresh tournament entrant: Elo 1200, zero matches, unreviewed.
        elo_rating=INITIAL_ELO_RATING,
        win_count=0,
        loss_count=0,
        reviews=[],
        # evolution_history records the derivation chain without mutating the
        # parent: the parent's prior texts plus the parent's own text.
        evolution_history=[*primary.evolution_history, primary.text],
    )


def _build_evolution_detail(
    parents: list[Hypothesis],
    child: Hypothesis,
    fields: _RefinedFields,
) -> dict[str, Any]:
    """Builds the evolution_detail record for an accepted refinement.

    Feeds evolution_details in evolve_node's state delta, which the UI
    surfaces as the rationale for each change; records every parent and the
    child id so the lineage edges are explicit.

    The ``operator`` field is not set here: it is carried on the LLM
    response rather than on the refined fields, so ``_apply_evolution_result``
    is its single writer. Seeding it with a default here as well meant every
    non-enhancement operator was written twice and read once.
    """
    return {
        "parent_id": parents[0].id,
        "parent_ids": [parent.id for parent in parents],
        "child_id": child.id,
        "original": parents[0].text,
        "evolved": fields.refined_text,
        "rationale": fields.refinement_summary,
    }


def _apply_refined_hypothesis(
    parents: list[Hypothesis],
    fields: _RefinedFields,
    max_similarity: float,
    context: _EvolutionContext,
) -> tuple[Hypothesis, dict[str, Any]]:
    """Builds an immutable child for an accepted refinement and its detail.

    The parents are NOT mutated. ``max_similarity`` is the max similarity
    to the sampled peer hypotheses, used only for the debug log; the round
    context supplies the creation iteration and the ``[C*]`` sources the
    child's own grounding paragraph resolves against.

    Returns:
        The new child hypothesis, and its evolution detail.
    """
    child = _build_evolution_child(
        parents,
        fields,
        context.creation_iteration,
        _citation_sources(context),
    )

    logger.debug(
        "evolved hypothesis into child %s (max similarity: %.2f)",
        child.id,
        max_similarity,
    )

    evolution_detail = _build_evolution_detail(parents, child, fields)
    return child, evolution_detail


def _citation_sources(
    context: _EvolutionContext,
) -> dict[str, dict[str, Any]]:
    """The round's ``[C*]`` sources, or an empty table when it has none."""
    if context.reference_index is None:
        return {}
    return context.reference_index.sources


def _rejected_as_unchanged(hypothesis: Hypothesis, refined_text: str) -> bool:
    """True if the refinement echoed the parent text back verbatim.

    The LLM sometimes echoes the input back verbatim (e.g. it judges no
    refinement is warranted); treat this as a no-op that creates no child
    rather than minting a duplicate of the parent.
    """
    if refined_text != hypothesis.text:
        return False
    # Info, not warning: the guard doing its job is a per-item verdict,
    # and the caller already records the attempt as producing no child.
    logger.info("Evolution returned the hypothesis unchanged; no child")
    return True


def _near_duplicate_similarity(
    hypothesis: Hypothesis,
    refined_text: str,
    peers: list[Hypothesis],
    proximity_graph: dict[str, Any] | None,
    excluded_ids: frozenset[str],
) -> float | None:
    """Max similarity to a peer, or None if it crosses the reject threshold.

    DUPLICATE_SIMILARITY_THRESHOLD (0.95) bounds the same decision proximity
    uses for high-similarity clusters; crossing it here means the refinement
    converged onto a peer, so no child is minted. The estimate per peer
    prefers the persisted proximity graph's weighted (LLM-judged) similarity
    and falls back to token coverage -- never union-based Jaccard -- and the
    threshold is only reachable through the strongest signals (a weight-1.0
    edge or near-total coverage). The guard stays deliberately conservative:
    a false duplicate silently and permanently drops a distinct idea, while
    a genuine duplicate that slips through is archived, labelled, and traced
    by the next proximity pass. Combination partners are exempt: a faithful
    merge necessarily resembles the ideas it merges. A targeted outcome
    child uses direct text coverage because a parent-peer graph edge does
    not measure similarity between the new child and that peer.

    Returns:
        The max peer similarity on acceptance, None when rejected.
    """
    guarded_peers = [peer for peer in peers if peer.id not in excluded_ids]
    max_similarity, nearest = find_nearest_peer(
        refined_text,
        hypothesis.id,
        guarded_peers,
        proximity_graph,
    )
    if max_similarity <= DUPLICATE_SIMILARITY_THRESHOLD:
        return max_similarity
    logger.info(
        "Evolution result duplicates an existing hypothesis "
        "(similarity %.2f); no child",
        max_similarity,
    )
    logger.debug("original: %s...", hypothesis.text[:100])
    if nearest is not None:
        logger.debug("similar to: %s...", nearest.text[:100])
    return None


def _apply_evolution_result(
    hypothesis: Hypothesis,
    response: dict[str, Any],
    peers: list[Hypothesis],
    context: _EvolutionContext,
    operation: _EvolutionOperation,
) -> tuple[Hypothesis | None, dict[str, Any] | None]:
    """Turns an LLM evolution response into a child hypothesis, if acceptable.

    Rejects the refinement (creating NO child, ``hypothesis`` never mutated)
    if the LLM echoed the input back verbatim, or if the refined text
    converged too closely onto one of the peer hypotheses shown as diversity
    context.

    Args:
        hypothesis: The hypothesis being evolved (the primary parent).
        response: Parsed LLM response, tagged with the operator used.
        peers: Sampled pool hypotheses forming the duplicate-rejection set.
        context: Run-level evolution context (creation iteration and the
            persisted proximity graph).
        operation: The per-hypothesis operation (its combination partners).

    Returns:
        A ``(child, detail)`` pair on acceptance, or ``(None, None)`` when the
        refinement is rejected (no child created).
    """
    fields = _extract_evolution_fields(hypothesis, response)
    if _rejected_as_unchanged(hypothesis, fields.refined_text):
        return None, None
    parents = _resolve_parents(hypothesis, response, operation.partners)
    max_similarity = _near_duplicate_similarity(
        hypothesis,
        fields.refined_text,
        peers,
        (
            None
            if operation.outcome_refinement is not None
            else context.proximity_graph
        ),
        frozenset(parent.id for parent in parents[1:]),
    )
    if max_similarity is None:
        return None, None
    child, detail = _apply_refined_hypothesis(
        parents, fields, max_similarity, context
    )
    detail["operator"] = str(
        response.get("_evolution_operator") or "enhancement"
    )
    return child, detail


def _collect_evolution_results(
    results: list[tuple[Hypothesis | None, dict[str, Any] | None]],
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Unpacks gathered evolution results into children and details.

    Args:
        results: Per-attempt (child or None, evolution_detail or None) pairs,
            in the same order as the dispatched evolution tasks.

    Returns:
        Tuple of (evolution children, evolution details). A rejected
        refinement contributes neither a child nor a detail, so producing a
        child cannot accidentally resurrect or duplicate a parent.
    """
    children: list[Hypothesis] = []
    evolution_details: list[dict[str, Any]] = []

    for child, detail in results:
        # child/detail are both None when evolve_single_hypothesis rejected
        # the refinement (unchanged text or near-duplicate): no child is
        # minted and nothing is recorded.
        if child is not None:
            children.append(child)
        if detail is not None:
            evolution_details.append(detail)

    return children, evolution_details


def _build_evolve_state_delta(
    children: list[Hypothesis],
    evolution_details: list[dict[str, Any]],
    llm_call_count: int,
) -> dict[str, Any]:
    """Builds the evolve_node state delta: metrics update plus payload.

    ``llm_call_count`` is every LLM call the round spent: one evolution
    attempt per parent plus the query-generation calls the enhancement
    retrievals make when the MCP server is up.

    Returns:
        The evolve_node state delta dictionary.
    """
    # llm_calls counts every attempt (one LLM call per parent, regardless of
    # accept/reject); evolutions_count counts children actually created.
    metrics = create_metrics_update(
        deltas=MetricDeltas(llm_calls=llm_call_count, evolutions=len(children))
    )
    logger.debug(
        "evolve node creating metrics delta: children=%s, llm_calls=%s",
        len(children),
        llm_call_count,
    )

    # AppendHypotheses tells the reducer to ADD these children to the pool
    # rather than replace it: parents (and every other hypothesis) stay in the
    # active pool and both parent and child compete in the next tournament
    # (paper invariant SSR §4, §12).
    return {
        "hypotheses": AppendHypotheses(children),
        "evolution_details": evolution_details,
        "metrics": metrics,
        "messages": phase_message(
            "evolve",
            f"Evolved {len(children)} new child hypotheses",
            evolved_count=len(children),
        ),
    }
