"""Deterministic content generators for the mock workflow.

These pure, side-effect-free helpers turn a seeded ``random.Random`` (plus the
research goal and indices) into the plausible-sounding hypotheses, evidence,
probes, clusters, and payloads the mock workflow emits. They never touch the
persistence layer, so the same seed always yields the same content.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import hashlib
import random
from typing import Any

from app.elo import MATCH_TIERS, UPSET_MARGIN
from app.run_modes import setup_guidance

# Named handles onto the app-owned decisiveness vocabulary (elo.MATCH_TIERS),
# so the mock's tier labels stay pinned to the single shared definition.
_UPSET, _DECISIVE, _CLEAR, _NARROW = MATCH_TIERS


def _seeded_rng(*parts: str) -> random.Random:
    """Build a `random.Random` seeded deterministically from `parts`."""
    # Hash the joined parts (typically run_id, goal, run_mode) down to a
    # 32-bit int; sha256 gives a stable, well-distributed seed independent
    # of Python's hash randomization (PYTHONHASHSEED).
    seed = int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16) % (
        2**32
    )
    return random.Random(seed)


# Word banks for `_hypothesis_seed`, hoisted to module scope so they are
# built once rather than reallocated on every call. `_HYPOTHESIS_ANGLES` and
# `_HYPOTHESIS_CATEGORIES` are parallel lists: pick one index and use it for
# both so the pairing stays explicit (no value-based lookup that could
# mis-map if an angle were ever duplicated or reordered).
_HYPOTHESIS_ANGLES: list[str] = [
    "modulating regulatory feedback in",
    "rerouting metabolic flux through",
    "perturbing transcriptional control of",
    "stabilizing a transient intermediate in",
    "decoupling co-expression in",
    "enforcing temporal restriction on",
    "exploiting allosteric switching in",
    "leveraging cross-pathway interference in",
]
_HYPOTHESIS_TARGETS: list[str] = [
    "the proposed mechanism",
    "the dominant pathway",
    "the upstream regulator",
    "the rate-limiting step",
    "the downstream effector",
    "the bottleneck enzyme",
    "the canonical signalling module",
]
_HYPOTHESIS_CATEGORIES: list[str] = [
    "Regulatory feedback",
    "Metabolic flux",
    "Transcriptional control",
    "Intermediate stabilization",
    "Co-expression decoupling",
    "Temporal restriction",
    "Allosteric switching",
    "Cross-pathway interference",
]


def _hypothesis_seed(rng: random.Random, goal: str, idx: int) -> dict[str, str]:
    """Generate a deterministic, plausible-sounding hypothesis stub."""
    # randrange consumes the RNG identically to choice, so the deterministic
    # output is unchanged from drawing angle/category via a single index.
    angle_index = rng.randrange(len(_HYPOTHESIS_ANGLES))
    angle = _HYPOTHESIS_ANGLES[angle_index]
    target = rng.choice(_HYPOTHESIS_TARGETS)
    category = _HYPOTHESIS_CATEGORIES[angle_index]
    title = f"H{idx + 1}: {angle.capitalize()} {target}".strip()
    statement = (
        f"In the context of '{goal[:120]}', we hypothesise that "
        f"{angle} {target} will produce a measurable effect via a "
        "mechanism distinct from current consensus."
    )
    mechanism = (
        f"The proposed pathway operates by {angle} {target}, with "
        "feedback at two checkpoints; the predicted intermediate state "
        "is detectable by standard assays."
    )
    expected = (
        "We expect a dose-dependent effect with a saturating response "
        "curve, distinguishable from baseline within standard error "
        "bounds."
    )
    experiment = (
        "Run a controlled in-vitro perturbation series with three "
        "replicates per condition; validate top hits in an orthogonal "
        "model system."
    )
    return {
        "title": title,
        "category": category,
        "statement": statement,
        "mechanism": mechanism,
        "expected_effect": expected,
        "experimental_context": experiment,
    }


def _evidence_seed(rng: random.Random, goal: str, idx: int) -> dict[str, Any]:
    """Generate a deterministic, plausible-sounding mock evidence record."""
    # Prefer longer words from the goal as a stand-in "topic" keyword; a
    # fixed fallback keeps output well-formed for very short/terse goals.
    keywords = [t for t in goal.lower().split() if len(t) > 4][:3] or [
        "mechanism"
    ]
    keyword = rng.choice(keywords)
    available = rng.random() > 0.15  # ~15% unavailable
    year = rng.randint(2015, 2025)
    return {
        "title": f"Mock study {idx + 1}: {keyword} dynamics in a model system",
        "url": f"https://example.org/mock/{idx + 1}" if available else "",
        "authors": [f"Author{idx + 1}.A.", f"Author{idx + 1}.B."],
        "year": year,
        "abstract": (
            f"This mock abstract discusses {keyword} dynamics, "
            "mechanism, regulatory feedback, and a measurable effect "
            "under controlled perturbation. It is provided in mock mode "
            "so the workflow can be exercised without external network "
            "calls."
        ),
        "available": available,
    }


def _cluster_id(idx: int) -> str:
    """Assign a hypothesis index to one of 3 fixed mock proximity clusters."""
    return f"cluster-{idx % 3}"  # 3 is an arbitrary fixed cluster count


# Number of top-ranked hypotheses subjected to deep verification. Hardcoded
# because the mock is offline and must not import the engine constant.
DEEP_VERIFICATION_TOP_K = 3

# Lead paragraph for the mock report, flagging its artefacts as illustrative.
_MOCK_SUMMARY = (
    "This run was executed in deterministic mock mode. Hypotheses, citations, "
    "and tournament results below are illustrative artefacts produced without "
    "any LLM provider."
)

# Probe question/answer/reasoning/is-fundamental templates for
# `_deep_verification_seed`, hoisted to module scope so the list is built
# once rather than reallocated on every call.
_DEEP_VERIFICATION_PROBE_TEMPLATES: list[tuple[str, str, str, bool]] = [
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
        "One supporting citation is weaker than assumed under closer reading.",
        "A shaky premise lowers confidence without undermining the whole "
        "hypothesis.",
        False,
    ),
]


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
    probe_count = rng.randint(2, 3)
    chosen = rng.sample(_DEEP_VERIFICATION_PROBE_TEMPLATES, probe_count)
    probes = [
        {
            "question": f"Regarding '{title[:60]}': {question}",
            "answer": answer,
            "reasoning": reasoning,
            "assumption_is_fundamental": fundamental,
        }
        for question, answer, reasoning, fundamental in chosen
    ]
    any_fundamental = any(p["assumption_is_fundamental"] for p in probes)
    verdict = (
        rng.choice(["weakened", "undermined"]) if any_fundamental else "holds"
    )
    return {"probes": probes, "verdict": verdict}


def _shuffled_research_directions(rng: random.Random) -> list[dict[str, Any]]:
    """Build the (shuffled) research-direction entries for the overview."""
    direction_angles = [
        (
            "Establish the causal mechanism",
            "Confirms the core assumption shared by the top hypotheses.",
        ),
        (
            "Probe pathway redundancy",
            "Determines whether compensatory routes blunt the expected effect.",
        ),
        (
            "Validate in an orthogonal model",
            "Guards against assay-specific artefacts before scale-up.",
        ),
    ]
    rng.shuffle(direction_angles)
    research_directions = []
    for idx, (title, importance) in enumerate(direction_angles[:3]):
        research_directions.append(
            {
                "title": title,
                "importance": importance,
                "suggested_experiments": [
                    "Run a controlled perturbation series with three "
                    "replicates per condition.",
                    "Quantify the readout against baseline for direction "
                    f"{idx + 1}.",
                ],
            }
        )
    return research_directions


def _nih_specific_aims_from_directions(
    goal: str, research_directions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Derive the NIH Specific Aims payload from the research directions."""
    aims = [
        {
            "aim": f"Aim {i + 1}: {direction['title']}.",
            "rationale": direction["importance"],
            "approach": direction["suggested_experiments"][0],
        }
        for i, direction in enumerate(research_directions)
    ]
    return {
        "introduction": (
            f"The proposed research targets '{goal[:120]}'. We organize the "
            "top-ranked hypotheses into complementary specific aims."
        ),
        "aims": aims,
        "impact": (
            "Successful completion would convert the leading mechanistic "
            "hypothesis into an actionable, falsifiable research program."
        ),
    }


def _research_overview_seed(
    rng: random.Random, goal: str, top_titles: list[str]
) -> dict[str, Any]:
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
        "below convert the highest-ranked mechanisms into a testable roadmap."
    )
    research_directions = _shuffled_research_directions(rng)
    nih_specific_aims = _nih_specific_aims_from_directions(
        goal, research_directions
    )
    return {
        "overview": {
            "summary": summary,
            "research_directions": research_directions,
        },
        "nih_specific_aims": nih_specific_aims,
    }


def _build_supervisor_plan(
    cfg: dict[str, Any], run_mode: str
) -> dict[str, Any]:
    """Build the supervisor's research plan + agent DAG payload."""
    return {
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
        "run_mode": run_mode,
        "config": cfg,
        "setup": cfg.get("setup", {}),
        "setup_guidance": setup_guidance(cfg.get("setup")),
        "narrative": (
            "Plan the canonical hypothesis-generation run for the "
            "research goal. Allocate compute across literature, "
            f"generation ({cfg['initial_hypotheses_count']} candidates), "
            f"{cfg['max_iterations']} iterations of reflect/rank/evolve, "
            "then synthesize a report."
        ),
    }


def _judge_pair(
    run_id: str, title_by_id: dict[str, str], a: str, b: str
) -> tuple[str, str, str]:
    """Deterministically judge a tournament pair by hashing seeded titles.

    Hashing (rather than drawing from the shared RNG) keeps the judged outcome
    reproducible for a fixed (run_id, goal) independent of RNG draws made
    elsewhere in the workflow.
    """
    a_title = title_by_id.get(a, a)
    b_title = title_by_id.get(b, b)
    if (
        hashlib.sha256((run_id + a_title + b_title).encode()).hexdigest()
        < hashlib.sha256((run_id + b_title + a_title).encode()).hexdigest()
    ):
        return a, b, "Mock judge: 'a' has stronger mechanistic specificity."
    return b, a, "Mock judge: 'b' presents a more decisive experimental test."


def _mock_match_tier(winner_elo_before: int, loser_elo_before: int) -> str:
    """Classify a pre-match Elo gap into the app-owned decisiveness vocabulary.

    Only the labels are shared with the engine's ``ranking.match_tier`` --
    the engine derives the non-upset tiers from judge confidence, which the
    mock does not have.
    """
    if loser_elo_before - winner_elo_before >= UPSET_MARGIN:
        return _UPSET
    gap = abs(winner_elo_before - loser_elo_before)
    if gap >= 60:  # arbitrary fixed cutoff, mock-only
        return _DECISIVE
    if gap >= 20:  # arbitrary fixed cutoff, mock-only
        return _CLEAR
    return _NARROW


def _build_evolved_child(
    rng: random.Random,
    research_goal: str,
    parent: dict[str, Any],
    seed_idx: int,
) -> dict[str, Any]:
    """Generate a deterministic child hypothesis derived from `parent`."""
    child_h = _hypothesis_seed(rng, research_goal, seed_idx)
    child_h["title"] = (
        f"{child_h['title']} (evolved from {parent['title'][:30]}...)"
    )
    child_h["statement"] = (
        f"Evolved variant of '{parent['title']}': "
        f"{child_h['statement']} Carries forward the "
        "parent's mechanistic frame with sharpened "
        "predictions."
    )
    return child_h


def _build_tournament_pairs(
    rng: random.Random,
    hyp_ids: list[str],
    pair_count: int,
) -> list[tuple[str, str]]:
    """Sample `pair_count` random hypothesis pairs.

    The pairs seed the first ranking round.
    """
    pairs = []
    for _ in range(pair_count):
        a, b = rng.sample(hyp_ids, 2)
        pairs.append((a, b))
    return pairs


def _ranking_round_payload(
    itr: int, round_matches: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the emitted payload for one ranking round."""
    return {
        "iteration": itr,
        "matches": [{"winner": str(m["winner_id"])} for m in round_matches],
    }
