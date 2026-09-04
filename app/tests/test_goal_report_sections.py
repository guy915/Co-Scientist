"""Tests for evidence-derived Goal Report sections.

The empty-leaderboard blocked-run reason (``_empty_leaderboard_reason``)
moved to ``test_goal_report_empty_leaderboard.py`` when this file passed
the module-size budget.
"""

from app import report_markdown, report_render, store
from tests._drain_helpers import _build_report
from tests._store_helpers import _add


def _hypothesis(identifier: str, title: str) -> dict[str, object]:
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
    released = _hypothesis("h1", "Feedback control")
    rejected = _hypothesis("h2", "Unsupported bypass")
    edges = [
        _edge("h1", "Feedback is rate-limiting.", "supports", ("ev1",)),
        _edge("h2", "The bypass is constitutively active.", "contradicts"),
    ]

    topics = report_render._knowledge_base_topics([released], edges)
    insights = report_render._agent_insights(
        [released],
        edges,
        {"common_weaknesses": ["Cell-type specificity remains uncertain."]},
    )
    buckets = report_render._idea_buckets(
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
    released = [_hypothesis(f"h{i}", f"Released {i}") for i in range(7)]
    excluded = [_hypothesis("x1", "Excluded")]

    buckets = report_render._idea_buckets(released, released + excluded, [])

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

    buckets = report_render._idea_buckets([released], [released, excluded], [])

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
    released = _hypothesis("h1", "Feedback control")
    deduped = _hypothesis("h2", "Near-duplicate idea")
    deduped["status"] = "rejected"
    # A speculative/insufficient edge is not a publication blocker, so it yields
    # no exclusion reason -- the rejection must be explained by the status.
    edges = [_edge("h2", "A speculative claim.", "insufficient", ("ev1",))]
    edges[0]["claim_role"] = "speculative"
    buckets = report_render._idea_buckets(
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
    released = _hypothesis("h1", "Feedback control")
    deduped = _hypothesis("h2", "Near-duplicate idea")
    deduped["status"] = "duplicate"
    rejected = _hypothesis("h3", "Unsound idea")
    rejected["status"] = "rejected"

    buckets = report_render._idea_buckets(
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
    hypothesis = _hypothesis("h1", "Feedback control")
    edges = [
        _edge("h1", "The bypass is constitutively active.", "contradicts"),
        _edge("h1", "", "contradicts"),
        _edge("h1", "Feedback is rate-limiting.", "supports"),
    ]

    insights = report_render._agent_insights([hypothesis], edges, {})

    assert len(insights["contradictions"]) == 1
    assert insights["contradictions"][0].startswith(
        "The bypass is constitutively active."
    )


def test_contradictions_name_ideas_the_report_withholds() -> None:
    """A contradiction says its idea is not in the report, and still shows.

    Two facts, and they only make sense together. A contradicted claim is
    exactly what makes the publication gate withhold its hypothesis, so the
    released edge list is contradiction-free by construction -- scoping the
    panel to it, for consistency with the rest of the report, would empty the
    panel on every run rather than drop a stray entry. The panel therefore
    keeps the run's whole edge list and each entry says, in itself, that the
    idea behind the claim was withheld; otherwise it reads as a reference to
    an idea the reader cannot find anywhere.
    """
    released = _hypothesis("h1", "Feedback control")
    contradicted = _hypothesis("h2", "Unsupported bypass")
    edges = [
        _edge("h1", "Feedback is rate-limiting.", "supports", ("ev1",)),
        _edge("h2", "The bypass is constitutively active.", "contradicts"),
    ]

    published = report_render._exclude_unsafe_hypotheses(
        "run-1", [released, contradicted], None, edges
    )
    released_edges = report_render._released_claim_evidence(
        published, edges, []
    )
    insights = report_render._agent_insights(published, edges, {})

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

    insights = report_render._agent_insights([hypothesis], [], {})
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

    insights = report_render._agent_insights([with_text, without_text], [], {})

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

    insights = report_render._agent_insights([], [], meta)

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
    topics = report_render._synthesized_knowledge_base_topics(
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
