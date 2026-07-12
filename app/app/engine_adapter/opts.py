"""Run-config translation: engine opts, steering, and generator setup.

Folds a run's durable config (composer setup, queued user steering, the
literature-review toggle) into the engine's `opts` vocabulary, drains the
pre-run steering queue, and constructs the per-run `HypothesisGenerator`.
"""

from __future__ import annotations

import os
from typing import Any

from app import run_corpus, store
from app.config import settings
from app.run_modes import (
    clean_string_list,
    focus_guidance,
    normalize_run_focus,
    setup_guidance,
)


def _drain_pre_run_steering(run_id: str, db_path: str | None) -> None:
    """Mark any steering queued before the run started as applied.

    Drains steering queued before the run started (e.g. via the composer) so
    it is not left "pending" and re-applied later inside run_mock_workflow's
    own per-iteration steering check.
    """
    pre_run_steering = store.get_pending_steering(run_id, db_path=db_path)
    if pre_run_steering:
        store.mark_steering_applied(
            [m.id for m in pre_run_steering], db_path=db_path
        )


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
    db_path: str | None, pending_steering: list[store.MessageRow]
) -> str | None:
    """Return the queued-steering preference text, marking it applied.

    Returns None (and leaves the queue untouched) when there is nothing
    pending.
    """
    if not pending_steering:
        return None
    guidance = "\n".join(f"- {m.content}" for m in pending_steering)
    store.mark_steering_applied(
        [m.id for m in pending_steering], db_path=db_path
    )
    return f"User steering guidance:\n{guidance}"


def _fold_steering_preferences(
    run_id: str, db_path: str | None, setup_text: str
) -> str | None:
    """Fold setup guidance and queued user steering into one "preferences" opt.

    Steering consumed here is marked applied so a later iteration does not
    replay the same message. Returns None when there is nothing to fold.
    """
    pending_steering = store.get_pending_steering(run_id, db_path=db_path)
    preference_parts: list[str] = []
    _append_if(preference_parts, setup_text)
    _append_if(
        preference_parts, _steering_preference_part(db_path, pending_steering)
    )
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


def _build_engine_opts(
    cfg: dict[str, Any], run_id: str, db_path: str | None
) -> dict[str, Any]:
    """Translate a run's durable config into the engine's `opts` vocabulary.

    Folds the composer "setup" (focus/attributes/requirements/criteria), any
    queued user steering, and the literature-review toggle into one opts
    dict. Steering consumed here is marked applied so a later iteration does
    not replay the same message.
    """
    initial_opts = _setup_opts_from_cfg(cfg.get("setup"))
    # Flag queued steering as a durable high-priority task BEFORE folding it
    # (folding marks it applied): the engine's orchestrator then schedules a
    # high-priority GENERATE to incorporate it at the next safe boundary,
    # rather than the steering only appearing as initial preference text.
    if store.get_pending_steering(run_id, db_path=db_path):
        initial_opts["pending_steering"] = True
    preferences = _fold_steering_preferences(
        run_id, db_path, str(initial_opts.get("run_setup_guidance") or "")
    )
    if preferences:
        initial_opts["preferences"] = preferences
    initial_opts["enable_literature_review_node"] = (
        _resolve_literature_review_toggle(cfg)
    )
    private_sources = run_corpus.engine_context_sources(
        store.list_evidence(run_id, db_path=db_path),
        str((cfg.get("setup") or {}).get("goal") or ""),
    )
    if private_sources:
        initial_opts["context_enrichment_sources"] = private_sources
        initial_opts["user_inputs"] = {
            "literature": [str(item["display"]) for item in private_sources]
        }
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
        # Forward the configured tools YAML so a real run actually enables the
        # domain tools (e.g. INDRA for the production indra_cancer.yaml). None
        # leaves the engine on its default PubMed-only tools. Startup already
        # validated this path is readable (see app.main lifespan).
        tools_config=settings.tools_config,
    )
