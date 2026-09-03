"""Synthesize the Top Ranking Hypotheses document's own goal restatement.

R14-3: the two report documents used to render the identical raw-flattened
Research Goal Details block. Google's published Top Ranking Hypotheses
document instead opens with a freshly synthesized narrative restatement of
the goal, in different words -- this module produces that restatement, once
per run at report-build time (not per hypothesis; see the caller in
``report_build.py``).

Generation is best-effort, matching ``title_gen.py``'s contract: any
failure, timeout, or empty/degenerate answer returns None, and the caller
falls back to rendering the same raw goal both documents already show. A
report that fails to build because a cosmetic restatement failed would be
strictly worse than the duplication this replaces.

Model resolution follows the run's own persisted offline/real backend
(``store.run_offline_backed``), not the process-wide offline predicate --
the same signal ``engine_adapter.opts._resolve_generator_models`` reads for
the generator's own models. Every curated demo pins ``llm_backend:
"offline"`` explicitly, so demo re-seeding never attempts a real call; an
offline-backed run instead routes through the engine's deterministic
router, which intercepts any ``offline/``-prefixed model regardless of
caller, so this call still produces genuinely different offline output
under ``make e2e``. A real-backed run resolves a real model but is gated on
``config.has_provider_credential`` before ever calling -- the hermetic app
test suite strips every provider credential env var (see
``tests/conftest.py``), so this is what keeps a bare test-created run row
(which can read as "real-backed" without going through bootstrap) from
attempting a network call.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import credentials, store
from app.config import has_provider_credential, settings
from app.config_thinking import (
    deepseek_thinking_kwargs,
    thinking_safe_max_tokens,
    thinking_safe_timeout,
)

logger = logging.getLogger(__name__)

# Bound the generation so a slow/hung model never blocks report finalization;
# a background durable task, not a caller watching a blank screen (see
# ``config_thinking.THINKING_FLOOR_TIMEOUT_SECONDS``'s note on which call
# sites that floor is safe to apply to), so the thinking floor is fine here.
_DEFAULT_TIMEOUT_SECONDS = 30.0

# Sized for a short paragraph, not a single phrase like the title generator's
# 24 -- thinking_safe_max_tokens raises this further for a model that
# reasons, so this is only the floor for a model that does not.
_MAX_TOKENS = 400

# Guard against a model that ignores the length instruction; a restatement
# longer than this is discarded in favor of the fallback.
_MAX_RESTATEMENT_CHARS = 1200

_SYSTEM_PROMPT = (
    "You restate a research goal for the opening of a ranked-hypotheses "
    "report. Given the goal, reply with a single narrative paragraph, in "
    "your own words, that:\n"
    "- Captures the same scientific question and scope as the original "
    "goal.\n"
    "- Uses noticeably different phrasing and sentence structure -- do not "
    "reuse the goal's own wording verbatim or make only cosmetic edits.\n"
    "- Reads as scene-setting prose introducing the report, not a restated "
    "instruction or a list.\n"
    "- Is one to three sentences.\n"
    "\n"
    "Reply with the restatement alone: no preamble, no heading, no "
    "quotation marks."
)


def _restatement_messages(research_goal: str) -> list[dict[str, str]]:
    """Build the chat messages requesting a restatement of ``research_goal``."""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Research goal: {research_goal}"},
    ]


def _clean_restatement(raw: str, research_goal: str) -> str | None:
    """Normalize a candidate restatement, or None if it is unusable.

    Strips wrapping quotes and whitespace. Discards an empty result, one
    long enough to suggest the model ignored the length instruction, or one
    that (after normalizing case and whitespace) just repeats the original
    goal -- any of those defeats the point of a *distinct* restatement, and
    the caller's raw-goal fallback is strictly better than duplicating it
    under a different label.
    """
    text = " ".join(raw.strip().split())
    text = text.strip("\"'").strip()
    if not text or len(text) > _MAX_RESTATEMENT_CHARS:
        return None
    if text.strip(".!?").lower() == research_goal.strip(".!?").lower():
        return None
    return text


def _resolve_model(
    run_id: str, db_path: str | None
) -> tuple[str, str | None] | None:
    """Resolve (model, api_key) for this run's restatement call, or None to skip.

    Returns:
        The model to call and an optional BYOK key override, or None when
        no credentialed model can be reached (skip generation entirely).
    """
    # Imported here rather than at module top so the app package does not
    # hard-depend on the engine at import time.
    from co_scientist.offline_llm import DEFAULT_OFFLINE_MODEL

    if store.run_offline_backed(
        run_id, missing_run_fallback=True, db_path=db_path
    ):
        return DEFAULT_OFFLINE_MODEL, None
    model, api_key = credentials.byok_model_and_key(
        settings.effective_supervisor_model
    )
    if api_key is None and not has_provider_credential(model):
        return None
    return model, api_key


async def _request_goal_restatement(
    research_goal: str, model: str, api_key: str | None
) -> Any:
    """Call ``model`` for a goal restatement, bounded by a thinking-safe budget."""
    import litellm

    return await asyncio.wait_for(
        litellm.acompletion(
            model=model,
            messages=_restatement_messages(research_goal),
            temperature=0.5,
            max_tokens=thinking_safe_max_tokens(model, _MAX_TOKENS),
            api_key=api_key,
            **deepseek_thinking_kwargs(model),
        ),
        timeout=thinking_safe_timeout(model, _DEFAULT_TIMEOUT_SECONDS),
    )


async def synthesize_goal_restatement(
    run_id: str, research_goal: str, db_path: str | None = None
) -> str | None:
    """Return a freshly synthesized narrative restatement of the goal.

    Runs once per run, at report-build time -- not per hypothesis. Every
    failure mode (no credentialed model, timeout, provider error, an empty
    or degenerate answer) returns None rather than raising, so the caller
    always has a report to finish building: it falls back to rendering the
    same raw goal both documents already show.

    Args:
        run_id: Identifier of the run being reported on, used to resolve
            its persisted offline/real backend.
        research_goal: The run's research goal to restate.
        db_path: Optional override for the SQLite database path.

    Returns:
        A cleaned narrative restatement, or None when generation is
        unavailable or produced nothing usable.
    """
    research_goal = research_goal.strip()
    if not research_goal:
        return None
    resolved = _resolve_model(run_id, db_path)
    if resolved is None:
        return None
    model, api_key = resolved
    try:
        response = await _request_goal_restatement(
            research_goal, model, api_key
        )
    except Exception as exc:
        # Best-effort, same contract as title_gen.generate_run_title: covers
        # timeout, a missing/broken litellm, a bad model, and API errors.
        logger.warning(
            "Goal restatement synthesis failed for run %s: %s",
            run_id[:8],
            exc,
        )
        return None
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    content = choices[0].message.content or ""
    return _clean_restatement(content, research_goal)
