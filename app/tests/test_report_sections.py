from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

import pytest

from app.report import build as report_build
from app.report import content as report_content
from app.report import gates as report_gates
from app.report import markdown as report_markdown
from app.store import hypotheses, runs
from app.store import retrieval_calls as retrieval
from app.store.hypotheses import HypothesisStateChanges
from app.store.retrieval_calls import NewRetrievalCall
from tests._drain_helpers import _build_report
from tests._store_helpers import _add, seed_run


@pytest.mark.parametrize(
    ("ideas", "tally", "expected"),
    [
        (
            15,
            {"review_rejected": 15},
            "No hypothesis could be published: of 15 ideas, 15 were rejected "
            "by peer review before ranking (the reviewer judged them "
            "inaccurate, non-novel, unsafe, or evidence-blocked).",
        ),
        (
            5,
            {"safety": 5},
            "No hypothesis could be published: of 5 ideas, 5 were withheld "
            "by the safety review.",
        ),
        (
            3,
            {"contradicted": 3},
            "No hypothesis could be published: of 3 ideas, 3 were "
            "contradicted by the evidence.",
        ),
        (
            0,
            {},
            "No hypothesis could be published: the run produced no ideas.",
        ),
    ],
)
def test_empty_leaderboard_reason_names_only_what_withheld_the_ideas(
    ideas: int, tally: dict[str, int], expected: str
) -> None:
    full = {
        "review_rejected": 0,
        "duplicate": 0,
        "contradicted": 0,
        "safety": 0,
    }

    assert (
        report_gates._empty_leaderboard_reason(ideas, full | tally) == expected
    )


def test_empty_leaderboard_reason_reads_duplicates_and_a_mix_distinctly() -> (
    None
):
    duplicates = report_gates._empty_leaderboard_reason(
        2,
        {"review_rejected": 0, "duplicate": 2, "contradicted": 0, "safety": 0},
    )
    mix = report_gates._empty_leaderboard_reason(
        4,
        {"review_rejected": 2, "duplicate": 0, "contradicted": 1, "safety": 1},
    )

    assert "folded into a higher-ranked idea" in duplicates
    assert "peer review" not in duplicates
    assert "2 were rejected by peer review" in mix
    assert "1 was contradicted by the evidence" in mix
    assert "1 was withheld by the safety review" in mix


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
    run = seed_run("ordering goal")
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


def _provenance_markdown(prepared_at: float | None) -> str:
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            prepared_at=prepared_at,
        )
    )


def test_the_date_is_derived_from_prepared_at_not_wall_clock() -> None:
    timestamp = 1_700_000_000.0
    expected = (
        datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        .date()
        .isoformat()
    )

    markdown = _provenance_markdown(timestamp)

    assert expected in markdown


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


async def test_a_built_report_pulls_its_own_runs_retrieval_calls(
    isolated_db: str,
) -> None:
    run = seed_run("cardiac goal")
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


def test_redact_run_goal_clears_the_restatement(isolated_db: str) -> None:
    # Redaction must clear the pre-screen restatement too, or it republishes the
    # goal in different words.
    run = seed_run(
        "Synthesize a controlled pathogen.", client_id="c1", db_path=isolated_db
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
