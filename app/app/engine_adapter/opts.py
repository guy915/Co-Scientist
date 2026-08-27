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
from app.run_modes import (
    clean_string_list,
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
    pending_steering: list[store.MessageRow],
) -> str | None:
    """Return the queued-steering preference text, acknowledging nothing.

    Returns None when there is nothing pending. Acknowledgement is
    deliberately not done here: see ``CONSUMED_STEERING_IDS_OPT``.
    """
    if not pending_steering:
        return None
    guidance = "\n".join(f"- {m.content}" for m in pending_steering)
    return f"User steering guidance:\n{guidance}"


def _fold_steering_preferences(
    setup_text: str,
    pending_steering: list[store.MessageRow],
) -> str | None:
    """Fold setup guidance and queued user steering into one "preferences" opt.

    Returns None when there is nothing to fold.
    """
    preference_parts: list[str] = []
    _append_if(preference_parts, setup_text)
    _append_if(preference_parts, _steering_preference_part(pending_steering))
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


# Tiers whose compute envelope funds the agentic draft path. Tool-calling
# generation spends one LLM round-trip per tool call and carries every
# prior tool result into the next prompt, so a single hypothesis costs
# roughly nine calls on prompts that grow past 12k tokens -- and it runs
# per hypothesis, per cycle. On express and standard that one technique
# outweighed every other phase combined, which is not a trade those tiers
# are offering: they promise a fast, cheap answer. The deep tiers are
# where a scientist has already asked for depth over turnaround.
_TOOL_CALLING_GENERATION_TIERS: frozenset[str] = frozenset(
    {"extended", "ultra"}
)


def _resolve_tool_calling_generation_toggle(cfg: dict[str, Any]) -> bool:
    """Decide whether this run funds the agentic literature-draft path.

    Args:
        cfg: The run's resolved config; ``resolved_run_config`` guarantees
            a normalized ``tier``.

    Returns:
        True only for the deep tiers. The engine treats this as an
        explicit request and still refuses it where the literature tools
        or MCP are unavailable, so a True here is a ceiling, not a
        guarantee.
    """
    return normalize_run_tier(cfg.get("tier")) in (
        _TOOL_CALLING_GENERATION_TIERS
    )


# Tiers whose compute envelope funds an executed simulation review. The
# same reasoning as the agentic draft path above, and the same answer: a
# tool loop runs per hypothesis, so its cost is a product with the pool
# size rather than a fixed addition, and express and standard promise a
# fast cheap answer instead of depth.

# Two things make the per-hypothesis figure a floor rather than the
# cost. A turn that comes back answerless is retried at a raised budget
# and then with thinking off, so one turn can be up to three completions
# (`llm_json_escalation.BudgetEscalation`). And the maturity scheduler
# keys on the full review alone, so a hypothesis whose *full* review
# fails re-issues its simulation review -- tool loop included -- on
# every later iteration.
_SIMULATION_EXECUTION_TIERS: frozenset[str] = frozenset({"extended", "ultra"})


def _resolve_simulation_execution_toggle(cfg: dict[str, Any]) -> bool:
    """Decide whether this run's simulation review may execute code.

    Args:
        cfg: The run's resolved config; ``resolved_run_config`` guarantees
            a normalized ``tier``.

    Returns:
        True only for the deep tiers. A ceiling, not a guarantee: the
        engine refuses it for the offline backend, and the review itself
        falls back to mental simulation on a host with no sandbox.
    """
    return normalize_run_tier(cfg.get("tier")) in _SIMULATION_EXECUTION_TIERS


# Tiers whose compute envelope funds an accuracy review of the terminal
# research overview. The same reasoning as the executed simulation review
# above: extra LLM calls on top of a call every run already pays for, so
# the deep tiers only.
_OVERVIEW_REVIEW_TIERS: frozenset[str] = frozenset({"extended", "ultra"})


def _resolve_overview_review_toggle(cfg: dict[str, Any]) -> bool:
    """Decide whether this run's research overview is accuracy-reviewed.

    Args:
        cfg: The run's resolved config; ``resolved_run_config`` guarantees
            a normalized ``tier``.

    Returns:
        True only for the deep tiers. A ceiling, not a guarantee: the
        engine refuses it for the offline backend.
    """
    return normalize_run_tier(cfg.get("tier")) in _OVERVIEW_REVIEW_TIERS


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


def _apply_capability_opts(
    initial_opts: dict[str, Any], cfg: dict[str, Any]
) -> None:
    """Set the five opts that decide how much depth a run may buy.

    Four are resolved to a yes or no here, because the engine treats
    each as a request it may still refuse. The fifth is the tier itself,
    passed verbatim: which tiers fund the literature review's
    deep-research phase is stated once, in the engine's
    ``research_adapter``, and a second copy of that list on this side is
    how the two drift apart.
    """
    initial_opts["enable_literature_review_node"] = (
        _resolve_literature_review_toggle(cfg)
    )
    initial_opts["enable_tool_calling_generation"] = (
        _resolve_tool_calling_generation_toggle(cfg)
    )
    initial_opts["enable_simulation_execution"] = (
        _resolve_simulation_execution_toggle(cfg)
    )
    initial_opts["enable_overview_review"] = _resolve_overview_review_toggle(
        cfg
    )
    initial_opts["research_tier"] = normalize_run_tier(cfg.get("tier"))


def _build_engine_opts(
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
    preferences = _fold_steering_preferences(
        str(initial_opts.get("run_setup_guidance") or ""),
        pending_steering,
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
            disable_tools=_resolve_disabled_tools(cfg),
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
