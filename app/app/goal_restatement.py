"""Generate a narrative restatement of a run's research goal.

GOAL-RESTATEMENT-001: Google's published run renders the goal two ways across
its two report surfaces -- the research overview inlines the raw structured
goal, while the top-ranking-hypotheses document opens with a freshly
synthesized narrative restatement in *different words*. Our single combined
report keeps the raw "Research Goal Details" block and adds this restatement
at the head of its top-hypotheses section, so one document carries both forms.

The restatement is a function of the goal alone (it names no hypothesis or
finding), so it is generated once, early, off the create critical path -- the
structural twin of ``title_gen`` -- and stored on the run
(``runs.goal_restatement``) for the report to read at finalize. Generation is
best-effort: any failure returns None and the report simply omits the
paragraph, exactly as an offline or keyless run does.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import (
    deepseek_thinking_kwargs,
    settings,
    thinking_off_kwargs,
    thinking_safe_max_tokens,
    thinking_safe_timeout,
)

# Generic litellm-response readers, shared rather than duplicated: neither is
# title-specific (each reads one completion), and the reasoning-only detection
# must match title_gen's exactly. Cross-module private import is the idiom
# this package already uses for re-exported helpers.
from app.title_gen import _reasoned_with_no_answer, _response_content

logger = logging.getLogger(__name__)

# A paragraph, not a title, so the answer itself is larger; thinking_safe_max_
# tokens lifts the call's actual budget to the reasoning floor for a model
# that thinks, the same way titling does.
_RESTATEMENT_MAX_TOKENS = 200

# Bound the generation so a slow/hung model never blocks the run's restatement
# indefinitely; on timeout the caller keeps None and the report omits it.
# thinking_safe_timeout lifts it to the reasoning floor for a thinking model.
_RESTATEMENT_TIMEOUT_SECONDS = 20.0

# Guard against a model that ignores the brevity instruction and returns an
# essay; a restatement longer than this is discarded in favor of None.
_MAX_RESTATEMENT_CHARS = 800

_SYSTEM_PROMPT = (
    "You restate a scientific research goal for the top of a research "
    "report. Given the goal, reply with a fresh narrative restatement of "
    "it.\n"
    "\n"
    "Rules:\n"
    "- Write 1 to 3 sentences of plain prose, one paragraph, describing "
    "what the research seeks to discover or explain.\n"
    "- Restate the goal in DIFFERENT words -- do not repeat its phrasing or "
    "echo its opening clause.\n"
    "- Write in the third person about the research itself; do not address "
    "the reader, and do not refer to yourself, the report, or 'the goal'.\n"
    "- Do NOT add any heading, label, preamble, bullet, or quotation "
    "marks; reply with the paragraph alone.\n"
    "- Write in the same language as the goal; where the goal has typos, "
    "infer the intended wording.\n"
    "\n"
    "Example:\n"
    "\n"
    "Goal: Find drug repurposing candidates that could slow the "
    "progression of amyotrophic lateral sclerosis.\n"
    "Restatement: This investigation seeks existing, already-approved "
    "drugs that might be redirected to decelerate the neurodegeneration "
    "characteristic of ALS, identifying candidates whose known mechanisms "
    "plausibly intersect the disease's progression."
)


def clean_restatement(raw: str) -> str | None:
    """Normalize a candidate restatement into one usable paragraph, or None.

    Collapses all internal whitespace (including newlines) to single spaces so
    the result renders as one paragraph, strips wrapping quotes, and returns
    None when the result is empty or implausibly long (a sign the model wrote
    an essay), so the caller omits the paragraph rather than surfacing it.
    """
    restatement = " ".join(raw.strip().split())
    restatement = restatement.strip("\"'").strip()
    if not restatement or len(restatement) > _MAX_RESTATEMENT_CHARS:
        return None
    return restatement


async def _request_restatement_completion(
    goal: str, *, thinking_enabled: bool = True
) -> Any:
    """Call the chat model for a goal-restatement completion.

    Bounded by :data:`_RESTATEMENT_TIMEOUT_SECONDS`; the caller catches any
    failure. A scoped bring-your-own-key credential overrides the model and
    the deployment credential.

    Args:
        goal: The run's research goal, sent as the user turn.
        thinking_enabled: False for the one retry a thinking-only response
            gets (see ``generate_goal_restatement``).
    """
    import litellm

    from app import credentials, offline_guard

    # The goal itself is the prompt, so this leaks exactly what forced offline
    # exists to keep in: refuse before the call. The caller treats any failure
    # as "no restatement", so the report simply omits the paragraph.
    offline_guard.require_remote_chat("goal restatement")
    model, api_key = credentials.byok_model_and_key(
        settings.effective_chat_model
    )
    thinking_kwargs = (
        deepseek_thinking_kwargs(model)
        if thinking_enabled
        else thinking_off_kwargs(model)
    )
    return await asyncio.wait_for(
        litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": goal},
            ],
            temperature=0.4,
            max_tokens=thinking_safe_max_tokens(
                model, _RESTATEMENT_MAX_TOKENS
            ),
            **thinking_kwargs,
            api_key=api_key,
        ),
        timeout=thinking_safe_timeout(model, _RESTATEMENT_TIMEOUT_SECONDS),
    )


async def generate_goal_restatement(goal: str) -> str | None:
    """Return a narrative restatement of ``goal``, or None on any failure.

    Best-effort: a missing/broken litellm, an unset/invalid model, a timeout,
    a forced-offline run, or an unusable reply all yield None so the report
    omits the paragraph rather than surfacing an error.

    Args:
        goal: The run's research goal.

    Returns:
        A cleaned one-paragraph restatement, or None when unavailable.
    """
    goal = goal.strip()
    if not goal:
        return None
    try:
        response = await _request_restatement_completion(goal)
    except Exception as exc:
        # Optional (covers timeout, missing/broken litellm, bad model, forced
        # offline, API errors); log and omit rather than failing the run.
        logger.warning("Goal restatement generation failed: %s", exc)
        return None
    content = _response_content(response)
    if not content.strip() and _reasoned_with_no_answer(response):
        # Spent its budget reasoning and wrote nothing -- not a provider
        # failure, so one retry with thinking off, exactly as titling is
        # retried; see title_gen.generate_run_title.
        logger.warning(
            "Goal restatement call reasoned and wrote no answer; retrying "
            "once with thinking off"
        )
        try:
            response = await _request_restatement_completion(
                goal, thinking_enabled=False
            )
        except Exception as exc:
            logger.warning(
                "Goal restatement retry without thinking failed: %s", exc
            )
            return None
        content = _response_content(response)
    return clean_restatement(content)
