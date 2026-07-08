"""Deterministic mock workflow used when no LLM provider is configured.

It emits the full agent-equivalent sequence the real engine produces — so the
backend, persistence layer, SSE stream, and frontend can be exercised end-to-end
without any external API calls.

Intake safety screening runs upstream at the shared workflow boundary
(``engine_adapter.run_workflow``) before this generator, so it is not emitted
here. Stages emitted (in order):
1. status: running
2. supervisor.plan       — research plan + agent DAG
3. literature_review     — retrieved evidence list
4. generate              — initial hypotheses (initial_count)
5. reflection            — per-hypothesis reflection notes
6. proximity             — clusters
7. ranking               — Elo tournament across pairs
8. evolve                — mutate top-k → child hypotheses (parent_id set)
9. ranking (post-evolve) — second round of Elo updates
10. meta_review          — synthesis critique
11. deep_verification    — probing Q&A + verdict on top-k by Elo (reviews)
12. citation_audit       — classify each citation
13. research_overview    — research overview + NIH Specific Aims (report)
14. safety.final         — final-output gate
15. report               — assembled report
16. status: completed

The output is fully deterministic given (research_goal, run mode, config). This
matters: tests assert against the workflow's behaviour, not flaky LLM output.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.citations import (CitationRecord, classify_citation,
                           empty_citation_summary)
from app.elo import INITIAL_ELO, UPSET_MARGIN, update_pair
from app.report_render import (
    article_stub,
    finalize_report,
    format_deep_verification_critique,
    hypothesis_stub,
    match_stub,
)
from app.run_modes import CANONICAL_RUN_MODE, setup_guidance
from app.store import RunStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seeded_rng(*parts: str) -> random.Random:
    seed = int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16) % (2**
                                                                            32)
    return random.Random(seed)


def _hypothesis_seed(rng: random.Random, goal: str, idx: int) -> dict[str, str]:
    """Generate a deterministic, plausible-sounding hypothesis stub."""
    angles = [
        "modulating regulatory feedback in",
        "rerouting metabolic flux through",
        "perturbing transcriptional control of",
        "stabilizing a transient intermediate in",
        "decoupling co-expression in",
        "enforcing temporal restriction on",
        "exploiting allosteric switching in",
        "leveraging cross-pathway interference in",
    ]
    targets = [
        "the proposed mechanism",
        "the dominant pathway",
        "the upstream regulator",
        "the rate-limiting step",
        "the downstream effector",
        "the bottleneck enzyme",
        "the canonical signalling module",
    ]
    categories = [
        "Regulatory feedback",
        "Metabolic flux",
        "Transcriptional control",
        "Intermediate stabilization",
        "Co-expression decoupling",
        "Temporal restriction",
        "Allosteric switching",
        "Cross-pathway interference",
    ]
    # angles and categories are parallel lists: pick one index and use it for
    # both so the pairing stays explicit (no value-based lookup that could
    # mis-map if an angle were ever duplicated or reordered). randrange consumes
    # the RNG identically to choice, so the deterministic output is unchanged.
    angle_index = rng.randrange(len(angles))
    angle = angles[angle_index]
    target = rng.choice(targets)
    category = categories[angle_index]
    title = f"H{idx + 1}: {angle.capitalize()} {target}".strip()
    statement = (
        f"In the context of '{goal[:120]}', we hypothesise that {angle} {target} will "  # pylint: disable=line-too-long
        "produce a measurable effect via a mechanism distinct from current consensus."  # pylint: disable=line-too-long
    )
    mechanism = (
        f"The proposed pathway operates by {angle} {target}, with feedback at two checkpoints; "  # pylint: disable=line-too-long
        "the predicted intermediate state is detectable by standard assays.")
    expected = (
        "We expect a dose-dependent effect with a saturating response curve, distinguishable "  # pylint: disable=line-too-long
        "from baseline within standard error bounds.")
    experiment = (
        "Run a controlled in-vitro perturbation series with three replicates per condition; "  # pylint: disable=line-too-long
        "validate top hits in an orthogonal model system.")
    return {
        "title": title,
        "category": category,
        "statement": statement,
        "mechanism": mechanism,
        "expected_effect": expected,
        "experimental_context": experiment,
    }


def _evidence_seed(rng: random.Random, goal: str, idx: int) -> dict[str, Any]:
    keywords = [t for t in goal.lower().split() if len(t) > 4
               ][:3] or ["mechanism"]
    keyword = rng.choice(keywords)
    available = rng.random() > 0.15  # ~15% unavailable
    year = rng.randint(2015, 2025)
    return {
        "title": f"Mock study {idx + 1}: {keyword} dynamics in a model system",
        "url": f"https://example.org/mock/{idx + 1}" if available else "",
        "authors": [f"Author{idx + 1}.A.", f"Author{idx + 1}.B."],
        "year": year,
        "abstract": (
            f"This mock abstract discusses {keyword} dynamics, mechanism, regulatory feedback, "  # pylint: disable=line-too-long
            "and a measurable effect under controlled perturbation. It is provided in mock mode "  # pylint: disable=line-too-long
            "so the workflow can be exercised without external network calls."),
        "available": available,
    }


def _cluster_id(idx: int) -> str:
    return f"cluster-{idx % 3}"


# Number of top-ranked hypotheses subjected to deep verification. Hardcoded
# because the mock is offline and must not import the engine constant.
DEEP_VERIFICATION_TOP_K = 3

# Lead paragraph for the mock report, flagging its artefacts as illustrative.
_MOCK_SUMMARY = (
    "This run was executed in deterministic mock mode. Hypotheses, citations, "
    "and tournament results below are illustrative artefacts produced without "
    "any LLM provider.")


def _deep_verification_seed(rng: random.Random, title: str) -> dict[str, Any]:
    """Generate deterministic probing Q&A plus a verdict for a hypothesis.

    Mirrors the canonical deep-verification review: each probe decomposes a
    fundamental assumption and attacks it, judging whether a failing
    assumption is fundamental.

    Args:
        rng: Seeded random generator shared by the workflow.
        title: Title of the hypothesis being probed; woven into the prompts.

    Returns:
        A dict with ``probes`` (a list of question/answer/reasoning/
        ``assumption_is_fundamental`` entries) and a ``verdict`` string.
    """
    probe_templates = [
        (
            "Does the proposed mechanism hold if the upstream regulator is "
            "redundant?",
            "Only partially; a parallel pathway can compensate when the "
            "primary route is blocked.",
            "Compensatory signalling weakens the causal claim but does not "
            "fully refute it.",
            True,
        ),
        (
            "Is the predicted intermediate state uniquely attributable to the "
            "proposed pathway?",
            "Not exclusively; the same readout can arise from an off-target "
            "effect.",
            "Lack of specificity introduces a confound that must be "
            "controlled for.",
            False,
        ),
        (
            "Would the expected dose-response survive in an orthogonal model "
            "system?",
            "Likely, though the effect size may shrink outside the original "
            "assay conditions.",
            "Reproducibility across systems is plausible but unproven.",
            True,
        ),
        (
            "Does the hypothesis depend on an assumption contradicted by "
            "prior work?",
            "One supporting citation is weaker than assumed under closer "
            "reading.",
            "A shaky premise lowers confidence without undermining the whole "
            "hypothesis.",
            False,
        ),
    ]
    probe_count = rng.randint(2, 3)
    chosen = rng.sample(probe_templates, probe_count)
    probes = [{
        "question": f"Regarding '{title[:60]}': {question}",
        "answer": answer,
        "reasoning": reasoning,
        "assumption_is_fundamental": fundamental,
    } for question, answer, reasoning, fundamental in chosen]
    any_fundamental = any(p["assumption_is_fundamental"] for p in probes)
    verdict = rng.choice(["weakened", "undermined"
                         ]) if any_fundamental else "holds"
    return {"probes": probes, "verdict": verdict}


def _research_overview_seed(rng: random.Random, goal: str,
                            top_titles: list[str]) -> dict[str, Any]:
    """Build a deterministic research overview + NIH Specific Aims payload.

    The shape matches the engine's ``research_overview`` exactly so the shared
    markdown renderer keys off the same field names.

    Args:
        rng: Seeded random generator shared by the workflow.
        goal: The natural-language research goal.
        top_titles: Titles of the top-ranked hypotheses, in Elo order.

    Returns:
        A dict shaped as ``{"overview": {...}, "nih_specific_aims": {...}}``.
    """
    lead = top_titles[0] if top_titles else "the leading hypothesis"
    summary = (
        f"Synthesizing the top hypotheses for '{goal[:120]}', a coherent "
        f"research program emerges around {lead.lower()}. The directions "
        "below convert the highest-ranked mechanisms into a testable roadmap.")
    direction_angles = [
        ("Establish the causal mechanism",
         "Confirms the core assumption shared by the top hypotheses."),
        ("Probe pathway redundancy",
         "Determines whether compensatory routes blunt the expected effect."),
        ("Validate in an orthogonal model",
         "Guards against assay-specific artefacts before scale-up."),
    ]
    rng.shuffle(direction_angles)
    research_directions = []
    for idx, (title, importance) in enumerate(direction_angles[:3]):
        research_directions.append({
            "title":
                title,
            "importance":
                importance,
            "suggested_experiments": [
                "Run a controlled perturbation series with three replicates "
                "per condition.",
                "Quantify the readout against baseline for direction "
                f"{idx + 1}.",
            ],
        })
    aims = [{
        "aim": f"Aim {i + 1}: {direction['title']}.",
        "rationale": direction["importance"],
        "approach": direction["suggested_experiments"][0],
    } for i, direction in enumerate(research_directions)]
    nih_specific_aims = {
        "introduction":
            (f"The proposed research targets '{goal[:120]}'. We organize the "
             "top-ranked hypotheses into complementary specific aims."),
        "aims":
            aims,
        "impact":
            ("Successful completion would convert the leading mechanistic "
             "hypothesis into an actionable, falsifiable research program."),
    }
    return {
        "overview": {
            "summary": summary,
            "research_directions": research_directions,
        },
        "nih_specific_aims": nih_specific_aims,
    }


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


async def run_mock_workflow(
    run_id: str,
    research_goal: str,
    config: dict[str, Any],
    *,
    db_path: str | None = None,
    cancelled: asyncio.Event | None = None,
    sleep_seconds: float = 0.05,
) -> AsyncIterator[dict[str, Any]]:
    """Execute the deterministic mock workflow and yield events as they happen.

    Intake safety screening is applied upstream at the shared workflow boundary
    (``engine_adapter.run_workflow``); this generator assumes intake passed.
    ``config`` must already be resolved via ``resolved_run_config`` — the
    shared boundary does this for every provider.
    """
    run_mode = CANONICAL_RUN_MODE
    cfg = config
    rng = _seeded_rng("mock", run_id, research_goal, run_mode)

    def _check_cancel() -> bool:
        return bool(cancelled and cancelled.is_set())

    async def emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        seq = store.append_event(run_id, type_, payload, db_path=db_path)
        await asyncio.sleep(sleep_seconds)
        return {"seq": seq, "type": type_, "payload": payload}

    # ---- 1. Mark running (intake screening runs at the shared boundary) ----
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    yield await emit("status", {"status": "running"})

    # ---- 2. Supervisor plan ----
    plan = {
        "agents": [
            "supervisor",
            "intake",
            "literature_review",
            "generation",
            "reflection",
            "proximity",
            "ranking",
            "evolution",
            "meta_review",
            "citation_audit",
            "safety",
            "report",
        ],
        "run_mode":
            run_mode,
        "config":
            cfg,
        "setup":
            cfg.get("setup", {}),
        "setup_guidance":
            setup_guidance(cfg.get("setup")) if isinstance(
                cfg.get("setup"), dict) else "",
        "narrative": (
            "Plan the canonical hypothesis-generation run for the research goal. Allocate compute across literature, "  # pylint: disable=line-too-long
            f"generation ({cfg['initial_hypotheses_count']} candidates), {cfg['max_iterations']} "  # pylint: disable=line-too-long
            "iterations of reflect/rank/evolve, then synthesize a report."),
    }
    yield await emit("supervisor.plan", plan)
    if _check_cancel():
        store.update_run_status(run_id, RunStatus.CANCELLED, db_path=db_path)
        yield await emit("status", {"status": "cancelled"})
        return

    # ---- 3. Literature review ----
    evidence_count = cfg["evidence_count"]
    evidence_ids: list[str] = []
    evidence_payload: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        for i in range(evidence_count):
            ev = _evidence_seed(rng, research_goal, i)
            ev_id = store.add_evidence(
                run_id,
                title=ev["title"],
                source="mock",
                url=ev["url"],
                authors=ev["authors"],
                year=ev["year"],
                abstract=ev["abstract"],
                available=ev["available"],
                conn=conn,
            )
            evidence_ids.append(ev_id)
            evidence_payload.append({"id": ev_id, **ev})
    yield await emit(
        "literature_review",
        {
            "count": len(evidence_payload),
            "evidence": [article_stub(e) for e in evidence_payload],
        },
    )

    # ---- 4. Generation ----
    initial_count = cfg["initial_hypotheses_count"]
    hyp_ids: list[str] = []
    hyp_payloads: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        for i in range(initial_count):
            h = _hypothesis_seed(rng, research_goal, i)
            hid = store.add_hypothesis(
                run_id,
                title=h["title"],
                statement=h["statement"],
                category=h.get("category"),
                mechanism=h["mechanism"],
                expected_effect=h["expected_effect"],
                experimental_context=h["experimental_context"],
                generation=0,
                created_by_agent="generation",
                conn=conn,
            )
            hyp_ids.append(hid)
            hyp_payloads.append({
                "id": hid,
                **h, "elo_rating": INITIAL_ELO,
                "generation": 0
            })
    yield await emit(
        "generate", {
            "count": len(hyp_payloads),
            "hypotheses": [hypothesis_stub(h) for h in hyp_payloads],
        })

    # ---- 5. Reflection ----
    with store.transaction(db_path) as conn:
        for hid, h in zip(hyp_ids, hyp_payloads):
            critique = (
                f"Reflection: '{h['title']}' offers a plausible mechanism but should be checked against "  # pylint: disable=line-too-long
                "the {N} retrieved sources for prior work; novelty is moderate; testability is high if "  # pylint: disable=line-too-long
                "the experimental context is constrained.").format(
                    N=evidence_count)
            store.add_review(
                run_id,
                hid,
                "reflection",
                summary=f"Initial reflection on {h['title']}",
                critique=critique,
                novelty=round(rng.uniform(0.4, 0.8), 2),
                plausibility=round(rng.uniform(0.5, 0.9), 2),
                testability=round(rng.uniform(0.5, 0.95), 2),
                overall=round(rng.uniform(0.55, 0.85), 2),
                conn=conn,
            )
    yield await emit("reflection", {"reviewed": len(hyp_ids)})

    # ---- 6. Proximity / clustering ----
    clusters: dict[str, list[str]] = {}
    with store.transaction(db_path) as conn:
        for i, hid in enumerate(hyp_ids):
            cid = _cluster_id(i)
            clusters.setdefault(cid, []).append(hid)
            store.update_hypothesis_state(hid, cluster_id=cid, conn=conn)
    yield await emit("proximity",
                     {"clusters": {
                         k: len(v) for k, v in clusters.items()
                     }})

    # ---- 7. First ranking round ----
    elo_state: dict[str, int] = {hid: INITIAL_ELO for hid in hyp_ids}

    # Map each hypothesis id to its seed-deterministic title so the tournament
    # outcome (and thus the leaderboard, deep-verification selection, and the
    # research overview) is reproducible for a fixed (run_id, goal). Keying the
    # judge on the row UUIDs would scramble ordering across runs.
    title_by_id: dict[str, str] = {p["id"]: p["title"] for p in hyp_payloads}

    def _judge(a: str, b: str) -> tuple[str, str, str]:
        # Deterministic: pick by hashing seeded titles so tests are stable.
        a_title = title_by_id.get(a, a)
        b_title = title_by_id.get(b, b)
        if hashlib.sha256(
            (run_id + a_title + b_title).encode()).hexdigest() < hashlib.sha256(
                (run_id + b_title + a_title).encode()).hexdigest():
            return a, b, "Mock judge: 'a' has stronger mechanistic specificity."
        return b, a, "Mock judge: 'b' presents a more decisive experimental test."  # pylint: disable=line-too-long

    pairs = []
    pair_count = cfg["tournament_pairs"]
    for _ in range(pair_count):
        a, b = rng.sample(hyp_ids, 2)
        pairs.append((a, b))

    for itr in range(1, cfg["max_iterations"] + 2):
        pending = store.get_pending_steering(run_id, db_path=db_path)
        if pending:
            steering_note = "; ".join(m.content for m in pending)
            logger.info("run %s iteration %d: applying steering: %s", run_id,
                        itr, steering_note)
            store.mark_steering_applied([m.id for m in pending],
                                        db_path=db_path)
        round_matches = []
        with store.transaction(db_path) as conn:
            for a, b in pairs:
                winner, loser, rationale = _judge(a, b)
                wb = elo_state[winner]
                lb = elo_state[loser]
                # Deterministic decisiveness tier from the pre-match Elo gap.
                # Only the label vocabulary matches the engine's
                # ranking.match_tier -- the engine derives the non-upset tiers
                # from judge confidence, which the mock does not have.
                if lb - wb >= UPSET_MARGIN:
                    tier = "upset"
                elif abs(wb - lb) >= 60:
                    tier = "decisive"
                elif abs(wb - lb) >= 20:
                    tier = "clear"
                else:
                    tier = "narrow"
                wa, la = update_pair(wb, lb, k_factor=cfg["k_factor"])
                elo_state[winner] = wa
                elo_state[loser] = la
                store.update_hypothesis_state(winner,
                                              elo_rating=wa,
                                              win_delta=1,
                                              conn=conn)
                store.update_hypothesis_state(loser,
                                              elo_rating=la,
                                              loss_delta=1,
                                              conn=conn)
                store.add_match(
                    run_id,
                    iteration=itr,
                    winner_id=winner,
                    loser_id=loser,
                    winner_before=wb,
                    winner_after=wa,
                    loser_before=lb,
                    loser_after=la,
                    rationale=rationale,
                    tier=tier,
                    conn=conn,
                )
                round_matches.append({
                    "winner_id": winner,
                    "loser_id": loser,
                    "winner_elo_before": wb,
                    "winner_elo_after": wa,
                    "loser_elo_before": lb,
                    "loser_elo_after": la,
                    "rationale": rationale,
                    "tier": tier,
                })
        yield await emit(
            "ranking",
            {
                "iteration":
                    itr,
                "matches": [
                    match_stub({"winner": m["winner_id"]})
                    for m in round_matches
                ],
            },
        )

        if _check_cancel():
            store.update_run_status(run_id,
                                    RunStatus.CANCELLED,
                                    db_path=db_path)
            yield await emit("status", {"status": "cancelled"})
            return

        # Only run evolve/meta inside iterations, not after the final ranking pass
        if itr <= cfg["max_iterations"]:
            # ---- 8. Evolve top-k ----
            top_k = sorted(elo_state.items(),
                           key=lambda kv: -kv[1])[:cfg["evolution_max_count"]]
            children: list[dict[str, Any]] = []
            with store.transaction(db_path) as conn:
                for parent_id, _ in top_k:
                    parent = store.get_hypothesis(parent_id, conn=conn)
                    if not parent:
                        continue
                    child_h = _hypothesis_seed(rng, research_goal,
                                               len(hyp_ids) + len(children))
                    child_h[
                        "title"] = f"{child_h['title']} (evolved from {parent['title'][:30]}...)"  # pylint: disable=line-too-long
                    child_h["statement"] = (
                        f"Evolved variant of '{parent['title']}': {child_h['statement']} "  # pylint: disable=line-too-long
                        "Carries forward the parent's mechanistic frame with sharpened predictions."  # pylint: disable=line-too-long
                    )
                    child_id = store.add_hypothesis(
                        run_id,
                        title=child_h["title"],
                        statement=child_h["statement"],
                        category=parent.get("category") or
                        child_h.get("category"),
                        mechanism=child_h["mechanism"],
                        expected_effect=child_h["expected_effect"],
                        experimental_context=child_h["experimental_context"],
                        parent_id=parent_id,
                        generation=parent["generation"] + 1,
                        created_by_agent="evolution",
                        conn=conn,
                    )
                    hyp_ids.append(child_id)
                    elo_state[child_id] = INITIAL_ELO
                    children.append({
                        "id": child_id,
                        "parent_id": parent_id,
                        **child_h
                    })
            yield await emit(
                "evolve", {
                    "children": [hypothesis_stub(c) for c in children],
                    "iteration": itr,
                })

            # ---- 9. Meta-review (per iteration) ----
            mr_critique = (
                f"Meta-review (iter {itr}): the leading hypotheses cluster around the same mechanistic "  # pylint: disable=line-too-long
                "frame; recommend diversifying the experimental context in the next round and "  # pylint: disable=line-too-long
                "tightening the citation grounding for the top three.")
            store.add_review(
                run_id,
                top_k[0][0] if top_k else hyp_ids[0],
                "meta_review",
                summary=f"Meta-review iteration {itr}",
                critique=mr_critique,
                db_path=db_path,
            )
            yield await emit(
                "meta_review",
                {
                    "iteration": itr,
                    "critique": mr_critique,
                    "top_k_ids": [t[0] for t in top_k]
                },
            )

    # ---- 10. Deep verification (top-k by Elo) ----
    leaderboard_ids = [
        hid for hid, _ in sorted(elo_state.items(), key=lambda kv: -kv[1])
    ]
    dv_entries: list[dict[str, Any]] = []
    with store.transaction(db_path) as conn:
        for hid in leaderboard_ids[:DEEP_VERIFICATION_TOP_K]:
            hyp = store.get_hypothesis(hid, conn=conn)
            if not hyp:
                continue
            dv = _deep_verification_seed(rng, hyp["title"])
            summary, critique = format_deep_verification_critique(
                dv["probes"], dv["verdict"])
            store.add_review(
                run_id,
                hid,
                "deep_verification",
                summary=summary,
                critique=critique,
                conn=conn,
            )
            dv_entries.append({
                "hypothesis_id": hid,
                "verdict": dv["verdict"],
                "probes": dv["probes"],
            })
    yield await emit("deep_verification", {
        "verified": len(dv_entries),
        "probes": dv_entries,
    })

    # ---- 11. Citation audit ----
    cit_summary = empty_citation_summary()
    with store.transaction(db_path) as conn:
        for hid in hyp_ids[:max(3, len(hyp_ids) // 2)]:
            # Link first 2 evidence items to each hypothesis as supporting
            # citations
            for ev in evidence_payload[:2]:
                claim = f"Mechanism mentioned in {ev['title'][:30]} supports hypothesis"  # pylint: disable=line-too-long
                state = classify_citation(
                    CitationRecord(
                        title=ev["title"],
                        url=ev["url"],
                        abstract=ev["abstract"],
                        claim=claim,
                        available=ev["available"],
                    ))
                cit_summary[state] += 1
                store.add_citation(run_id,
                                   hid,
                                   ev["id"],
                                   claim,
                                   state,
                                   conn=conn)
    yield await emit("citation_audit", cit_summary)

    # ---- 12. Final safety + report ----
    with store.connect(db_path) as conn:
        top_hypotheses_raw = [
            store.get_hypothesis(hid, conn=conn) for hid in leaderboard_ids[:5]
        ]
    top_hypotheses = [h for h in top_hypotheses_raw if h]

    # ---- 13. Research overview + NIH Specific Aims ----
    research_overview = _research_overview_seed(
        rng, research_goal, [h["title"] for h in top_hypotheses])
    yield await emit("research_overview",
                     {"research_overview": research_overview})

    # ---- 14. Final safety + report, via the shared finalize path ----
    async for event in finalize_report(
        run_id=run_id,
        research_goal=research_goal,
        run_mode=run_mode,
        provider="mock",
        citation_summary=cit_summary,
        meta_review=None,
        research_overview=research_overview,
        emit=emit,
        summary=_MOCK_SUMMARY,
        db_path=db_path,
    ):
        yield event
