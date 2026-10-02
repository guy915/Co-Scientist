"""Terminal synthesis payloads for a curated demo run.

Split out of ``app.seed``: this module builds the research-overview and
meta-review objects a completed run carries, in the same shape a real run's
synthesis produces, so the demo exercises the whole report surface.
"""

# The curated payload below is reader-facing scientific prose; keeping each
# source-backed statement intact makes the fixture auditable.
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

from app.demo_seed_data import (
    _SCENARIO_KEYS,
    DemoEvidence,
    DemoHypothesis,
    DemoScenario,
    scenario_key,
)
from app.seed.meta_review import _curated_meta_review as _curated_meta_review

# Grounded in each scenario's own top-3 hypotheses
# (demo_seed_data/scenarios.py) -- every entry connects two of those
# hypotheses in a way neither states on its own, or reframes one of their
# shared assumptions, rather than describing a specific published finding.
# Order matches ``_curated_research_overview``'s own ``top = hypotheses[:3]``
# only loosely: these are cross-cutting, not indexed to one hypothesis.
_UNEXPECTED_DIRECTIONS: dict[str, tuple[dict[str, str], ...]] = {
    _SCENARIO_KEYS[0]: (
        {
            "title": "Persister-State Convergence",
            "description": (
                "If the metabolic-wake-up pulse and the MazEF transcriptional "
                "state are tracking the same underlying dormancy program "
                "rather than two independent mechanisms, a real-time MazEF "
                "reporter could time the pulse itself -- closing the loop "
                "between biomarker and intervention instead of treating them "
                "as a validation pair and a separate therapeutic lead."
            ),
        },
        {
            "title": "The Matrix as a Drug-Delivery Barrier, Not Only a Metabolic One",
            "description": (
                "The spatial-microgradient hypothesis frames nutrient and "
                "oxygen limitation as what creates tolerance, but the same "
                "matrix structure could equally be limiting antibiotic "
                "penetration to those cells -- a confound that would make a "
                "single-drug rescue experiment unable to distinguish "
                "metabolic tolerance from simple diffusion failure."
            ),
        },
        {
            "title": "Inter-Isolate MazEF Stoichiometry as a Generalizability Risk",
            "description": (
                "Because the MazEF hypothesis already needs a rescue "
                "experiment across strains, an unanticipated risk is that "
                "the toxin-to-antitoxin ratio -- not merely MazEF's presence "
                "-- varies enough between clinical isolates that a single "
                "transcriptional signature never generalizes past the "
                "isolates it was defined in."
            ),
        },
    ),
    _SCENARIO_KEYS[1]: (
        {
            "title": "Complement Tagging as the Window's Molecular Clock",
            "description": (
                "Complement-associated tagging is proposed as a marker of "
                "which synapses get pruned, but it could instead set the "
                "calibration window's own onset and offset -- meaning a "
                "perturbation of the tagging machinery directly would shift "
                "when refinement happens, not only which synapses it "
                "touches."
            ),
        },
        {
            "title": "Pubertal-Stage-Indexed Window Timing",
            "description": (
                "The narrow refinement window is framed against a fixed "
                "postnatal-day range, but its true anchor may be individual "
                "pubertal-stage milestones rather than chronological age -- "
                "so indexing the window to a physiological marker of "
                "puberty, not age alone, could resolve animals the current "
                "design would otherwise misclassify as outside it."
            ),
        },
        {
            "title": "Circuit Synchrony as an Upstream Signal, Not Only a Downstream Readout",
            "description": (
                "Prefrontal synchrony is treated as mediating between "
                "synapse remodeling and behavior, but activity-dependent "
                "synchrony could instead partly precede structural pruning "
                "-- an upstream signal that guides which synapses get "
                "tagged, reversing the assumed causal order rather than "
                "only relaying it."
            ),
        },
    ),
    _SCENARIO_KEYS[2]: (
        {
            "title": "A Shared PTEN-NRF2 Buffering Spectrum",
            "description": (
                "CPEB1-low tumors and the ARID3A-high/PTEN-suppressed "
                "subgroup are treated as two independent stratification "
                "biomarkers, but PTEN and NRF2-pathway regulation intersect "
                "in redox control broadly -- raising the possibility that "
                "they are overlapping ends of a single buffering-capacity "
                "spectrum a combined, not either-or, biomarker panel could "
                "resolve."
            ),
        },
        {
            "title": "Using the Kinetic Predictor to Re-Bin the Static Biomarkers",
            "description": (
                "The early lipid-peroxidation kinetics assay is proposed as "
                "a standalone de-risking readout, but it could instead "
                "reclassify tumors ambiguous on the CPEB1 and ARID3A status "
                "markers -- resolving cases where the two genetic biomarkers "
                "disagree, rather than only validating models already "
                "stratified by them."
            ),
        },
        {
            "title": "Ferroptosis Resistance as a Chemotherapy-Induced State, Not Only a Baseline Trait",
            "description": (
                "All three proposals treat ferroptosis susceptibility as a "
                "pre-existing property to measure before treatment, but "
                "gemcitabine exposure itself could dynamically shift "
                "NRF2/GPX4 buffering capacity over the treatment course -- so "
                "a single pre-treatment biomarker read might miss resistance "
                "that only develops after the first dosing cycle."
            ),
        },
    ),
}


def curated_unexpected_directions(key: str) -> list[dict[str, Any]]:
    """Return one scenario's synthesized unexpected research directions."""
    return [dict(item) for item in _UNEXPECTED_DIRECTIONS[key]]


def _overview_directions(
    top: tuple[DemoHypothesis, ...],
) -> list[dict[str, Any]]:
    """Return the research directions the overview recommends."""
    return [
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


def _overview_aims(top: tuple[DemoHypothesis, ...]) -> list[dict[str, Any]]:
    """Return the grant-style specific aims derived from the top ideas."""
    return [
        {
            "overarching_goal": f"Aim {index}: Test {item.title}",
            "hypothesis": item.statement,
            "reasoning": item.experiment,
        }
        for index, item in enumerate(top, start=1)
    ]


def _overview_knowledge_base(
    evidence: tuple[DemoEvidence, ...],
    hypotheses: tuple[DemoHypothesis, ...],
) -> list[dict[str, Any]]:
    """Return the knowledge-base topics, each citing two curated sources."""
    return [
        {
            "title": item.title,
            "summary": item.mechanism,
            "detail": item.experiment,
            "uncertainty": item.review,
            "references": [
                {"title": evidence[item.evidence_index].title},
                {
                    "title": evidence[
                        (item.evidence_index + 1) % len(evidence)
                    ].title
                },
            ],
        }
        for item in hypotheses[:6]
    ]


# R14-6: which of a scenario's three top research directions each of its
# first three evidence sources (the ``evidence[:3]`` a contact is drawn
# from) most directly speaks to, plus the group's "why they are best for
# this direction" rationale -- grounded in what that specific source
# actually reports, not a generic template. Order matches
# ``_overview_contacts``'s own ``evidence[:3]`` iteration.
_CONTACT_DIRECTIONS: dict[str, tuple[tuple[int, str], ...]] = {
    _SCENARIO_KEYS[0]: (
        (
            1,
            "Ma et al. is the primary source connecting the MazEF toxin-antitoxin system to S. aureus biofilm antibiotic tolerance, the state marker this direction proposes to track.",
        ),
        (
            2,
            "Tuon et al.'s review explains why intact-biofilm physiology, not just planktonic susceptibility, governs antibiotic response — the premise behind treating the matrix as a spatial niche.",
        ),
        (
            0,
            "Kim et al. link small-molecule activation of respiration to reduced biofilm formation and higher aminoglycoside sensitivity — the same 'raise metabolic activity before antibiotic exposure' logic this direction tests.",
        ),
    ),
    _SCENARIO_KEYS[1]: (
        (
            0,
            "Mallya et al. is the primary source reporting a transient, adolescence-restricted rise in microglial synaptic engulfment in the prefrontal cortex — the timing window this direction proposes to calibrate.",
        ),
        (
            2,
            "Kätzel et al. tie adolescent prefrontal circuit reorganization directly to later cognitive maturation, the circuit-to-behavior link this direction tests.",
        ),
        (
            1,
            "Koss et al. describe subregion-specific adolescent spine refinement and shifts in cytoskeletal regulatory factors, consistent with selective rather than bulk synapse turnover.",
        ),
    ),
    _SCENARIO_KEYS[2]: (
        (
            0,
            "Liu et al. is the primary source connecting CPEB1 loss to p62/KEAP1/NRF2 signaling and reduced ferroptosis susceptibility, the exact axis this direction proposes.",
        ),
        (
            1,
            "Mao et al. is the primary source linking ARID3A, PTEN, and GPX4 to gemcitabine response through ferroptosis, the pathway this direction stratifies on.",
        ),
        (
            2,
            "Hsu et al.'s NRF2-ADSL ferroptosis-escape work motivates using an early redox/lipid-peroxidation signal, rather than a static marker, to detect that escape.",
        ),
    ),
}


def _overview_contacts(
    evidence: tuple[DemoEvidence, ...],
    top: tuple[DemoHypothesis, ...],
    directions: tuple[tuple[int, str], ...],
) -> list[dict[str, Any]]:
    """Return the authorship-derived contacts, each tagged to a direction."""
    return [
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
            "research_direction": top[directions[index][0]].title,
        }
        for index, evidence_item in enumerate(evidence[:3])
    ]


def _overview_contact_groups(
    top: tuple[DemoHypothesis, ...],
    directions: tuple[tuple[int, str], ...],
    hypothesis_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Return one contact group per direction (R14-6), example ids included."""
    return [
        {
            "research_direction": top[direction_index].title,
            "rationale": rationale,
            "example_hypothesis_ids": [hypothesis_ids[direction_index]],
        }
        for direction_index, rationale in directions
    ]


def _overview_nih_aims(top: tuple[DemoHypothesis, ...]) -> dict[str, Any]:
    """Return the grant-style NIH Specific Aims sub-document."""
    return {
        "disease_description": (
            "This curated demonstration models a grant-style synthesis of a "
            "condition whose broad phenomenon is established but whose "
            "driving mechanism is not."
        ),
        "unmet_need": (
            "The central gap is not whether the broad phenomenon exists, but "
            "which specific causal mechanism is both measurable and "
            "falsifiable."
        ),
        "proposed_solution": (
            "Separate the competing mechanisms and decide between them with "
            "perturbation, rescue, and independent-model replication."
        ),
        "aims": _overview_aims(top),
        "pilot_evaluation": (
            "The intended output is a reproducible decision framework for "
            "prioritizing a preclinical mechanism. It is illustrative only and "
            "does not establish a clinical intervention."
        ),
    }


def _curated_research_overview(
    scenario: DemoScenario,
    evidence: tuple[DemoEvidence, ...],
    hypotheses: tuple[DemoHypothesis, ...],
    hypothesis_ids: list[str],
) -> dict[str, Any]:
    """Build the complete terminal synthesis shape used by real runs."""
    top = hypotheses[:3]
    directions = _CONTACT_DIRECTIONS[scenario_key(scenario)]
    ids = tuple(hypothesis_ids[:3])
    return {
        "overview": {
            "summary": (
                f"{scenario.meta_review} The ranked program deliberately keeps "
                "competing mechanisms separate, then uses perturbation, rescue, "
                "and independent-model replication to decide which should advance."
            ),
            "research_directions": _overview_directions(top),
        },
        "nih_specific_aims": _overview_nih_aims(top),
        "research_contacts": _overview_contacts(evidence, top, directions),
        "research_contact_groups": _overview_contact_groups(
            top, directions, ids
        ),
        "knowledge_base": _overview_knowledge_base(evidence, hypotheses),
        "unexpected_research_directions": curated_unexpected_directions(
            scenario_key(scenario)
        ),
    }
