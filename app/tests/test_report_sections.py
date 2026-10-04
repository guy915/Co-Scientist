from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

import pytest

from app.report import build as report_build
from app.report import content as report_content
from app.report import gates as report_gates
from app.report import markdown as report_markdown
from app.report.markdown.hypothesis import _HYPOTHESIS_DISCLAIMER
from app.store import hypotheses, runs
from app.store import retrieval_calls as retrieval
from app.store.hypotheses import HypothesisStateChanges
from app.store.retrieval_calls import NewRetrievalCall
from app.store.runs import RunCreateOptions
from tests._drain_helpers import _build_report
from tests._store_helpers import _add


def test_empty_leaderboard_reason_names_review_rejection_alone() -> None:
    # Empty reports must name the exclusion causes that actually ran.
    tally = {
        "review_rejected": 15,
        "duplicate": 0,
        "contradicted": 0,
        "safety": 0,
    }

    reason = report_gates._empty_leaderboard_reason(15, tally)

    assert reason == (
        "No hypothesis could be published: of 15 ideas, 15 were rejected "
        "by peer review before ranking (the reviewer judged them "
        "inaccurate, non-novel, unsafe, or evidence-blocked)."
    )
    assert "safety review" not in reason
    assert "contradicted" not in reason


def test_empty_leaderboard_reason_keeps_safety_wording() -> None:
    tally = {
        "review_rejected": 0,
        "duplicate": 0,
        "contradicted": 0,
        "safety": 5,
    }

    reason = report_gates._empty_leaderboard_reason(5, tally)

    assert reason == (
        "No hypothesis could be published: of 5 ideas, 5 were withheld "
        "by the safety review."
    )
    assert "peer review" not in reason
    assert "contradicted" not in reason


def test_empty_leaderboard_reason_keeps_evidence_wording() -> None:
    tally = {
        "review_rejected": 0,
        "duplicate": 0,
        "contradicted": 3,
        "safety": 0,
    }

    reason = report_gates._empty_leaderboard_reason(3, tally)

    assert reason == (
        "No hypothesis could be published: of 3 ideas, 3 were "
        "contradicted by the evidence."
    )
    assert "peer review" not in reason
    assert "safety review" not in reason


def test_empty_leaderboard_reason_names_duplicates_distinctly() -> None:
    tally = {
        "review_rejected": 0,
        "duplicate": 2,
        "contradicted": 0,
        "safety": 0,
    }

    reason = report_gates._empty_leaderboard_reason(2, tally)

    assert "folded into a higher-ranked idea" in reason
    assert "peer review" not in reason
    assert "rejected" not in reason


def test_empty_leaderboard_reason_reads_a_mix_as_a_mix() -> None:
    tally = {
        "review_rejected": 2,
        "duplicate": 0,
        "contradicted": 1,
        "safety": 1,
    }

    reason = report_gates._empty_leaderboard_reason(4, tally)

    assert "2 were rejected by peer review" in reason
    assert "1 was contradicted by the evidence" in reason
    assert "1 was withheld by the safety review" in reason
    assert reason.count(",") >= 2


def test_empty_leaderboard_reason_handles_zero_ideas() -> None:
    reason = report_gates._empty_leaderboard_reason(
        0,
        {"review_rejected": 0, "duplicate": 0, "contradicted": 0, "safety": 0},
    )

    assert (
        reason == "No hypothesis could be published: the run produced no ideas."
    )


def _leaderboard_hypothesis(identifier: str, title: str) -> dict[str, object]:
    return {
        "id": identifier,
        "title": title,
        "statement": f"{title} changes the measured phenotype.",
        "safety_status": "allowed",
    }


def _contradicted(hypothesis_id: str, claim: str, role: str) -> dict[str, Any]:
    return {
        "hypothesis_id": hypothesis_id,
        "claim": claim,
        "label": "contradicts",
        "claim_role": role,
        "supporting": [],
        "contradicting": [{"evidence_id": "ev1", "quote": "A cited passage."}],
        "assessor": "llm",
    }


def test_a_contradicted_proposal_is_not_reported_as_withheld() -> None:
    # Proposal contradictions publish as findings; only categorical
    # contradictions withhold ideas.
    withheld = _leaderboard_hypothesis("h2", "Unsupported bypass")
    proposing = _leaderboard_hypothesis("h3", "Speculative bypass")
    edges = [
        _contradicted(
            "h2", "The bypass is constitutively active.", "categorical"
        ),
        _contradicted(
            "h3", "Blocking the loop may raise the flux.", "speculative"
        ),
    ]

    published = report_gates.exclude_unsafe_hypotheses(
        "run-1", [withheld, proposing], None, edges
    )
    insights = report_content._agent_insights(published, edges, {})

    assert [hyp["id"] for hyp in published] == ["h3"]
    by_claim = {
        entry.split(" (", 1)[0]: entry for entry in insights["contradictions"]
    }
    assert "withheld" in by_claim["The bypass is constitutively active."]
    assert "withheld" not in by_claim["Blocking the loop may raise the flux."]


def _sections_hypothesis(identifier: str, title: str) -> dict[str, object]:
    return {
        "id": identifier,
        "title": title,
        "statement": f"{title} changes the measured phenotype.",
        "mechanism": f"{title} acts through a causal feedback mechanism.",
        "experimental_context": f"Perturb {title} with matched controls.",
        "safety_status": "allowed",
    }


def _edge(
    hypothesis_id: str,
    claim: str,
    label: str,
    evidence_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    # Fixtures must use persisted claim/supporting keys to expose drift in the
    # real store contract.
    return {
        "hypothesis_id": hypothesis_id,
        "claim": claim,
        "label": label,
        "claim_role": "categorical",
        "supporting": [
            {"evidence_id": evidence_id, "quote": "A cited passage."}
            for evidence_id in evidence_ids
        ],
        "contradicting": [],
        "assessor": "llm",
    }


def test_goal_report_sections_preserve_claim_grounding() -> None:
    released = _sections_hypothesis("h1", "Feedback control")
    rejected = _sections_hypothesis("h2", "Unsupported bypass")
    edges = [
        _edge("h1", "Feedback is rate-limiting.", "supports", ("ev1",)),
        _edge("h2", "The bypass is constitutively active.", "contradicts"),
    ]

    topics = report_content._knowledge_base_topics([released], edges)
    insights = report_content._agent_insights(
        [released],
        edges,
        {"common_weaknesses": ["Cell-type specificity remains uncertain."]},
    )
    buckets = report_content._idea_buckets(
        [released], [released, rejected], edges
    )

    assert topics[0]["title"] == "Feedback control"
    assert topics[0]["reference_ids"] == ["ev1"]
    assert len(insights["contradictions"]) == 1
    assert insights["contradictions"][0].startswith(
        "The bypass is constitutively active."
    )
    assert insights["uncertainties"] == [
        "Cell-type specificity remains uncertain."
    ]
    assert buckets["high_potential"][0]["id"] == "h1"
    assert buckets["non_viable"][0]["id"] == "h2"
    assert "Evidence verification" in buckets["non_viable"][0]["reason"]


def test_idea_buckets_partition_every_idea() -> None:
    # Released and non-viable buckets must partition the entire pool, including
    # more than five released ideas.
    released = [
        _sections_hypothesis(f"h{i}", f"Released {i}") for i in range(7)
    ]
    excluded = [_sections_hypothesis("x1", "Excluded")]

    buckets = report_content._idea_buckets(released, released + excluded, [])

    assert len(buckets["high_potential"]) == 7
    assert len(buckets["non_viable"]) == 1
    assert {entry["id"] for entry in buckets["high_potential"]} | {
        entry["id"] for entry in buckets["non_viable"]
    } == {hyp["id"] for hyp in released + excluded}


def test_idea_bucket_titles_use_the_shared_title_helper() -> None:
    released: dict[str, object] = {
        "id": "h1",
        "text": "Feedback control is rate-limiting.",
    }
    excluded: dict[str, object] = {
        "id": "h2",
        "text": "The bypass is constitutively active.",
        "status": "rejected",
    }

    buckets = report_content._idea_buckets([released], [released, excluded], [])

    assert (
        buckets["high_potential"][0]["title"]
        == "Feedback control is rate-limiting."
    )
    assert (
        buckets["non_viable"][0]["title"]
        == "The bypass is constitutively active."
    )


def test_idea_buckets_explain_a_review_rejected_idea_as_deduplicated() -> None:
    # Unsupported ideas publish as Unverified; rejection must not be misreported
    # as an evidence block.
    released = _sections_hypothesis("h1", "Feedback control")
    deduped = _sections_hypothesis("h2", "Near-duplicate idea")
    deduped["status"] = "rejected"
    edges = [_edge("h2", "A speculative claim.", "insufficient", ("ev1",))]
    edges[0]["claim_role"] = "speculative"
    buckets = report_content._idea_buckets(
        [released], [released, deduped], edges
    )
    reason = buckets["non_viable"][0]["reason"].lower()
    assert "review" in reason or "duplicate" in reason
    assert "release gate" not in reason


def test_a_duplicate_and_a_rejected_idea_get_different_reasons() -> None:
    # Duplicates were never judged; merging them must not read as failed peer
    # review.
    released = _sections_hypothesis("h1", "Feedback control")
    deduped = _sections_hypothesis("h2", "Near-duplicate idea")
    deduped["status"] = "duplicate"
    rejected = _sections_hypothesis("h3", "Unsound idea")
    rejected["status"] = "rejected"

    buckets = report_content._idea_buckets(
        [released], [released, deduped, rejected], []
    )

    reasons = {entry["id"]: entry["reason"] for entry in buckets["non_viable"]}
    assert "higher-ranked" in reasons["h2"]
    assert "review" in reasons["h3"].lower()
    assert reasons["h2"] != reasons["h3"]


def test_contradictions_carry_claim_text_and_never_blank_entries() -> None:
    hypothesis = _sections_hypothesis("h1", "Feedback control")
    edges = [
        _edge("h1", "The bypass is constitutively active.", "contradicts"),
        _edge("h1", "", "contradicts"),
        _edge("h1", "Feedback is rate-limiting.", "supports"),
    ]

    insights = report_content._agent_insights([hypothesis], edges, {})

    assert len(insights["contradictions"]) == 1
    assert insights["contradictions"][0].startswith(
        "The bypass is constitutively active."
    )


def test_contradictions_name_ideas_the_report_withholds() -> None:
    # Contradiction panels need the whole edge pool: restricting to released
    # edges hides every withheld idea.
    released = _sections_hypothesis("h1", "Feedback control")
    contradicted = _sections_hypothesis("h2", "Unsupported bypass")
    edges = [
        _edge("h1", "Feedback is rate-limiting.", "supports", ("ev1",)),
        _edge("h2", "The bypass is constitutively active.", "contradicts"),
    ]

    published = report_gates.exclude_unsafe_hypotheses(
        "run-1", [released, contradicted], None, edges
    )
    released_edges = report_content.released_claim_evidence(
        published, edges, []
    )
    insights = report_content._agent_insights(published, edges, {})

    assert [hyp["id"] for hyp in published] == ["h1"]
    assert not [e for e in released_edges if e["label"] == "contradicts"]
    entry = insights["contradictions"][0]
    assert entry.startswith("The bypass is constitutively active.")
    assert "withheld" in entry


def test_insights_and_markdown_show_one_statement_per_idea() -> None:
    # Panel and body must quote the same whole proposal rather than different
    # title/text fallbacks.
    hypothesis = {
        "id": "h1",
        "title": "Feedback control is rate-limiting.",
        "text": (
            "Feedback control is rate-limiting. Blocking the loop raises "
            "the steady-state flux."
        ),
    }

    insights = report_content._agent_insights([hypothesis], [], {})
    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[hypothesis],
        )
    )

    finding = insights["key_findings"][0].removeprefix("Proposed hypothesis: ")
    rendered_label = "**Proposed hypothesis:** "
    rendered = [
        line.removeprefix(rendered_label)
        for line in markdown.splitlines()
        if line.startswith(rendered_label)
    ]
    assert rendered == [finding]
    assert finding == hypothesis["text"]


def test_markdown_renders_scene_setting_before_the_proposed_hypothesis() -> (
    None
):
    hypothesis = {
        "id": "h1",
        "title": "Feedback control is rate-limiting.",
        "statement": "Blocking the loop raises the steady-state flux.",
        "introduction": "Metabolic disease remains a major cause of morbidity.",
        "recent_findings": "Feedback inhibition has been studied for decades.",
        "mechanism": "The enzyme is allosterically inhibited by its product.",
    }

    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[hypothesis],
        )
    )

    intro_at = markdown.index("#### Introduction")
    findings_at = markdown.index("#### Recent findings and related research")
    statement_at = markdown.index("**Proposed hypothesis:**")
    assert intro_at < findings_at < statement_at
    assert "Metabolic disease remains a major cause of morbidity." in markdown
    assert "Feedback inhibition has been studied for decades." in markdown


def test_markdown_renders_the_proposers_safety_and_toxicity_section() -> None:
    # Proposer safety/toxicity is distinct from the reviewer safety assessment.
    hypothesis = {
        "id": "h1",
        "title": "Feedback control is rate-limiting.",
        "statement": "Blocking the loop raises the steady-state flux.",
        "mechanism": "The enzyme is allosterically inhibited by its product.",
        "safety_and_toxicity": (
            "Limited human safety data exists for this class."
        ),
    }

    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[hypothesis],
        )
    )

    assert "#### Safety and toxicity" in markdown
    assert "Limited human safety data exists for this class." in markdown


def test_markdown_omits_safety_and_toxicity_when_absent() -> None:
    hypothesis = {
        "id": "h1",
        "title": "Feedback control is rate-limiting.",
        "statement": "Blocking the loop raises the steady-state flux.",
    }

    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[hypothesis],
        )
    )

    assert "#### Safety and toxicity" not in markdown


def test_markdown_omits_scene_setting_sections_when_absent() -> None:
    hypothesis = {
        "id": "h1",
        "title": "Feedback control is rate-limiting.",
        "statement": "Blocking the loop raises the steady-state flux.",
    }

    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the feedback loop.",
            provider="engine",
            top_hypotheses=[hypothesis],
        )
    )

    assert "#### Introduction" not in markdown
    assert "#### Recent findings and related research" not in markdown


def test_key_findings_omit_an_idea_with_no_proposal_text() -> None:
    with_text = {"id": "h1", "statement": "Blocking the loop raises flux."}
    without_text = {"id": "h2", "title": "A title with no statement."}

    insights = report_content._agent_insights([with_text, without_text], [], {})

    assert insights["key_findings"] == [
        "Proposed hypothesis: Blocking the loop raises flux."
    ]


def test_recommended_directions_keep_their_three_named_fields() -> None:
    meta = {
        "strategic_recommendations": [
            {
                "focus_area": "Receptor pharmacology",
                "recommendation": "Measure binding directly.",
                "justification": "The affinity is unproven.",
            },
            "A bare string recommendation.",
        ]
    }

    insights = report_content._agent_insights([], [], meta)

    assert insights["recommended_directions"] == [
        {
            "focus_area": "Receptor pharmacology",
            "recommendation": "Measure binding directly.",
            "justification": "The affinity is unproven.",
        },
        {
            "focus_area": "",
            "recommendation": "A bare string recommendation.",
            "justification": "",
        },
    ]


def test_synthesized_topics_map_only_to_persisted_evidence() -> None:
    overview = {
        "knowledge_base": [
            {
                "id": "topic-1",
                "title": "Cross-source mechanism",
                "summary": "Two findings converge.",
                "detail": "A detailed synthesis.",
                "uncertainty": "The causal direction remains uncertain.",
                "references": [
                    {"title": "Persisted study"},
                    {"title": "Missing study"},
                ],
            },
            {
                "id": "topic-2",
                "title": "Unsupported synthesis",
                "references": [{"title": "Missing study"}],
            },
        ]
    }
    topics = report_content._synthesized_knowledge_base_topics(
        overview, [{"id": "ev-1", "title": "Persisted study"}]
    )

    assert len(topics) == 1
    assert topics[0]["reference_ids"] == ["ev-1"]
    assert topics[0]["uncertainty"].startswith("The causal direction")


async def test_report_body_opens_with_the_same_idea_as_the_standings(
    isolated_db: str,
) -> None:
    # Markdown and leaderboard must apply the same demotion for fundamentally
    # undermined ideas.
    run = runs.create_run("ordering goal", "standard", "engine", {})
    doubted = _add(run.id, "Doubted idea", "A doubted proposal.", isolated_db)
    sound = _add(run.id, "Sound idea", "A sound proposal.", isolated_db)
    hypotheses.update_hypothesis_state(
        doubted,
        HypothesisStateChanges(
            elo_rating=1300,
            win_delta=3,
            verification_verdict="undermined",
        ),
        db_path=isolated_db,
    )
    hypotheses.update_hypothesis_state(
        sound,
        HypothesisStateChanges(elo_rating=1100, win_delta=1),
        db_path=isolated_db,
    )

    payload, markdown = await _build_report(run, isolated_db)

    assert [row["id"] for row in payload["leaderboard"]] == [sound, doubted]
    assert markdown.index("Sound idea") < markdown.index("Doubted idea")


_DocumentFn = Callable[[report_markdown.ReportMarkdownInputs], str]


def _disclosure_markdown(fn: _DocumentFn) -> str:
    return fn(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
        )
    )


def test_the_overview_document_carries_the_about_disclosure() -> None:
    markdown = _disclosure_markdown(report_markdown.render_report_markdown)

    assert (
        "**About**: *This is an experimental system for generating novel"
        " and testable hypotheses. The hypotheses are generated by a"
        " model and may be wrong. For research purposes only.*"
    ) in markdown


def test_it_is_byte_identical_to_the_per_hypothesis_disclaimer() -> None:
    markdown = _disclosure_markdown(report_markdown.render_report_markdown)

    assert _HYPOTHESIS_DISCLAIMER in markdown


def test_it_renders_before_the_table_of_contents() -> None:
    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            meta_review={"summary": "Ideas converge on a shared mechanism."},
        )
    )

    about_at = markdown.index("**About**:")
    toc_at = markdown.index("#### Table of contents:")
    assert about_at < toc_at


def _provenance_markdown(prepared_at: float | None) -> str:
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            prepared_at=prepared_at,
        )
    )


def test_the_header_carries_the_research_purposes_only_caution() -> None:
    markdown = _provenance_markdown(1_700_000_000.0)

    assert "For research purposes only." in markdown


def test_the_header_names_this_system_not_googles() -> None:
    markdown = _provenance_markdown(1_700_000_000.0)

    assert "Prepared by Co-Scientist on" in markdown
    assert "AI co-scientist" not in markdown


def test_the_date_is_derived_from_prepared_at_not_wall_clock() -> None:
    timestamp = 1_700_000_000.0
    expected = (
        datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        .date()
        .isoformat()
    )

    markdown = _provenance_markdown(timestamp)

    assert expected in markdown


def test_no_prepared_at_renders_no_provenance_line() -> None:
    # Legacy reports have no known preparation date; rendering the wall clock
    # would invent provenance.
    markdown = _provenance_markdown(None)

    assert "Prepared by" not in markdown


def _notice_markdown(skills_used: dict[str, int] | None) -> str:
    hypothesis: dict[str, Any] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            skills_used=skills_used,
        )
    )


def test_a_queried_source_is_named_with_its_terms() -> None:
    markdown = _notice_markdown({"string-database": 2})

    assert "## Data sources" in markdown
    assert "string-database" in markdown
    assert "SKILL_LICENSES.md" in markdown


def test_a_source_the_run_never_touched_is_not_claimed() -> None:
    # Installed sources are not evidence that a run queried them.
    markdown = _notice_markdown({"string-database": 1})

    assert "chembl-database" not in markdown


def test_a_run_without_skills_carries_no_notice() -> None:
    assert "## Data sources" not in _notice_markdown(None)
    assert "## Data sources" not in _notice_markdown({})


def _retrieval_markdown(retrieval_calls: list[dict[str, Any]] | None) -> str:
    hypothesis: dict[str, Any] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            retrieval_calls=retrieval_calls,
        )
    )


def _call(
    source: str, question: str, question_id: str, query: str = "q"
) -> dict[str, Any]:
    return {
        "source": source,
        "question": question,
        "question_id": question_id,
        "query": query,
    }


def test_a_run_with_searches_names_source_and_count() -> None:
    markdown = _retrieval_markdown(
        [
            _call("pubmed", "What drives fibrosis?", "q1"),
            _call("pubmed", "What drives fibrosis?", "q1"),
        ]
    )

    assert "## Data sources" in markdown
    assert "pubmed" in markdown
    assert "2 searches" in markdown
    assert "What drives fibrosis?" in markdown


def test_a_run_without_searches_carries_no_summary() -> None:
    assert "## Data sources" not in _retrieval_markdown(None)
    assert "## Data sources" not in _retrieval_markdown([])
    assert "Literature searches" not in _retrieval_markdown(None)


def test_counts_are_right_per_source_with_overlapping_questions() -> None:
    markdown = _retrieval_markdown(
        [
            _call("pubmed", "What drives fibrosis?", "q1"),
            _call("pubmed", "Is NHE1 druggable?", "q2"),
            _call("openalex", "What drives fibrosis?", "q1"),
        ]
    )

    pubmed_line = next(
        line for line in markdown.splitlines() if "pubmed" in line
    )
    openalex_line = next(
        line for line in markdown.splitlines() if "openalex" in line
    )
    assert "2 searches" in pubmed_line
    assert "1 search" in openalex_line
    assert "What drives fibrosis?" in markdown
    assert "Is NHE1 druggable?" in markdown


def test_survives_alongside_the_skills_used_notice() -> None:
    with_skills = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[
                {
                    "id": "h1",
                    "title": "NHE1 coupling",
                    "statement": "NHE1 couples to the RSK axis in HFpEF.",
                }
            ],
            retrieval_calls=[_call("pubmed", "What drives fibrosis?", "q1")],
            skills_used={"string-database": 2},
        )
    )

    assert with_skills.count("## Data sources") == 1
    assert "string-database" in with_skills
    assert "pubmed" in with_skills


async def test_a_built_report_pulls_its_own_runs_retrieval_calls(
    isolated_db: str,
) -> None:
    run = runs.create_run("cardiac goal", "standard", "engine", {})
    retrieval.add_retrieval_calls(
        [
            NewRetrievalCall(
                run_id=run.id,
                id="c1",
                question="What drives fibrosis?",
                question_id="q1",
                query="fibrosis mechanism",
                source="pubmed",
                depth=1,
                status="ok",
            )
        ],
        db_path=isolated_db,
    )

    built = await report_build.build_report_content(
        run.id,
        report_build.ReportRequest(
            research_goal=run.research_goal,
            run_mode="standard",
            provider="engine",
            db_path=isolated_db,
        ),
    )

    assert "## Data sources" in built.markdown
    assert "pubmed" in built.markdown
    assert "What drives fibrosis?" in built.markdown


def test_empty_question_id_does_not_collapse_distinct_questions() -> None:
    # TEXT NOT NULL permits empty question ids; grouping them together would
    # silently lose distinct questions.
    markdown = _retrieval_markdown(
        [
            _call("pubmed", "What regulates NHE1 activity in tumours?", ""),
            _call("pubmed", "Which inhibitors target SLC9A1?", ""),
        ]
    )

    assert "What regulates NHE1 activity in tumours?" in markdown
    assert "Which inhibitors target SLC9A1?" in markdown


def _header_markdown(setup: dict[str, object] | None) -> str:
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            setup=setup,
        )
    )


def test_the_header_carries_goal_requirements_attributes_and_criteria() -> None:
    markdown = _header_markdown(
        {
            "goal": "Explain the cardiac benefit.",
            "requirements": ["Must be testable in vitro."],
            "attributes": ["Mechanistically specific"],
            "criteria": ["Scientific soundness"],
        }
    )

    assert "## Research Goal Details" in markdown
    assert "**Goal:** Explain the cardiac benefit." in markdown
    assert "**Requirements:**" in markdown
    assert "Must be testable in vitro." in markdown
    assert "**Attributes:**" in markdown
    assert "Mechanistically specific" in markdown
    assert "**Criteria:**" in markdown
    assert "Scientific soundness" in markdown


def test_the_header_renders_r12_4_name_value_criteria() -> None:
    markdown = _header_markdown(
        {
            "goal": "Explain the cardiac benefit.",
            "criteria": [{"name": "Idea correctness", "value": "Required"}],
        }
    )

    assert "**Criteria:**" in markdown
    assert "- Idea correctness: Required" in markdown


def test_the_header_renders_r12_5_structured_attributes() -> None:
    markdown = _header_markdown(
        {
            "goal": "Explain the cardiac benefit.",
            "attributes": [
                {
                    "name": "Mechanism Novelty",
                    "scale": {"1": "Low", "3": "Moderate", "5": "High"},
                },
                {"name": "Target Area", "values": ["Heart", "Vasculature"]},
            ],
        }
    )

    assert "**Attributes:**" in markdown
    assert (
        "- Mechanism Novelty: 1-5 scale (1: Low, 3: Moderate, 5: High)"
        in markdown
    )
    assert "- Target Area (Heart or Vasculature)" in markdown


def test_the_header_still_leads_with_the_title_and_provider() -> None:
    markdown = _header_markdown({"requirements": ["A requirement."]})

    lines = markdown.splitlines()
    assert lines[0] == "# Research Report — Explain the cardiac benefit."
    assert "_Provider: **engine**_" in markdown


@pytest.mark.parametrize(
    "setup", [None, {"requirements": [], "attributes": [], "criteria": []}]
)
def test_no_setup_block_renders_no_goal_details_section(
    setup: dict[str, object] | None,
) -> None:
    markdown = _header_markdown(setup)

    assert "Research Goal Details" not in markdown


def _restatement_hypothesis() -> dict[str, object]:
    return {
        "id": "h1",
        "title": "Feedback control is rate-limiting.",
        "statement": "Blocking the loop raises the steady-state flux.",
    }


def _render(restatement: str | None) -> str:
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the metabolic feedback loop.",
            goal_restatement=restatement,
            provider="engine",
            top_hypotheses=[_restatement_hypothesis()],
        )
    )


def test_restatement_leads_the_top_hypotheses_section() -> None:
    restatement = (
        "This investigation seeks to chart how a metabolic feedback circuit "
        "governs pathway flux."
    )
    markdown = _render(restatement)

    heading_at = markdown.index("## Top hypotheses")
    restatement_at = markdown.index(restatement)
    first_idea_at = markdown.index("### 1.")
    assert heading_at < restatement_at < first_idea_at
    assert "Map the metabolic feedback loop." in markdown


def test_restatement_absent_leaves_the_section_unchanged() -> None:
    markdown = _render(None)

    assert "## Top hypotheses" in markdown
    assert "### 1." in markdown
    assert "This investigation seeks" not in markdown


def test_set_run_goal_restatement_persists_and_reads_back(
    isolated_db: str,
) -> None:
    run = runs.create_run(
        "Map the feedback loop.",
        "standard",
        "engine",
        {},
        RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    assert run.goal_restatement is None

    runs.set_run_goal_restatement(
        run.id, "A narrative restatement.", db_path=isolated_db
    )

    reloaded = runs.get_run(run.id, db_path=isolated_db)
    assert reloaded is not None
    assert reloaded.goal_restatement == "A narrative restatement."


def test_set_run_goal_restatement_missing_run_is_noop(
    isolated_db: str,
) -> None:
    runs.set_run_goal_restatement("no-such-run", "orphan", db_path=isolated_db)
    assert runs.get_run("no-such-run", db_path=isolated_db) is None


def test_redact_run_goal_clears_the_restatement(isolated_db: str) -> None:
    # Redaction must clear the pre-screen restatement too, or it republishes the
    # goal in different words.
    run = runs.create_run(
        "Synthesize a controlled pathogen.",
        "standard",
        "engine",
        {},
        RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    runs.set_run_goal_restatement(
        run.id, "A paraphrase of the goal.", db_path=isolated_db
    )

    runs.redact_run_goal(
        run.id, "[redacted]", "[redacted]", db_path=isolated_db
    )

    reloaded = runs.get_run(run.id, db_path=isolated_db)
    assert reloaded is not None
    assert reloaded.goal_restatement is None


def _base_markdown(knowledge_base: list[dict[str, object]]) -> str:
    hypothesis: dict[str, object] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            knowledge_base=knowledge_base,
        )
    )


def test_a_topic_renders_its_title_summary_and_detail() -> None:
    markdown = _base_markdown(
        [
            {
                "id": "topic-1",
                "title": "Mitochondrial calcium handling",
                "summary": "Calcium influx couples to ROS production.",
                "detail": (
                    "Perturbing MCU activity shifts the balance toward"
                    " sustained oxidative stress in motor neurons."
                ),
                "reference_ids": ["ev-1", "ev-2"],
            }
        ]
    )

    assert "## Knowledge Base" in markdown
    assert "### Knowledge Summary" in markdown
    assert "Mitochondrial calcium handling" in markdown
    assert "Calcium influx couples to ROS production." in markdown
    assert "Perturbing MCU activity shifts the balance" in markdown


def test_the_section_carries_no_citation_apparatus() -> None:
    markdown = _base_markdown(
        [
            {
                "id": "topic-1",
                "title": "Autophagy dysfunction",
                "summary": "Autophagosome clearance is delayed.",
                "detail": "See the retrieved literature for detail.",
                "reference_ids": ["ev-42"],
            }
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert "ev-42" not in section
    assert "[" not in section.split("### Knowledge Summary")[1]


def test_no_topics_renders_no_section() -> None:
    markdown = _base_markdown([])

    assert "Knowledge Base" not in markdown


def test_a_topic_with_no_title_is_skipped() -> None:
    markdown = _base_markdown(
        [{"id": "topic-1", "summary": "orphaned prose", "detail": ""}]
    )

    assert "orphaned prose" not in markdown


# Themes must be real headings so outlines retain the taxonomy rather than
# flattening it.


def _themed(theme: str, title: str, detail: str) -> dict[str, object]:
    return {
        "id": f"topic-{title}",
        "theme": theme,
        "title": title,
        "summary": "",
        "detail": detail,
        "uncertainty": "",
        "reference_ids": ["ev-1"],
    }


def test_a_theme_is_printed_once_above_its_sections() -> None:
    markdown = _base_markdown(
        [
            _themed("Matrix Architecture", "Cross-Linking", "Dense prose."),
            _themed("Matrix Architecture", "Stiffness", "More prose."),
            _themed("Immune Niche", "Macrophages", "Other prose."),
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert section.count("### Matrix Architecture") == 1
    assert section.count("### Immune Niche") == 1
    assert "#### Cross-Linking" in section
    assert "#### Stiffness" in section
    assert "#### Macrophages" in section
    assert "**" not in section


def test_every_theme_reaches_the_reader_as_its_own_heading() -> None:
    themes = [f"Theme {index}" for index in range(1, 9)]
    markdown = _base_markdown(
        [
            _themed(theme, f"{theme} section {number}", "Dense prose.")
            for theme in themes
            for number in (1, 2, 3)
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert [
        line for line in section.splitlines() if line.startswith("### ")
    ] == [f"### {theme}" for theme in themes]
    assert section.count("#### ") == 24
    assert "### Knowledge Summary" not in section


def test_a_single_theme_still_renders_as_that_theme() -> None:
    markdown = _base_markdown(
        [
            _themed("Matrix Architecture", "Cross-Linking", "Dense prose."),
            _themed("Matrix Architecture", "Stiffness", "More prose."),
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert section.count("### Matrix Architecture") == 1
    assert "Knowledge Summary" not in section


def test_an_unthemed_topic_never_inherits_the_previous_theme() -> None:
    markdown = _base_markdown(
        [
            _themed("Matrix Architecture", "Cross-Linking", "Dense prose."),
            {
                "id": "topic-flat",
                "title": "Autophagy dysfunction",
                "summary": "",
                "detail": "Detail prose.",
                "uncertainty": "",
            },
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert "### Knowledge Summary\n\n#### Autophagy dysfunction" in section


def test_untheme_d_topics_render_exactly_as_before() -> None:
    markdown = _base_markdown(
        [
            {
                "id": "topic-1",
                "title": "Autophagy dysfunction",
                "summary": "Clearance is delayed.",
                "detail": "Detail prose.",
                "reference_ids": [],
            }
        ]
    )

    section = markdown.split("## Knowledge Base")[1]
    assert "### Knowledge Summary" in section
    assert "#### Autophagy dysfunction" in section
    assert "**" not in section
