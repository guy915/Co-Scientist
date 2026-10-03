"""Tests for report document 1."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

from app import store
from app.report import build as report_build
from app.report import content as report_content
from app.report import gates as report_gates
from app.report import markdown as report_markdown
from app.report.markdown.hypothesis import _HYPOTHESIS_DISCLAIMER
from tests._drain_helpers import _build_report
from tests._store_helpers import _add

# Tests for the empty-leaderboard blocked-run reason.
#
# Split out of ``test_goal_report_sections.py`` when that file passed the
# module-size budget. ``_empty_leaderboard_reason`` is the one place that
# turns a tally of why every idea left the report into the sentence a
# scientist reads, so its wording -- which cause it names, which it omits,
# how it reads a mix of causes -- gets its own module rather than sharing one
# with the rest of the report-section tests.


def test_empty_leaderboard_reason_names_review_rejection_alone() -> None:
    """A run every idea failed peer review must not blame safety/evidence.

    Reproduces run 44e848fb: safety screened 18/blocked 0, claim grounding
    assessed 0 claims, and every idea carried a blocking review
    disposition. The old fixed-pair reason ("contradicted by the evidence
    or withheld by the safety review") named two causes that never ran.
    """
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
    """A genuinely safety-withheld run still says so."""
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
    """A genuinely evidence-contradicted run still says so."""
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
    """Duplicate exclusion reads as its own cause, not "rejected"."""
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
    """Several causes each land as their own clause, not one picked cause."""
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
    assert reason.count(",") >= 2  # more than one clause is actually listed


def test_empty_leaderboard_reason_handles_zero_ideas() -> None:
    """A run that produced no ideas at all is its own case, not "withheld"."""
    reason = report_gates._empty_leaderboard_reason(
        0,
        {"review_rejected": 0, "duplicate": 0, "contradicted": 0, "safety": 0},
    )

    assert (
        reason == "No hypothesis could be published: the run produced no ideas."
    )


def _leaderboard_hypothesis(identifier: str, title: str) -> dict[str, object]:
    """One report-ready hypothesis the safety review has already allowed."""
    return {
        "id": identifier,
        "title": title,
        "statement": f"{title} changes the measured phenotype.",
        "safety_status": "allowed",
    }


def _contradicted(hypothesis_id: str, claim: str, role: str) -> dict[str, Any]:
    """A contradicted edge as ``store.list_claim_evidence`` returns it."""
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
    """The panel only says "withheld" of an idea the gate actually withheld.

    The gate withholds an idea for a contradicted *categorical* claim; one
    contradicting only the idea's own proposal publishes with the idea. The
    panel lists both (the evidence against a proposal is a finding), but its
    entry used to say the idea was withheld for either, which is false of the
    proposal's idea: that idea is in the report the entry sits in.
    """
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


# Tests for evidence-derived Goal Report sections.
#
# The empty-leaderboard blocked-run reason (``_empty_leaderboard_reason``)
# moved to ``test_goal_report_empty_leaderboard.py`` when this file passed
# the module-size budget.


def _sections_hypothesis(identifier: str, title: str) -> dict[str, object]:
    """Build one report-ready hypothesis fixture."""
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
    """Build one edge in the shape ``store.list_claim_evidence`` returns.

    The column names matter: the report derives contradiction text from
    ``claim`` and evidence ids from the ``supporting`` passage spans, so a
    fixture inventing flatter keys hides real key drift.
    """
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
    """Topics, insights, and idea buckets retain evidence-release decisions."""
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
    """The two buckets cover the run's ideas exactly once, at any size.

    The UI shows both as counts side by side, so they have to sum to the
    run's idea count. ``non_viable`` is defined as everything not released,
    and ``high_potential`` used to be capped at the top five -- which held
    only until a run released a sixth idea, then quietly lost the rest.
    """
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
    """An idea carrying only ``text`` is named in both buckets.

    Every other surface of the same report -- the markdown body, the event
    stream, the leaderboard -- resolves a display name through
    ``text_utils.hypothesis_title``, which falls back to ``text``. The two
    bucket builders read ``title`` alone, so exactly one section of the
    report called such an idea "Untitled idea".
    """
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
    """A review/dedup-rejected idea gets an accurate reason, not "release gate".

    Under rank-and-publish a merely-unsupported idea is published (badged
    "Unverified"), so the only non-viable ideas are contradicted, unsafe, or
    set aside during review/deduplication. A rejected idea with no contradicting
    edge must be explained by that rejection -- never the legacy "release gate
    excluded this idea" text.
    """
    released = _sections_hypothesis("h1", "Feedback control")
    deduped = _sections_hypothesis("h2", "Near-duplicate idea")
    deduped["status"] = "rejected"
    # A speculative/insufficient edge is not a publication blocker, so it yields
    # no exclusion reason -- the rejection must be explained by the status.
    edges = [_edge("h2", "A speculative claim.", "insufficient", ("ev1",))]
    edges[0]["claim_role"] = "speculative"
    buckets = report_content._idea_buckets(
        [released], [released, deduped], edges
    )
    reason = buckets["non_viable"][0]["reason"].lower()
    assert "review" in reason or "duplicate" in reason
    assert "release gate" not in reason


def test_a_duplicate_and_a_rejected_idea_get_different_reasons() -> None:
    """Deduplication and review rejection are different facts, reported apart.

    Both leave the ranked report, but a duplicate was never judged -- a
    higher-ranked idea simply says the same thing. One shared sentence told
    a scientist their idea had failed peer review when it had only been
    folded into another.
    """
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
    """Every contradiction is readable text, so no empty bullet is emitted.

    A blank entry is worse than an absent one: the section header renders on
    list length alone, so blanks produce a heading with nothing under it.
    """
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
    """A contradiction says its idea is not in the report, and still shows.

    Two facts, and they only make sense together. A contradicted categorical
    claim is exactly what makes the publication gate withhold its hypothesis,
    so the released edge list carries none -- scoping the panel to it, for
    consistency with the rest of the report, would drop every withheld idea's
    entry rather than a stray one. The panel therefore
    keeps the run's whole edge list and each entry says, in itself, that the
    idea behind the claim was withheld; otherwise it reads as a reference to
    an idea the reader cannot find anywhere.
    """
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
    """Both sections quote the same proposal text for the same idea.

    The panel entry and the markdown body carry the same label -- "Proposed
    hypothesis" -- so they have to carry the same string. They resolved it
    through different fallbacks (``statement or title`` against ``statement
    or text``), which diverged on exactly the idea whose statement is empty:
    the panel fell back to the title, which the drain derives as the
    statement's *first sentence*, so one report quoted a whole proposal in
    one section and its opening sentence in another.
    """
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
    """Introduction/Recent findings (MO-6) render ahead of the mechanism.

    The published proposal opens with an Introduction and a Recent
    findings and related research section before the hypothesis itself;
    no field carried this before.
    """
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
    """Safety and toxicity (MO-10) is the proposer's own field, not review's.

    Distinct from a reviewer's safety_ethical_concerns, which lives on the
    review row rather than the hypothesis and is rendered elsewhere.
    """
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
    """No Safety and toxicity heading renders without the data."""
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
    """No Introduction/Recent findings heading renders without the data."""
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
    """An idea with nothing to propose is dropped, not labelled blank.

    The markdown entry omits its "Proposed hypothesis" line when there is no
    statement; the panel emitted the bare label instead, and the frontend's
    blank-entry filter cannot catch it because the label itself is text.
    """
    with_text = {"id": "h1", "statement": "Blocking the loop raises flux."}
    without_text = {"id": "h2", "title": "A title with no statement."}

    insights = report_content._agent_insights([with_text, without_text], [], {})

    assert insights["key_findings"] == [
        "Proposed hypothesis: Blocking the loop raises flux."
    ]


def test_recommended_directions_keep_their_three_named_fields() -> None:
    """Structured recommendations survive as fields, not stringified objects."""
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
    """Engine topic references become ids; unsupported topics drop."""
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
    """The markdown's top ideas must follow the leaderboard's order.

    The store returns hypotheses by raw Elo, and the report body sliced
    that list directly while the payload's leaderboard applied the
    undermined demotion. So one run told two stories: the standings led
    with the sound idea and the prose beneath them led with the idea a
    probe had found a fundamental flaw in.
    """
    run = store.create_run("ordering goal", "standard", "engine", {})
    doubted = _add(run.id, "Doubted idea", "A doubted proposal.", isolated_db)
    sound = _add(run.id, "Sound idea", "A sound proposal.", isolated_db)
    store.update_hypothesis_state(
        doubted,
        store.HypothesisStateChanges(
            elo_rating=1300,
            win_delta=3,
            verification_verdict="undermined",
        ),
        db_path=isolated_db,
    )
    store.update_hypothesis_state(
        sound,
        store.HypothesisStateChanges(elo_rating=1100, win_delta=1),
        db_path=isolated_db,
    )

    payload, markdown = await _build_report(run, isolated_db)

    assert [row["id"] for row in payload["leaderboard"]] == [sound, doubted]
    assert markdown.index("Sound idea") < markdown.index("Doubted idea")


# Report headers retain the research disclosure and timestamp provenance.


_DocumentFn = Callable[[report_markdown.ReportMarkdownInputs], str]


def _disclosure_markdown(fn: _DocumentFn) -> str:
    """Render a minimal report through the given document function."""
    return fn(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
        )
    )


def test_the_overview_document_carries_the_about_disclosure() -> None:
    """The disclosure renders, verbatim, on the Goal Report document."""
    markdown = _disclosure_markdown(report_markdown.render_report_markdown)

    assert (
        "**About**: *This is an experimental system for generating novel"
        " and testable hypotheses. The hypotheses are generated by a"
        " model and may be wrong. For research purposes only.*"
    ) in markdown


def test_it_is_byte_identical_to_the_per_hypothesis_disclaimer() -> None:
    """One real wording, not two near-identical strings drifting apart."""
    markdown = _disclosure_markdown(report_markdown.render_report_markdown)

    assert _HYPOTHESIS_DISCLAIMER in markdown


def test_it_renders_before_the_table_of_contents() -> None:
    """Matches the published order: About, then the nav list."""
    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            # A populated section so the table of contents actually
            # renders (it is itself omitted on an empty report).
            meta_review={"summary": "Ideas converge on a shared mechanism."},
        )
    )

    about_at = markdown.index("**About**:")
    toc_at = markdown.index("#### Table of contents:")
    assert about_at < toc_at


def _provenance_markdown(prepared_at: float | None) -> str:
    """Render a minimal report carrying only the given prepared_at."""
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            prepared_at=prepared_at,
        )
    )


def test_the_header_carries_the_research_purposes_only_caution() -> None:
    """The caution line renders verbatim."""
    markdown = _provenance_markdown(1_700_000_000.0)

    assert "For research purposes only." in markdown


def test_the_header_names_this_system_not_googles() -> None:
    """Provenance is attributed to this system, never "AI co-scientist"."""
    markdown = _provenance_markdown(1_700_000_000.0)

    assert "Prepared by Co-Scientist on" in markdown
    assert "AI co-scientist" not in markdown


def test_the_date_is_derived_from_prepared_at_not_wall_clock() -> None:
    """The rendered date matches the supplied timestamp, not datetime.now()."""
    timestamp = 1_700_000_000.0
    expected = (
        datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        .date()
        .isoformat()
    )

    markdown = _provenance_markdown(timestamp)

    assert expected in markdown


def test_no_prepared_at_renders_no_provenance_line() -> None:
    """A report with no known preparation time carries no caution line.

    Covers a report persisted before this field existed rather than
    stating a date this system does not actually know. Checks the
    provenance line's own wording, not the bare "For research purposes
    only" phrase -- the R14-4 About disclosure (report/markdown/header.py)
    carries that same closing phrase unconditionally, on every render.
    """
    markdown = _provenance_markdown(None)

    assert "Prepared by" not in markdown


# Reports attribute consulted skills and recorded literature searches.


def _notice_markdown(skills_used: dict[str, int] | None) -> str:
    """Render a minimal report with the given skill attribution."""
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
    """A run that used a skill attributes it and points at the terms."""
    markdown = _notice_markdown({"string-database": 2})

    assert "## Data sources" in markdown
    assert "string-database" in markdown
    assert "SKILL_LICENSES.md" in markdown


def test_a_source_the_run_never_touched_is_not_claimed() -> None:
    """Only what the run queried is named, not the whole catalogue.

    A blanket list of every installed skill would be the easy thing to
    render and would attribute the run's work to databases it never
    reached, which is a worse disclosure than none.
    """
    markdown = _notice_markdown({"string-database": 1})

    assert "chembl-database" not in markdown


def test_a_run_without_skills_carries_no_notice() -> None:
    """The section is absent, not empty, when nothing was queried.

    Every run without ``COSCIENTIST_SKILLS_DIR`` is this run, so an
    always-rendered heading would put a data-source section on reports
    that used no data source.
    """
    assert "## Data sources" not in _notice_markdown(None)
    assert "## Data sources" not in _notice_markdown({})


def _retrieval_markdown(retrieval_calls: list[dict[str, Any]] | None) -> str:
    """Render a minimal report with the given retrieval provenance."""
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
    """One row shaped like ``store.list_retrieval_calls`` returns."""
    return {
        "source": source,
        "question": question,
        "question_id": question_id,
        "query": query,
    }


def test_a_run_with_searches_names_source_and_count() -> None:
    """A queried source is named with how many searches it served."""
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
    """No section at all when the run recorded no retrieval calls."""
    assert "## Data sources" not in _retrieval_markdown(None)
    assert "## Data sources" not in _retrieval_markdown([])
    assert "Literature searches" not in _retrieval_markdown(None)


def test_counts_are_right_per_source_with_overlapping_questions() -> None:
    """One source serving two questions, one question hitting two sources.

    ``pubmed`` serves both q1 and q2 (count 2, two distinct questions).
    ``openalex`` serves only q1 (count 1). The counts must not be
    conflated: source search counts and distinct-question counts are two
    different numbers.
    """
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
    """Both the skill attribution and the search summary render together."""
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
    """The report reads the store directly -- no field has to feed it in.

    ``retrieval_calls`` is already written by the research loop keyed on
    ``run_id``; a report build only has to read its own run's rows, not
    have them threaded through the finalize request.
    """
    run = store.create_run("cardiac goal", "standard", "engine", {})
    store.add_retrieval_calls(
        [
            store.NewRetrievalCall(
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
    """An empty ``question_id`` must not read as 'the same question again'.

    ``question_id`` is ``TEXT NOT NULL``, which permits ``''`` -- not
    every row is guaranteed a real id. Deduplicating on the id alone
    would silently drop the second of two different questions while
    ``count`` kept counting both, which reads as data loss to a reader
    who sees a count of two beside a single question.
    """
    markdown = _retrieval_markdown(
        [
            _call("pubmed", "What regulates NHE1 activity in tumours?", ""),
            _call("pubmed", "Which inhibitors target SLC9A1?", ""),
        ]
    )

    assert "What regulates NHE1 activity in tumours?" in markdown
    assert "Which inhibitors target SLC9A1?" in markdown


def _header_markdown(setup: dict[str, object] | None) -> str:
    """Render a minimal report carrying only the given setup block."""
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[],
            setup=setup,
        )
    )


def test_the_header_carries_goal_requirements_attributes_and_criteria() -> None:
    """Every configured section of the run's plan renders."""
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
    """A run created after R12-4 stores criteria as name/value pairs."""
    markdown = _header_markdown(
        {
            "goal": "Explain the cardiac benefit.",
            "criteria": [{"name": "Idea correctness", "value": "Required"}],
        }
    )

    assert "**Criteria:**" in markdown
    assert "- Idea correctness: Required" in markdown


def test_the_header_renders_r12_5_structured_attributes() -> None:
    """A run created after R12-5 stores attributes as structured axes."""
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
    """The new section is additive: title and provider line still open."""
    markdown = _header_markdown({"requirements": ["A requirement."]})

    lines = markdown.splitlines()
    assert lines[0] == "# Research Report — Explain the cardiac benefit."
    assert "_Provider: **engine**_" in markdown


def test_no_setup_block_renders_no_goal_details_section() -> None:
    """A report built without a setup block (an old persisted run) is fine."""
    markdown = _header_markdown(None)

    assert "Research Goal Details" not in markdown


def test_an_empty_setup_block_renders_no_goal_details_section() -> None:
    """A setup block with nothing configured emits no bare heading."""
    markdown = _header_markdown(
        {"requirements": [], "attributes": [], "criteria": []}
    )

    assert "Research Goal Details" not in markdown


# GOAL-RESTATEMENT-001: the report's synthesized goal restatement.
#
# Google's published run renders the goal two ways -- the research overview
# inlines the raw structured goal, and the top-ranking-hypotheses document
# opens with a freshly synthesized narrative restatement in different words.
# Our single combined report keeps the raw "Research Goal Details" block and
# leads the top-hypotheses section with the restatement, so one document
# carries both forms. The restatement is a run column filled by a background
# generator; None (offline/keyless runs, legacy rows) omits the paragraph.


def _restatement_hypothesis() -> dict[str, object]:
    """One report-ready hypothesis fixture."""
    return {
        "id": "h1",
        "title": "Feedback control is rate-limiting.",
        "statement": "Blocking the loop raises the steady-state flux.",
    }


def _render(restatement: str | None) -> str:
    """Render the report markdown with the given restatement (or None)."""
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Map the metabolic feedback loop.",
            goal_restatement=restatement,
            provider="engine",
            top_hypotheses=[_restatement_hypothesis()],
        )
    )


def test_restatement_leads_the_top_hypotheses_section() -> None:
    """When present, the restatement opens '## Top hypotheses'.

    It sits after the heading and before the first numbered idea, and the
    raw goal still renders separately in its own Research Goal Details block
    -- one document carrying both forms, as R14-3 shows across Google's two.
    """
    restatement = (
        "This investigation seeks to chart how a metabolic feedback circuit "
        "governs pathway flux."
    )
    markdown = _render(restatement)

    heading_at = markdown.index("## Top hypotheses")
    restatement_at = markdown.index(restatement)
    first_idea_at = markdown.index("### 1.")
    assert heading_at < restatement_at < first_idea_at
    # The raw goal is still rendered separately, not replaced.
    assert "Map the metabolic feedback loop." in markdown


def test_restatement_absent_leaves_the_section_unchanged() -> None:
    """None omits the paragraph; the section still renders its ideas."""
    markdown = _render(None)

    assert "## Top hypotheses" in markdown
    assert "### 1." in markdown
    assert "This investigation seeks" not in markdown


def test_set_run_goal_restatement_persists_and_reads_back(
    isolated_db: str,
) -> None:
    """The store setter round-trips onto the run row."""
    run = store.create_run(
        "Map the feedback loop.",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    assert run.goal_restatement is None

    store.set_run_goal_restatement(
        run.id, "A narrative restatement.", db_path=isolated_db
    )

    reloaded = store.get_run(run.id, db_path=isolated_db)
    assert reloaded is not None
    assert reloaded.goal_restatement == "A narrative restatement."


def test_set_run_goal_restatement_missing_run_is_noop(
    isolated_db: str,
) -> None:
    """Setting the restatement on an absent run does not raise."""
    store.set_run_goal_restatement("no-such-run", "orphan", db_path=isolated_db)
    assert store.get_run("no-such-run", db_path=isolated_db) is None


def test_redact_run_goal_clears_the_restatement(isolated_db: str) -> None:
    """Redacting the goal also clears its paraphrase.

    The restatement is stamped at create, before the intake screen can
    reach a ``redact`` verdict; leaving it would surface the redacted goal
    in different words at the head of the top-hypotheses section.
    """
    run = store.create_run(
        "Synthesize a controlled pathogen.",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    store.set_run_goal_restatement(
        run.id, "A paraphrase of the goal.", db_path=isolated_db
    )

    store.redact_run_goal(
        run.id, "[redacted]", "[redacted]", db_path=isolated_db
    )

    reloaded = store.get_run(run.id, db_path=isolated_db)
    assert reloaded is not None
    assert reloaded.goal_restatement is None


def _base_markdown(knowledge_base: list[dict[str, object]]) -> str:
    """Render a minimal report carrying only the given knowledge base."""
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
    """Each topic prints as a named subject heading with its prose."""
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
    """Reference ids attached to a topic never surface as markdown output.

    Verified over the whole published span (R12-6): the Knowledge Base
    carries zero citations, unlike every other numbered report section.
    """
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
    """An empty knowledge base emits no heading at all."""
    markdown = _base_markdown([])

    assert "Knowledge Base" not in markdown


def test_a_topic_with_no_title_is_skipped() -> None:
    """A malformed topic with no title contributes nothing renderable."""
    markdown = _base_markdown(
        [{"id": "topic-1", "summary": "orphaned prose", "detail": ""}]
    )

    assert "orphaned prose" not in markdown


# F8: the published Knowledge Base groups its named subject headings under
# themes ("Extracellular Matrix Architecture And Biomechanical Barriers"
# over "Matrix Composition And Cross-Linking Constraints", ...). The engine
# synthesizes those as one topic per section carrying its theme; the
# renderer prints each theme once, as a heading one level above the
# sections that belong to it, exactly as the exemplar does.
#
# Production run d1273490 is why these assert on heading level rather than
# on the theme text appearing at all: the deep call answered with 8 themes
# over 38 grounded sections, and the renderer emitted every theme as a
# **bold paragraph** under one static "### Knowledge Summary". The depth
# landed and the taxonomy did not -- in an outline, a table of contents or
# any heading-based view the whole section read as a single theme, and the
# earlier test passed because it asserted the bold form.


def _themed(theme: str, title: str, detail: str) -> dict[str, object]:
    """One themed knowledge-base section as the engine emits it."""
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
    """Consecutive sections of one theme share a single theme heading."""
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
    """A run's whole taxonomy renders as headings, not as one section.

    The shape production run d1273490 actually produced: the maximum 8
    themes, several sections each. Every theme must be its own ``###``,
    and the flat path's label must not appear at all.
    """
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
    """One theme is a legitimate answer, not the degraded shape."""
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
    """A topic with no theme falls under the flat label, not a theme."""
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
    """The flat shape the overview call still produces is unchanged."""
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
