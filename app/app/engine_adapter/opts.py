"""Run-config translation: engine opts, steering, and generator setup.

Folds a run's durable config (composer setup, queued user steering, the
literature-review toggle) into the engine's `opts` vocabulary, drains the
pre-run steering queue, and constructs the per-run `HypothesisGenerator`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from app import paper_corpus, run_corpus, store
from app.config import settings
from app.run_modes import (
    clean_string_list,
    focus_guidance,
    normalize_run_focus,
    setup_guidance,
)

if TYPE_CHECKING:
    from app.credentials import ByokCredential


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
    db_path: str | None,
    setup_text: str,
    pending_steering: list[store.MessageRow],
) -> str | None:
    """Fold setup guidance and queued user steering into one "preferences" opt.

    Steering consumed here is marked applied so a later iteration does not
    replay the same message. Returns None when there is nothing to fold.
    """
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


def _lab_constraints_for_run(
    cfg: dict[str, Any], db_path: str | None
) -> list[str]:
    """Resolve the interview-elicited lab constraints for a run (K5).

    Runs created from a goal interview carry its id in the run config; the
    interview's ``lab_constraints`` field is the scientist's statement of
    what their laboratory can do, and it threads to the engine's
    generation/evolution feasibility prompts. Resolved here -- at the opts
    boundary -- because the interview merge into the create request only
    maps the goal/requirements/attributes fields, and this field must not
    depend on that path.

    Args:
        cfg: The run's resolved config (``interview_id`` when it came from
            an interview).
        db_path: Optional database override.

    Returns:
        The cleaned lab-constraint strings, empty when the run has no
        interview, the interview is gone, or no constraints were declared.
        An empty result leaves the engine prompts exactly as they were.
    """
    interview_id = cfg.get("interview_id")
    if not interview_id:
        return []
    interview = store.get_interview(str(interview_id), db_path=db_path)
    if interview is None:
        return []
    raw = interview["fields"].get("lab_constraints") or []
    return clean_string_list([str(value) for value in raw])


def _apply_private_sources(
    initial_opts: dict[str, Any], run_id: str, goal: str, db_path: str | None
) -> None:
    """Fold scientist-uploaded document sources into opts, when any exist.

    The group's own papers no longer ride the literature channel as
    retrieved passages: the whole catalog (title + abstract of every paper)
    is injected into the run's setup context up front (see
    runs_models._build_create_run_config), and the agent fetches any paper
    in full with fetch_paper. Only scientist-uploaded documents land here.
    """
    private_sources = run_corpus.engine_context_sources(
        store.list_evidence(run_id, db_path=db_path),
        goal,
    )
    if private_sources:
        initial_opts["context_enrichment_sources"] = private_sources
        initial_opts["user_inputs"] = {
            "literature": [str(item["display"]) for item in private_sources]
        }


def _build_engine_opts(
    cfg: dict[str, Any], run_id: str, db_path: str | None
) -> dict[str, Any]:
    """Translate a run's durable config into the engine's `opts` vocabulary.

    Folds the composer "setup" (focus/attributes/requirements/criteria), any
    queued user steering, the literature-review toggle, and the interview's
    lab constraints (K5) into one opts dict. Steering consumed here is marked
    applied so a later iteration does not replay the same message.
    """
    initial_opts = _setup_opts_from_cfg(cfg.get("setup"))
    # Flag queued steering as a durable high-priority task BEFORE folding it
    # (folding marks it applied): the engine's orchestrator then schedules a
    # high-priority GENERATE to incorporate it at the next safe boundary,
    # rather than the steering only appearing as initial preference text.
    pending_steering = store.get_pending_steering(run_id, db_path=db_path)
    if pending_steering:
        initial_opts["pending_steering"] = True
    preferences = _fold_steering_preferences(
        db_path,
        str(initial_opts.get("run_setup_guidance") or ""),
        pending_steering,
    )
    if preferences:
        initial_opts["preferences"] = preferences
    initial_opts["enable_literature_review_node"] = (
        _resolve_literature_review_toggle(cfg)
    )
    # K5: thread the interview's lab constraints to the engine's
    # generation/evolution feasibility prompts; empty renders no section.
    lab_constraints = _lab_constraints_for_run(cfg, db_path)
    if lab_constraints:
        initial_opts["lab_constraints"] = lab_constraints
    goal = str((cfg.get("setup") or {}).get("goal") or "")
    _apply_private_sources(initial_opts, run_id, goal, db_path)
    return initial_opts


def _resolve_disabled_tools(cfg: dict[str, Any]) -> list[str]:
    """Map the run's connector toggles onto engine tool ids to disable.

    Only ``web_search`` is disabled when the web-search connector is off.
    ``read_url`` is deliberately left enabled: it is the generic
    content-fetch tool, used as the ``content_tool`` for PDF and full-text
    retrieval in the arXiv, Google Scholar, and web configs, so disabling it
    here would break literature retrieval for unrelated sources.

    Args:
        cfg: Resolved run config; ``resolved_run_config`` guarantees the
            toggle keys are present.

    Returns:
        Engine tool ids to disable for this run, empty when nothing is off.
    """
    disabled: list[str] = []
    if not cfg.get("enable_web_search", True):
        disabled.append("web_search")
    return disabled


def _resolve_generator_models(
    offline: bool,
) -> tuple[str, str | None, bool | None]:
    """Return (model_name, supervisor_model_name, enable_cache) for a run.

    When `offline`, both models are pinned to ``DEFAULT_OFFLINE_MODEL`` and
    caching is disabled for this generator's own calls (scoped to its own
    execution -- see ``co_scientist.cache.scoped_cache_override`` -- so it
    never disables caching for a concurrently-running real run in the same
    embedded worker). This is a minor optimization, not a correctness
    requirement: the router is already deterministic, and a cached
    ``offline/``-prefixed entry could never be served to (or collide with) a
    real-model call, since the cache key includes the model name.
    """
    if not offline:
        return settings.model_name, settings.supervisor_model_name, None
    # Imported here rather than at module top so the app package does not
    # hard-depend on the engine at import time; the engine is on sys.path
    # by the time a run is built.
    from co_scientist.offline_llm import DEFAULT_OFFLINE_MODEL

    return DEFAULT_OFFLINE_MODEL, DEFAULT_OFFLINE_MODEL, False


def _resolve_generator_disable_tools(cfg: dict[str, Any]) -> list[str]:
    """Return combined engine tool ids to disable for one run's generator.

    Two sources of per-run tool withholding, combined. (1) The group's
    paper corpus is one lab's library; the tools YAML enables it
    unconditionally, so withhold it here for every other audience --
    otherwise any run could search another lab's papers directly, which no
    audience gate on injected context would catch. (2) The run's connector
    toggles, applied by the engine's ToolRegistry as `tool.enabled = False`.
    """
    return [
        *paper_corpus.disabled_tools_for(
            str(cfg.get("audience") or ""),
            enabled=cfg.get("enable_paper_corpus", True) is not False,
        ),
        *_resolve_disabled_tools(cfg),
    ]


def _generator_kwargs(
    cfg: dict[str, Any],
    model_name: str,
    supervisor_model_name: str | None,
    enable_cache: bool | None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Build the `HypothesisGenerator` constructor kwargs for one run.

    `cfg` went through `resolved_run_config` upstream, so every numeric key
    is present -- index directly rather than re-inventing defaults here.
    The four run-size knobs stay top-level; every other engine knob is
    grouped into the engine's ``GeneratorOptions`` bundle. ``api_key`` is
    a bring-your-own-key credential (see ``GeneratorOptions.api_key``):
    it rides the options bundle into the generator instance and is never
    part of the run config or the workflow state.
    """
    from co_scientist import GeneratorOptions

    return {
        "model_name": model_name,
        "max_iterations": int(cfg["max_iterations"]),
        "initial_hypotheses_count": int(cfg["initial_hypotheses_count"]),
        "evolution_max_count": int(cfg["evolution_max_count"]),
        "options": GeneratorOptions(
            supervisor_model_name=supervisor_model_name,
            enable_cache=enable_cache,
            # Hard termination ceiling on top of max_iterations. Present
            # even for runs created before the knob existed:
            # resolved_run_config seeds every load from the tier table.
            budget={"max_llm_calls": int(cfg["max_llm_calls"])},
            tournament_pairs=int(cfg["tournament_pairs"]),
            elo_k_factor=int(cfg["k_factor"]),
            # ``evidence_count`` is the single literature-budget knob in the
            # tier table; map it to the engine's parameter name at this
            # translation boundary rather than persisting a second synced
            # key.
            literature_review_papers_count=int(cfg["evidence_count"]),
            # Forward the configured tools YAML so a real run actually
            # enables the domain tools (e.g. INDRA for the production
            # indra_cancer.yaml). None loads the engine's bundled default
            # registry, whose literature_review workflow is multi-source
            # (the group's paper corpus, PubMed, and OpenAlex) -- not
            # PubMed-only. Startup already validated this path is readable
            # (see app.main lifespan).
            tools_config=settings.tools_config,
            disable_tools=_resolve_generator_disable_tools(cfg),
            api_key=api_key,
        ),
    }


def _build_generator(
    generator_cls: Any,
    cfg: dict[str, Any],
    *,
    offline: bool = False,
    byok: ByokCredential | None = None,
) -> Any:
    """Construct a fresh `HypothesisGenerator` from the run's resolved config.

    A fresh generator is constructed per run rather than reused, so each
    run's model/tier settings apply independently of any other run.

    Args:
        generator_cls: The engine's ``HypothesisGenerator`` class.
        cfg: The run's resolved config.
        offline: When True the run is backed by the deterministic offline
            router; see ``_resolve_generator_models`` for what that pins.
        byok: The run's bring-your-own-key credential, when it has one.
            Forces the real backend (a validated user key must never be
            shadowed by the offline router) and runs EVERY tier -- worker
            and supervisor alike -- on the credential's model, since the
            deployment cannot know what else the key may call.

    Returns:
        A constructed generator instance.
    """
    if byok is not None:
        # One model for every tier (see the byok doc above); the cache
        # override stays unset and the engine forces caching off itself
        # once it sees the key (GeneratorOptions.api_key).
        model_name: str = byok.model
        supervisor_model_name: str | None = byok.model
        enable_cache: bool | None = None
    else:
        model_name, supervisor_model_name, enable_cache = (
            _resolve_generator_models(offline)
        )
    return generator_cls(
        **_generator_kwargs(
            cfg,
            model_name,
            supervisor_model_name,
            enable_cache,
            api_key=byok.api_key if byok else None,
        )
    )
