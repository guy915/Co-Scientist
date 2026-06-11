"""Engine adapter — chooses real engine or mock workflow at runtime.

Logic:
- Provider = `mock` if `COSCIENTIST_FORCE_MOCK=1`, OR no LLM key is set, OR the
  `open_coscientist` package can't be imported. Otherwise `engine`.
- Real-engine path imports lazily so the app boots even when the engine isn't
  installed yet (e.g. during initial setup).

The `mock` provider is the only one we exercise in CI / tests.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from typing import Any

from . import store
from .mock_workflow import resolved_config, run_mock_workflow

# Editable-install .pth files aren't always processed in Python 3.12 venvs.
# Inject the sibling engine src into sys.path at import time so that
# `from open_coscientist import HypothesisGenerator` in main.py succeeds.
_engine_src = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ai-coscientist-engine", "src")
)
if os.path.isdir(_engine_src) and _engine_src not in sys.path:
    sys.path.insert(0, _engine_src)

logger = logging.getLogger(__name__)


def _has_provider_key() -> bool:
    return any(
        bool(os.getenv(k))
        for k in (
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AZURE_API_KEY",
            "DEEPSEEK_API_KEY",
        )
    )


def _engine_importable() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("open_coscientist") is not None
    except Exception:
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
        "model_name": os.getenv("MODEL_NAME", "gemini/gemini-2.5-flash"),
        "mcp_server_url": os.getenv("MCP_SERVER_URL", ""),
    }


def _format_milestone(node_type: str, payload: dict[str, Any]) -> str | None:
    """Return a human-readable milestone string for key node events, or None."""
    if node_type in ("supervisor", "supervisor.plan"):
        return "Research plan ready — supervisor complete"
    if node_type == "generate":
        count = payload.get("count") or payload.get("hypothesis_count", 0)
        itr = payload.get("iteration", 0)
        label = f"iteration {itr}" if itr else "initial"
        return f"{count} hypotheses generated ({label})"
    if node_type == "ranking":
        count = payload.get("hypothesis_count") or payload.get("matches_count", 0)
        itr = payload.get("iteration", 0)
        return f"Tournament complete (iteration {itr}, {count} matches)"
    if node_type == "meta_review":
        return "Meta-review complete"
    if node_type == "evolve":
        count = payload.get("count") or payload.get("hypothesis_count", 0)
        itr = payload.get("iteration", 0)
        return f"{count} hypotheses evolved (iteration {itr})"
    return None


async def run_workflow(
    run_id: str,
    research_goal: str,
    profile: str,
    config: dict[str, Any],
    *,
    db_path: str | None = None,
    cancelled: asyncio.Event | None = None,
    sleep_seconds: float = 0.05,
    force_provider: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the chosen workflow and yield events as the store records them."""
    provider = force_provider or select_provider()
    cfg = resolved_config(profile, config)

    logger.info("starting workflow run=%s provider=%s profile=%s", run_id, provider, profile)

    if provider == "mock":
        pre_run_steering = store.get_pending_steering(run_id, db_path=db_path)
        if pre_run_steering:
            store.mark_steering_applied([m.id for m in pre_run_steering], db_path=db_path)

        async for event in run_mock_workflow(
            run_id=run_id,
            research_goal=research_goal,
            profile=profile,
            config=cfg,
            db_path=db_path,
            cancelled=cancelled,
            sleep_seconds=sleep_seconds,
        ):
            milestone = _format_milestone(event.get("type", ""), event.get("payload", {}))
            if milestone:
                store.append_message(run_id, "system", milestone, "milestone", db_path=db_path)
            yield event
        return

    # Real engine path — bridge engine streaming events into our event log.
    try:
        from open_coscientist import HypothesisGenerator  # type: ignore[import-untyped]
    except Exception as e:  # pragma: no cover (defensive)
        logger.error("engine import failed: %s — falling back to mock", e)
        async for event in run_mock_workflow(
            run_id=run_id,
            research_goal=research_goal,
            profile=profile,
            config=cfg,
            db_path=db_path,
            cancelled=cancelled,
            sleep_seconds=sleep_seconds,
        ):
            yield event
        return

    # DeepSeek doesn't support response_format=json_schema. Two patches are needed:
    # 1. acompletion: downgrade json_schema → json_object and inject schema as prompt text.
    # 2. validate_json_schema: fill in default values for any fields DeepSeek still omits,
    #    so schema validation doesn't abort the run over missing nested keys like
    #    performance_assessment.agent_performance.reflection_agent.
    model_name_env = os.getenv("MODEL_NAME", "gemini/gemini-2.5-flash")
    if "deepseek" in model_name_env.lower():
        try:
            import json as _json

            import litellm as _litellm  # type: ignore[import-untyped]
            import open_coscientist.llm as _oc_llm  # type: ignore[import-untyped]

            # --- patch 1: acompletion ---
            _orig_acompletion = _litellm.acompletion

            async def _patched_acompletion(**kwargs: Any) -> Any:
                rf = kwargs.get("response_format")
                if isinstance(rf, dict) and rf.get("type") == "json_schema":
                    schema_def = rf.get("json_schema", {})
                    actual_schema = schema_def.get("schema", schema_def)
                    schema_str = _json.dumps(actual_schema, indent=2)
                    messages = kwargs.get("messages") or []
                    new_messages = [dict(m) for m in messages]
                    for i in range(len(new_messages) - 1, -1, -1):
                        if new_messages[i].get("role") == "user":
                            new_messages[i] = dict(new_messages[i])
                            new_messages[i]["content"] = (
                                str(new_messages[i].get("content", ""))
                                + "\n\n---\nRESPOND WITH VALID JSON ONLY. "
                                "Your output MUST strictly match this JSON schema "
                                "(all required fields must be present):\n"
                                + schema_str
                            )
                            break
                    kwargs = dict(kwargs)
                    kwargs["messages"] = new_messages
                    kwargs["response_format"] = {"type": "json_object"}
                return await _orig_acompletion(**kwargs)

            _litellm.acompletion = _patched_acompletion

            # --- patch 2: validate_json_schema — fill defaults before validation ---
            _orig_validate = _oc_llm.validate_json_schema

            def _fill_schema_defaults(obj: Any, schema: dict[str, Any]) -> None:
                """Recursively fill missing required fields with empty defaults."""
                if not isinstance(obj, dict) or not isinstance(schema, dict):
                    return
                props = schema.get("properties", {})
                for field in schema.get("required", []):
                    if field not in obj and field in props:
                        fs = props[field]
                        t = fs.get("type")
                        if t == "string":
                            obj[field] = fs.get("enum", [""])[0] if "enum" in fs else ""
                        elif t == "object":
                            obj[field] = {}
                        elif t == "array":
                            obj[field] = []
                        elif t in ("integer", "number"):
                            obj[field] = 0
                        else:
                            obj[field] = ""
                for key, val in obj.items():
                    if key in props:
                        _fill_schema_defaults(val, props[key])

            def _patched_validate(result: Any, json_schema: Any) -> None:  # type: ignore[misc]
                if json_schema is not None and isinstance(result, dict):
                    actual = json_schema.get("schema", json_schema)
                    _fill_schema_defaults(result, actual)
                _orig_validate(result, json_schema)

            _oc_llm.validate_json_schema = _patched_validate  # type: ignore[assignment]

        except Exception as _patch_err:
            logger.warning("could not patch litellm/validate for deepseek compat: %s", _patch_err)

    async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        seq = store.append_event(run_id, type_, payload, db_path=db_path)
        return {"seq": seq, "type": type_, "payload": payload}

    yield await _emit("status", {"status": "running"})

    pending_steering = store.get_pending_steering(run_id, db_path=db_path)
    initial_opts: dict[str, Any] = {}
    if pending_steering:
        guidance = "\n".join(f"- {m.content}" for m in pending_steering)
        initial_opts["preferences"] = f"User steering guidance:\n{guidance}"
        store.mark_steering_applied([m.id for m in pending_steering], db_path=db_path)

    generator = HypothesisGenerator(
        model_name=os.getenv("MODEL_NAME", "gemini/gemini-2.5-flash"),
        max_iterations=int(cfg.get("max_iterations", 1)),
        initial_hypotheses_count=int(cfg.get("initial_hypotheses_count", 5)),
        evolution_max_count=int(cfg.get("evolution_max_count", 2)),
    )

    start = time.time()
    # Accumulate the full final state across all streamed nodes.
    final_state: dict[str, Any] = {
        "hypotheses": [],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
    }
    try:
        async for node_name, state in generator.generate_hypotheses(  # type: ignore[union-attr]
            research_goal=research_goal,
            stream=True,
            run_id=run_id,
            opts=initial_opts if initial_opts else None,
        ):
            if cancelled and cancelled.is_set():
                store.update_run_status(run_id, "cancelled", db_path=db_path)
                yield await _emit("status", {"status": "cancelled"})
                return

            # Update final_state from each yielded cumulative snapshot.
            for key in ("hypotheses", "articles", "tournament_matchups", "meta_review", "evolution_details"):
                if state.get(key) is not None:
                    final_state[key] = state[key]

            payload = {
                "node": node_name,
                "iteration": state.get("current_iteration", 0),
                "hypothesis_count": len(state.get("hypotheses") or []),
                "matches_count": len(state.get("tournament_matchups") or []),
                "articles_count": len(state.get("articles") or []),
            }
            milestone = _format_milestone(node_name, payload)
            if milestone:
                store.append_message(run_id, "system", milestone, "milestone", db_path=db_path)
            yield await _emit(f"engine.{node_name}", payload)

        # ---- Drain final state into the store ----
        hyps: list[dict[str, Any]] = final_state["hypotheses"] or []
        articles: list[dict[str, Any]] = final_state["articles"] or []
        matchups: list[dict[str, Any]] = final_state["tournament_matchups"] or []

        # 1. Evidence: persist retrieved articles.
        ev_id_by_title: dict[str, str] = {}
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
                db_path=db_path,
            )
            ev_id_by_title[art.get("title", "")] = ev_id

        # 2. Hypotheses: persist in generation order; mark evolved ones.
        hyp_id_by_text: dict[str, str] = {}
        for h in hyps:
            is_evolved = bool(h.get("evolution_history"))
            generation = 1 if is_evolved else 0
            agent = "evolution" if is_evolved else "generation"
            # Derive a short title from the first sentence / 120 chars.
            text = h.get("text", "")
            title = text.split(".")[0][:120] or text[:120]
            hyp_id = store.add_hypothesis(
                run_id=run_id,
                title=title,
                statement=text,
                mechanism=h.get("literature_grounding") or "",
                expected_effect=h.get("explanation") or "",
                experimental_context=h.get("experiment") or "",
                generation=generation,
                created_by_agent=agent,
                db_path=db_path,
            )
            hyp_id_by_text[text[:200]] = hyp_id         # exact 200-char truncation
            hyp_id_by_text[text[:200] + "..."] = hyp_id  # engine appends "..." when truncated
            hyp_id_by_text[text] = hyp_id

            # Update mutable state: Elo, wins, losses, scores.
            store.update_hypothesis_state(
                hyp_id,
                elo_rating=int(h.get("elo_rating", 1200)),
                win_delta=int(h.get("win_count", 0)),
                loss_delta=int(h.get("loss_count", 0)),
                novelty=float(h.get("score", 0) or 0) or None,
                db_path=db_path,
            )

            # Persist per-hypothesis reviews.
            for rv in h.get("reviews") or []:
                store.add_review(
                    run_id=run_id,
                    hypothesis_id=hyp_id,
                    reviewer_agent="review",
                    summary=rv.get("review_summary", ""),
                    critique=rv.get("constructive_feedback", ""),
                    novelty=float(rv.get("scores", {}).get("novelty", 0) or 0) or None,
                    plausibility=float(rv.get("scores", {}).get("scientific_soundness", 0) or 0) or None,
                    testability=float(rv.get("scores", {}).get("testability", 0) or 0) or None,
                    overall=float(rv.get("overall_score", 0) or 0) or None,
                    db_path=db_path,
                )

            # Persist citations from the hypothesis citation_map.
            for cite_key, cite_info in (h.get("citation_map") or {}).items():
                cite_title = cite_info.get("title", cite_key)
                ev_id = ev_id_by_title.get(cite_title)
                if ev_id is None:
                    # Add evidence on the fly for this citation source.
                    ev_id = store.add_evidence(
                        run_id,
                        cite_title,
                        source=cite_info.get("type", "engine"),
                        url=cite_info.get("url") or "",
                        authors=cite_info.get("authors") or [],
                        year=cite_info.get("year"),
                        abstract="",
                        available=True,
                        db_path=db_path,
                    )
                    ev_id_by_title[cite_title] = ev_id
                claim = f"[{cite_key}] cited in hypothesis"
                store.add_citation(run_id, hyp_id, ev_id, claim, "verified", db_path=db_path)

        # 3. Tournament matches: match by hypothesis text prefix (engine truncates at 200).
        for m in matchups:
            h_a_text = m.get("hypothesis_a", "")
            h_b_text = m.get("hypothesis_b", "")
            winner_label = m.get("winner", "a")

            winner_text = h_a_text if winner_label == "a" else h_b_text
            loser_text = h_b_text if winner_label == "a" else h_a_text

            winner_id = hyp_id_by_text.get(winner_text)
            loser_id = hyp_id_by_text.get(loser_text)
            if not winner_id or not loser_id:
                continue  # can't match — skip rather than persist bad data

            store.add_match(
                run_id=run_id,
                iteration=0,
                winner_id=winner_id,
                loser_id=loser_id,
                winner_before=int(m.get("winner_elo_before", 1200)),
                winner_after=int(m.get("winner_elo_after", 1200)),
                loser_before=int(m.get("loser_elo_before", 1200)),
                loser_after=int(m.get("loser_elo_after", 1200)),
                rationale=m.get("reasoning", ""),
                db_path=db_path,
            )

        # 4. Build and persist the report.
        sorted_hyps = sorted(hyps, key=lambda h: -int(h.get("elo_rating", 1200)))
        leaderboard = [
            {
                "rank": idx + 1,
                "title": h.get("text", "")[:120],
                "elo": h.get("elo_rating", 1200),
                "wins": h.get("win_count", 0),
                "losses": h.get("loss_count", 0),
            }
            for idx, h in enumerate(sorted_hyps[:10])
        ]
        report_payload = {
            "research_goal": research_goal,
            "profile": profile,
            "provider": "engine",
            "execution_time": time.time() - start,
            "hypothesis_count": len(hyps),
            "evidence_count": len(articles),
            "match_count": len(matchups),
            "leaderboard": leaderboard,
            "meta_review": final_state.get("meta_review") or {},
        }
        md_lines = [
            f"# Co-Scientist Run — {research_goal}",
            f"\n**Profile:** {profile} | **Provider:** engine | **Hypotheses:** {len(hyps)}",
            "\n## Top hypotheses by Elo\n",
        ]
        for entry in leaderboard:
            md_lines.append(f"{entry['rank']}. **{entry['title']}** — Elo {entry['elo']}")
        meta = final_state.get("meta_review") or {}
        if meta and isinstance(meta, dict):
            md_lines.append("\n## Meta-review insights\n")

            if meta.get("summary"):
                md_lines.append(f"{meta['summary']}\n")

            for section_key, heading in (
                ("common_strengths", "### Common strengths"),
                ("common_weaknesses", "### Common weaknesses"),
                ("emerging_themes", "### Emerging themes"),
                ("areas_for_improvement", "### Areas for improvement"),
            ):
                items = meta.get(section_key) or []
                if items:
                    md_lines.append(f"\n{heading}\n")
                    for item in items:
                        md_lines.append(f"- {item}")

            recs = meta.get("strategic_recommendations") or []
            if recs:
                md_lines.append("\n### Strategic recommendations\n")
                for rec in recs:
                    if isinstance(rec, dict):
                        area = rec.get("focus_area", "")
                        recommendation = rec.get("recommendation", "")
                        justification = rec.get("justification", "")
                        md_lines.append(f"**{area}**: {recommendation}")
                        if justification:
                            md_lines.append(f"  *{justification}*")
                    else:
                        md_lines.append(f"- {rec}")
        markdown = "\n".join(md_lines)

        store.save_report(run_id, report_payload, markdown, db_path=db_path)
        yield await _emit("report", report_payload)
        store.update_run_status(run_id, "completed", db_path=db_path)
        yield await _emit("status", {"status": "completed"})
    except Exception as e:
        logger.exception("engine run failed: %s", e)
        store.update_run_status(run_id, "failed", error=str(e), db_path=db_path)
        yield await _emit("status", {"status": "failed", "error": str(e)})
