from __future__ import annotations

import dataclasses
import itertools
import re
import time
from typing import Any

from app.citations import CitationState
from app.claims.gate import ClaimRole, EntailmentLabel
from app.demo_seed_data import (
    _SCENARIO_KEYS,
    DEMO_SEED_VERSION,
    DemoEvidence,
    DemoHypothesis,
    DemoScenario,
    scenario_evidence,
    scenario_hypotheses,
    scenario_key,
)
from app.report import ReportRequest, build_report_content
from app.run_modes import PlanningLists
from app.seed.chat import seed_example_chat
from app.seed.overview import (
    _curated_meta_review,
    _curated_research_overview,
    mature_review_rows,
)
from app.store import events, reports, runs
from app.store import hypotheses as store_hypotheses
from app.store import records as store
from app.store import retrieval_calls as retrieval
from app.store import runs_views as views
from app.store.hypotheses import HypothesisStateChanges, NewHypothesis
from app.store.models import RunRow, RunStatus
from app.store.records import (
    NewCitation,
    NewClaimEvidence,
    NewEvidence,
    NewMatch,
    NewProximityEdge,
    NewReview,
)

# ruff: noqa: E501


_STRATIFICATION_ATTRIBUTES: dict[str, tuple[dict[str, str], ...]] = {
    _SCENARIO_KEYS[0]: (
        {
            "name": "Mechanistic specificity",
            "rubric": "1 = generic stress or growth-rate explanation; 3 = plausible with an untested confound; 5 = isolated from growth-rate and generic-stress alternatives by a rescue or genetic control",
        },
        {
            "name": "Biofilm relevance",
            "rubric": "1 = planktonic-only evidence; 3 = tested in young or immature biofilms; 5 = tested in mature, clinical-isolate biofilms with matched planktonic controls",
        },
        {
            "name": "Translational caution",
            "rubric": "1 = implies treatment readiness; 3 = notes preclinical status without controls; 5 = explicitly scoped as preclinical and gated on strain-aware replication",
        },
    ),
    _SCENARIO_KEYS[1]: (
        {
            "name": "Temporal precision",
            "rubric": "1 = adolescence treated as one uniform window; 3 = a window is proposed without pre-registration; 5 = a pre-registered window compared against an explicit outside-window control",
        },
        {
            "name": "Circuit-to-behavior linkage",
            "rubric": "1 = circuit and behavior measured separately; 3 = both measured but not mediation-tested; 5 = the same cohort links circuit change to behavior with a pre-specified mediation analysis",
        },
        {
            "name": "Causal perturbation strength",
            "rubric": "1 = correlational only; 3 = a perturbation exists but lacks a rescue; 5 = a targeted perturbation with an independent rescue arm",
        },
    ),
    _SCENARIO_KEYS[2]: (
        {
            "name": "Death-pathway specificity",
            "rubric": "1 = viability-only readout; 3 = lipid peroxidation measured without an orthogonal control; 5 = ferroptosis distinguished from apoptosis or necroptosis by orthogonal rescue",
        },
        {
            "name": "Biomarker stratification",
            "rubric": "1 = unselected panel only; 3 = a candidate biomarker proposed but unvalidated; 5 = response stratified by a biomarker validated across an independent model panel",
        },
        {
            "name": "Combination rationale",
            "rubric": "1 = no mechanistic link to gemcitabine response; 3 = a plausible link without dose ordering; 5 = a mechanistic link with dose ordering and normal-cell toxicity characterized",
        },
    ),
}


def _questions(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "question": question} for name, question in pairs]


_CRITICAL_CRITERIA: dict[str, tuple[dict[str, Any], ...]] = {
    _SCENARIO_KEYS[0]: (
        {
            "name": "Causal specificity",
            "description": "Whether the proposal isolates its mechanism from generic growth-rate or stress-response confounds.",
            "questions": _questions(
                (
                    "Confound control",
                    "Does the design include a control that rules out a generic growth-rate or stress-response explanation?",
                ),
                (
                    "Rescue evidence",
                    "Is a rescue or knockdown/knockout arm specified that would restore the untreated phenotype?",
                ),
                (
                    "Causal chain",
                    "Does the proposal state which perturbation, readout, and expected direction would falsify the mechanism?",
                ),
            ),
        },
        {
            "name": "Biofilm relevance",
            "description": "Whether the evidence comes from mature, clinical-isolate biofilms rather than planktonic or immature-biofilm surrogates.",
            "questions": _questions(
                (
                    "Biofilm maturity",
                    "Are the biofilms mature (typically 48 hours or more) rather than early-attachment surrogates?",
                ),
                (
                    "Isolate diversity",
                    "Does the design include more than one clinical isolate or genetic background?",
                ),
                (
                    "Planktonic control",
                    "Is a matched planktonic control included to separate biofilm-specific effects from general antibiotic response?",
                ),
            ),
        },
        {
            "name": "Experimental tractability",
            "description": "Whether the proposed measurements and interventions are achievable with standard biofilm and microbiology methods.",
            "questions": _questions(
                (
                    "Readout feasibility",
                    "Can the primary readout (e.g. CFU, ATP, kill-curve) be measured reliably in an intact biofilm?",
                ),
                (
                    "Timeline realism",
                    "Is the proposed timeline consistent with standard biofilm growth and antibiotic-exposure protocols?",
                ),
                (
                    "Technical risk",
                    "Are technically demanding steps (e.g. spatial imaging, epistasis strains) sequenced after simpler validation steps?",
                ),
            ),
        },
        {
            "name": "Safety",
            "description": "Whether the proposal avoids implying clinical treatment guidance from preclinical biofilm data.",
            "questions": _questions(
                (
                    "Scope statement",
                    "Does the proposal explicitly frame its findings as preclinical rather than treatment guidance?",
                ),
                (
                    "Dose framing",
                    "Are antibiotic or metabolic-stimulus doses framed as experimental conditions, not therapeutic recommendations?",
                ),
                (
                    "Overclaim check",
                    "Does the proposal avoid asserting that an in-vitro mechanism is already established in patients?",
                ),
            ),
        },
    ),
    _SCENARIO_KEYS[1]: (
        {
            "name": "Temporal specificity",
            "description": "Whether the proposal targets a defined adolescent window rather than treating adolescence as one uniform period.",
            "questions": _questions(
                (
                    "Window definition",
                    "Is the candidate developmental window defined and pre-registered before data collection?",
                ),
                (
                    "Outside-window control",
                    "Does the design include an age-matched control perturbed outside the candidate window?",
                ),
                (
                    "Timing confound",
                    "Does the design rule out that an observed effect reflects total exposure duration rather than window timing?",
                ),
            ),
        },
        {
            "name": "Circuit-to-behavior link",
            "description": "Whether circuit-level and behavioral measures are collected in the same animals with a stated link between them.",
            "questions": _questions(
                (
                    "Same-subject design",
                    "Are circuit and behavioral measures collected in the same animals rather than separate cohorts?",
                ),
                (
                    "Mediation test",
                    "Is a mediation or equivalent analysis specified linking the circuit measure to the behavioral outcome?",
                ),
                (
                    "Readout specificity",
                    "Is the behavioral task specific to cognitive flexibility rather than general locomotor or exploratory activity?",
                ),
            ),
        },
        {
            "name": "Causal perturbation",
            "description": "Whether the proposal manipulates the candidate mechanism directly rather than relying on observational correlation.",
            "questions": _questions(
                (
                    "Targeted manipulation",
                    "Does the proposal specify a targeted, not systemic, perturbation of the candidate mechanism?",
                ),
                (
                    "Rescue arm",
                    "Is a rescue or reversal condition included to support a causal, not merely correlational, claim?",
                ),
                (
                    "Cell-type specificity",
                    "Is the perturbation restricted to the implicated cell type rather than a broad inflammatory or systemic manipulation?",
                ),
            ),
        },
        {
            "name": "Replicability",
            "description": "Whether the design anticipates and controls for known confounds in developmental behavioral neuroscience.",
            "questions": _questions(
                (
                    "Sex as a variable",
                    "Does the design include, or explicitly justify excluding, sex as a biological variable?",
                ),
                (
                    "Locomotor control",
                    "Are locomotor and exploratory controls included to rule out non-specific behavioral effects?",
                ),
                (
                    "Cohort power",
                    "Is the cohort size, or a pilot-then-confirm plan, specified to support the proposed interaction tests?",
                ),
            ),
        },
    ),
    _SCENARIO_KEYS[2]: (
        {
            "name": "Pathway specificity",
            "description": "Whether the proposal distinguishes ferroptosis from other death pathways rather than treating cell death as a single endpoint.",
            "questions": _questions(
                (
                    "Death-pathway control",
                    "Does the design include an orthogonal death-pathway control (e.g. an apoptosis or necroptosis inhibitor) alongside the ferroptosis readout?",
                ),
                (
                    "Lipid peroxidation evidence",
                    "Is lipid peroxidation measured directly rather than inferred solely from viability loss?",
                ),
                (
                    "Rescue specificity",
                    "Does a proposed rescue restore viability specifically through the ferroptosis-linked mechanism rather than general antioxidant protection?",
                ),
            ),
        },
        {
            "name": "Model generalizability",
            "description": "Whether the finding is tested beyond a single cell line or model system.",
            "questions": _questions(
                (
                    "Model diversity",
                    "Does the design include both cell-line and organoid or patient-derived models?",
                ),
                (
                    "Independent validation",
                    "Is an independent validation set reserved and not used during model or predictor development?",
                ),
                (
                    "Biomarker range",
                    "Is the candidate biomarker tested across a range of expression rather than only extreme high/low models?",
                ),
            ),
        },
        {
            "name": "Combination rationale",
            "description": "Whether the proposed drug combination has a specified mechanistic link rather than an empirical pairing.",
            "questions": _questions(
                (
                    "Mechanistic link",
                    "Does the proposal state the specific molecular link between the perturbation and gemcitabine sensitization?",
                ),
                (
                    "Dose ordering",
                    "Is the order and timing of combination dosing specified and justified?",
                ),
                (
                    "Synergy evidence",
                    "Is a synergy or potentiation analysis specified beyond a simple additive-effect comparison?",
                ),
            ),
        },
        {
            "name": "Safety",
            "description": "Whether the proposal accounts for normal-tissue toxicity and avoids treatment claims from preclinical data.",
            "questions": _questions(
                (
                    "Normal-cell toxicity",
                    "Does the design include a normal or non-tumor cell control for combination toxicity?",
                ),
                (
                    "Scope statement",
                    "Does the proposal explicitly frame its findings as preclinical and not patient-care guidance?",
                ),
                (
                    "Therapeutic index",
                    "Is a therapeutic index or comparable safety margin considered before combination doses are proposed?",
                ),
            ),
        },
    ),
}


def curated_stratification_attributes(key: str) -> list[dict[str, str]]:
    return [dict(item) for item in _STRATIFICATION_ATTRIBUTES[key]]


def curated_critical_criteria(key: str) -> list[dict[str, Any]]:
    return [
        {**item, "questions": [dict(q) for q in item["questions"]]}
        for item in _CRITICAL_CRITERIA[key]
    ]


# ruff: noqa: E501


_PLANNING_LISTS: dict[str, PlanningLists] = {
    _SCENARIO_KEYS[0]: PlanningLists(
        requirements=[
            "Separate phenotypic antibiotic tolerance from stable resistance.",
            "Use mature biofilms, clinical-isolate replication, and matched planktonic controls.",
            "Advance only mechanisms with a measurable perturbation, rescue, and kill-curve readout.",
            "Measure matrix permeability and cellular physiology in the same intact-biofilm experiment.",
            "Distinguish transient persister recovery from stable small-colony or resistance lineages.",
            "Do not infer clinical treatment benefit from the preclinical demonstration.",
        ],
        attributes=[
            {
                "name": "Mechanistic discrimination",
                "scale": {
                    "1": "No distinction from a generic growth-rate or stress-response confound",
                    "3": "Plausible mechanism with an untested confound",
                    "5": "Isolated from a growth-rate or stress-response confound by a rescue or genetic control",
                },
            },
            {
                "name": "Strain generalizability",
                "scale": {
                    "1": "Single-isolate observation only",
                    "3": "Reproduced in a second clinical isolate",
                    "5": "Reproduced across three or more clinical isolates spanning distinct genetic backgrounds",
                },
            },
            {
                "name": "Spatial resolution",
                "scale": {
                    "1": "Bulk, well-level readout only",
                    "3": "Coarse spatial readout (e.g. biofilm layer)",
                    "5": "Micro-region or single-cell resolved readout within an intact biofilm",
                },
            },
            {
                "name": "Replication readiness",
                "scale": {
                    "1": "No defined rescue or control arm",
                    "3": "A rescue arm is proposed but not yet validated",
                    "5": "A validated rescue or knockdown arm with a pre-specified kill-curve endpoint",
                },
            },
            {
                "name": "Primary tolerance mechanism",
                "values": [
                    "Metabolic state",
                    "Matrix or spatial niche",
                    "Genetic regulatory network",
                ],
            },
        ],
    ),
    _SCENARIO_KEYS[1]: PlanningLists(
        requirements=[
            "Resolve developmental timing rather than treating adolescence as a single window.",
            "Measure circuit, cellular, and behavioral outcomes in the same experimental framework.",
            "Include sex, subregion, locomotor, and stress controls before assigning a flexibility phenotype.",
            "Separate total synapse number from selective refinement of activity-defined synapses.",
            "Use temporally restricted perturbations and an age-matched adult control condition.",
            "Treat the model as developmental neuroscience, not a clinical disease mechanism.",
        ],
        attributes=[
            {
                "name": "Temporal specificity",
                "scale": {
                    "1": "No defined developmental window",
                    "3": "A candidate window is proposed but not pre-registered",
                    "5": "A pre-registered window compared against an explicit outside-window control",
                },
            },
            {
                "name": "Cell-type specificity",
                "scale": {
                    "1": "Bulk tissue manipulation only",
                    "3": "Cell-type enrichment without a targeted perturbation",
                    "5": "A targeted, cell-type-specific perturbation with an independent rescue",
                },
            },
            {
                "name": "Circuit-to-behavior linkage",
                "scale": {
                    "1": "No behavioral readout",
                    "3": "A behavioral readout is collected but not linked mechanistically",
                    "5": "Circuit and behavioral readouts in the same cohort with a pre-specified mediation test",
                },
            },
            {
                "name": "Multimodal integration",
                "scale": {
                    "1": "A single modality (e.g. histology only)",
                    "3": "Two modalities collected but not co-registered",
                    "5": "Circuit, cellular, and behavioral modalities co-registered in one longitudinal cohort",
                },
            },
            {
                "name": "Primary refinement mechanism",
                "values": [
                    "Microglial engulfment",
                    "Complement tagging",
                    "Circuit synchrony",
                ],
            },
        ],
    ),
    _SCENARIO_KEYS[2]: PlanningLists(
        requirements=[
            "Treat every proposed combination as a preclinical, biomarker-stratified hypothesis.",
            "Distinguish ferroptosis from apoptosis and other death pathways with orthogonal rescue controls.",
            "Validate a locked prediction in independent cell-line and organoid models before translation.",
            "Measure lipid peroxidation, redox state, and clonogenic survival on a time-resolved schedule.",
            "Test target engagement and a genetic rescue before interpreting a drug combination as pathway-specific.",
            "Do not infer patient benefit or recommend treatment from the demonstration data.",
        ],
        attributes=[
            {
                "name": "Death-pathway resolution",
                "scale": {
                    "1": "Viability endpoint only, death pathway unresolved",
                    "3": "Lipid peroxidation measured without an orthogonal death-pathway control",
                    "5": "Ferroptosis distinguished from apoptosis or necroptosis by orthogonal rescue",
                },
            },
            {
                "name": "Biomarker specificity",
                "scale": {
                    "1": "No biomarker stratification",
                    "3": "A candidate biomarker is proposed but not validated across models",
                    "5": "Response stratified by a biomarker validated across an independent model panel",
                },
            },
            {
                "name": "Experimental readiness",
                "scale": {
                    "1": "No defined perturbation-rescue pair",
                    "3": "A perturbation is proposed without a matched rescue",
                    "5": "A perturbation-rescue pair with a pre-specified clonogenic or lipid-peroxidation endpoint",
                },
            },
            {
                "name": "Translational caution",
                "scale": {
                    "1": "Findings framed as directly clinically actionable",
                    "3": "Framed cautiously but without an explicit preclinical-only statement",
                    "5": "Explicitly scoped as preclinical, gated on independent patient-derived organoid validation",
                },
            },
            {
                "name": "Primary resistance axis",
                "values": [
                    "NRF2/KEAP1 buffering",
                    "GPX4/lipid-peroxidation control",
                    "Redox-kinetic biomarker",
                ],
            },
        ],
    ),
}


def _scenario_planning_lists(scenario: DemoScenario | None) -> PlanningLists:
    if scenario is None:
        return PlanningLists()
    return _PLANNING_LISTS[scenario_key(scenario)]


# ruff: noqa: E501


# Derive PMIDs from the curated PubMed URLs rather than inventing separately
# authored identifiers.
_PUBMED_URL_PMID = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


def _pmid_from_url(url: str) -> str | None:
    match = _PUBMED_URL_PMID.search(url)
    return match.group(1) if match else None


def insert_scenario_evidence(
    run_id: str,
    evidence: tuple[DemoEvidence, ...],
    db_path: str | None,
) -> list[str]:
    return [
        store.add_evidence(
            NewEvidence(
                run_id=run_id,
                title=item.title,
                source="pubmed",
                url=item.url,
                authors=item.authors,
                year=item.year,
                abstract=item.abstract,
                pmid=_pmid_from_url(item.url),
            ),
            db_path=db_path,
        )
        for item in evidence
    ]


@dataclasses.dataclass(frozen=True)
class _CuratedSeed:
    run: RunRow
    scenario: DemoScenario
    evidence: tuple[DemoEvidence, ...]
    hypotheses: tuple[DemoHypothesis, ...]
    db_path: str | None


@dataclasses.dataclass(frozen=True)
class _ScenarioCounts:
    evidence: int
    initial_hypotheses: int
    hypotheses: int
    matches: int


def _initial_count(seed: _CuratedSeed) -> int:
    return (
        len(seed.hypotheses)
        - seed.scenario.evolution_count
        - seed.scenario.second_pass_count
    )


def _lineage(
    seed: _CuratedSeed, index: int, hypothesis_ids: list[str]
) -> tuple[str | None, int]:
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
    parent_id, generation = lineage
    hyp_id = store_hypotheses.add_hypothesis(
        NewHypothesis(
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
    store_hypotheses.update_hypothesis_state(
        hyp_id,
        HypothesisStateChanges(
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
            NewReview(
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
    evidence = seed.evidence[item.evidence_index]
    evidence_id = evidence_ids[item.evidence_index]
    claim = item.statement
    store.add_citation(
        NewCitation(
            run_id=seed.run.id,
            hypothesis_id=hyp_id,
            evidence_id=evidence_id,
            claim=claim,
            state=CitationState.PARTIAL,
        ),
        db_path=seed.db_path,
    )
    store.add_claim_evidence(
        NewClaimEvidence(
            run_id=seed.run.id,
            hypothesis_id=hyp_id,
            claim=claim,
            label=EntailmentLabel.PARTIAL.value,
            claim_role=ClaimRole.SPECULATIVE.value,
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
    key = scenario_key(seed.scenario)
    hypothesis_ids: list[str] = []
    for index, item in enumerate(seed.hypotheses):
        lineage = _lineage(seed, index, hypothesis_ids)
        hyp_id = _add_hypothesis(seed, index, item, lineage)
        hypothesis_ids.append(hyp_id)
        _add_reviews(seed, hyp_id, index, item)
        # Only leading ideas receive expensive full/simulation reviews, matching
        # the selective mature-review cascade.
        for review in mature_review_rows(seed.run.id, hyp_id, key, index):
            store.add_review(review, db_path=seed.db_path)
        _add_claim_rows(seed, hyp_id, item, evidence_ids)
    return hypothesis_ids


def _matchups(count: int) -> list[tuple[int, int]]:
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
) -> NewMatch:
    winner_index, loser_index = pair
    scenario = seed.scenario
    winner_elo = scenario.elo_ceiling - winner_index * scenario.elo_step
    loser_elo = scenario.elo_ceiling - loser_index * scenario.elo_step
    return NewMatch(
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
    match = _match_row(seed, iteration, pair, hypothesis_ids)
    store.add_match(match, db_path=seed.db_path)
    store_hypotheses.update_hypothesis_state(
        match.winner_id,
        HypothesisStateChanges(win_delta=1),
        db_path=seed.db_path,
    )
    store_hypotheses.update_hypothesis_state(
        match.loser_id,
        HypothesisStateChanges(loss_delta=1),
        db_path=seed.db_path,
    )


def _seed_tournament(
    seed: _CuratedSeed, hypothesis_ids: list[str]
) -> list[tuple[int, int]]:
    matchups = _matchups(len(hypothesis_ids))
    for iteration, pair in enumerate(matchups, start=1):
        _record_match(seed, iteration, pair, hypothesis_ids)
    return matchups


def _seed_proximity(seed: _CuratedSeed, hypothesis_ids: list[str]) -> None:
    if len(hypothesis_ids) > 1:
        store.add_proximity_edge(
            NewProximityEdge(
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
        # Supervisor-synthesized guidance is distinct from the scientist's setup
        # fields; reports must not conflate them.
        attributes=curated_stratification_attributes(key),
        critical_criteria=curated_critical_criteria(key),
        prepared_at=time.time(),
        db_path=seed.db_path,
    )


async def _save_scenario_report(
    seed: _CuratedSeed, hypothesis_ids: list[str]
) -> dict[str, Any]:
    overview = _curated_research_overview(
        seed.scenario, seed.evidence, seed.hypotheses, hypothesis_ids
    )
    meta_review = _curated_meta_review(seed.scenario, seed.hypotheses)
    built = await build_report_content(
        seed.run.id,
        _scenario_report_request(seed, hypothesis_ids, overview, meta_review),
    )
    payload = {**built.payload, "demo_seed_version": DEMO_SEED_VERSION}
    banner = (
        "> **Curated demonstration only.** These are illustrative research "
        "proposals, not validated findings or treatment guidance.\n\n"
    )
    reports.save_report(
        seed.run.id,
        payload,
        banner + built.markdown,
        db_path=seed.db_path,
    )
    return meta_review


def _emit_scenario_events(
    seed: _CuratedSeed, counts: _ScenarioCounts, meta_review: dict[str, Any]
) -> None:
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
        events.append_event(
            seed.run.id, event_type, event_payload, db_path=seed.db_path
        )


def _finalize_scenario_run(seed: _CuratedSeed, counts: _ScenarioCounts) -> None:
    duration = seed.scenario.duration_seconds
    runs.update_run_status(
        seed.run.id, RunStatus.COMPLETED, db_path=seed.db_path
    )
    runs.set_run_timing(seed.run.id, duration, db_path=seed.db_path)
    retrieval.save_run_metrics(
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
    views.clear_run_derived_data(run.id, db_path=db_path)
    runs.set_run_title(run.id, f"Example: {scenario.title}", db_path=db_path)
    seed = _CuratedSeed(
        run=run,
        scenario=scenario,
        evidence=scenario_evidence(scenario),
        hypotheses=scenario_hypotheses(scenario),
        db_path=db_path,
    )
    evidence_ids = insert_scenario_evidence(
        seed.run.id, seed.evidence, seed.db_path
    )
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
    seed_example_chat(run, scenario, db_path)
