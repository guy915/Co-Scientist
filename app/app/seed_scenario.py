"""Store writers that populate one curated demo run's derived rows.

Split out of ``app.seed``: this module turns a ``DemoScenario`` into the
evidence, hypotheses, reviews, citations, matches, report, events, and
metrics a completed run shows. ``app.seed`` decides which runs are seeded;
everything here writes one already-created run's rows.
"""

# The curated payload below is reader-facing scientific prose; keeping each
# source-backed statement intact makes the fixture auditable.
# ruff: noqa: E501

from __future__ import annotations

import dataclasses
import itertools
import time
from typing import Any

from app import store
from app.citations import CitationState
from app.demo_seed_data import (
    DEMO_SEED_VERSION,
    DemoEvidence,
    DemoHypothesis,
    DemoScenario,
    scenario_evidence,
    scenario_hypotheses,
    scenario_key,
)
from app.report_render import ReportRequest, _build_report_content
from app.seed_config_synthesis import (
    curated_critical_criteria,
    curated_stratification_attributes,
)
from app.seed_overview import _curated_meta_review, _curated_research_overview
from app.seed_review_detail import mature_review_rows
from app.store import RunRow


@dataclasses.dataclass(frozen=True)
class _CuratedSeed:
    """One curated scenario's inputs, grouped for the writers below.

    Attributes:
        run: The demo run row being populated.
        scenario: The curated scenario supplying the content.
        evidence: The scenario's full source bundle.
        hypotheses: The scenario's multi-generation hypothesis set.
        db_path: Optional override for the SQLite database path.
    """

    run: RunRow
    scenario: DemoScenario
    evidence: tuple[DemoEvidence, ...]
    hypotheses: tuple[DemoHypothesis, ...]
    db_path: str | None


@dataclasses.dataclass(frozen=True)
class _ScenarioCounts:
    """The row counts one seeded scenario reports in events and metrics.

    Attributes:
        evidence: How many sources were persisted.
        initial_hypotheses: How many hypotheses came from generation.
        hypotheses: How many hypotheses exist across all generations.
        matches: How many tournament matches were recorded.
    """

    evidence: int
    initial_hypotheses: int
    hypotheses: int
    matches: int


def _initial_count(seed: _CuratedSeed) -> int:
    """Return how many of the scenario's hypotheses are first generation."""
    return (
        len(seed.hypotheses)
        - seed.scenario.evolution_count
        - seed.scenario.second_pass_count
    )


def _insert_evidence(seed: _CuratedSeed) -> list[str]:
    """Persist the scenario's sources and return their new row ids."""
    return [
        store.add_evidence(
            store.NewEvidence(
                run_id=seed.run.id,
                title=item.title,
                source="pubmed",
                url=item.url,
                authors=item.authors,
                year=item.year,
                abstract=item.abstract,
            ),
            db_path=seed.db_path,
        )
        for item in seed.evidence
    ]


def _lineage(
    seed: _CuratedSeed, index: int, hypothesis_ids: list[str]
) -> tuple[str | None, int]:
    """Return the parent id and generation for the hypothesis at `index`.

    Returns:
        A ``(parent_id, generation)`` pair; the parent is None for the
        generation-wave ideas, which have no ancestor.
    """
    initial_count = _initial_count(seed)
    if index < initial_count:
        return None, 0
    if index < initial_count + seed.scenario.evolution_count:
        return hypothesis_ids[index - initial_count], 1
    return hypothesis_ids[index - seed.scenario.evolution_count], 2


def _add_hypothesis(
    seed: _CuratedSeed,
    index: int,
    item: DemoHypothesis,
    lineage: tuple[str | None, int],
) -> str:
    """Persist one hypothesis with its ranked state and return its id."""
    parent_id, generation = lineage
    hyp_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=seed.run.id,
            title=item.title,
            statement=item.statement,
            parent_id=parent_id,
            generation=generation,
            category=(
                "Evolved proposal" if parent_id else "Generated proposal"
            ),
            mechanism=item.mechanism,
            expected_effect=item.expected_effect,
            experimental_context=item.experiment,
            created_by_agent="evolve" if parent_id else "generation",
        ),
        db_path=seed.db_path,
    )
    elo = seed.scenario.elo_ceiling - index * seed.scenario.elo_step
    store.update_hypothesis_state(
        hyp_id,
        store.HypothesisStateChanges(
            elo_rating=elo,
            novelty=round(0.86 - index * 0.015, 2),
            safety_status="allow",
            status="active",
        ),
        db_path=seed.db_path,
    )
    return hyp_id


def _add_reviews(
    seed: _CuratedSeed, hyp_id: str, index: int, item: DemoHypothesis
) -> None:
    """Persist the reflection and deep-verification reviews for one idea."""
    for reviewer, summary, critique in (
        (
            "reflection",
            "Mechanistic review: a falsifiable proposal with an explicit test.",
            item.review,
        ),
        (
            "deep_verification",
            "Verification review: advance only if the rescue and orthogonal readout agree.",
            (
                "Probe the proposed mediator with a perturbation, an independent "
                "readout, and a matched control that could falsify the causal chain. "
                + item.review
            ),
        ),
    ):
        store.add_review(
            store.NewReview(
                run_id=seed.run.id,
                hypothesis_id=hyp_id,
                reviewer_agent=reviewer,
                summary=summary,
                critique=critique,
                novelty=round(0.83 - index * 0.012, 2),
                plausibility=round(0.84 - index * 0.01, 2),
                testability=round(0.9 - index * 0.012, 2),
                overall=round(0.86 - index * 0.012, 2),
            ),
            db_path=seed.db_path,
        )


def _add_claim_rows(
    seed: _CuratedSeed,
    hyp_id: str,
    item: DemoHypothesis,
    evidence_ids: list[str],
) -> None:
    """Persist one idea's citation and its claim-level evidence edge."""
    evidence = seed.evidence[item.evidence_index]
    evidence_id = evidence_ids[item.evidence_index]
    claim = item.statement
    store.add_citation(
        store.NewCitation(
            run_id=seed.run.id,
            hypothesis_id=hyp_id,
            evidence_id=evidence_id,
            claim=claim,
            state=CitationState.PARTIAL,
        ),
        db_path=seed.db_path,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=seed.run.id,
            hypothesis_id=hyp_id,
            claim=claim,
            label="partial",
            claim_role="speculative",
            supporting=[
                {
                    "evidence_id": evidence_id,
                    "source_title": evidence.title,
                    "url": evidence.url,
                    "quote": f"Curated paraphrase: {evidence.abstract}",
                }
            ],
            contradicting=[],
            assessor="curated-demo-v3",
        ),
        db_path=seed.db_path,
    )


def _seed_hypotheses(seed: _CuratedSeed, evidence_ids: list[str]) -> list[str]:
    """Persist every hypothesis with its lineage, reviews, and citations.

    Returns:
        The new hypothesis row ids, in the scenario's ranked order.
    """
    key = scenario_key(seed.scenario)
    hypothesis_ids: list[str] = []
    for index, item in enumerate(seed.hypotheses):
        lineage = _lineage(seed, index, hypothesis_ids)
        hyp_id = _add_hypothesis(seed, index, item, lineage)
        hypothesis_ids.append(hyp_id)
        _add_reviews(seed, hyp_id, index, item)
        # Only the scenario's highest-ranked ideas carry a curated
        # full/simulation review row (audit E1) -- mirroring how a real
        # run reserves the mature cascade's more expensive review types
        # for fewer candidates (see the root AGENTS.md per-item-LLM-pass
        # Gotcha).
        for review in mature_review_rows(seed.run.id, hyp_id, key, index):
            store.add_review(review, db_path=seed.db_path)
        _add_claim_rows(seed, hyp_id, item, evidence_ids)
    return hypothesis_ids


def _matchups(count: int) -> list[tuple[int, int]]:
    """Return the ranked index pairs the curated tournament judged.

    Returns:
        Every adjacent pair, then a second pass across the halves, so no
        idea is shown unranked.
    """
    matchups = list(itertools.pairwise(range(count)))
    half = count // 2
    matchups.extend(
        (index, index + half) for index in range(min(half, count - half))
    )
    return matchups


def _match_row(
    seed: _CuratedSeed,
    iteration: int,
    pair: tuple[int, int],
    hypothesis_ids: list[str],
) -> store.NewMatch:
    """Build the match row for one ranked pair, with its Elo movement."""
    winner_index, loser_index = pair
    scenario = seed.scenario
    winner_elo = scenario.elo_ceiling - winner_index * scenario.elo_step
    loser_elo = scenario.elo_ceiling - loser_index * scenario.elo_step
    return store.NewMatch(
        run_id=seed.run.id,
        iteration=iteration,
        winner_id=hypothesis_ids[winner_index],
        loser_id=hypothesis_ids[loser_index],
        winner_before=winner_elo - 12,
        winner_after=winner_elo,
        loser_before=loser_elo + 12,
        loser_after=loser_elo,
        rationale=(
            "The winner paired a more specific causal perturbation with "
            "a clearer falsification and replication path."
        ),
        tier="clear" if iteration % 3 else "narrow",
        debate_turns=2 if iteration % 4 else 3,
    )


def _record_match(
    seed: _CuratedSeed,
    iteration: int,
    pair: tuple[int, int],
    hypothesis_ids: list[str],
) -> None:
    """Persist one tournament match and both competitors' win/loss counts."""
    match = _match_row(seed, iteration, pair, hypothesis_ids)
    store.add_match(match, db_path=seed.db_path)
    store.update_hypothesis_state(
        match.winner_id,
        store.HypothesisStateChanges(win_delta=1),
        db_path=seed.db_path,
    )
    store.update_hypothesis_state(
        match.loser_id,
        store.HypothesisStateChanges(loss_delta=1),
        db_path=seed.db_path,
    )


def _seed_tournament(
    seed: _CuratedSeed, hypothesis_ids: list[str]
) -> list[tuple[int, int]]:
    """Persist the curated tournament and return the matchups it judged."""
    matchups = _matchups(len(hypothesis_ids))
    for iteration, pair in enumerate(matchups, start=1):
        _record_match(seed, iteration, pair, hypothesis_ids)
    return matchups


def _seed_proximity(seed: _CuratedSeed, hypothesis_ids: list[str]) -> None:
    """Persist the curated proximity edge between the two leading ideas."""
    if len(hypothesis_ids) > 1:
        store.add_proximity_edge(
            store.NewProximityEdge(
                run_id=seed.run.id,
                source_hypothesis_id=hypothesis_ids[0],
                target_hypothesis_id=hypothesis_ids[1],
                similarity=0.42,
                degree="related",
                cluster_id="curated-mechanisms",
                method="curated-demo",
                version=str(DEMO_SEED_VERSION),
            ),
            db_path=seed.db_path,
        )


def _scenario_report_request(
    seed: _CuratedSeed,
    hypothesis_ids: list[str],
    overview: dict[str, Any],
    meta_review: dict[str, Any],
) -> ReportRequest:
    """Assemble the curated report's build inputs from the seed scenario."""
    setup = (
        seed.run.config.get("setup")
        if isinstance(seed.run.config, dict)
        else None
    )
    key = scenario_key(seed.scenario)
    return ReportRequest(
        research_goal=seed.run.research_goal,
        run_mode=seed.run.profile,
        provider=seed.run.provider,
        citation_summary={"partial": len(hypothesis_ids)},
        meta_review=meta_review,
        research_overview=overview,
        summary=seed.scenario.summary,
        execution_time=seed.scenario.duration_seconds,
        setup=setup if isinstance(setup, dict) else None,
        # Supervisor-synthesized guidance (R12-17/R12-18/R12-23): a
        # different, goal-specific field from ``setup`` above -- see
        # ``report_markdown_supervisor.py``'s vocabulary warning.
        attributes=curated_stratification_attributes(key),
        critical_criteria=curated_critical_criteria(key),
        prepared_at=time.time(),
        db_path=seed.db_path,
    )


async def _save_scenario_report(
    seed: _CuratedSeed, hypothesis_ids: list[str]
) -> dict[str, Any]:
    """Build and persist the curated report; return its meta-review payload."""
    overview = _curated_research_overview(
        seed.scenario, seed.evidence, seed.hypotheses, hypothesis_ids
    )
    meta_review = _curated_meta_review(seed.scenario)
    built = await _build_report_content(
        seed.run.id,
        _scenario_report_request(seed, hypothesis_ids, overview, meta_review),
    )
    payload = {**built.payload, "demo_seed_version": DEMO_SEED_VERSION}
    banner = (
        "> **Curated demonstration only.** These are illustrative research "
        "proposals, not validated findings or treatment guidance.\n\n"
    )
    store.save_report(
        seed.run.id,
        payload,
        store.ReportMarkdownDocuments(
            banner + built.markdown, banner + built.ranking_markdown
        ),
        db_path=seed.db_path,
    )
    return meta_review


def _emit_scenario_events(
    seed: _CuratedSeed, counts: _ScenarioCounts, meta_review: dict[str, Any]
) -> None:
    """Append the stage events a completed run's timeline shows."""
    for event_type, event_payload in (
        ("supervisor.plan", {"summary": "Curated demo plan prepared."}),
        ("literature_review", {"evidence_count": counts.evidence}),
        ("generate", {"hypothesis_count": counts.initial_hypotheses}),
        ("reflection", {"review_count": counts.hypotheses * 2}),
        ("ranking", {"match_count": counts.matches}),
        (
            "evolve",
            {"hypothesis_count": counts.hypotheses - counts.initial_hypotheses},
        ),
        ("meta_review", {"summary": meta_review["summary"]}),
        ("research_overview", {"knowledge_topics": 6}),
        ("report", {"hypothesis_count": counts.hypotheses}),
        ("status", {"status": "completed"}),
    ):
        store.append_event(
            seed.run.id, event_type, event_payload, db_path=seed.db_path
        )


def _finalize_scenario_run(seed: _CuratedSeed, counts: _ScenarioCounts) -> None:
    """Complete the run and persist the metrics its Learning tab reads."""
    duration = seed.scenario.duration_seconds
    store.update_run_status(
        seed.run.id, store.RunStatus.COMPLETED, db_path=seed.db_path
    )
    store.set_run_timing(seed.run.id, duration, db_path=seed.db_path)
    store.save_run_metrics(
        seed.run.id,
        {
            "total_time": duration,
            "hypothesis_count": counts.hypotheses,
            "reviews_count": counts.hypotheses * 2,
            "tournaments_count": counts.matches,
            "evolutions_count": counts.hypotheses - counts.initial_hypotheses,
            "llm_calls": 86,
            "phase_times": {
                "literature_review": round(duration * 0.18, 1),
                "generate": round(duration * 0.24, 1),
                "reflection": round(duration * 0.27, 1),
                "ranking": round(duration * 0.17, 1),
                "research_overview": round(duration * 0.14, 1),
            },
        },
        db_path=seed.db_path,
    )


async def _seed_curated_scenario(
    run: RunRow, scenario: DemoScenario, db_path: str | None
) -> None:
    """Replace one demo's derived rows with a complete illustrative scenario."""
    store.clear_run_derived_data(run.id, db_path=db_path)
    store.set_run_title(run.id, scenario.title, db_path=db_path)
    seed = _CuratedSeed(
        run=run,
        scenario=scenario,
        evidence=scenario_evidence(scenario),
        hypotheses=scenario_hypotheses(scenario),
        db_path=db_path,
    )
    evidence_ids = _insert_evidence(seed)
    hypothesis_ids = _seed_hypotheses(seed, evidence_ids)
    matchups = _seed_tournament(seed, hypothesis_ids)
    _seed_proximity(seed, hypothesis_ids)
    meta_review = await _save_scenario_report(seed, hypothesis_ids)
    counts = _ScenarioCounts(
        evidence=len(evidence_ids),
        initial_hypotheses=_initial_count(seed),
        hypotheses=len(hypothesis_ids),
        matches=len(matchups),
    )
    _emit_scenario_events(seed, counts, meta_review)
    _finalize_scenario_run(seed, counts)
