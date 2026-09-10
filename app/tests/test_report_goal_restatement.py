"""GOAL-RESTATEMENT-001: the report's synthesized goal restatement.

Google's published run renders the goal two ways -- the research overview
inlines the raw structured goal, and the top-ranking-hypotheses document
opens with a freshly synthesized narrative restatement in different words.
Our single combined report keeps the raw "Research Goal Details" block and
leads the top-hypotheses section with the restatement, so one document
carries both forms. The restatement is a run column filled by a background
generator; None (offline/keyless runs, legacy rows) omits the paragraph.
"""

from __future__ import annotations

from app import report_markdown, store


def _hypothesis() -> dict[str, object]:
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
            top_hypotheses=[_hypothesis()],
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
