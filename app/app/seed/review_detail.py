"""Curated mature-cascade review verdicts for the demo scenarios' top ideas.

A real run's Reflection cascade produces full/simulation/recurrent review
rows only for the hypotheses that reach that stage (audit E1); a curated
demo has no cascade to draw them from. This module hand-authors the same
two review types -- full review's Go/No-Go framing (R14-15) and simulation
review's numbered failure points (R14-22) -- for each scenario's five
highest-ranked ideas (full review) and two highest-ranked ideas (simulation
review, the more expensive review type a real run reserves for fewer
candidates), grounded in that idea's own mechanism and limitation already
authored in ``demo_seed_data.scenarios``/``demo_seed_data.proposals``.

Split out of ``seed.scenario`` so that module stays within the line-count
cap; content and row-shaping only, keyed by ``scenario_key`` and hypothesis
rank exactly as the other curated content modules are.
"""

# The curated payload below is reader-facing scientific prose; keeping each
# statement intact makes the fixture auditable.
# ruff: noqa: E501

from __future__ import annotations

import json

from app import store
from app.demo_seed_data import _SCENARIO_KEYS

# (go_no_go, time_to_verdict) per scenario, in ranked order, for the top
# five ideas -- the ideas the report's "Top hypotheses" section renders.
_FULL_REVIEWS: dict[str, tuple[tuple[str, str], ...]] = {
    _SCENARIO_KEYS[0]: (
        (
            "Go — proceed once the biomass/growth-rate control is built into the same experiment, not run as a separate check.",
            "6-8 weeks for the initial pulse-kill-curve comparison across three isolates.",
        ),
        (
            "Go, conditional — advance to the rescue/knockdown arm only if the MazEF signature replicates across at least two independent antibiotic pulses.",
            "10-12 weeks including targeted reporter validation.",
        ),
        (
            "Go, staged — validate the spatial oxygen/metabolic readout in intact biofilms before committing to a matrix-modulation intervention arm.",
            "12-14 weeks; the imaging readout alone is a 4-5 week milestone.",
        ),
        (
            "Go, conditional — requires the abiotic antibiotic-stability control to rule out oxygen altering vancomycin chemistry directly.",
            "8-10 weeks for the oxygenation-by-antibiotic factorial.",
        ),
        (
            "Go, narrow scope — restrict the first pass to one clinical background and require complementation before extending to a second.",
            "14-16 weeks for genetics plus replication across two backgrounds.",
        ),
    ),
    _SCENARIO_KEYS[1]: (
        (
            "Go, conditional — proceed only with the age windows and locomotor/exploratory controls pre-registered before the perturbation cohort begins.",
            "16-20 weeks (adolescent tracking window plus adult behavioral testing).",
        ),
        (
            "Go, staged — needs a cell-type-specific complement manipulation before the tagging result can be treated as more than correlational.",
            "18-22 weeks including the longitudinal engulfment cohort.",
        ),
        (
            "Go, contingent — pilot recording feasibility before committing the full behavioral cohort to the higher-risk imaging pipeline.",
            "20-24 weeks; the imaging pilot is a 6-8 week gate.",
        ),
        (
            "Go, narrow — restrict the first pass to one receptor manipulation (D1 or P2RY12) rather than both, to keep the causal claim interpretable.",
            "16-18 weeks for the imaging-plus-perturbation window.",
        ),
        (
            "Go, conditional — requires a manipulation that changes tagging independent of activity, not colocalization alone.",
            "14-16 weeks across early/mid/late adolescent sampling.",
        ),
    ),
    _SCENARIO_KEYS[2]: (
        (
            "Go — the CPEB1 biomarker and lipid-antioxidant rescue arm are both already specified; confirm ferroptotic, not generic-stress, death before advancing.",
            "10-12 weeks across the PDAC line and organoid panel.",
        ),
        (
            "Go, conditional — dose-ordering and normal-cell toxicity must be characterized before the subgroup result is treated as a translatable combination.",
            "12-14 weeks for the isogenic-perturbation matrix.",
        ),
        (
            "Go, staged — lock the analysis plan and predictor before the independent organoid validation, to avoid overfitting the training panel.",
            "16-18 weeks (training panel plus independent validation).",
        ),
        (
            "Go, conditional — requires an NRF2-rescue arm that isolates the CUL2 branch from its other cellular roles.",
            "12-14 weeks for the knockdown-plus-rescue matrix.",
        ),
        (
            "Go, narrow — restrict the first pass to catalytic-dead USP8 and NRF2-rescue controls, since proteostasis effects are otherwise hard to attribute.",
            "14-16 weeks for the pulse-chase and imaging combination.",
        ),
    ),
}

# (failure_points, decisive_step) per scenario, in ranked order, for the
# two highest-ranked ideas only.
_SIMULATION_REVIEWS: dict[str, tuple[tuple[tuple[str, ...], str], ...]] = {
    _SCENARIO_KEYS[0]: (
        (
            (
                "A metabolic pulse strong enough to sensitize cells may itself trigger early dispersal, so a lower CFU count could reflect unintended biofilm breakup rather than antibiotic sensitization.",
                "ATP and CFU can move together for reasons unrelated to antibiotic exposure, so a killing effect could be misread as a tolerance shift without an antibiotic-only comparator run in parallel.",
            ),
            "The vehicle-plus-vancomycin and pulse-only arms must show no CFU change relative to baseline before the pulse-plus-vancomycin result is attributed to a tolerance shift.",
        ),
        (
            (
                "An expression signature enriched in survivors could reflect selection of a pre-existing subpopulation rather than an induced state change, which RNA profiling alone cannot distinguish.",
                "Targeted knockdown may lower general stress fitness rather than specifically removing the tolerant state, producing a rescue-shaped result for the wrong reason.",
            ),
            "The knockdown/rescue arm must restore wild-type survival specifically under antibiotic pulse conditions, not under unchallenged growth, before the marker is treated as causal.",
        ),
    ),
    _SCENARIO_KEYS[1]: (
        (
            (
                "A perturbation delivered inside the candidate window could act by changing overall arousal or locomotor state rather than the specific refinement process, producing a window-specific-looking effect for the wrong reason.",
                "Adult set-shifting performance is sensitive to handling and testing order; without counterbalancing, apparent window-specificity could be a scheduling artifact rather than developmental timing.",
            ),
            "The locomotor and exploratory control cohort must show no perturbation-related shift before the set-shifting difference is attributed to the refinement window itself.",
        ),
        (
            (
                "Complement and activity labels may correlate simply because active synapses are larger and more visible, not because complement selectively tags them for removal.",
                "A broad inflammatory response to the labeling procedure itself could increase apparent engulfment independent of any synapse-specific tagging mechanism.",
            ),
            "The cell-type-specific complement perturbation must change engulfment of tagged synapses without altering total microglial activation, before the tagging mechanism is treated as causal.",
        ),
    ),
    _SCENARIO_KEYS[2]: (
        (
            (
                "Combination killing could reflect additive off-target chemotherapy toxicity rather than a ferroptosis-specific interaction, especially at doses that also stress non-ferroptotic pathways.",
                "The lipid-antioxidant rescue could non-specifically protect cells from general oxidative stress, giving a false-positive rescue that does not confirm the CPEB1-NRF2 mechanism.",
            ),
            "The rescue must be reversed by a ferroptosis-specific inhibitor panel, not a general antioxidant alone, before the CPEB1-low result is treated as mechanism-confirming.",
        ),
        (
            (
                "ARID3A perturbation can have transcriptional effects well beyond the PTEN-GPX4 axis, so a sensitization effect may not run through the proposed route.",
                "A benefit seen only as an unselected-panel average could hide a biomarker-negative subgroup that is actually harmed, if per-model variance is not reported alongside the group mean.",
            ),
            "The PTEN-rescue arm must restore resistance in ARID3A-high models before the ARID3A-PTEN-GPX4 route is treated as the operative mechanism.",
        ),
    ),
}


def full_review_row(scenario_key: str, index: int) -> tuple[str, str, str]:
    """Return one hypothesis's (summary, critique, detail_json) full review.

    Empty strings/``""`` for ``critique`` are never returned -- the caller
    only invokes this for ranks that ``_FULL_REVIEWS`` actually covers.
    """
    go_no_go, time_to_verdict = _FULL_REVIEWS[scenario_key][index]
    summary = "Full review verdict: sound"
    critique = f"Justification: {go_no_go}\nTime to verdict: {time_to_verdict}"
    detail = json.dumps(
        {"go_no_go": go_no_go, "time_to_verdict": time_to_verdict}
    )
    return summary, critique, detail


def simulation_review_row(
    scenario_key: str, index: int
) -> tuple[str, str, str]:
    """Return one hypothesis's (summary, critique, detail_json) simulation."""
    failure_points, decisive_step = _SIMULATION_REVIEWS[scenario_key][index]
    summary = "Simulation review verdict: holds"
    critique = "\n".join(
        [f"Failure point: {point}" for point in failure_points]
        + [f"Decisive step: {decisive_step}"]
    )
    detail = json.dumps(
        {"failure_points": list(failure_points), "decisive_step": decisive_step}
    )
    return summary, critique, detail


def full_review_count(scenario_key: str) -> int:
    """How many ranked ideas in this scenario carry a full review row."""
    return len(_FULL_REVIEWS[scenario_key])


def simulation_review_count(scenario_key: str) -> int:
    """How many ranked ideas in this scenario carry a simulation review row."""
    return len(_SIMULATION_REVIEWS[scenario_key])


def mature_review_rows(
    run_id: str, hypothesis_id: str, scenario_key: str, index: int
) -> list[store.NewReview]:
    """Return the curated full/simulation review rows for one ranked idea.

    Empty for a rank neither table covers -- most of a scenario's ideas,
    matching how a real run's mature Reflection cascade reaches only a
    subset of hypotheses.
    """
    rows: list[store.NewReview] = []
    if index < full_review_count(scenario_key):
        summary, critique, detail = full_review_row(scenario_key, index)
        rows.append(
            store.NewReview(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                reviewer_agent="full_review",
                summary=summary,
                critique=critique,
                detail_json=detail,
            )
        )
    if index < simulation_review_count(scenario_key):
        summary, critique, detail = simulation_review_row(scenario_key, index)
        rows.append(
            store.NewReview(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                reviewer_agent="simulation_review",
                summary=summary,
                critique=critique,
                detail_json=detail,
            )
        )
    return rows
