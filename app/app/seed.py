"""Startup seeding for complete, curated demo runs.

Creates three browseable examples for newcomers. The default scenarios are
curated, illustrative fixtures with realistic run artifacts; ad-hoc seed
calls retain the real offline-engine fallback used by tests and developers.
"""

# The curated payload below is reader-facing scientific prose; keeping each
# source-backed statement intact makes the fixture auditable.
# ruff: noqa: E501, C901

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any

from app import store, task_worker
from app.citations import CitationState
from app.demo_seed_data import (
    DEMO_SCENARIOS,
    DEMO_SEED_VERSION,
    DemoScenario,
    scenario_evidence,
    scenario_hypotheses,
)
from app.report_render import ReportRequest, _build_report_content
from app.run_modes import PlanningLists, resolved_run_config, setup_config
from app.store import DEMO_CLIENT_ID, RunRow

logger = logging.getLogger(__name__)

# The fallback engine path stays intentionally small. Curated scenarios do
# not consume this budget, but direct callers can still ask to seed an
# arbitrary goal through the deterministic engine.
_DEMO_TIER = "express"

_DEMO_GOALS: list[str] = [
    "What mechanisms drive antibiotic resistance in Staphylococcus aureus "
    "biofilms, and which metabolic pathways could be targeted to restore "
    "susceptibility?",
    "How does synaptic pruning in the prefrontal cortex contribute to "
    "cognitive flexibility during adolescent development?",
    "What are the key molecular regulators of ferroptosis in pancreatic cancer "
    "cells, and how might their modulation enhance chemotherapy sensitivity?",
]


def _build_demo_run_config(goal: str) -> dict[str, Any]:
    """Build the resolved run config for one demo goal.

    The marker allows deployed instances to replace an older thin demo with
    the current curated artifact bundle exactly once.
    """
    scenario = DEMO_SCENARIOS.get(goal)
    config = resolved_run_config(
        {
            "setup": setup_config(
                research_goal=goal,
                tier="standard",
                focus="balance",
                lists=_scenario_planning_lists(scenario),
            ),
            "enable_literature_review": False,
            "llm_backend": "offline",
        }
    )
    config["demo_seed_version"] = DEMO_SEED_VERSION
    return config


def _scenario_planning_lists(scenario: DemoScenario | None) -> PlanningLists:
    """Return the goal detail fields shown for a curated demo run."""
    if scenario is None:
        return PlanningLists()
    if "Biofilms" in scenario.title:
        return PlanningLists(
            requirements=[
                "Separate phenotypic antibiotic tolerance from stable resistance.",
                "Use mature biofilms, clinical-isolate replication, and matched planktonic controls.",
                "Advance only mechanisms with a measurable perturbation, rescue, and kill-curve readout.",
                "Measure matrix permeability and cellular physiology in the same intact-biofilm experiment.",
                "Distinguish transient persister recovery from stable small-colony or resistance lineages.",
                "Do not infer clinical treatment benefit from the preclinical demonstration.",
            ],
            attributes=[
                "Spatially resolved",
                "Mechanistically discriminating",
                "Preclinical and falsifiable",
                "Strain-aware",
                "Replication-ready",
            ],
            criteria=["Causal specificity", "Biofilm relevance", "Experimental tractability", "Safety"],
        )
    if "Circuit" in scenario.title:
        return PlanningLists(
            requirements=[
                "Resolve developmental timing rather than treating adolescence as a single window.",
                "Measure circuit, cellular, and behavioral outcomes in the same experimental framework.",
                "Include sex, subregion, locomotor, and stress controls before assigning a flexibility phenotype.",
                "Separate total synapse number from selective refinement of activity-defined synapses.",
                "Use temporally restricted perturbations and an age-matched adult control condition.",
                "Treat the model as developmental neuroscience, not a clinical disease mechanism.",
            ],
            attributes=[
                "Longitudinal",
                "Cell-type specific",
                "Behaviorally anchored",
                "Window-specific",
                "Multimodal",
            ],
            criteria=["Temporal specificity", "Circuit-to-behavior link", "Causal perturbation", "Replicability"],
        )
    return PlanningLists(
        requirements=[
            "Treat every proposed combination as a preclinical, biomarker-stratified hypothesis.",
            "Distinguish ferroptosis from apoptosis and other death pathways with orthogonal rescue controls.",
            "Validate a locked prediction in independent cell-line and organoid models before translation.",
            "Measure lipid peroxidation, redox state, and clonogenic survival on a time-resolved schedule.",
            "Test target engagement and a genetic rescue before interpreting a drug combination as pathway-specific.",
            "Do not infer patient benefit or recommend treatment from the demonstration data.",
        ],
        attributes=[
            "Mechanistically explicit",
            "Biomarker-guided",
            "Experiment-ready",
            "Death-pathway resolved",
            "Preclinical only",
        ],
        criteria=["Pathway specificity", "Model generalizability", "Combination rationale", "Safety"],
    )


def _ensure_demo_run_row(
    goal: str,
    run: RunRow | None,
    config: dict[str, Any],
    db_path: str | None,
) -> RunRow:
    """Return `run`, creating the demo run row first if one doesn't exist."""
    if run is not None:
        return run
    scenario = DEMO_SCENARIOS.get(goal)
    return store.create_run(
        goal,
        _DEMO_TIER,
        "engine",
        config,
        store.RunCreateOptions(
            client_id=DEMO_CLIENT_ID,
            title=scenario.title if scenario else None,
            llm_backend="offline",
            db_path=db_path,
        ),
    )


def _drive_demo_run(run_id: str, db_path: str | None) -> None:
    """Drain one demo run's durable task chain to completion.

    Runs a bounded worker cohort on its own event loop, exactly as the
    embedded API worker does for a real ``POST /start`` (see
    ``runs_lifecycle._enqueue_workflow_and_maybe_launch_worker``). The cohort
    returns once the run has no ready task left -- i.e. once it has reached a
    terminal state and persisted its report -- so the caller can rely on the
    demo run being complete when this returns.
    """
    policy = task_worker.WorkerPolicy(db_path=db_path)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run_id,
            f"demo-seed:{run_id[:8]}",
            policy=policy,
        )
    )


def _scenario_report_is_current(run: RunRow, db_path: str | None) -> bool:
    """Return whether a curated scenario has the current artifact revision."""
    report = store.get_latest_report(run.id, db_path=db_path)
    return bool(
        report
        and report["payload"].get("demo_seed_version") == DEMO_SEED_VERSION
    )


def _curated_research_overview(
    scenario: DemoScenario,
    evidence: tuple[Any, ...],
    hypotheses: tuple[Any, ...],
) -> dict[str, Any]:
    """Build the complete terminal synthesis shape used by real runs."""
    top = hypotheses[:3]
    directions = [
        {
            "title": item.title,
            "importance": item.mechanism,
            "suggested_experiments": [
                item.experiment,
                "Repeat the discriminating condition in an independent model set with a prespecified rescue criterion.",
            ],
        }
        for item in top
    ]
    aims = [
        {
            "aim": f"Aim {index}: Test {item.title}",
            "rationale": item.statement,
            "approach": item.experiment,
        }
        for index, item in enumerate(top, start=1)
    ]
    knowledge_base = [
        {
            "title": item.title,
            "summary": item.mechanism,
            "detail": item.experiment,
            "uncertainty": item.review,
            "references": [
                {"title": evidence[item.evidence_index].title},
                {"title": evidence[(item.evidence_index + 1) % len(evidence)].title},
            ],
        }
        for item in hypotheses[:6]
    ]
    contacts = [
        {
            "candidate_id": f"demo-contact-{index + 1}",
            "name": evidence_item.authors[0].replace(" et al.", ""),
            "expertise": (
                "Author of a source analyzed in this demonstration; their paper "
                "is relevant to the experimental and mechanistic question."
            ),
            "justification": (
                "This suggestion is derived only from the authorship metadata of "
                "a source in the run and is not a recommendation or contact claim."
            ),
            "source_id": f"demo-evidence-{index + 1}",
            "source_title": evidence_item.title,
            "source_url": evidence_item.url,
            "source": "pubmed",
        }
        for index, evidence_item in enumerate(evidence[:3])
    ]
    return {
        "overview": {
            "summary": (
                f"{scenario.meta_review} The ranked program deliberately keeps "
                "competing mechanisms separate, then uses perturbation, rescue, "
                "and independent-model replication to decide which should advance."
            ),
            "research_directions": directions,
        },
        "nih_specific_aims": {
            "introduction": (
                "This curated demonstration models a grant-style synthesis: the "
                "central gap is not whether the broad phenomenon exists, but which "
                "specific causal mechanism is both measurable and falsifiable."
            ),
            "aims": aims,
            "impact": (
                "The intended output is a reproducible decision framework for "
                "prioritizing a preclinical mechanism. It is illustrative only and "
                "does not establish a clinical intervention."
            ),
        },
        "research_contacts": contacts,
        "knowledge_base": knowledge_base,
    }


def _curated_meta_review(scenario: DemoScenario) -> dict[str, Any]:
    """Create a full meta-review payload rather than a one-line summary."""
    return {
        "summary": scenario.meta_review,
        "common_strengths": [
            "The highest-ranked ideas name a specific mediator, perturbation, readout, and falsification criterion.",
            "The program preserves multiple causal explanations instead of collapsing to one generic mechanism.",
        ],
        "common_weaknesses": [
            "The cited literature is contextual support, not direct proof of each proposed causal chain.",
            "Model-system effects and generic stress responses must be separated from the nominated mechanism.",
            "Every promising result needs an independent replication set before it is used for prioritization.",
        ],
        "emerging_themes": [
            "Time-resolved state measurements are more discriminating than a single terminal viability readout.",
            "Biomarker or state stratification can prevent an average effect from being mistaken for a universal mechanism.",
        ],
        "strategic_recommendations": [
            {
                "focus_area": "Causal inference",
                "recommendation": "Pair each perturbation with a rescue and an orthogonal assay before advancing it in the ranking.",
                "justification": "A correlated marker or single readout cannot establish the proposed mechanism.",
            },
            {
                "focus_area": "Replication",
                "recommendation": "Reserve an independent model set for a locked confirmatory experiment.",
                "justification": "The demo intentionally mirrors a real run's need to test generalizability.",
            },
        ],
    }


def _seed_curated_scenario(
    run: RunRow, scenario: DemoScenario, db_path: str | None
) -> None:
    """Replace one demo's derived rows with a complete illustrative scenario."""
    store.clear_run_derived_data(run.id, db_path=db_path)
    store.set_run_title(run.id, scenario.title, db_path=db_path)
    evidence_items = scenario_evidence(scenario)
    hypothesis_items = scenario_hypotheses(scenario)
    evidence_ids = [
        store.add_evidence(
            store.NewEvidence(
                run_id=run.id,
                title=item.title,
                source="pubmed",
                url=item.url,
                authors=item.authors,
                year=item.year,
                abstract=item.abstract,
            ),
            db_path=db_path,
        )
        for item in evidence_items
    ]
    hypothesis_ids: list[str] = []
    for index, item in enumerate(hypothesis_items):
        parent_id = hypothesis_ids[index - 9] if index >= 9 else None
        hyp_id = store.add_hypothesis(
            store.NewHypothesis(
                run_id=run.id,
                title=item.title,
                statement=item.statement,
                parent_id=parent_id,
                generation=1 if parent_id else 0,
                category=("Evolved proposal" if parent_id else "Generated proposal"),
                mechanism=item.mechanism,
                expected_effect=item.expected_effect,
                experimental_context=item.experiment,
                created_by_agent="evolve" if parent_id else "generation",
            ),
            db_path=db_path,
        )
        hypothesis_ids.append(hyp_id)
        elo = scenario.elo_ceiling - index * scenario.elo_step
        store.update_hypothesis_state(
            hyp_id,
            store.HypothesisStateChanges(
                elo_rating=elo,
                novelty=round(0.86 - index * 0.015, 2),
                safety_status="allow",
                status="active",
            ),
            db_path=db_path,
        )
        evidence = evidence_items[item.evidence_index]
        evidence_id = evidence_ids[item.evidence_index]
        claim = item.statement
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
                    run_id=run.id,
                    hypothesis_id=hyp_id,
                    reviewer_agent=reviewer,
                    summary=summary,
                    critique=critique,
                    novelty=round(0.83 - index * 0.012, 2),
                    plausibility=round(0.84 - index * 0.01, 2),
                    testability=round(0.9 - index * 0.012, 2),
                    overall=round(0.86 - index * 0.012, 2),
                ),
                db_path=db_path,
            )
        store.add_citation(
            store.NewCitation(
                run_id=run.id,
                hypothesis_id=hyp_id,
                evidence_id=evidence_id,
                claim=claim,
                state=CitationState.PARTIAL,
            ),
            db_path=db_path,
        )
        store.add_claim_evidence(
            store.NewClaimEvidence(
                run_id=run.id,
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
            db_path=db_path,
        )
    matchups = list(itertools.pairwise(range(len(hypothesis_ids))))
    matchups.extend((index, index + 9) for index in range(9))
    for iteration, (winner_index, loser_index) in enumerate(matchups, start=1):
        winner = hypothesis_ids[winner_index]
        loser = hypothesis_ids[loser_index]
        winner_elo = scenario.elo_ceiling - winner_index * scenario.elo_step
        loser_elo = scenario.elo_ceiling - loser_index * scenario.elo_step
        store.add_match(
            store.NewMatch(
                run_id=run.id,
                iteration=iteration,
                winner_id=winner,
                loser_id=loser,
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
            ),
            db_path=db_path,
        )
        store.update_hypothesis_state(
            winner,
            store.HypothesisStateChanges(win_delta=1),
            db_path=db_path,
        )
        store.update_hypothesis_state(
            loser,
            store.HypothesisStateChanges(loss_delta=1),
            db_path=db_path,
        )
    if len(hypothesis_ids) > 1:
        store.add_proximity_edge(
            store.NewProximityEdge(
                run_id=run.id,
                source_hypothesis_id=hypothesis_ids[0],
                target_hypothesis_id=hypothesis_ids[1],
                similarity=0.42,
                degree="related",
                cluster_id="curated-mechanisms",
                method="curated-demo",
                version=str(DEMO_SEED_VERSION),
            ),
            db_path=db_path,
        )
    overview = _curated_research_overview(
        scenario, evidence_items, hypothesis_items
    )
    meta_review = _curated_meta_review(scenario)
    built = _build_report_content(
        run.id,
        ReportRequest(
            research_goal=run.research_goal,
            run_mode=run.profile,
            provider=run.provider,
            citation_summary={"partial": len(hypothesis_ids)},
            meta_review=meta_review,
            research_overview=overview,
            summary=scenario.summary,
            execution_time=scenario.duration_seconds,
            db_path=db_path,
        ),
    )
    payload = {**built.payload, "demo_seed_version": DEMO_SEED_VERSION}
    markdown = (
        "> **Curated demonstration only.** These are illustrative research "
        "proposals, not validated findings or treatment guidance.\n\n"
        + built.markdown
    )
    store.save_report(run.id, payload, markdown, db_path=db_path)
    for event_type, event_payload in (
        ("supervisor.plan", {"summary": "Curated demo plan prepared."}),
        ("literature_review", {"evidence_count": len(evidence_ids)}),
        ("generate", {"hypothesis_count": len(hypothesis_ids)}),
        ("reflection", {"review_count": len(hypothesis_ids) * 2}),
        ("ranking", {"match_count": len(matchups)}),
        ("evolve", {"hypothesis_count": len(hypothesis_ids) // 2}),
        ("meta_review", {"summary": meta_review["summary"]}),
        ("research_overview", {"knowledge_topics": 6}),
        ("report", {"hypothesis_count": len(hypothesis_ids)}),
        ("status", {"status": "completed"}),
    ):
        store.append_event(run.id, event_type, event_payload, db_path=db_path)
    store.update_run_status(run.id, store.RunStatus.COMPLETED, db_path=db_path)
    store.set_run_timing(run.id, scenario.duration_seconds, db_path=db_path)
    store.save_run_metrics(
        run.id,
        {
            "total_time": scenario.duration_seconds,
            "hypothesis_count": len(hypothesis_ids),
            "reviews_count": len(hypothesis_ids) * 2,
            "tournaments_count": len(matchups),
            "evolutions_count": len(hypothesis_ids) // 2,
            "llm_calls": 86,
            "phase_times": {
                "literature_review": round(scenario.duration_seconds * 0.18, 1),
                "generate": round(scenario.duration_seconds * 0.24, 1),
                "reflection": round(scenario.duration_seconds * 0.27, 1),
                "ranking": round(scenario.duration_seconds * 0.17, 1),
                "research_overview": round(scenario.duration_seconds * 0.14, 1),
            },
        },
        db_path=db_path,
    )


async def _seed_demo_run(
    goal: str,
    run: RunRow | None,
    db_path: str | None,
) -> None:
    """Create one curated default scenario or an offline-engine fallback.

    Known default goals receive a complete curated fixture. Other callers use
    the existing durable, deterministic engine path, keeping a realistic
    exercise route available without making product examples depend on it.

    Args:
        goal: The demo research goal to seed.
        run: The existing run row for this goal, or None to create one.
        db_path: Optional override for the SQLite database path.
    """
    config = _build_demo_run_config(goal)
    run = _ensure_demo_run_row(goal, run, config, db_path)
    scenario = DEMO_SCENARIOS.get(goal)
    if scenario is not None:
        _seed_curated_scenario(run, scenario, db_path)
        logger.info("Seeded curated demo run %s (%.60s…)", run.id[:8], goal)
        return
    task_worker.enqueue_run_workflow(run.id, db_path=db_path)
    # Run the cohort on its own loop/thread (mirroring the embedded worker)
    # and await it, so seeding blocks until the run is complete rather than
    # racing startup.
    await asyncio.to_thread(_drive_demo_run, run.id, db_path)
    logger.info("Seeded offline engine demo run %s (%.60s…)", run.id[:8], goal)


def _runs_by_goal(runs: list[RunRow]) -> dict[str, RunRow]:
    """Index demo run rows by their research goal for lookup."""
    return {r.research_goal: r for r in runs}


def _has_readable_report(run: RunRow, db_path: str | None) -> bool:
    """True if `run` already has a persisted, readable report markdown."""
    return store.read_report_markdown(run.id, db_path=db_path) is not None


async def _seed_or_reseed_demo_run(
    goal: str,
    run: RunRow | None,
    db_path: str | None,
) -> None:
    """Seed `goal`, skipping an existing demo at the current revision.

    A failed seed must not take down app startup; it is logged and swallowed
    here so the caller can move on to the next demo goal.
    """
    if run is not None:
        scenario = DEMO_SCENARIOS.get(goal)
        current = (
            _scenario_report_is_current(run, db_path)
            if scenario is not None
            else _has_readable_report(run, db_path)
        )
        if current:
            logger.info(
                "demo run %s already has a report, skipping", run.id[:8]
            )
            return
        logger.info(
            "demo run %s exists but has no readable report; re-seeding",
            run.id[:8],
        )
    try:
        await _seed_demo_run(goal, run, db_path)
    except Exception:
        logger.exception("Failed to seed demo run for goal: %.60s", goal)


async def seed_demo_runs(db_path: str | None = None) -> None:
    """Seed demo runs if they are not already present.

    Also re-seeds any existing demo run whose report is missing or
    unreadable (e.g. after a container restart that cleared the on-disk
    .md files before the markdown_text column was added).
    """
    # main.py's lifespan already installs the offline router unconditionally
    # before calling this, but this function is also exercised directly (by
    # tests) without that lifespan running first. Installing it here too is
    # idempotent and guarantees the demo runs' offline/ model calls resolve
    # regardless of caller.
    from co_scientist.offline_llm import install_offline_router

    install_offline_router()

    existing = store.list_runs(client_id=DEMO_CLIENT_ID, db_path=db_path)
    existing_by_goal = _runs_by_goal(existing)

    for goal in _DEMO_GOALS:
        await _seed_or_reseed_demo_run(
            goal, existing_by_goal.get(goal), db_path
        )
