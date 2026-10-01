"""What the chat knows about a run, beyond its ideas and evidence.

The scientist keeps talking to the chat after the run starts, so the Q&A
prompt has to answer "how far along is it?" and "what did it conclude?"
as readily as it answers questions about a hypothesis. This module gathers
that half of the context -- live progress while the run executes, and the
finished report's synthesis once it completes -- and renders both as prompt
sections.

Split from ``app.qa.manifest`` (evidence and prompt assembly) so neither
file carries two subjects; ``app.qa`` re-exports the names, keeping the
one import surface callers already use.

Deliberately read-only and bounded: this runs on every question, on the
same connection the rest of the Q&A context is gathered on, so it uses the
capped event read (``store.recent_events``) rather than the whole log, and
never writes -- a write per question would join the single SQLite writer's
queue behind every run in flight.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from app import store

# How many trailing events the "recent steps" narrative is built from.
# Consecutive events sharing an activity collapse into one step, so this is
# a raw-event budget, not a step count -- a tournament wave alone can be
# dozens of events of one kind.
_EVENT_WINDOW = 60

# Most collapsed steps rendered into the prompt, newest last.
_MAX_STEPS = 12

# Ideas listed in the prompt's index. Every idea the run has is named there
# (title, Elo, status) so the model knows what exists; the bodies are
# fetched on demand with the search tool (see ``app.qa.ideas``), because a
# run's full ideas together are larger than the whole rest of the prompt.
_MAX_INDEXED_IDEAS = 40

# Conclusions drawn mid-run: the meta-review agent's notes, which is the
# only synthesis the store holds before a report is finalized.
_META_REVIEW_AGENT = "meta_review"
_MAX_CONCLUSIONS = 5

# Statuses in which a run is no longer executing. Mirrors
# ``store.TERMINAL_STATUSES``, resolved through the store so the two
# cannot drift.
_TERMINAL = store.TERMINAL_STATUSES


@dataclasses.dataclass(frozen=True)
class RunProgress:
    """A run's execution state, as the chat should be able to describe it.

    Attributes:
        status: The run's lifecycle status.
        elapsed_seconds: Wall-clock time since the run began executing, or
            None when it never started.
        idea_count: Ideas generated so far.
        evidence_count: Sources retrieved so far.
        match_count: Tournament matches judged so far.
        active_task: The durable task currently leased, if any.
        completed_tasks: Durable tasks committed so far.
        queued_tasks: Durable tasks waiting to be claimed.
        steps: The recent pipeline steps, oldest first.
        conclusions: Mid-run meta-review notes, newest last.
    """

    status: str
    elapsed_seconds: float | None
    idea_count: int
    evidence_count: int
    match_count: int
    active_task: str | None
    completed_tasks: int
    queued_tasks: int
    steps: list[str]
    conclusions: list[str]

    @property
    def is_running(self) -> bool:
        """Whether the run is still executing."""
        return self.status not in _TERMINAL


@dataclasses.dataclass(frozen=True)
class ReportFacts:
    """The finished report's synthesis, as prompt-ready text.

    Only the parts a conversation needs: what the run concluded and what it
    learned. The ranked ideas themselves are deliberately absent -- they are
    reachable through the idea search tool instead.

    Attributes:
        summary: The research overview's own summary paragraph.
        aims: The overview's specific aims.
        key_findings: The leading ideas' proposals, as the report states them.
        strengths: Meta-review common strengths.
        weaknesses: Meta-review common weaknesses.
        recommendations: Meta-review strategic recommendations, rendered.
        counts: Headline counts (ideas explored, released, verified, sources).
    """

    summary: str
    aims: list[str]
    key_findings: list[str]
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    counts: dict[str, int]


def _step_label(event: dict[str, Any]) -> str | None:
    """Name the pipeline step an event belongs to, or None to skip it.

    Uses the server-computed ``activity`` discriminator (see
    ``store.event_activity``) rather than the event type, so the narrative
    reads in the same vocabulary the live activity log shows the scientist
    -- and so a tournament's many match events read as one "tournament"
    step rather than dozens of lines.
    """
    if event.get("type") == "status":
        return None
    payload = event.get("payload")
    activity = payload.get("activity") if isinstance(payload, dict) else None
    if not activity or activity == "other":
        # Control-plane events (created/queued/completed) and anything the
        # activity table does not classify fall back to the event's own type,
        # which is already a node or lifecycle name.
        return str(event.get("type") or "") or None
    return str(activity)


def _collapse_steps(events: list[dict[str, Any]]) -> list[str]:
    """Collapse consecutive events sharing a step into one label each.

    Args:
        events: Events oldest-first.

    Returns:
        The step labels in order, with runs of one step collapsed, capped to
        the most recent ``_MAX_STEPS``.
    """
    steps: list[str] = []
    for event in events:
        label = _step_label(event)
        if label and (not steps or steps[-1] != label):
            steps.append(label)
    return steps[-_MAX_STEPS:]


def _conclusions(reviews: list[dict[str, Any]]) -> list[str]:
    """Return the meta-review agent's notes, newest last.

    The meta-review is the only synthesis the store holds while a run is
    still executing; the report's own conclusions do not exist until
    finalize.
    """
    notes = [
        str(r.get("summary") or "").strip()
        for r in reviews
        if r.get("reviewer_agent") == _META_REVIEW_AGENT
    ]
    return [note for note in notes if note][-_MAX_CONCLUSIONS:]


def gather_run_progress(
    run: store.RunRow,
    reviews: list[dict[str, Any]],
    counts: dict[str, int],
    conn: Any,
    now: float,
) -> RunProgress:
    """Read a run's live execution state for the Q&A prompt.

    Args:
        run: The run row being asked about.
        reviews: The run's reviews, already loaded for the prompt.
        counts: Pre-computed ``idea``/``evidence``/``match`` counts.
        conn: The open connection the rest of the Q&A context is read on.
        now: Current epoch seconds, injected so the elapsed clock is
            testable.

    Returns:
        The run's progress facts.
    """
    started_at = store.run_execution_started_at(run.id, conn=conn)
    finished_at = run.completed_at if run.status in _TERMINAL else None
    progress = store.task_progress(run.id, conn=conn)
    events = store.recent_events(run.id, _EVENT_WINDOW, conn=conn)
    return RunProgress(
        status=run.status,
        elapsed_seconds=(
            max(0.0, (finished_at or now) - started_at)
            if started_at is not None
            else None
        ),
        idea_count=counts.get("ideas", 0),
        evidence_count=counts.get("evidence", 0),
        match_count=counts.get("matches", 0),
        active_task=progress.get("active_task"),
        completed_tasks=int(progress.get("completed_tasks") or 0),
        queued_tasks=int(progress.get("queued_tasks") or 0),
        steps=_collapse_steps(events),
        conclusions=_conclusions(reviews),
    )


def _string_list(raw: Any, cap: int) -> list[str]:
    """Coerce a payload field to a capped list of non-empty strings."""
    if not isinstance(raw, list):
        return []
    values = [str(item).strip() for item in raw if not isinstance(item, dict)]
    return [value for value in values if value][:cap]


def _rendered_recommendations(raw: Any, cap: int) -> list[str]:
    """Render meta-review recommendations, structured or bare, as lines.

    A recommendation is either a ``{focus_area, recommendation,
    justification}`` dict or a bare string (see ``report.content``); both
    reach the reader as one line here.
    """
    if not isinstance(raw, list):
        return []
    lines: list[str] = []
    for item in raw[:cap]:
        if isinstance(item, dict):
            # Either half can be empty -- a model that put the whole
            # recommendation in `focus_area` must not render as a heading
            # with a colon and nothing after it.
            parts = [
                str(item.get(key) or "").strip()
                for key in ("focus_area", "recommendation")
            ]
            line = ": ".join(part for part in parts if part)
        else:
            line = str(item).strip()
        if line:
            lines.append(line)
    return lines


def _report_counts(payload: dict[str, Any]) -> dict[str, int]:
    """Pull the report's headline counts, defaulting each to zero.

    The three idea counts name different things and are computed
    differently (see ``report.gates``); they are carried through
    under their own names rather than collapsed, because reading one where
    another is meant is exactly how a report ends up contradicting itself.
    """
    keys = (
        "idea_count",
        "hypothesis_count",
        "verified_count",
        "evidence_count",
        "match_count",
    )
    return {key: int(payload.get(key) or 0) for key in keys}


def build_report_facts(payload: dict[str, Any]) -> ReportFacts:
    """Extract the conversational half of a finished report payload.

    Args:
        payload: The persisted report payload (see ``build_report_payload``).

    Returns:
        The report's synthesis as prompt-ready text.
    """
    overview = payload.get("research_overview")
    overview = overview if isinstance(overview, dict) else {}
    meta = payload.get("meta_review")
    meta = meta if isinstance(meta, dict) else {}
    insights = payload.get("agent_insights")
    insights = insights if isinstance(insights, dict) else {}
    return ReportFacts(
        summary=str(overview.get("summary") or "").strip(),
        aims=_string_list(overview.get("specific_aims"), 6),
        key_findings=_string_list(insights.get("key_findings"), 6),
        strengths=_string_list(meta.get("common_strengths"), 5),
        weaknesses=_string_list(meta.get("common_weaknesses"), 5),
        recommendations=_rendered_recommendations(
            meta.get("strategic_recommendations"), 5
        ),
        counts=_report_counts(payload),
    )


def gather_report_facts(run_id: str) -> ReportFacts | None:
    """Read a run's finished report, or None when it has not produced one.

    Not read on the shared Q&A connection: the report row carries the whole
    payload JSON, so it is fetched only for a run that has one rather than
    on every question.
    """
    latest = store.get_latest_report(run_id)
    payload = latest.get("payload") if latest else None
    return build_report_facts(payload) if isinstance(payload, dict) else None


def _bullets(lines: list[str]) -> str:
    """Render lines as a bullet block, or the empty string."""
    return "\n".join(f"- {line}" for line in lines)


def _elapsed_phrase(seconds: float | None) -> str:
    """Render an elapsed duration the way a person would say it."""
    if seconds is None:
        return "not started yet"
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def render_progress(progress: RunProgress) -> str:
    """Render the live-progress prompt section.

    Returns:
        The section body, always non-empty: a run that has produced nothing
        yet is itself the answer to "how is it going".
    """
    running = "running" if progress.is_running else progress.status
    elapsed = _elapsed_phrase(progress.elapsed_seconds)
    lines = [
        f"Status: {running} (elapsed {elapsed})",
        f"Ideas generated so far: {progress.idea_count}",
        f"Sources retrieved: {progress.evidence_count}",
        f"Tournament matches judged: {progress.match_count}",
    ]
    if progress.is_running:
        lines.append(
            f"Current step: {progress.active_task or 'between steps'} "
            f"({progress.completed_tasks} steps done, "
            f"{progress.queued_tasks} queued)"
        )
    if progress.steps:
        lines.append(
            f"Steps so far (oldest first): {', '.join(progress.steps)}"
        )
    if progress.conclusions:
        lines.append("Conclusions drawn so far:")
        lines.append(_bullets(progress.conclusions))
    return "\n".join(lines)


def _report_section(heading: str, lines: list[str]) -> list[str]:
    """Render one report subsection, or nothing when it has no content."""
    return [f"{heading}:", _bullets(lines)] if lines else []


def render_report(report: ReportFacts) -> str:
    """Render the finished-report prompt section.

    Returns:
        The section body, or the empty string when the report carried no
        synthesis at all (a run whose generation failed still finalizes).
    """
    counts = report.counts
    lines = [
        f"Ideas explored: {counts.get('idea_count', 0)}; "
        f"released to the report: {counts.get('hypothesis_count', 0)}; "
        f"evidence-verified: {counts.get('verified_count', 0)}; "
        f"sources: {counts.get('evidence_count', 0)}."
    ]
    if report.summary:
        lines.append(f"Overview: {report.summary}")
    lines += _report_section("Specific aims", report.aims)
    lines += _report_section("Key findings", report.key_findings)
    lines += _report_section("Common strengths", report.strengths)
    lines += _report_section("Common weaknesses", report.weaknesses)
    lines += _report_section("Recommended next steps", report.recommendations)
    return "\n".join(lines)


def render_idea_index(hypotheses: list[dict[str, Any]]) -> str:
    """Render the compact index of every idea the run holds.

    Titles, ranking and status only. The bodies are what the idea search
    tool is for: a run's ideas are individually long and collectively
    larger than the rest of the prompt put together, so dumping them
    crowds out everything else the answer needs -- but a model that cannot
    see an idea exists will never think to look it up either, which is why
    the index is not also trimmed to the leaders.

    Returns:
        One line per idea, capped, or the empty string when there are none.
    """
    lines = []
    for hyp in hypotheses[:_MAX_INDEXED_IDEAS]:
        status = str(hyp.get("status") or "active")
        verdict = hyp.get("verification_verdict")
        suffix = f", {verdict}" if verdict else ""
        lines.append(
            f"- {hyp.get('title') or 'Untitled'} "
            f"(Elo {hyp.get('elo_rating')}, {status}{suffix})"
        )
    remaining = len(hypotheses) - _MAX_INDEXED_IDEAS
    if remaining > 0:
        lines.append(f"- ...and {remaining} more (search to reach them)")
    return "\n".join(lines)
