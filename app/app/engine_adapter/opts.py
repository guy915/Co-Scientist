"""Run-config translation: engine opts, steering, and generator setup.

Folds a run's durable config (composer setup, queued user steering, the
literature-review toggle) into the engine's `opts` vocabulary, drains the
pre-run steering queue, and constructs the per-run `HypothesisGenerator`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from app import run_corpus, store
from app.config import settings
from app.execution_policy import effective_execution_model
from app.run_modes import (
    attribute_names,
    clean_string_list,
    criteria_display_strings,
    focus_guidance,
    normalize_run_focus,
    normalize_run_tier,
    setup_guidance,
)

if TYPE_CHECKING:
    from app.credentials import ByokCredential

# Opts key carrying the ids of the steering messages whose text this opts
# dict folded in. It is app bookkeeping, not engine input -- the engine
# reads opts by explicit key and never sees it. The durable executor takes
# it off the opts and acknowledges those ids inside the transaction that
# commits the checkpoint carrying the guidance, so the acknowledgement and
# the state that honors it are one write. Acknowledging at build time
# instead put minutes of provider work between the two, and a worker that
# died in that window retired a steer nothing had acted on.
CONSUMED_STEERING_IDS_OPT = "consumed_steering_ids"


def _apply_capability_opts(
    initial_opts: dict[str, Any], cfg: dict[str, Any]
) -> None:
    """Translate tier funding, connector policy and ablations into opts.

    Tool-based generation and simulation run per hypothesis; overview review
    adds calls to terminal synthesis. Only extended/ultra fund these costs.
    The flags remain requests: the engine still checks tools, offline mode
    and sandbox availability before using them. Meta-review only controls
    its periodic cadence, and the engine validates a forced strategy.
    """
    tier = normalize_run_tier(cfg.get("tier"))
    deep = tier in {"extended", "ultra"}
    strategy = cfg.get("generation_strategy")
    initial_opts.update(
        enable_literature_review_node=(
            bool(cfg.get("enable_literature_review", True))
            and os.getenv("FORCE_LITERATURE_REVIEW") != "0"
        ),
        enable_tool_calling_generation=deep,
        enable_simulation_execution=deep,
        enable_overview_review=deep,
        research_tier=tier,
        enable_meta_review=cfg.get("enable_meta_review", True) is not False,
        generation_strategy=strategy if isinstance(strategy, str) else "",
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
        # Attributes may be stored as the legacy free-prose list or the
        # R12-5 structured axis list; the engine's `attributes` state
        # field is `list[str] | None`, and several of its prompt
        # formatters comma-join the list (see `attribute_names`'s
        # docstring), so this sends bare names rather than the full
        # anchored rubric text -- which still reaches the engine,
        # bulleted, via `run_setup_guidance` above.
        "attributes": attribute_names(setup.get("attributes")),
        "constraints": _clean_list_field(setup, "requirements"),
        # Criteria may be stored as the legacy free-prose list or the
        # R12-4 name/value pair list; the engine's `criteria` state field
        # is `list[str] | None` (planning/ranking/review-gate prompt
        # text), so both shapes render down to one display string per
        # criterion here rather than the generic stringify above.
        "criteria": criteria_display_strings(setup.get("criteria")),
    }


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
    """Fold scientist-uploaded document sources into opts, when any exist."""
    private_sources = run_corpus.engine_context_sources(
        store.list_evidence(run_id, db_path=db_path),
        goal,
    )
    if private_sources:
        initial_opts["context_enrichment_sources"] = private_sources
        initial_opts["user_inputs"] = {
            "literature": [str(item["display"]) for item in private_sources]
        }


def build_engine_opts(
    cfg: dict[str, Any], run_id: str, db_path: str | None
) -> dict[str, Any]:
    """Translate a run's durable config into the engine's `opts` vocabulary.

    Folds the composer "setup" (focus/attributes/requirements/criteria), any
    queued user steering, the literature-review toggle, and the interview's
    lab constraints (K5) into one opts dict. Steering read here is reported
    under ``CONSUMED_STEERING_IDS_OPT`` for the caller to acknowledge at its
    commit; nothing is acknowledged here.
    """
    initial_opts = _setup_opts_from_cfg(cfg.get("setup"))
    # Flag queued steering as a durable high-priority task as well as folding
    # its text in: the engine's orchestrator then schedules a high-priority
    # GENERATE to incorporate it at the next safe boundary, rather than the
    # steering only appearing as initial preference text.
    pending_steering = store.get_pending_steering(run_id, db_path=db_path)
    if pending_steering:
        initial_opts["pending_steering"] = True
        initial_opts[CONSUMED_STEERING_IDS_OPT] = [
            message.id for message in pending_steering
        ]
    preferences = _steering_preferences(
        str(initial_opts.get("run_setup_guidance") or ""),
        store.list_messages(run_id, db_path=db_path),
    )
    if preferences:
        initial_opts["preferences"] = preferences
    _apply_capability_opts(initial_opts, cfg)
    # K5: thread the interview's lab constraints to the engine's
    # generation/evolution feasibility prompts; empty renders no section.
    lab_constraints = _lab_constraints_for_run(cfg, db_path)
    if lab_constraints:
        initial_opts["lab_constraints"] = lab_constraints
    goal = str((cfg.get("setup") or {}).get("goal") or "")
    _apply_private_sources(initial_opts, run_id, goal, db_path)
    return initial_opts


def _resolve_generator_models(
    offline: bool,
    campaign_model_name: str | None = None,
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
        if campaign_model_name is not None:
            return campaign_model_name, campaign_model_name, None
        return (
            effective_execution_model(settings.model_name)
            or settings.model_name,
            effective_execution_model(settings.supervisor_model_name),
            None,
        )
    # Imported here rather than at module top so the app package does not
    # hard-depend on the engine at import time; the engine is on sys.path
    # by the time a run is built.
    from co_scientist.offline.llm import DEFAULT_OFFLINE_MODEL

    return DEFAULT_OFFLINE_MODEL, DEFAULT_OFFLINE_MODEL, False


def _generator_kwargs(
    cfg: dict[str, Any],
    model_name: str,
    supervisor_model_name: str | None,
    enable_cache: bool | None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Resolved config supplies numeric keys; BYOK stays out of run state."""
    from co_scientist.generator.run_setup import GeneratorOptions

    return {
        "model_name": model_name,
        "max_iterations": int(cfg["max_iterations"]),
        "initial_hypotheses_count": int(cfg["initial_hypotheses_count"]),
        "evolution_max_count": int(cfg["evolution_max_count"]),
        "options": GeneratorOptions(
            supervisor_model_name=supervisor_model_name,
            enable_cache=enable_cache,
            budget={
                "max_llm_calls": int(cfg["max_llm_calls"]),
                "max_ideas": int(cfg["max_ideas"]),
                "max_matches_per_idea": float(cfg["max_matches_per_idea"]),
            },
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
            disable_tools=[]
            if cfg.get("enable_web_search", True)
            else ["web_search"],
            api_key=api_key,
        ),
    }


def build_generator(
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
            shadowed by the offline router) and runs the worker tier on
            the credential's model and the supervisor tier on its
            supervisor model (the worker model when none was chosen).

    Returns:
        A constructed generator instance.
    """
    model_name: str
    supervisor_model_name: str | None
    enable_cache: bool | None
    campaign_model = effective_execution_model(None)
    if campaign_model is not None and not offline:
        model_name, supervisor_model_name, enable_cache = (
            _resolve_generator_models(offline, campaign_model)
        )
        byok = None
    elif byok is not None:
        # The scientist's worker and supervisor choices (see the byok doc
        # above); the cache override stays unset and the engine forces
        # caching off itself once it sees the key (GeneratorOptions.api_key).
        model_name = byok.model
        supervisor_model_name = byok.supervisor_model or byok.model
        enable_cache = None
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


def _steering_preferences(
    setup_text: str, messages: list[store.MessageRow]
) -> str | None:
    """Keep all steering guidance after acknowledgement and across restores."""
    steering = [
        f"- {message.content}"
        for message in messages
        if message.kind == "steering"
    ]
    parts = [setup_text] if setup_text else []
    if steering:
        parts.append("User steering guidance:\n" + "\n".join(steering))
    return "\n\n".join(parts) or None
