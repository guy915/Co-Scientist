# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Deterministic mock workflow used when no LLM provider is configured.

It emits the full agent-equivalent sequence the real engine produces — so the
backend, persistence layer, SSE stream, and frontend can be exercised end-to-end
without any external API calls.

Stages emitted (in order):
1. supervisor.plan       — research plan + agent DAG
2. intake.scope          — clarified goal + safety screen
3. literature_review     — retrieved evidence list
4. generate              — initial hypotheses (initial_count)
5. reflection            — per-hypothesis reflection notes
6. proximity             — clusters
7. ranking               — Elo tournament across pairs
8. evolve                — mutate top-k → child hypotheses (parent_id set)
9. ranking (post-evolve) — second round of Elo updates
10. meta_review          — synthesis critique
11. citation_audit       — classify each citation
12. safety.final         — final-output gate
13. report               — assembled report
14. status: completed

The output is fully deterministic given (research_goal, profile, config). This
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

from . import store
from .citations import CitationRecord, classify_citation
from .elo import DEFAULT_K_FACTOR, INITIAL_ELO, update_pair
from .safety import screen_final, screen_intake

logger = logging.getLogger(__name__)

PROFILE_DEFAULTS: dict[str, dict[str, int]] = {
    "standard": {
        "initial_hypotheses_count": 5,
        "max_iterations": 1,
        "evolution_max_count": 5,
        "tournament_pairs": 6,
        "evidence_count": 4,
    },
    "advanced": {
        "initial_hypotheses_count": 8,
        "max_iterations": 2,
        "evolution_max_count": 8,
        "tournament_pairs": 12,
        "evidence_count": 8,
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolved_config(profile: str,
                    overrides: dict[str, int] | None = None) -> dict[str, int]:
    base = dict(PROFILE_DEFAULTS.get(profile, PROFILE_DEFAULTS["standard"]))
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                base[k] = int(v)
    base.setdefault("k_factor", DEFAULT_K_FACTOR)
    return base


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
    angle = rng.choice(angles)
    target = rng.choice(targets)
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


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


async def run_mock_workflow(
    run_id: str,
    research_goal: str,
    profile: str,
    config: dict[str, Any],
    *,
    db_path: str | None = None,
    cancelled: asyncio.Event | None = None,
    sleep_seconds: float = 0.05,
) -> AsyncIterator[dict[str, Any]]:
    """Execute the deterministic mock workflow and yield events as they happen."""  # pylint: disable=line-too-long
    cfg = resolved_config(profile, config)
    rng = _seeded_rng("mock", run_id, research_goal, profile)

    def _check_cancel() -> bool:
        return bool(cancelled and cancelled.is_set())

    async def emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        seq = store.append_event(run_id, type_, payload, db_path=db_path)
        await asyncio.sleep(sleep_seconds)
        return {"seq": seq, "type": type_, "payload": payload}

    # ---- 1. Intake / Safety (input gate) ----
    intake = screen_intake(research_goal)
    store.add_safety_decision(run_id,
                              intake.stage,
                              intake.decision,
                              intake.reason,
                              intake.matches,
                              db_path=db_path)
    yield await emit("safety.intake", intake.to_dict())
    if intake.decision == "block":
        store.update_run_status(run_id,
                                "blocked",
                                error=intake.reason,
                                db_path=db_path)
        yield await emit("status", {
            "status": "blocked",
            "error": intake.reason
        })
        return

    store.update_run_status(run_id, "running", db_path=db_path)
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
        "profile":
            profile,
        "config":
            cfg,
        "narrative": (
            f"Plan a {profile} run for the research goal. Allocate compute across literature, "  # pylint: disable=line-too-long
            f"generation ({cfg['initial_hypotheses_count']} candidates), {cfg['max_iterations']} "  # pylint: disable=line-too-long
            "iterations of reflect/rank/evolve, then synthesize a report."),
    }
    yield await emit("supervisor.plan", plan)
    if _check_cancel():
        store.update_run_status(run_id, "cancelled", db_path=db_path)
        yield await emit("status", {"status": "cancelled"})
        return

    # ---- 3. Literature review ----
    evidence_count = cfg["evidence_count"]
    evidence_ids: list[str] = []
    evidence_payload: list[dict[str, Any]] = []
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
            db_path=db_path,
        )
        evidence_ids.append(ev_id)
        evidence_payload.append({"id": ev_id, **ev})
    yield await emit(
        "literature_review",
        {
            "count": len(evidence_payload),
            "evidence": evidence_payload
        },
    )

    # ---- 4. Generation ----
    initial_count = cfg["initial_hypotheses_count"]
    hyp_ids: list[str] = []
    hyp_payloads: list[dict[str, Any]] = []
    for i in range(initial_count):
        h = _hypothesis_seed(rng, research_goal, i)
        hid = store.add_hypothesis(
            run_id,
            title=h["title"],
            statement=h["statement"],
            mechanism=h["mechanism"],
            expected_effect=h["expected_effect"],
            experimental_context=h["experimental_context"],
            generation=0,
            created_by_agent="generation",
            db_path=db_path,
        )
        hyp_ids.append(hid)
        hyp_payloads.append({
            "id": hid,
            **h, "elo_rating": INITIAL_ELO,
            "generation": 0
        })
    yield await emit("generate", {
        "count": len(hyp_payloads),
        "hypotheses": hyp_payloads
    })

    # ---- 5. Reflection ----
    for hid, h in zip(hyp_ids, hyp_payloads):
        critique = (
            f"Reflection: '{h['title']}' offers a plausible mechanism but should be checked against "  # pylint: disable=line-too-long
            "the {N} retrieved sources for prior work; novelty is moderate; testability is high if "  # pylint: disable=line-too-long
            "the experimental context is constrained.").format(N=evidence_count)
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
            db_path=db_path,
        )
    yield await emit("reflection", {"reviewed": len(hyp_ids)})

    # ---- 6. Proximity / clustering ----
    clusters: dict[str, list[str]] = {}
    for i, hid in enumerate(hyp_ids):
        cid = _cluster_id(i)
        clusters.setdefault(cid, []).append(hid)
        store.update_hypothesis_state(hid, cluster_id=cid, db_path=db_path)
    yield await emit("proximity",
                     {"clusters": {
                         k: len(v) for k, v in clusters.items()
                     }})

    # ---- 7. First ranking round ----
    elo_state: dict[str, int] = {hid: INITIAL_ELO for hid in hyp_ids}

    def _judge(a: str, b: str) -> tuple[str, str, str]:
        # deterministic: pick by hash so tests are stable
        if hashlib.sha256(
            (run_id + a + b).encode()).hexdigest() < hashlib.sha256(
                (run_id + b + a).encode()).hexdigest():
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
        for a, b in pairs:
            winner, loser, rationale = _judge(a, b)
            wb = elo_state[winner]
            lb = elo_state[loser]
            wa, la = update_pair(wb, lb, k_factor=cfg["k_factor"])
            elo_state[winner] = wa
            elo_state[loser] = la
            store.update_hypothesis_state(winner,
                                          elo_rating=wa,
                                          win_delta=1,
                                          db_path=db_path)
            store.update_hypothesis_state(loser,
                                          elo_rating=la,
                                          loss_delta=1,
                                          db_path=db_path)
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
                db_path=db_path,
            )
            round_matches.append({
                "winner_id": winner,
                "loser_id": loser,
                "winner_elo_before": wb,
                "winner_elo_after": wa,
                "loser_elo_before": lb,
                "loser_elo_after": la,
                "rationale": rationale,
            })
        yield await emit(
            "ranking",
            {
                "iteration":
                    itr,
                "matches":
                    round_matches,
                "leaderboard":
                    sorted(elo_state.items(), key=lambda kv: -kv[1])[:5]
            },
        )

        if _check_cancel():
            store.update_run_status(run_id, "cancelled", db_path=db_path)
            yield await emit("status", {"status": "cancelled"})
            return

        # only run evolve/meta inside iterations, not after the final ranking pass
        if itr <= cfg["max_iterations"]:
            # ---- 8. Evolve top-k ----
            top_k = sorted(elo_state.items(),
                           key=lambda kv: -kv[1])[:cfg["evolution_max_count"]]
            children: list[dict[str, Any]] = []
            for parent_id, _ in top_k:
                parent = store.get_hypothesis(parent_id, db_path=db_path)
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
                    mechanism=child_h["mechanism"],
                    expected_effect=child_h["expected_effect"],
                    experimental_context=child_h["experimental_context"],
                    parent_id=parent_id,
                    generation=parent["generation"] + 1,
                    created_by_agent="evolution",
                    db_path=db_path,
                )
                hyp_ids.append(child_id)
                elo_state[child_id] = INITIAL_ELO
                children.append({
                    "id": child_id,
                    "parent_id": parent_id,
                    **child_h
                })
            yield await emit("evolve", {"children": children, "iteration": itr})

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

    # ---- 10. Citation audit ----
    cit_summary = {
        "verified": 0,
        "partial": 0,
        "unsupported": 0,
        "unavailable": 0
    }
    for hid in hyp_ids[:max(3, len(hyp_ids) // 2)]:
        # link first 2 evidence items to each hypothesis as supporting citations
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
                               db_path=db_path)
    yield await emit("citation_audit", cit_summary)

    # ---- 11. Final safety + report ----
    leaderboard_ids = [
        hid for hid, _ in sorted(elo_state.items(), key=lambda kv: -kv[1])
    ]
    top_hypotheses_raw = [
        store.get_hypothesis(hid, db_path=db_path)
        for hid in leaderboard_ids[:5]
    ]
    top_hypotheses = [h for h in top_hypotheses_raw if h]

    md_lines: list[str] = []
    md_lines.append(f"# Research Report — {research_goal}")
    md_lines.append("")
    md_lines.append(f"_Profile: **{profile}** · Provider: **mock**_")
    md_lines.append("")
    md_lines.append("## Summary")
    md_lines.append(
        "This run was executed in deterministic mock mode. Hypotheses, citations, and tournament "  # pylint: disable=line-too-long
        "results below are illustrative artefacts produced without any LLM provider."
    )
    md_lines.append("")
    md_lines.append("## Top hypotheses")
    for i, h in enumerate(top_hypotheses, 1):
        md_lines.append(f"### {i}. {h['title']}  _Elo: {h['elo_rating']}_")
        md_lines.append(h["statement"])
        md_lines.append("")
        md_lines.append(f"**Mechanism:** {h['mechanism']}")
        md_lines.append("")
        md_lines.append(f"**Expected effect:** {h['expected_effect']}")
        md_lines.append("")
    md_lines.append("## Citation audit")
    for cit_state, count in cit_summary.items():
        md_lines.append(f"- {cit_state}: {count}")
    md_lines.append("")
    md_lines.append("## Notes")
    md_lines.append(
        "- Append-only evolution: evolved hypotheses appear as new rows with `parent_id`."  # pylint: disable=line-too-long
    )
    md_lines.append("- Elo: initial 1200, K = " + str(cfg["k_factor"]) +
                    ", standard formula.")
    md_lines.append("")
    markdown = "\n".join(md_lines)

    final_safety = screen_final(markdown)
    store.add_safety_decision(
        run_id,
        final_safety.stage,
        final_safety.decision,
        final_safety.reason,
        final_safety.matches,
        db_path=db_path,
    )
    yield await emit("safety.final", final_safety.to_dict())

    if final_safety.decision == "block":
        store.update_run_status(run_id,
                                "blocked",
                                error=final_safety.reason,
                                db_path=db_path)
        yield await emit("status", {
            "status": "blocked",
            "error": final_safety.reason
        })
        return

    payload = {
        "research_goal": research_goal,
        "profile": profile,
        "provider": "mock",
        "leaderboard": [{
            "id": h["id"],
            "title": h["title"],
            "elo": h["elo_rating"]
        } for h in top_hypotheses],
        "citation_summary": cit_summary,
        "evidence_count": len(evidence_payload),
        "matches_count": len(pairs) * (cfg["max_iterations"] + 1),
    }
    saved = store.save_report(run_id, payload, markdown, db_path=db_path)
    yield await emit("report", {**payload, "report_id": saved["id"]})

    store.update_run_status(run_id, "completed", db_path=db_path)
    yield await emit("status", {"status": "completed"})
