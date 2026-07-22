"""Generate a short session title for a run from its research goal.

The recents surfaces show a bold title above the full goal. Deriving the title
from the goal's opening words duplicates the goal, so instead a small language
model condenses the goal into a distinct 3-6 word heading (in the spirit of how
Gemini/ChatGPT name chats). Generation is best-effort: any failure returns None
and callers fall back to a clause of the goal.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import deepseek_non_thinking_extra_body, settings

logger = logging.getLogger(__name__)

# Bound the generation so a slow/hung model never blocks a run's title
# indefinitely; on timeout the caller keeps the goal-clause fallback.
_TITLE_TIMEOUT_SECONDS = 15.0

# Guard against a model that ignores the brevity instruction and returns a
# paragraph; a title longer than this is discarded in favor of the fallback.
_MAX_TITLE_CHARS = 80

_SYSTEM_PROMPT = (
    "You name research sessions. Given a research goal, reply with a concise "
    "title of 3 to 6 words that captures its topic — like a chat title. Use "
    "Title Case. Do not restate the goal verbatim or begin with filler such "
    "as 'What', 'How', 'Find', 'Propose', or 'Develop'. Reply with the title "
    "only: no quotes, no trailing punctuation, no preamble."
)


def _clean_title(raw: str) -> str | None:
    """Normalize a model reply into a usable title, or None if unusable.

    Strips wrapping quotes, surrounding whitespace, and trailing sentence
    punctuation, then collapses internal whitespace. Returns None when the
    result is empty or implausibly long (a sign the model ignored the brevity
    instruction), so the caller falls back to the goal clause.
    """
    title = " ".join(raw.strip().split())
    title = title.strip("\"'").strip()
    title = title.rstrip(".!?,;:").strip()
    if not title or len(title) > _MAX_TITLE_CHARS:
        return None
    return title


async def _request_title_completion(goal: str) -> Any:
    """Call the chat model for a title completion.

    Bounded by :data:`_TITLE_TIMEOUT_SECONDS` so a slow/hung model never
    blocks a run's title indefinitely; the caller catches any failure.
    """
    import litellm

    return await asyncio.wait_for(
        litellm.acompletion(
            model=settings.effective_chat_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": goal},
            ],
            temperature=0.3,
            max_tokens=24,
            extra_body=deepseek_non_thinking_extra_body(
                settings.effective_chat_model
            ),
        ),
        timeout=_TITLE_TIMEOUT_SECONDS,
    )


async def generate_run_title(goal: str) -> str | None:
    """Return a short session title for ``goal``, or None on any failure.

    Best-effort: a missing/broken litellm, an unset/invalid model, a timeout,
    or an unusable reply all yield None so the caller keeps the goal-clause
    fallback rather than surfacing an error.

    Args:
        goal: The run's research goal.

    Returns:
        A cleaned 3-6 word title, or None when generation is unavailable.
    """
    goal = goal.strip()
    if not goal:
        return None
    try:
        response = await _request_title_completion(goal)
    except Exception as exc:
        # Titling is optional (covers timeout, missing/broken litellm, bad
        # model, API errors); log and fall back rather than failing the run.
        logger.warning("Run title generation failed: %s", exc)
        return None
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    content = choices[0].message.content or ""
    return _clean_title(content)
