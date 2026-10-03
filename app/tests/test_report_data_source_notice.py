"""Reports attribute consulted skills and recorded literature searches."""

from typing import Any

from app import store
from app.report import build as report_build
from app.report import markdown as report_markdown


def _markdown(skills_used: dict[str, int] | None) -> str:
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
    markdown = _markdown({"string-database": 2})

    assert "## Data sources" in markdown
    assert "string-database" in markdown
    assert "SKILL_LICENSES.md" in markdown


def test_a_source_the_run_never_touched_is_not_claimed() -> None:
    """Only what the run queried is named, not the whole catalogue.

    A blanket list of every installed skill would be the easy thing to
    render and would attribute the run's work to databases it never
    reached, which is a worse disclosure than none.
    """
    markdown = _markdown({"string-database": 1})

    assert "chembl-database" not in markdown


def test_a_run_without_skills_carries_no_notice() -> None:
    """The section is absent, not empty, when nothing was queried.

    Every run without ``COSCIENTIST_SKILLS_DIR`` is this run, so an
    always-rendered heading would put a data-source section on reports
    that used no data source.
    """
    assert "## Data sources" not in _markdown(None)
    assert "## Data sources" not in _markdown({})


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
