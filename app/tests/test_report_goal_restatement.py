"""Tests for R14-3's ranking-document goal restatement.

The two report documents used to render the identical raw-flattened
Research Goal Details block. ``report_goal_synthesis.synthesize_goal_restatement``
now supplies the ranking document's own "Goal:" line, so this file asserts
the actual behavior the ledger row demands: the two documents' goal blocks
differ, generation degrades gracefully, and its multiplicity stays one call
per run (not per hypothesis).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app import report_render, store
from app.report_goal_synthesis import _clean_restatement, synthesize_goal_restatement


def _offline_run(isolated_db: str, goal: str = "cardiac fibrosis goal") -> store.RunRow:
    """Create an offline-backed run with a non-empty Research Goal Details setup."""
    return store.create_run(
        goal,
        "standard",
        "engine",
        {},
        store.RunCreateOptions(llm_backend="offline", db_path=isolated_db),
    )


class TestCleanRestatement:
    """Unit coverage for the output-normalizing helper."""

    def test_strips_wrapping_quotes_and_whitespace(self) -> None:
        cleaned = _clean_restatement('  "A restated goal."  ', "The goal.")
        assert cleaned == "A restated goal."

    def test_rejects_empty_output(self) -> None:
        assert _clean_restatement("   ", "The goal.") is None

    def test_rejects_output_that_just_repeats_the_goal(self) -> None:
        assert _clean_restatement("The goal.", "the goal") is None

    def test_rejects_implausibly_long_output(self) -> None:
        assert _clean_restatement("x" * 2000, "The goal.") is None


class TestSynthesizeGoalRestatement:
    """Coverage for the top-level generation function's degradation contract."""

    async def test_empty_goal_returns_none_without_calling_the_model(
        self, isolated_db: str
    ) -> None:
        run = _offline_run(isolated_db)
        with patch("litellm.acompletion", new_callable=AsyncMock) as mocked:
            result = await synthesize_goal_restatement(
                run.id, "   ", db_path=isolated_db
            )
        assert result is None
        mocked.assert_not_called()

    async def test_a_provider_failure_falls_back_to_none(
        self, isolated_db: str
    ) -> None:
        run = _offline_run(isolated_db)
        with patch(
            "app.report_goal_synthesis._request_goal_restatement",
            side_effect=RuntimeError("boom"),
        ):
            result = await synthesize_goal_restatement(
                run.id, run.research_goal, db_path=isolated_db
            )
        assert result is None

    async def test_offline_backed_run_produces_a_real_distinct_restatement(
        self, isolated_db: str
    ) -> None:
        """The deterministic offline backend itself, no mocking -- proves the
        call actually works under ``make e2e``'s fully offline environment."""
        run = _offline_run(isolated_db)
        result = await synthesize_goal_restatement(
            run.id, run.research_goal, db_path=isolated_db
        )
        assert result
        assert result.strip().lower() != run.research_goal.strip().lower()


class TestBuiltReportGoalBlocksDiffer:
    """End-to-end: the built overview and ranking documents disagree on the
    goal line only when a restatement was actually synthesized."""

    async def test_ranking_document_goal_line_differs_from_overview(
        self, isolated_db: str
    ) -> None:
        run = _offline_run(isolated_db, "What sustains biofilm tolerance?")
        req = report_render.ReportRequest(
            research_goal=run.research_goal,
            run_mode="standard",
            provider="engine",
            setup={"requirements": ["Use an isogenic control."]},
            db_path=isolated_db,
        )

        built = await report_render._build_report_content(run.id, req)

        assert f"**Goal:** {run.research_goal}" in built.markdown
        assert f"**Goal:** {run.research_goal}" not in built.ranking_markdown
        assert "## Research Goal Details" in built.ranking_markdown

    async def test_synthesis_failure_falls_back_to_the_raw_goal_on_both(
        self, isolated_db: str
    ) -> None:
        """A report must still finish building when the restatement fails --
        the duplication this replaces is strictly better than no report."""
        run = _offline_run(isolated_db, "What sustains biofilm tolerance?")
        req = report_render.ReportRequest(
            research_goal=run.research_goal,
            run_mode="standard",
            provider="engine",
            setup={"requirements": ["Use an isogenic control."]},
            db_path=isolated_db,
        )

        with patch(
            "app.report_build.synthesize_goal_restatement",
            new_callable=AsyncMock,
            return_value=None,
        ):
            built = await report_render._build_report_content(run.id, req)

        assert f"**Goal:** {run.research_goal}" in built.markdown
        assert f"**Goal:** {run.research_goal}" in built.ranking_markdown

    async def test_restatement_is_synthesized_once_per_run(
        self, isolated_db: str
    ) -> None:
        """Report-build time, not per hypothesis -- exactly one call."""
        run = _offline_run(isolated_db, "What sustains biofilm tolerance?")
        req = report_render.ReportRequest(
            research_goal=run.research_goal,
            run_mode="standard",
            provider="engine",
            db_path=isolated_db,
        )

        with patch(
            "app.report_build.synthesize_goal_restatement",
            new_callable=AsyncMock,
            return_value="A distinct narrative restatement.",
        ) as mocked:
            await report_render._build_report_content(run.id, req)

        mocked.assert_awaited_once_with(
            run.id, run.research_goal, db_path=isolated_db
        )
