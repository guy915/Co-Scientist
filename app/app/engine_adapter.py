"""Engine adapter — chooses real engine or mock workflow at runtime.

Logic:
- Provider = `mock` if `COSCIENTIST_FORCE_MOCK=1`, OR no LLM key is set, OR the
  `co_scientist` package can't be imported. Otherwise `engine`.
- Real-engine path imports lazily so the app boots even when the engine isn't
  installed yet (e.g. during initial setup).

The `mock` provider is the only one we exercise in CI / tests.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from app import store
from app.citations import (CitationRecord, classify_citation,
                           empty_citation_summary)
from app.config import settings
from app.elo import INITIAL_ELO
from app.mock_workflow import run_mock_workflow
from app.report_render import (
    EmitFn,
    article_stub,
    finalize_report,
    format_deep_verification_critique,
    hypothesis_stub,
    make_emitter,
    match_stub,
)
from app.run_modes import (
    CANONICAL_RUN_MODE,
    clean_string_list,
    focus_guidance,
    normalize_run_focus,
    resolved_run_config,
    setup_guidance,
)
from app.safety import apply_safety_gate, screen_intake
from app.store import RunStatus

# Editable-install .pth files aren't always processed in Python 3.12 venvs.
# Inject the sibling engine src into sys.path at import time so that
# `from co_scientist import HypothesisGenerator` in main.py succeeds.
_engine_src = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "engine", "src"))
if os.path.isdir(_engine_src) and _engine_src not in sys.path:
    sys.path.insert(0, _engine_src)

logger = logging.getLogger(__name__)


# True if any provider key that LiteLLM/the engine reads from the
# environment is present. Any single key is sufficient to attempt the
# real-engine path; which model actually gets used is a separate concern
# controlled by settings.model_name / settings.supervisor_model_name.
def _has_provider_key() -> bool:
    return any(
        bool(os.getenv(k)) for k in (
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AZURE_API_KEY",
            "DEEPSEEK_API_KEY",
        ))


# Checks importability via find_spec rather than a real import, so this can
# be probed cheaply and repeatedly without triggering the engine's own
# import-time side effects (e.g. LangGraph module setup).
def _engine_importable() -> bool:
    try:
        import importlib.util  # pylint: disable=import-outside-toplevel
        return importlib.util.find_spec("co_scientist") is not None
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def select_provider() -> str:
    """Return 'mock' or 'engine'. Persisted on the run row."""
    if os.getenv("COSCIENTIST_FORCE_MOCK") == "1":
        return "mock"  # explicit override, e.g. for tests or local dev
    if not _has_provider_key():
        return "mock"  # no LLM credentials configured
    if not _engine_importable():
        return "mock"  # co_scientist package not installed/importable
    return "engine"


def system_status() -> dict[str, Any]:
    """Return provider/engine diagnostic info for the /status route."""
    has_key = _has_provider_key()
    engine = _engine_importable()
    provider = select_provider()
    return {
        "provider": provider,
        "mock_mode": provider == "mock",
        "has_provider_key": has_key,
        "engine_importable": engine,
        "model_name": settings.model_name,
        # Report the effective supervisor model: the generator falls back to
        # model_name when supervisor_model_name is unset, so mirror that here.
        "supervisor_model_name": (settings.supervisor_model_name or
                                  settings.model_name),
        "mcp_server_url": settings.mcp_server_url,
    }


def _canonical_event_type(node_name: str) -> str:
    """Map an engine node name to the canonical mock event vocabulary.

    Only ``supervisor`` diverges from its node name (it emits
    ``supervisor.plan``). Every other node -- including any with no mock
    counterpart, such as ``review`` -- keeps its unprefixed node name, so it
    renders via the frontend's prettify fallback rather than a legacy
    ``engine.`` prefix.

    Args:
        node_name: The engine graph node name streamed by the generator.

    Returns:
        The canonical event type used across the mock, adapter, and frontend.
    """
    return "supervisor.plan" if node_name == "supervisor" else node_name


# Canonical pipeline stages the real engine runs, surfaced in the
# ``supervisor.plan`` payload's ``agents`` key so the frontend summary matches
# the mock's shape. Derived from the engine's actual graph nodes rather than
# copying the mock's list (which carries stages the engine never emits).
_ENGINE_PIPELINE_AGENTS: list[str] = [
    "supervisor",
    "literature_review",
    "generate",
    "reflection",
    "review",
    "ranking",
    "proximity",
    "evolve",
    "meta_review",
    "deep_verification",
    "research_overview",
]


def _generate_payload_extra(state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``generate`` node's payload keys."""
    hyps: list[dict[str, Any]] = state.get("hypotheses") or []
    return {
        "count": len(hyps),
        "hypotheses": [hypothesis_stub(h) for h in hyps],
    }


def _literature_review_payload_extra(state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``literature_review`` node's payload keys."""
    articles: list[dict[str, Any]] = state.get("articles") or []
    return {
        "count": len(articles),
        "evidence": [article_stub(a) for a in articles],
    }


def _ranking_payload_extra(state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``ranking`` node's payload keys."""
    matchups: list[dict[str, Any]] = state.get("tournament_matchups") or []
    return {"matches": [match_stub(m) for m in matchups]}


def _evolve_payload_extra(state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``evolve`` node's payload keys."""
    hyps: list[dict[str, Any]] = state.get("hypotheses") or []
    return {
        "children": [
            hypothesis_stub(h) for h in hyps if h.get("evolution_history")
        ]
    }


def _supervisor_plan_payload_extra(
        unused_state: dict[str, Any]) -> dict[str, Any]:
    """Build the ``supervisor.plan`` node's payload keys."""
    del unused_state
    return {"agents": list(_ENGINE_PIPELINE_AGENTS)}


# Per-node-type payload builders, keyed by the canonical event type. Nodes
# with no entry (e.g. ``reflection``, ``review``) get no extra payload keys
# beyond the common ``node``/``iteration`` pair built in
# ``_canonical_engine_payload``.
_PAYLOAD_BUILDERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "generate": _generate_payload_extra,
    "literature_review": _literature_review_payload_extra,
    "ranking": _ranking_payload_extra,
    "evolve": _evolve_payload_extra,
    "supervisor.plan": _supervisor_plan_payload_extra,
}


def _canonical_engine_payload(node_name: str, node_type: str,
                              state: dict[str, Any]) -> dict[str, Any]:
    """Build a canonical event payload for a streamed engine node.

    Per-stage keys match the mock's payload shape (``count``, ``hypotheses``,
    ``evidence``, ``matches``, ``children``, ``agents``) so a single
    vocabulary drives ``_format_milestone`` and the raw event log console.

    The list-shaped keys are projected to minimal stubs rather than carrying
    raw engine-state objects: every consumer reads only their ``length``, and
    ``store.append_event`` JSON-serializes the payload with no fallback
    handler, so raw hypothesis/article dicts (which may carry non-serializable
    fields such as embeddings) must never be embedded whole. This mirrors the
    projection discipline in ``_persist_final_state``.

    Args:
        node_name: The engine graph node name.
        node_type: The canonical event type for ``node_name``.
        state: The cumulative engine state snapshot for this node.

    Returns:
        The event payload dict (JSON-serializable; only plain dicts/lists).
    """
    payload: dict[str, Any] = {
        "node": node_name,
        "iteration": state.get("current_iteration", 0),
    }
    builder = _PAYLOAD_BUILDERS.get(node_type)
    if builder is not None:
        payload.update(builder(state))
    return payload


def _milestone_supervisor_plan(unused_payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed supervisor plan."""
    del unused_payload
    return "Research plan ready — supervisor complete"


def _milestone_generate(payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed generation round."""
    count = payload.get("count", 0)
    itr = payload.get("iteration", 0)
    label = f"iteration {itr}" if itr else "initial"
    return f"{count} hypotheses generated ({label})"


def _milestone_ranking(payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed ranking round."""
    count = len(payload.get("matches") or [])
    itr = payload.get("iteration", 0)
    return f"Tournament complete (iteration {itr}, {count} matches)"


def _milestone_meta_review(unused_payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed meta-review."""
    del unused_payload
    return "Meta-review complete"


def _milestone_evolve(payload: dict[str, Any]) -> str:
    """Build the milestone text for a completed evolve round."""
    count = len(payload.get("children") or [])
    itr = payload.get("iteration", 0)
    return f"{count} hypotheses evolved (iteration {itr})"


# Per-node-type milestone builders, keyed by the canonical event type. Nodes
# with no entry (e.g. ``reflection``, ``review``) generate no milestone,
# mirroring ``_PAYLOAD_BUILDERS``'s dispatch shape above.
_MILESTONE_BUILDERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "supervisor.plan": _milestone_supervisor_plan,
    "generate": _milestone_generate,
    "ranking": _milestone_ranking,
    "meta_review": _milestone_meta_review,
    "evolve": _milestone_evolve,
}


def _format_milestone(node_type: str, payload: dict[str, Any]) -> str | None:
    """Return a human-readable milestone string for key node events, or None.

    Reads the single canonical (mock-shaped) payload vocabulary. Unknown or
    legacy types (e.g. old persisted ``engine.*`` events) fall through to
    ``None``, so no milestone is generated — the same behaviour today's code
    has for unmatched types.
    """
    builder = _MILESTONE_BUILDERS.get(node_type)
    return builder(payload) if builder is not None else None


def _article_coalesced_fields(
        art: dict[str, Any]) -> tuple[str, list[str], str]:
    """Extract an article's (url, authors, abstract), each falling back.

    Isolates the fields whose raw value needs an empty-default fallback (as
    opposed to the fields below that already have a `dict.get` default), so
    the persistence loop stays free of branching.
    """
    url = art.get("url") or ""
    authors = art.get("authors") or []
    abstract = art.get("abstract") or ""
    return url, authors, abstract


def _persist_engine_evidence(
    run_id: str,
    articles: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> tuple[dict[str, str], dict[str, str]]:
    """Persist retrieved articles as evidence rows.

    Returns:
        A tuple of (evidence id by title, abstract by title) lookups the
        hypothesis/citation pass needs: the citation_map carries no abstract
        of its own, so a cited source is classified against its evidence
        row's abstract via this title-keyed map.
    """
    ev_id_by_title: dict[str, str] = {}
    abstract_by_title: dict[str, str] = {}
    for art in articles:
        url, authors, abstract = _article_coalesced_fields(art)
        ev_id = store.add_evidence(
            run_id,
            art.get("title", "Untitled"),
            source=art.get("source", "engine"),
            url=url,
            authors=authors,
            year=art.get("year"),
            abstract=abstract,
            available=True,
            conn=conn,
        )
        ev_id_by_title[art.get("title", "")] = ev_id
        abstract_by_title[art.get("title", "")] = abstract
    return ev_id_by_title, abstract_by_title


def _derive_hypothesis_identity(
        h: dict[str, Any]) -> tuple[str, str, int, str, str | None]:
    """Derive an engine hypothesis's statement, title, generation, and ids.

    The title is the first sentence (or first 120 chars) of the statement.

    Returns:
        A tuple of (statement text, derived title, generation number,
        creating agent label, the engine's own id or None).
    """
    is_evolved = bool(h.get("evolution_history"))
    text = h.get("text", "")
    title = text.split(".")[0][:120] or text[:120]
    engine_id = h.get("id") or None
    generation = 1 if is_evolved else 0
    agent = "evolution" if is_evolved else "generation"
    return text, title, generation, agent, engine_id


def _persist_hypothesis_state(hyp_id: str, h: dict[str, Any],
                              conn: sqlite3.Connection) -> None:
    """Persist a hypothesis's mutable state: Elo rating, wins, losses, score."""
    store.update_hypothesis_state(
        hyp_id,
        elo_rating=int(h.get("elo_rating", INITIAL_ELO)),
        win_delta=int(h.get("win_count", 0)),
        loss_delta=int(h.get("loss_count", 0)),
        novelty=float(h.get("score", 0) or 0) or None,
        conn=conn,
    )


def _persist_engine_hypothesis_row(
    run_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> tuple[str, str | None]:
    """Persist one engine hypothesis's row and mutable state (Elo/wins/losses).

    The engine's stable hypothesis id is passed straight through as the store
    row id, so identity holds end-to-end (engine -> DB -> API -> UI) and
    matchups resolve by id rather than by fragile text-prefix matching.

    Returns:
        A tuple of (persisted store row id, the engine's own id or None).
    """
    text, title, generation, agent, engine_id = _derive_hypothesis_identity(h)
    hyp_id = store.add_hypothesis(
        run_id=run_id,
        title=title,
        statement=text,
        hypothesis_id=engine_id,
        category=h.get("category") or None,
        mechanism=h.get("literature_grounding") or "",
        expected_effect=h.get("explanation") or "",
        experimental_context=h.get("experiment") or "",
        generation=generation,
        created_by_agent=agent,
        conn=conn,
    )
    _persist_hypothesis_state(hyp_id, h, conn)
    return hyp_id, engine_id


def _score_or_none(value: Any) -> float | None:
    """Coerce a raw engine score to a float, treating 0/falsy as unset."""
    return float(value or 0) or None


def _persist_engine_review_rows(run_id: str, hyp_id: str, h: dict[str, Any],
                                conn: sqlite3.Connection) -> None:
    """Persist a hypothesis's per-review rows from the engine's reviews list."""
    for rv in h.get("reviews") or []:
        scores = rv.get("scores", {})
        store.add_review(
            run_id=run_id,
            hypothesis_id=hyp_id,
            reviewer_agent="review",
            summary=rv.get("review_summary", ""),
            critique=rv.get("constructive_feedback", ""),
            novelty=_score_or_none(scores.get("novelty", 0)),
            plausibility=_score_or_none(scores.get("scientific_soundness", 0)),
            testability=_score_or_none(scores.get("testability", 0)),
            overall=_score_or_none(rv.get("overall_score", 0)),
            conn=conn,
        )


def _persist_deep_verification_review(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist deep-verification probes as a dedicated review row, if any."""
    probes = h.get("deep_verification_probes") or []
    if not probes:
        return
    summary, critique = format_deep_verification_critique(
        probes, h.get("deep_verification_verdict"))
    store.add_review(
        run_id=run_id,
        hypothesis_id=hyp_id,
        reviewer_agent="deep_verification",
        summary=summary,
        critique=critique,
        conn=conn,
    )


def _persist_engine_reviews(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist a hypothesis's per-review rows plus its deep-verification row."""
    _persist_engine_review_rows(run_id, hyp_id, h, conn)
    _persist_deep_verification_review(run_id, hyp_id, h, conn)


def _ensure_citation_evidence_id(
    run_id: str,
    cite_title: str,
    cite_info: dict[str, Any],
    cite_url: str,
    ev_id_by_title: dict[str, str],
    conn: sqlite3.Connection,
) -> str:
    """Return the evidence id for a cited source, adding it on the fly.

    Mutates `ev_id_by_title` in place when a new evidence row is added.
    """
    cite_ev_id = ev_id_by_title.get(cite_title)
    if cite_ev_id is None:
        cite_ev_id = store.add_evidence(
            run_id,
            cite_title,
            source=cite_info.get("type", "engine"),
            url=cite_url,
            authors=cite_info.get("authors") or [],
            year=cite_info.get("year"),
            abstract="",
            available=True,
            conn=conn,
        )
        ev_id_by_title[cite_title] = cite_ev_id
    return cite_ev_id


def _hypothesis_grounding_text(h: dict[str, Any]) -> str:
    """Return the literature-grounding text used as a citation's claim basis.

    Falls back to the hypothesis's own statement text, then to empty, when no
    dedicated grounding text was generated.
    """
    return str(h.get("literature_grounding") or h.get("text") or "")


def _citation_map(h: dict[str, Any]) -> dict[str, Any]:
    """Return a hypothesis's raw engine citation map, defaulting to empty."""
    return h.get("citation_map") or {}


def _citation_url(cite_info: dict[str, Any]) -> str:
    """Return a citation's URL, defaulting to empty (an unavailable source)."""
    return cite_info.get("url") or ""


def _persist_engine_citations(
    run_id: str,
    hyp_id: str,
    h: dict[str, Any],
    ev_id_by_title: dict[str, str],
    abstract_by_title: dict[str, str],
    citation_summary: dict[str, int],
    conn: sqlite3.Connection,
) -> None:
    """Persist a hypothesis's citations, classifying each via the shared path.

    Route each through the shared classifier (the same path the mock uses)
    rather than hardcoding a state, so the four-state citation UI reflects
    real runs. The hypothesis grounding is the claim the citation supports;
    it is matched against the cited paper's abstract (when the source was
    retrieved), and a source with no resolvable URL (e.g. a knowledge-graph
    statement) falls out as "unavailable".

    Mutates `ev_id_by_title` (a citation may add evidence for its source on
    the fly) and `citation_summary` (running citation-state counts) in place.
    """
    grounding = _hypothesis_grounding_text(h)
    for cite_key, cite_info in _citation_map(h).items():
        cite_title = cite_info.get("title", cite_key)
        cite_url = _citation_url(cite_info)
        cite_ev_id = _ensure_citation_evidence_id(run_id, cite_title, cite_info,
                                                  cite_url, ev_id_by_title,
                                                  conn)
        claim = f"[{cite_key}] cited in hypothesis"
        state = classify_citation(
            CitationRecord(
                url=cite_url,
                abstract=abstract_by_title.get(cite_title, ""),
                claim=grounding,
                available=True,
            ))
        citation_summary[state] += 1
        store.add_citation(run_id, hyp_id, cite_ev_id, claim, state, conn=conn)


def _persist_engine_hypothesis(
    run_id: str,
    h: dict[str, Any],
    ev_id_by_title: dict[str, str],
    abstract_by_title: dict[str, str],
    store_id_by_engine_id: dict[str, str],
    citation_summary: dict[str, int],
    conn: sqlite3.Connection,
) -> None:
    """Persist one engine hypothesis: its row, state, reviews, and citations.

    Mutates `store_id_by_engine_id` (engine id -> persisted row id),
    `ev_id_by_title` (a citation may add evidence for its source on the fly),
    and `citation_summary` (running citation-state counts) in place.
    """
    hyp_id, engine_id = _persist_engine_hypothesis_row(run_id, h, conn)
    if engine_id:
        store_id_by_engine_id[engine_id] = hyp_id
    _persist_engine_reviews(run_id, hyp_id, h, conn)
    _persist_engine_citations(run_id, hyp_id, h, ev_id_by_title,
                              abstract_by_title, citation_summary, conn)


def _matchup_loser_engine_id(m: dict[str, Any], a_engine_id: str | None,
                             winner_engine_id: str | None) -> str | None:
    """Return the losing side's engine id: whichever side didn't win."""
    b_engine_id = m.get("hypothesis_b_id")
    return b_engine_id if winner_engine_id == a_engine_id else a_engine_id


def _resolve_match_sides(
    m: dict[str, Any],
    store_id_by_engine_id: dict[str, str],
) -> tuple[str, str] | None:
    """Resolve a matchup's winner/loser store ids, or None if unresolved.

    Matchups may legitimately reference hypotheses that were dropped from the
    final set (evolve discards lower-ranked ones), so an unresolved id is
    expected rather than an error — logged and skipped by the caller.
    """
    a_engine_id = m.get("hypothesis_a_id")
    winner_engine_id = m.get("winner_id")
    loser_engine_id = _matchup_loser_engine_id(m, a_engine_id, winner_engine_id)

    winner_id = store_id_by_engine_id.get(winner_engine_id or "")
    loser_id = store_id_by_engine_id.get(loser_engine_id or "")
    # Inlined (rather than routed through a predicate helper) so mypy's
    # flow-sensitive narrowing sees both ids as non-None below.
    if not winner_id or not loser_id:
        logger.warning(
            "skipping matchup: unresolved hypothesis id "
            "(winner=%s, loser=%s) — likely a hypothesis dropped "
            "during evolution", winner_engine_id, loser_engine_id)
        return None
    return winner_id, loser_id


def _persist_engine_matches(
    run_id: str,
    matchups: list[dict[str, Any]],
    store_id_by_engine_id: dict[str, str],
    conn: sqlite3.Connection,
) -> None:
    """Persist tournament matches, resolving each side by engine id."""
    for m in matchups:
        sides = _resolve_match_sides(m, store_id_by_engine_id)
        if sides is None:
            continue
        winner_id, loser_id = sides
        store.add_match(
            run_id=run_id,
            iteration=0,
            winner_id=winner_id,
            loser_id=loser_id,
            winner_before=int(m.get("winner_elo_before", INITIAL_ELO)),
            winner_after=int(m.get("winner_elo_after", INITIAL_ELO)),
            loser_before=int(m.get("loser_elo_before", INITIAL_ELO)),
            loser_after=int(m.get("loser_elo_after", INITIAL_ELO)),
            rationale=m.get("reasoning", ""),
            tier=m.get("tier") or None,
            conn=conn,
        )


def _final_state_list(final_state: dict[str, Any],
                      key: str) -> list[dict[str, Any]]:
    """Return a list-valued key from the engine's final state, or empty."""
    return final_state.get(key) or []


def _final_state_dict(final_state: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a dict-valued key from the engine's final state, or empty."""
    return final_state.get(key) or {}


def _persist_final_state(
    *,
    run_id: str,
    final_state: dict[str, Any],
    db_path: str | None = None,
) -> dict[str, Any]:
    """Drain an engine final state into the store.

    Writes evidence, hypotheses (with reviews, deep-verification reviews, and
    citations), and tournament matches. Deep-verification probes ride the
    reviews table as ``reviewer_agent="deep_verification"`` rows. The report
    itself is built and persisted separately by ``finalize_report``; this helper
    returns the provider-specific inputs that path needs.

    Args:
        run_id: Identifier of the run being drained.
        final_state: Accumulated engine final state.
        db_path: Optional override for the SQLite database path.

    Returns:
        The report inputs only this provider knows: ``citation_summary``,
        ``meta_review``, and ``research_overview``. Row counts are not
        returned; ``finalize_report`` reads them from the store.
    """
    hyps = _final_state_list(final_state, "hypotheses")
    articles = _final_state_list(final_state, "articles")
    matchups = _final_state_list(final_state, "tournament_matchups")
    citation_summary = empty_citation_summary()
    store_id_by_engine_id: dict[str, str] = {}

    # Batch the whole drain into one transaction: a real run writes dozens of
    # rows here, and per-call connections would fsync each one individually.
    with store.transaction(db_path) as conn:
        # 1. Evidence: persist retrieved articles.
        ev_id_by_title, abstract_by_title = _persist_engine_evidence(
            run_id, articles, conn)

        # 2. Hypotheses: persist in generation order; mark evolved ones.
        for h in hyps:
            _persist_engine_hypothesis(run_id, h, ev_id_by_title,
                                       abstract_by_title, store_id_by_engine_id,
                                       citation_summary, conn)

        # 3. Tournament matches: resolve each side by the engine's stable
        # hypothesis id.
        _persist_engine_matches(run_id, matchups, store_id_by_engine_id, conn)

    return {
        "citation_summary":
            citation_summary,
        "meta_review":
            _final_state_dict(final_state, "meta_review"),
        "research_overview":
            _final_state_dict(final_state, "research_overview"),
    }


async def _stream_mock_provider(
    run_id: str,
    research_goal: str,
    cfg: dict[str, Any],
    *,
    db_path: str | None,
    cancelled: asyncio.Event | None,
    sleep_seconds: float,
) -> AsyncIterator[dict[str, Any]]:
    """Drain pre-run steering, then stream the mock workflow with milestones.

    Forwards every mock event on the SSE stream, additionally surfacing
    select event types as a user-facing chat message.
    """
    # Drain any steering queued before the run started (e.g. via the
    # composer) so it is not left "pending" and re-applied later inside
    # run_mock_workflow's own per-iteration steering check.
    pre_run_steering = store.get_pending_steering(run_id, db_path=db_path)
    if pre_run_steering:
        store.mark_steering_applied([m.id for m in pre_run_steering],
                                    db_path=db_path)

    async for event in run_mock_workflow(
            run_id=run_id,
            research_goal=research_goal,
            config=cfg,
            db_path=db_path,
            cancelled=cancelled,
            sleep_seconds=sleep_seconds,
    ):
        # In addition to forwarding the raw event on the SSE stream, surface
        # select event types as a user-facing chat message.
        milestone = _format_milestone(event.get("type", ""),
                                      event.get("payload", {}))
        if milestone:
            store.append_message(run_id,
                                 "system",
                                 milestone,
                                 "milestone",
                                 db_path=db_path)
        yield event


def _import_hypothesis_generator() -> Any | None:
    """Import the engine's `HypothesisGenerator`, or None if unavailable."""
    try:
        from co_scientist import HypothesisGenerator  # type: ignore[import-not-found, unused-ignore]  # pylint: disable=import-outside-toplevel
        return HypothesisGenerator
    # pylint: disable-next=broad-exception-caught
    except Exception as e:  # pragma: no cover (defensive)
        logger.error("engine import failed: %s — falling back to mock", e)
        return None


def _clean_list_field(setup: dict[str, Any], key: str) -> list[str]:
    """Return a setup dict's list field, stringified and cleaned."""
    return clean_string_list([str(value) for value in setup.get(key) or []])


def _setup_opts_from_cfg(setup: dict[str, Any] | None) -> dict[str, Any]:
    """Translate the composer "setup" dict into engine opts keys.

    Note "requirements" (UI/store term) maps to "constraints" (engine term)
    -- the only renamed key in this block. Returns an empty dict when `setup`
    is not a dict (e.g. absent from an older/partial run config).
    """
    if not isinstance(setup, dict):
        return {}
    focus = normalize_run_focus(setup.get("focus"))
    return {
        "run_focus_guidance": focus_guidance(focus),
        "run_setup_guidance": setup_guidance(setup),
        "attributes": _clean_list_field(setup, "attributes"),
        "constraints": _clean_list_field(setup, "requirements"),
        "criteria": _clean_list_field(setup, "criteria"),
    }


def _append_if(parts: list[str], value: str | None) -> None:
    """Append `value` to `parts` if it is present (truthy)."""
    if value:
        parts.append(value)


def _steering_preference_part(
        db_path: str | None,
        pending_steering: list[store.MessageRow]) -> str | None:
    """Return the queued-steering preference text, marking it applied.

    Returns None (and leaves the queue untouched) when there is nothing
    pending.
    """
    if not pending_steering:
        return None
    guidance = "\n".join(f"- {m.content}" for m in pending_steering)
    store.mark_steering_applied([m.id for m in pending_steering],
                                db_path=db_path)
    return f"User steering guidance:\n{guidance}"


def _fold_steering_preferences(run_id: str, db_path: str | None,
                               setup_text: str) -> str | None:
    """Fold setup guidance and queued user steering into one "preferences" opt.

    Steering consumed here is marked applied so a later iteration does not
    replay the same message. Returns None when there is nothing to fold.
    """
    pending_steering = store.get_pending_steering(run_id, db_path=db_path)
    preference_parts: list[str] = []
    _append_if(preference_parts, setup_text)
    _append_if(preference_parts,
               _steering_preference_part(db_path, pending_steering))
    return "\n\n".join(preference_parts) if preference_parts else None


def _resolve_literature_review_toggle(cfg: dict[str, Any]) -> bool:
    """Resolve the per-run literature-review toggle, honoring the kill switch.

    Literature grounding defaults on but is user-controlled per run (the
    PubMed connector toggle in the composer). The engine still degrades
    gracefully to LLM-only if MCP is unreachable, so a down MCP never breaks
    a run. FORCE_LITERATURE_REVIEW=0 is a hard kill switch for tests/dev
    that must run without it, regardless of the per-run setting.
    """
    enable_literature_review = bool(cfg.get("enable_literature_review", True))
    if os.getenv("FORCE_LITERATURE_REVIEW") == "0":
        enable_literature_review = False
    return enable_literature_review


def _build_engine_opts(cfg: dict[str, Any], run_id: str,
                       db_path: str | None) -> dict[str, Any]:
    """Translate a run's durable config into the engine's `opts` vocabulary.

    Folds the composer "setup" (focus/attributes/requirements/criteria), any
    queued user steering, and the literature-review toggle into one opts
    dict. Steering consumed here is marked applied so a later iteration does
    not replay the same message.
    """
    initial_opts = _setup_opts_from_cfg(cfg.get("setup"))
    preferences = _fold_steering_preferences(
        run_id, db_path, str(initial_opts.get("run_setup_guidance") or ""))
    if preferences:
        initial_opts["preferences"] = preferences
    initial_opts["enable_literature_review_node"] = (
        _resolve_literature_review_toggle(cfg))
    return initial_opts


def _build_generator(generator_cls: Any, cfg: dict[str, Any]) -> Any:
    """Construct a fresh `HypothesisGenerator` from the run's resolved config.

    A fresh generator is constructed per run rather than reused, so each
    run's model/tier settings apply independently of any other run. `cfg`
    went through `resolved_run_config` upstream, so every numeric key is
    present -- index directly rather than re-inventing defaults here.
    """
    return generator_cls(
        model_name=settings.model_name,
        supervisor_model_name=settings.supervisor_model_name,
        max_iterations=int(cfg["max_iterations"]),
        initial_hypotheses_count=int(cfg["initial_hypotheses_count"]),
        evolution_max_count=int(cfg["evolution_max_count"]),
        tournament_pairs=int(cfg["tournament_pairs"]),
        # ``evidence_count`` is the single literature-budget knob in the tier
        # table; map it to the engine's parameter name at this translation
        # boundary rather than persisting a second synced key.
        literature_review_papers_count=int(cfg["evidence_count"]),
    )


def _merge_engine_state(final_state: dict[str, Any], state: dict[str,
                                                                 Any]) -> None:
    """Merge one streamed engine snapshot's known keys into `final_state`.

    Mutates `final_state` in place with any of the tracked keys present in
    `state` (a node may omit keys it doesn't touch).
    """
    for key in ("hypotheses", "articles", "tournament_matchups", "meta_review",
                "research_overview"):
        if state.get(key) is not None:
            final_state[key] = state[key]


async def _stream_engine_nodes(
    generator: Any,
    research_goal: str,
    run_id: str,
    initial_opts: dict[str, Any] | None,
    final_state: dict[str, Any],
    *,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Stream the engine's per-node events, updating `final_state` in place.

    Normalizes each node to the canonical mock event vocabulary, emits it
    (with a milestone side-message for key events), and yields the streamed
    event. On cancellation, yields a final "cancelled" status event and
    returns early; the caller checks `cancelled.is_set()` once this generator
    is exhausted to distinguish that from a natural finish.
    """
    async for node_name, state in generator.generate_hypotheses(
            research_goal=research_goal,
            stream=True,
            run_id=run_id,
            opts=initial_opts,
    ):
        if cancelled and cancelled.is_set():
            store.update_run_status(run_id,
                                    RunStatus.CANCELLED,
                                    db_path=db_path)
            yield await emit("status", {"status": "cancelled"})
            return

        # Update final_state from each yielded cumulative snapshot.
        _merge_engine_state(final_state, state)

        # Normalize the engine node to the canonical mock event vocabulary so
        # every downstream consumer reads one shape (no engine.* types).
        node_type = _canonical_event_type(node_name)
        payload = _canonical_engine_payload(node_name, node_type, state)
        milestone = _format_milestone(node_type, payload)
        if milestone:
            store.append_message(run_id,
                                 "system",
                                 milestone,
                                 "milestone",
                                 db_path=db_path)
        yield await emit(node_type, payload)


async def _run_engine_and_report(
    generator: Any,
    research_goal: str,
    run_id: str,
    run_mode: str,
    initial_opts: dict[str, Any] | None,
    *,
    start: float,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Stream the engine's nodes, then drain final state and emit the report.

    Yields every streamed event. On cancellation, `_stream_engine_nodes` has
    already emitted the terminal "cancelled" status event, so this returns
    early and skips draining/reporting.
    """
    # Accumulate the full final state across all streamed nodes.
    final_state: dict[str, Any] = {
        "hypotheses": [],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }
    async for event in _stream_engine_nodes(
            generator,
            research_goal,
            run_id,
            initial_opts,
            final_state,
            cancelled=cancelled,
            db_path=db_path,
            emit=emit,
    ):
        yield event
    if cancelled and cancelled.is_set():
        return

    # ---- Drain final state into the store ----
    report_inputs = _persist_final_state(
        run_id=run_id,
        final_state=final_state,
        db_path=db_path,
    )

    # Build, screen, persist, and emit the report through the shared
    # finalize path (final safety gate included), so the engine is gated
    # and reported on exactly the same terms as the mock.
    async for event in finalize_report(
        run_id=run_id,
        research_goal=research_goal,
        run_mode=run_mode,
        provider="engine",
        emit=emit,
        execution_time=time.time() - start,
        db_path=db_path,
        **report_inputs,
    ):
        yield event


async def _run_engine_provider(
    generator_cls: Any,
    research_goal: str,
    run_id: str,
    run_mode: str,
    cfg: dict[str, Any],
    *,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Run the real engine end to end: stream nodes, drain state, report.

    Persists the running status, then delegates streaming/draining/reporting
    to `_run_engine_and_report`. On any exception, marks the run failed and
    yields a terminal "failed" status event.
    """
    # Persist the running state, not just emit it. The mock path sets this; the
    # engine path previously only emitted the event, leaving the run row stuck
    # at "queued" for the entire run (misleading status pill in the UI).
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    yield await emit("status", {"status": "running"})

    initial_opts = _build_engine_opts(cfg, run_id, db_path)
    generator = _build_generator(generator_cls, cfg)
    start = time.time()

    try:
        async for event in _run_engine_and_report(
                generator,
                research_goal,
                run_id,
                run_mode,
                initial_opts if initial_opts else None,
                start=start,
                cancelled=cancelled,
                db_path=db_path,
                emit=emit,
        ):
            yield event
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("engine run failed: %s", e)
        store.update_run_status(run_id,
                                RunStatus.FAILED,
                                error=str(e),
                                db_path=db_path)
        yield await emit("status", {"status": "failed", "error": str(e)})


async def _select_provider_stream(
    provider: str,
    research_goal: str,
    run_id: str,
    run_mode: str,
    cfg: dict[str, Any],
    *,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    sleep_seconds: float,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Return the event stream for the resolved provider, choosing a fallback.

    Falls back to the mock workflow if the real engine cannot be imported
    even though `provider` resolved to "engine" (e.g. a partial install).
    """
    if provider == "mock":
        return _stream_mock_provider(
            run_id,
            research_goal,
            cfg,
            db_path=db_path,
            cancelled=cancelled,
            sleep_seconds=sleep_seconds,
        )

    # Real engine path — bridge engine streaming events into our event log.
    generator_cls = _import_hypothesis_generator()
    if generator_cls is None:
        return run_mock_workflow(
            run_id=run_id,
            research_goal=research_goal,
            config=cfg,
            db_path=db_path,
            cancelled=cancelled,
            sleep_seconds=sleep_seconds,
        )

    return _run_engine_provider(
        generator_cls,
        research_goal,
        run_id,
        run_mode,
        cfg,
        cancelled=cancelled,
        db_path=db_path,
        emit=emit,
    )


async def _dispatch_provider(
    provider: str,
    research_goal: str,
    run_id: str,
    run_mode: str,
    cfg: dict[str, Any],
    *,
    cancelled: asyncio.Event | None,
    db_path: str | None,
    sleep_seconds: float,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Dispatch to the mock or real-engine workflow after the intake gate."""
    stream = await _select_provider_stream(
        provider,
        research_goal,
        run_id,
        run_mode,
        cfg,
        cancelled=cancelled,
        db_path=db_path,
        sleep_seconds=sleep_seconds,
        emit=emit,
    )
    async for event in stream:
        yield event


async def run_workflow(
    run_id: str,
    research_goal: str,
    config: dict[str, Any],
    *,
    db_path: str | None = None,
    cancelled: asyncio.Event | None = None,
    sleep_seconds: float = 0.05,
    force_provider: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the chosen workflow and yield events as the store records them.

    Intake safety screening runs here, at the shared boundary both providers
    pass through, so every run (engine or mock) is gated before any work.
    """
    # force_provider lets a caller (e.g. seed.py's demo seeding) pin the
    # provider explicitly, bypassing select_provider()'s env/import probes.
    provider = force_provider or select_provider()
    run_mode = CANONICAL_RUN_MODE
    cfg = resolved_run_config(config)

    logger.info("starting workflow run=%s provider=%s run_mode=%s", run_id,
                provider, run_mode)

    emit = make_emitter(run_id, db_path=db_path)

    # Intake safety gate, shared by every provider. A hard block short-circuits
    # the run before any hypotheses are generated.
    intake = screen_intake(research_goal)
    async for event in apply_safety_gate(run_id, intake, emit, db_path=db_path):
        yield event
    if intake.decision == "block":
        return

    async for event in _dispatch_provider(
            provider,
            research_goal,
            run_id,
            run_mode,
            cfg,
            cancelled=cancelled,
            db_path=db_path,
            sleep_seconds=sleep_seconds,
            emit=emit,
    ):
        yield event
