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
import sys
import time
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.citations import (CitationRecord, classify_citation,
                           empty_citation_summary)
from app.config import settings
from app.elo import INITIAL_ELO
from app.mock_workflow import run_mock_workflow
from app.report_render import (
    article_stub,
    finalize_report,
    format_deep_verification_critique,
    hypothesis_stub,
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


def _has_provider_key() -> bool:
    return any(
        bool(os.getenv(k)) for k in (
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AZURE_API_KEY",
            "DEEPSEEK_API_KEY",
        ))


def _engine_importable() -> bool:
    try:
        import importlib.util  # pylint: disable=import-outside-toplevel
        return importlib.util.find_spec("co_scientist") is not None
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def select_provider() -> str:
    """Return 'mock' or 'engine'. Persisted on the run row."""
    if os.getenv("COSCIENTIST_FORCE_MOCK") == "1":
        return "mock"
    if not _has_provider_key():
        return "mock"
    if not _engine_importable():
        return "mock"
    return "engine"


def system_status() -> dict[str, Any]:
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
        "mcp_server_url": os.getenv("MCP_SERVER_URL", ""),
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
    hyps: list[dict[str, Any]] = state.get("hypotheses") or []
    matchups: list[dict[str, Any]] = state.get("tournament_matchups") or []
    articles: list[dict[str, Any]] = state.get("articles") or []
    iteration = state.get("current_iteration", 0)

    payload: dict[str, Any] = {
        "node": node_name,
        "iteration": iteration,
    }

    if node_type == "generate":
        payload["count"] = len(hyps)
        payload["hypotheses"] = [hypothesis_stub(h) for h in hyps]
    elif node_type == "literature_review":
        payload["count"] = len(articles)
        payload["evidence"] = [article_stub(a) for a in articles]
    elif node_type == "ranking":
        payload["matches"] = [match_stub(m) for m in matchups]
    elif node_type == "evolve":
        payload["children"] = [
            hypothesis_stub(h) for h in hyps if h.get("evolution_history")
        ]
    elif node_type == "supervisor.plan":
        payload["agents"] = list(_ENGINE_PIPELINE_AGENTS)

    return payload


def _format_milestone(node_type: str, payload: dict[str, Any]) -> str | None:
    """Return a human-readable milestone string for key node events, or None.

    Reads the single canonical (mock-shaped) payload vocabulary. Unknown or
    legacy types (e.g. old persisted ``engine.*`` events) fall through to
    ``None``, so no milestone is generated — the same behaviour today's code
    has for unmatched types.
    """
    if node_type == "supervisor.plan":
        return "Research plan ready — supervisor complete"
    if node_type == "generate":
        count = payload.get("count", 0)
        itr = payload.get("iteration", 0)
        label = f"iteration {itr}" if itr else "initial"
        return f"{count} hypotheses generated ({label})"
    if node_type == "ranking":
        count = len(payload.get("matches") or [])
        itr = payload.get("iteration", 0)
        return f"Tournament complete (iteration {itr}, {count} matches)"
    if node_type == "meta_review":
        return "Meta-review complete"
    if node_type == "evolve":
        count = len(payload.get("children") or [])
        itr = payload.get("iteration", 0)
        return f"{count} hypotheses evolved (iteration {itr})"
    return None


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
    hyps: list[dict[str, Any]] = final_state.get("hypotheses") or []
    articles: list[dict[str, Any]] = final_state.get("articles") or []
    matchups: list[dict[str,
                        Any]] = final_state.get("tournament_matchups") or []
    citation_summary = empty_citation_summary()

    # Batch the whole drain into one transaction: a real run writes dozens of
    # rows here, and per-call connections would fsync each one individually.
    with store.transaction(db_path) as conn:
        # 1. Evidence: persist retrieved articles. Keep each article's abstract
        # keyed by title so the citation pass can classify a cited source
        # against it (the citation_map carries no abstract of its own).
        ev_id_by_title: dict[str, str] = {}
        abstract_by_title: dict[str, str] = {}
        for art in articles:
            ev_id = store.add_evidence(
                run_id,
                art.get("title", "Untitled"),
                source=art.get("source", "engine"),
                url=art.get("url") or "",
                authors=art.get("authors") or [],
                year=art.get("year"),
                abstract=art.get("abstract") or "",
                available=True,
                conn=conn,
            )
            ev_id_by_title[art.get("title", "")] = ev_id
            abstract_by_title[art.get("title", "")] = art.get("abstract") or ""

        # 2. Hypotheses: persist in generation order; mark evolved ones. The
        # engine's stable hypothesis id is passed straight through as the store
        # row id, so identity holds end-to-end (engine -> DB -> API -> UI) and
        # matchups resolve by id rather than by fragile text-prefix matching.
        store_id_by_engine_id: dict[str, str] = {}
        for h in hyps:
            is_evolved = bool(h.get("evolution_history"))
            generation = 1 if is_evolved else 0
            agent = "evolution" if is_evolved else "generation"
            # Derive a short title from the first sentence / 120 chars.
            text = h.get("text", "")
            title = text.split(".")[0][:120] or text[:120]
            engine_id = h.get("id") or None
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
            if engine_id:
                store_id_by_engine_id[engine_id] = hyp_id

            # Update mutable state: Elo, wins, losses, scores.
            store.update_hypothesis_state(
                hyp_id,
                elo_rating=int(h.get("elo_rating", INITIAL_ELO)),
                win_delta=int(h.get("win_count", 0)),
                loss_delta=int(h.get("loss_count", 0)),
                novelty=float(h.get("score", 0) or 0) or None,
                conn=conn,
            )

            # Persist per-hypothesis reviews.
            for rv in h.get("reviews") or []:
                store.add_review(
                    run_id=run_id,
                    hypothesis_id=hyp_id,
                    reviewer_agent="review",
                    summary=rv.get("review_summary", ""),
                    critique=rv.get("constructive_feedback", ""),
                    novelty=float(rv.get("scores", {}).get("novelty", 0) or
                                  0) or None,
                    plausibility=float(
                        rv.get("scores", {}).get("scientific_soundness", 0) or
                        0) or None,
                    testability=float(
                        rv.get("scores", {}).get("testability", 0) or 0) or
                    None,
                    overall=float(rv.get("overall_score", 0) or 0) or None,
                    conn=conn,
                )

            # Persist deep-verification probes as a dedicated review row.
            probes = h.get("deep_verification_probes") or []
            if probes:
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

            # Persist citations from the hypothesis citation_map. Route each
            # through the shared classifier (the same path the mock uses) rather
            # than hardcoding a state, so the four-state citation UI reflects
            # real runs. The hypothesis grounding is the claim the citation
            # supports; it is matched against the cited paper's abstract (when
            # the source was retrieved), and a source with no resolvable URL
            # (e.g. a knowledge-graph statement) falls out as "unavailable".
            grounding = str(
                h.get("literature_grounding") or h.get("text") or "")
            for cite_key, cite_info in (h.get("citation_map") or {}).items():
                cite_title = cite_info.get("title", cite_key)
                cite_url = cite_info.get("url") or ""
                cite_ev_id = ev_id_by_title.get(cite_title)
                if cite_ev_id is None:
                    # Add evidence on the fly for this citation source.
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
                claim = f"[{cite_key}] cited in hypothesis"
                state = classify_citation(
                    CitationRecord(
                        url=cite_url,
                        abstract=abstract_by_title.get(cite_title, ""),
                        claim=grounding,
                        available=True,
                    ))
                citation_summary[state] += 1
                store.add_citation(run_id,
                                   hyp_id,
                                   cite_ev_id,
                                   claim,
                                   state,
                                   conn=conn)

        # 3. Tournament matches: resolve each side by the engine's stable
        # hypothesis id. Matchups may legitimately reference hypotheses that
        # were dropped from the final set (evolve discards lower-ranked ones),
        # so an unresolved id is expected rather than an error — log and skip.
        for m in matchups:
            a_engine_id = m.get("hypothesis_a_id")
            b_engine_id = m.get("hypothesis_b_id")
            winner_engine_id = m.get("winner_id")

            loser_engine_id = (b_engine_id if winner_engine_id == a_engine_id
                               else a_engine_id)

            winner_id = store_id_by_engine_id.get(winner_engine_id or "")
            loser_id = store_id_by_engine_id.get(loser_engine_id or "")
            if not winner_id or not loser_id:
                logger.warning(
                    "skipping matchup: unresolved hypothesis id "
                    "(winner=%s, loser=%s) — likely a hypothesis dropped "
                    "during evolution", winner_engine_id, loser_engine_id)
                continue

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

    return {
        "citation_summary": citation_summary,
        "meta_review": final_state.get("meta_review") or {},
        "research_overview": final_state.get("research_overview") or {},
    }


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
    provider = force_provider or select_provider()
    run_mode = CANONICAL_RUN_MODE
    cfg = resolved_run_config(config)

    logger.info("starting workflow run=%s provider=%s run_mode=%s", run_id,
                provider, run_mode)

    async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        seq = store.append_event(run_id, type_, payload, db_path=db_path)
        return {"seq": seq, "type": type_, "payload": payload}

    # Intake safety gate, shared by every provider. A hard block short-circuits
    # the run before any hypotheses are generated.
    intake = screen_intake(research_goal)
    async for event in apply_safety_gate(run_id, intake, _emit,
                                         db_path=db_path):
        yield event
    if intake.decision == "block":
        return

    if provider == "mock":
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
            milestone = _format_milestone(event.get("type", ""),
                                          event.get("payload", {}))
            if milestone:
                store.append_message(run_id,
                                     "system",
                                     milestone,
                                     "milestone",
                                     db_path=db_path)
            yield event
        return

    # Real engine path — bridge engine streaming events into our event log.
    try:
        from co_scientist import HypothesisGenerator  # type: ignore[import-not-found, unused-ignore]  # pylint: disable=import-outside-toplevel
    except Exception as e:  # pragma: no cover (defensive)  # pylint: disable=broad-exception-caught
        logger.error("engine import failed: %s — falling back to mock", e)
        async for event in run_mock_workflow(
                run_id=run_id,
                research_goal=research_goal,
                config=cfg,
                db_path=db_path,
                cancelled=cancelled,
                sleep_seconds=sleep_seconds,
        ):
            yield event
        return

    # Persist the running state, not just emit it. The mock path sets this; the
    # engine path previously only emitted the event, leaving the run row stuck
    # at "queued" for the entire run (misleading status pill in the UI).
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    yield await _emit("status", {"status": "running"})

    initial_opts: dict[str, Any] = {}
    setup = cfg.get("setup")
    if isinstance(setup, dict):
        focus = normalize_run_focus(setup.get("focus"))
        setup_text = setup_guidance(setup)
        initial_opts["run_focus_guidance"] = focus_guidance(focus)
        initial_opts["run_setup_guidance"] = setup_text
        initial_opts["attributes"] = clean_string_list(
            [str(value) for value in setup.get("attributes") or []])
        initial_opts["constraints"] = clean_string_list(
            [str(value) for value in setup.get("requirements") or []])
        initial_opts["criteria"] = clean_string_list(
            [str(value) for value in setup.get("criteria") or []])

    pending_steering = store.get_pending_steering(run_id, db_path=db_path)
    preference_parts: list[str] = []
    setup_text = str(initial_opts.get("run_setup_guidance") or "")
    if setup_text:
        preference_parts.append(setup_text)
    if pending_steering:
        guidance = "\n".join(f"- {m.content}" for m in pending_steering)
        preference_parts.append(f"User steering guidance:\n{guidance}")
        store.mark_steering_applied([m.id for m in pending_steering],
                                    db_path=db_path)
    if preference_parts:
        initial_opts["preferences"] = "\n\n".join(preference_parts)

    # Literature grounding defaults on but is user-controlled per run (the
    # PubMed connector toggle in the composer). The engine still degrades
    # gracefully to LLM-only if MCP is unreachable, so a down MCP never breaks
    # a run. FORCE_LITERATURE_REVIEW=0 is a hard kill switch for tests/dev
    # that must run without it, regardless of the per-run setting.
    enable_literature_review = bool(cfg.get("enable_literature_review", True))
    if os.getenv("FORCE_LITERATURE_REVIEW") == "0":
        enable_literature_review = False
    initial_opts["enable_literature_review_node"] = enable_literature_review

    # cfg went through resolved_run_config above, so every numeric key is
    # present -- index directly rather than re-inventing defaults here.
    generator = HypothesisGenerator(
        model_name=settings.model_name,
        supervisor_model_name=settings.supervisor_model_name,
        max_iterations=int(cfg["max_iterations"]),
        initial_hypotheses_count=int(cfg["initial_hypotheses_count"]),
        evolution_max_count=int(cfg["evolution_max_count"]),
        tournament_pairs=int(cfg["tournament_pairs"]),
        literature_review_papers_count=int(
            cfg["literature_review_papers_count"]),
    )

    start = time.time()
    # Accumulate the full final state across all streamed nodes.
    final_state: dict[str, Any] = {
        "hypotheses": [],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "research_overview": {},
    }
    try:
        async for node_name, state in generator.generate_hypotheses(  # pylint: disable=line-too-long
                research_goal=research_goal,
                stream=True,
                run_id=run_id,
                opts=initial_opts if initial_opts else None,
        ):
            if cancelled and cancelled.is_set():
                store.update_run_status(run_id,
                                        RunStatus.CANCELLED,
                                        db_path=db_path)
                yield await _emit("status", {"status": "cancelled"})
                return

            # Update final_state from each yielded cumulative snapshot.
            for key in ("hypotheses", "articles", "tournament_matchups",
                        "meta_review", "research_overview"):
                if state.get(key) is not None:
                    final_state[key] = state[key]

            # Normalize the engine node to the canonical mock event vocabulary
            # so every downstream consumer reads one shape (no engine.* types).
            node_type = _canonical_event_type(node_name)
            payload = _canonical_engine_payload(node_name, node_type, state)
            milestone = _format_milestone(node_type, payload)
            if milestone:
                store.append_message(run_id,
                                     "system",
                                     milestone,
                                     "milestone",
                                     db_path=db_path)
            yield await _emit(node_type, payload)

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
            emit=_emit,
            execution_time=time.time() - start,
            db_path=db_path,
            **report_inputs,
        ):
            yield event
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("engine run failed: %s", e)
        store.update_run_status(run_id,
                                RunStatus.FAILED,
                                error=str(e),
                                db_path=db_path)
        yield await _emit("status", {"status": "failed", "error": str(e)})
