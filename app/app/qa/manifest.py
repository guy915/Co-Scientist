"""Evidence-manifest and prompt assembly for grounded Q&A."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import app.store as store
from app.citations import STATE_RANK

logger = logging.getLogger(__name__)

# How many trailing events the "recent steps" narrative is built from.
# Consecutive events sharing an activity collapse into one step, so this is
# a raw-event budget, not a step count -- a tournament wave alone can be
# dozens of events of one kind.
_EVENT_WINDOW = 60

# Most collapsed steps rendered into the prompt, newest last.
_MAX_STEPS = 12

# Ideas listed in the prompt's index. Every idea the run has is named there
# (title, Elo, status) so the model knows what exists; the bodies are
# fetched on demand with the search tool (see ``app.qa.manifest``), because a
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
        payload: The persisted report payload.

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


# Tool name, in the model's vocabulary.
SEARCH_IDEAS_TOOL = "search_ideas"

# Bounds on one tool result. The point of the tool is to keep the prompt
# small, so a search that returns half the run is the failure it exists to
# prevent: the model is expected to ask again with better terms rather than
# be handed the pool.
_MAX_RESULTS = 5
_DEFAULT_RESULTS = 3
_FIELD_MAX_CHARS = 1200

_WORD_RE = re.compile(r"[a-z0-9]+")

# The fields an idea's body is assembled from, in the order they read.
_BODY_FIELDS: tuple[tuple[str, str], ...] = (
    ("statement", "Statement"),
    ("mechanism", "Mechanism"),
    ("expected_effect", "Expected effect"),
    ("experimental_context", "Experimental context"),
)


def tool_declaration() -> dict[str, Any]:
    """Return the provider-facing declaration of the idea search tool."""
    return {
        "type": "function",
        "function": {
            "name": SEARCH_IDEAS_TOOL,
            "description": (
                "Look up the full text of this run's ideas by topic. The "
                "conversation carries only an index of idea titles, so call "
                "this whenever the answer needs what an idea actually says "
                "-- its statement, mechanism, expected effect or "
                "experimental context. Search with the terms of the "
                "question, or with words from an idea's title in the index."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Topic words to match against the ideas, or an "
                            "idea title from the index."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"How many ideas to return "
                            f"(1-{_MAX_RESULTS}, default {_DEFAULT_RESULTS})."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    }


def _tokenize(text: str) -> frozenset[str]:
    """Split text into lowercase word tokens, dropping short noise words."""
    return frozenset(t for t in _WORD_RE.findall(text.lower()) if len(t) > 3)


def _searchable_text(hyp: dict[str, Any]) -> str:
    """Join the idea fields a query is matched against."""
    parts = [str(hyp.get("title") or ""), str(hyp.get("category") or "")]
    parts += [str(hyp.get(field) or "") for field, _ in _BODY_FIELDS]
    return " ".join(parts)


def _score(query_tokens: frozenset[str], hyp: dict[str, Any]) -> int:
    """Score one idea against the query's terms.

    Title matches count double: a query naming an idea should return that
    idea, not whichever body happens to repeat the words most.
    """
    title_tokens = _tokenize(str(hyp.get("title") or ""))
    body_tokens = _tokenize(_searchable_text(hyp))
    return 2 * len(query_tokens & title_tokens) + len(
        query_tokens & body_tokens
    )


def _clip(text: str) -> str:
    """Bound one rendered field so a single long idea cannot fill the reply."""
    text = text.strip()
    if len(text) <= _FIELD_MAX_CHARS:
        return text
    return text[:_FIELD_MAX_CHARS].rstrip() + "…"


def _render_idea(hyp: dict[str, Any]) -> dict[str, Any]:
    """Render one idea as the tool's result entry."""
    body = {
        label: _clip(str(hyp.get(field) or ""))
        for field, label in _BODY_FIELDS
        if str(hyp.get(field) or "").strip()
    }
    return {
        "title": hyp.get("title") or "Untitled",
        "elo": hyp.get("elo_rating"),
        "status": hyp.get("status") or "active",
        "verification": hyp.get("verification_verdict"),
        "generation": hyp.get("generation"),
        **body,
    }


def _clamp_limit(raw: Any) -> int:
    """Clamp a model-supplied result limit into the allowed range."""
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RESULTS
    return max(1, min(_MAX_RESULTS, limit))


def search_ideas(
    hypotheses: list[dict[str, Any]],
    query: str,
    limit: Any = None,
) -> list[dict[str, Any]]:
    """Return the ideas best matching ``query``, in full.

    Args:
        hypotheses: The run's ideas, already ordered by Elo descending.
        query: The model's search terms.
        limit: Requested result count; clamped into range, defaulted when
            absent or unparseable.

    Returns:
        Up to ``limit`` rendered ideas. A query matching nothing falls back
        to the top-ranked ideas rather than an empty result: the model asked
        because it needs idea text, and "nothing found" for a run that has
        ideas reads to it as a run with no ideas.
    """
    count = _clamp_limit(limit)
    tokens = _tokenize(query or "")
    if tokens:
        scored = sorted(
            enumerate(hypotheses),
            key=lambda pair: (-_score(tokens, pair[1]), pair[0]),
        )
        matches = [hyp for _, hyp in scored if _score(tokens, hyp) > 0]
        if matches:
            return [_render_idea(hyp) for hyp in matches[:count]]
    return [_render_idea(hyp) for hyp in hypotheses[:count]]


def _tool_arguments(raw: str) -> dict[str, Any]:
    """Parse a tool call's JSON arguments, tolerating a malformed blob.

    A model that streams a truncated or non-JSON argument string still gets
    a search rather than an error: the raw text is a usable query on its
    own, which is better than failing the turn over punctuation.
    """
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        return {"query": raw}
    return parsed if isinstance(parsed, dict) else {"query": str(parsed)}


def run_tool_call(
    call: dict[str, Any], hypotheses: list[dict[str, Any]]
) -> str:
    """Execute one accumulated tool call and return its JSON result.

    Args:
        call: The accumulated ``{id, name, arguments}`` tool call.
        hypotheses: The run's ideas, ordered by Elo descending.

    Returns:
        The tool result as a JSON string, ready to send back as a ``tool``
        message. An unknown tool name returns an error object rather than
        raising -- the answer continues without it.
    """
    if call.get("name") != SEARCH_IDEAS_TOOL:
        logger.warning("Q&A model called unknown tool %s", call.get("name"))
        return json.dumps({"error": f"unknown tool {call.get('name')}"})
    args = _tool_arguments(str(call.get("arguments") or ""))
    results = search_ideas(
        hypotheses, str(args.get("query") or ""), args.get("limit")
    )
    return json.dumps({"ideas": results})


def accumulate_tool_calls(
    accumulated: dict[int, dict[str, Any]], delta: Any
) -> None:
    """Merge one streamed chunk's tool-call fragments into ``accumulated``.

    Providers stream a tool call the way they stream text: the name arrives
    in one chunk and the arguments in pieces across the next several, keyed
    only by the call's index in the list. Reassembling by index is what
    turns those fragments back into a call.

    Args:
        accumulated: Calls so far, keyed by their index in the response.
        delta: The chunk's ``delta`` object.
    """
    for fragment in getattr(delta, "tool_calls", None) or []:
        index = int(getattr(fragment, "index", 0) or 0)
        call = accumulated.setdefault(
            index, {"id": None, "name": None, "arguments": ""}
        )
        if getattr(fragment, "id", None):
            call["id"] = fragment.id
        function = getattr(fragment, "function", None)
        if function is None:
            continue
        if getattr(function, "name", None):
            call["name"] = function.name
        call["arguments"] += getattr(function, "arguments", None) or ""


def assistant_tool_message(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Render the assistant turn that requested ``calls``.

    The provider requires the call it is about to be given results for to
    appear in the transcript first, in its own message.
    """
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
            }
            for call in calls
        ],
    }


# States a Q&A answer must not treat as support: "unsupported" means the
# claim was checked against the source and the source did not back it, and
# "unavailable" means the source could not be resolved at all. Both are
# withheld from the manifest entirely rather than shown-but-labelled, so the
# model can never cite one as [n] -- there is no [n] to cite.
_UNCITABLE_STATES = frozenset({"unsupported", "unavailable"})

# Evidence rows carry a full abstract; only a bounded excerpt goes into the
# prompt so one long abstract cannot dominate the manifest's token budget.
_PASSAGE_MAX_CHARS = 600


def _eligible_citations(
    citations: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> Iterator[tuple[str, str]]:
    """Yield ``(evidence_id, state)`` for citations pointing at known evidence.

    Citations with no evidence id, or pointing at evidence we do not have,
    are skipped.
    """
    for citation in citations:
        raw_eid = citation.get("evidence_id")
        if raw_eid is None:
            continue
        eid = str(raw_eid)
        if eid in by_id:
            yield eid, str(citation.get("state") or "")


def _record_citation(
    cited_order: list[str],
    cited_state: dict[str, str],
    eid: str,
    state: str,
) -> None:
    """Record ``eid``'s manifest position (once) and its strongest state.

    An item's position is fixed by its first citation; a later citation of
    the same item can only upgrade its recorded state (never move it),
    keeping manifest numbering stable across the citation list.
    """
    if eid not in cited_state:
        # First citation of this item fixes its manifest position.
        cited_order.append(eid)
        cited_state[eid] = state
    elif STATE_RANK.get(state, -1) > STATE_RANK.get(cited_state[eid], -1):
        # Cited again with a stronger state: upgrade the state only,
        # keeping the original position so numbering stays stable.
        cited_state[eid] = state


def _rank_cited_evidence(
    citations: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    """Resolve each cited evidence id's manifest position and best state.

    Args:
        citations: Citation rows for the run.
        by_id: Evidence rows for the run, keyed by string id.

    Returns:
        A ``(cited_order, cited_state)`` pair: the evidence ids in first-cited
        order, and the strongest citation state seen for each id.
    """
    cited_state: dict[str, str] = {}
    cited_order: list[str] = []
    for eid, state in _eligible_citations(citations, by_id):
        _record_citation(cited_order, cited_state, eid, state)
    return cited_order, cited_state


def _resolve_entry_state(row: dict[str, Any], entry_state: str | None) -> str:
    """Resolve a manifest entry's state, defaulting uncited rows.

    Args:
        row: The evidence row.
        entry_state: The strongest citation state seen for this row, or None
            when the row was never cited.

    Returns:
        The citation state, or one derived from the row's availability flag
        when it was never cited.
    """
    if entry_state is not None:
        return entry_state
    return "available" if row.get("available", True) else "unavailable"


def _passage(row: dict[str, Any]) -> str | None:
    """Return a bounded excerpt of the evidence's abstract, or None.

    This is the content a citation actually grounds against: without it the
    model is told to cite ``[n]`` sources it was never shown the substance
    of, which invites fabricating what they say.
    """
    abstract = (row.get("abstract") or "").strip()
    if not abstract:
        return None
    if len(abstract) <= _PASSAGE_MAX_CHARS:
        return abstract
    return abstract[:_PASSAGE_MAX_CHARS].rstrip() + "…"


def _withhold_uncitable(
    ordered_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    cited_state: dict[str, str],
) -> list[str]:
    """Drop ids whose resolved state cannot ground an answer.

    Args:
        ordered_ids: Evidence ids, cited items first, in manifest order.
        by_id: Evidence rows for the run, keyed by string id.
        cited_state: Strongest citation state seen for each cited id.

    Returns:
        ``ordered_ids`` with every ``unsupported``/``unavailable`` id
        removed, order otherwise preserved.
    """
    return [
        eid
        for eid in ordered_ids
        if _resolve_entry_state(by_id[eid], cited_state.get(eid))
        not in _UNCITABLE_STATES
    ]


def _build_manifest_entries(
    ordered_ids: list[str],
    by_id: dict[str, dict[str, Any]],
    cited_state: dict[str, str],
    cap: int,
) -> list[dict[str, Any]]:
    """Materialize the capped, 1-based manifest entries for ``ordered_ids``.

    Args:
        ordered_ids: Evidence ids, cited items first, in manifest order.
        by_id: Evidence rows for the run, keyed by string id.
        cited_state: Strongest citation state seen for each cited id.
        cap: Maximum number of sources to include.

    Returns:
        A list of ``{n, evidence_id, title, url, source, year, state,
        passage}`` dicts.
    """
    manifest: list[dict[str, Any]] = []
    # 1-based numbering matches the [n] citation markers in the prompt.
    for n, eid in enumerate(ordered_ids[:cap], start=1):
        row = by_id[eid]
        manifest.append(
            {
                "n": n,
                "evidence_id": eid,
                "title": row.get("title") or "Untitled source",
                "url": row.get("url"),
                "source": row.get("source"),
                "year": row.get("year"),
                "state": _resolve_entry_state(row, cited_state.get(eid)),
                "passage": _passage(row),
            }
        )
    return manifest


def build_evidence_manifest(
    evidence: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    cap: int = 12,
) -> list[dict[str, Any]]:
    """Build a numbered, deterministic source list for grounded Q&A.

    Cited evidence comes first (in citation order, keeping the strongest state
    when an item is cited by several claims), then any remaining evidence.
    Sources classified ``unsupported`` or ``unavailable`` are withheld
    entirely -- they were checked against a claim and found not to back it,
    or could not be resolved at all, so nothing about them belongs in a
    grounded answer's context. What remains is capped to keep the prompt
    bounded. Each entry carries the fields the model needs to cite (title,
    a grounding passage) and the UI needs to render a reference chip.

    Args:
        evidence: Evidence rows for the run.
        citations: Citation rows for the run.
        cap: Maximum number of sources to include.

    Returns:
        A list of ``{n, evidence_id, title, url, source, year, state,
        passage}`` dicts.
    """
    by_id: dict[str, dict[str, Any]] = {
        str(e["id"]): e for e in evidence if e.get("id") is not None
    }
    cited_order, cited_state = _rank_cited_evidence(citations, by_id)
    # Uncited evidence trails the cited items, in retrieval (dict) order.
    ordered_ids = cited_order + [eid for eid in by_id if eid not in cited_state]
    usable_ids = _withhold_uncitable(ordered_ids, by_id, cited_state)
    return _build_manifest_entries(usable_ids, by_id, cited_state, cap)


def _format_manifest_for_prompt(manifest: list[dict[str, Any]]) -> str:
    """Render the manifest as numbered lines for the system prompt.

    A source's passage (when one was retrieved) is rendered as a quoted
    line under its heading, so a citation has actual text to ground
    against rather than only a title.
    """
    lines = []
    for entry in manifest:
        meta = ", ".join(
            str(part)
            for part in (entry.get("source"), entry.get("year"))
            if part
        )
        suffix = f" ({meta})" if meta else ""
        lines.append(
            f"[{entry['n']}] {entry['title']}{suffix} — {entry['state']}"
        )
        passage = entry.get("passage")
        if passage:
            lines.append(f'    "{passage}"')
    return "\n".join(lines)


@dataclasses.dataclass(frozen=True)
class QaRunContext:
    """One run's current state, as the grounded-Q&A prompt sees it.

    Attributes:
        research_goal: The run's research goal.
        hypotheses: The run's hypotheses, already ordered by Elo descending.
        reviews: The run's reviews, oldest-first.
        matches: The run's tournament matches, oldest-first.
        history: Prior chat messages, excluding the current question.
        manifest: The numbered evidence manifest citations resolve against.
        progress: The run's execution state -- how long it has been going,
            what step it is on, what it has produced. None only for a caller
            that did not gather it.
        report: The finished report's synthesis, once the run has produced
            one; None while it is still running.
    """

    research_goal: str
    hypotheses: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
    matches: list[dict[str, Any]]
    history: list[Any]
    manifest: list[dict[str, Any]]
    progress: RunProgress | None = None
    report: ReportFacts | None = None


@dataclasses.dataclass(frozen=True)
class _PromptSections:
    """The rendered prompt sections, in the order the template lays them out."""

    ideas: str
    reviews: str
    matches: str
    evidence: str
    conversation: str


def _summarize_run_context(context: QaRunContext) -> _PromptSections:
    """Summarize hypotheses, reviews, matches, evidence, and history.

    Every section but the idea index is truncated (last 5 reviews, last 3
    matches, last 10 messages) to keep the prompt bounded on long runs. The
    index is not: it is titles only, and it is what tells the model which
    ideas it can look up (see ``render_idea_index``).

    Returns:
        The five rendered prompt sections.
    """
    return _PromptSections(
        ideas=render_idea_index(context.hypotheses),
        reviews="\n".join(
            f"- {r['reviewer_agent']} on {r['hypothesis_id'][:8]}: "
            f"{r['summary'][:120]}"
            for r in context.reviews[-5:]
        ),
        matches="\n".join(
            f"- Winner {m['winner_id'][:8]} (Elo {m['winner_elo_after']}) — "
            f"{(m.get('rationale') or '')[:100]}"
            for m in context.matches[-3:]
        ),
        evidence=_format_manifest_for_prompt(context.manifest),
        conversation="\n".join(
            f"{'User' if m.sender == 'user' else 'Assistant'}: {m.content}"
            for m in context.history[-10:]
        ),
    )


# What the answer may and may not do with the context above. Kept apart
# from the sections so the rules read as one paragraph rather than as the
# tail of the last artifact rendered.
_ANSWER_RULES = (
    "Claims about this run -- what the ideas say, how they were reviewed "
    "or ranked, how far the run has got, and what the evidence shows -- "
    "must come ONLY from the context above and from the search_ideas tool. "
    "The idea index lists titles, not what the ideas say: call search_ideas "
    "before answering anything about an idea's content. If the run's "
    "artifacts do not contain the answer, say so plainly rather than "
    "speculating. Inline citations refer only to the numbered evidence "
    "list. Do not repeat the question. When a statement is supported by a "
    "listed source, cite it inline as [n]."
)


def _state_sections(context: QaRunContext) -> list[str]:
    """Render the run's own state: how it is going, and what it concluded.

    The report section is present only once the run has produced one, so a
    running run's prompt never carries an empty "Final report" heading for
    the model to answer out of.
    """
    sections: list[str] = []
    if context.progress is not None:
        sections.append(f"Run status:\n{render_progress(context.progress)}")
    if context.report is not None:
        body = render_report(context.report)
        if body:
            sections.append(f"Final report:\n{body}")
    return sections


def _artifact_sections(sections: _PromptSections) -> list[str]:
    """Render the run's artifacts in the order the prompt lays them out."""
    return [
        "Ideas in this run (titles only -- call the search_ideas tool for "
        f"what any of them actually says):\n{sections.ideas or '(none yet)'}",
        f"Recent reviews:\n{sections.reviews or '(none yet)'}",
        f"Recent tournament matches:\n{sections.matches or '(none yet)'}",
        "Evidence (cite supporting sources inline as [n] using ONLY this "
        "numbered list; never invent a citation):\n"
        f"{sections.evidence or '(no evidence retrieved)'}",
        f"Conversation history:\n{sections.conversation or '(none)'}",
    ]


def build_system_prompt(context: QaRunContext) -> str:
    """Assemble the grounded-Q&A system prompt from a run's current state.

    Args:
        context: The run state the answer must stay grounded in.

    Returns:
        The system prompt string.
    """
    sections = _summarize_run_context(context)
    blocks = [
        "You are a concise research assistant helping the user understand "
        "an AI-driven hypothesis generation run.",
        f"Research goal: {context.research_goal}",
        *_state_sections(context),
        *_artifact_sections(sections),
        _ANSWER_RULES,
    ]
    return "\n\n".join(blocks)
