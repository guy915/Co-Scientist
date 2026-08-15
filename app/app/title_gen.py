"""Generate a short session title for a run from its research goal.

The recents surfaces show a bold title above the full goal. Deriving the title
from the goal's opening words duplicates the goal, so instead a small language
model condenses the goal into a distinct 3-6 word heading, prompted after the
Gemini Enterprise chat-naming prompt (see the comment on ``_SYSTEM_PROMPT``
for what that baseline contributes and what it does not). Generation is
best-effort: any failure returns None and callers fall back to a clause of the
goal.
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

# Sized to the answer alone, which is only safe because this call does not
# think: reasoning tokens are drawn from the same budget and are emitted
# first, so a thinking title call spends all 24 on its chain of thought and
# returns an empty completion. This ceiling and the thinking opt-out below
# are one decision -- change either and change both.
_TITLE_MAX_TOKENS = 24

# Guard against a model that ignores the brevity instruction and returns a
# paragraph; a title longer than this is discarded in favor of the fallback.
_MAX_TITLE_CHARS = 80

# Adapted from the Gemini Enterprise chat-naming prompt kept at
# references/ui-ux/gemini-enterprise/chat-naming-prompt.md. Three of its
# rules are dropped as inapplicable here: it names a chat from an evolving
# conversation, so it branches on user-only vs. full history, handles
# attached filenames, and special-cases questions about the assistant's own
# identity. This call sees one research goal, once, at run create. Its
# 30-character ceiling is dropped too -- that budget exists for a sidebar
# chip that truncates, whereas the recents row shows the full goal beneath
# the title, and a fair share of real research titles ("Ferroptosis Targets
# in Pancreatic Cancer") do not fit in 30 characters.
_SYSTEM_PROMPT = (
    "You generate the sidebar title for a research session. Given the "
    "session's research goal, reply with a short title summarizing its "
    "subject.\n"
    "\n"
    "Rules:\n"
    "- The title MUST be 3 to 6 words and MUST summarize the goal, not "
    "repeat its opening words.\n"
    "- Put the most distinctive words first: the disease, organism, "
    "molecule, method, or system the goal is about. DO NOT begin with an "
    "article or a preposition.\n"
    "- DO NOT begin with the goal's framing verb or question word, such as "
    "'Find', 'Propose', 'Develop', 'Investigate', 'How', or 'What'.\n"
    "- Use Title Case. Write the title in the same language as the goal; "
    "where the goal has typos, infer the intended wording.\n"
    "- DO NOT use colons, quotation marks, or trailing punctuation.\n"
    "- DO NOT use words like 'research', 'goal', 'study', 'session', or "
    "'title' unless they carry real meaning in the goal.\n"
    "- Reply with the title alone, as a standalone string: no preamble, no "
    "explanation, no surrounding data structure.\n"
    "\n"
    "Examples:\n"
    "\n"
    "Goal: Find drug repurposing candidates that could slow the "
    "progression of amyotrophic lateral sclerosis.\n"
    "Title: Drug Repurposing in ALS\n"
    "\n"
    "Goal: What mechanisms allow senescent cells to escape immune "
    "clearance in aged tissue?\n"
    "Title: Senescent Cell Immune Escape\n"
    "\n"
    "Goal: Propose experiments testing whether ferroptosis regulators can "
    "be targeted in pancreatic cancer.\n"
    "Title: Ferroptosis Targets in Pancreatic Cancer\n"
    "\n"
    "Goal: How does antibiotic resistance emerge in Pseudomonas "
    "aeruginosa biofilms, and how might it be disrupted?\n"
    "Title: Pseudomonas Biofilm Antibiotic Resistance\n"
    "\n"
    "Goal: Develop a computational model of tau propagation across "
    "cortical networks.\n"
    "Title: Tau Propagation Network Modeling"
)


def clean_title(raw: str) -> str | None:
    """Normalize a candidate title into a usable one, or None if unusable.

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
    blocks a run's title indefinitely; the caller catches any failure. A
    scoped bring-your-own-key credential overrides the model and the
    deployment credential.
    """
    import litellm

    from app import credentials, offline_guard

    # The goal itself is the prompt here, so titling leaks exactly what
    # forced offline exists to keep in: refuse before the call. The caller
    # already treats any failure as "no title", so the run keeps its
    # goal-clause fallback.
    offline_guard.require_remote_chat("run titling")
    model, api_key = credentials.byok_model_and_key(
        settings.effective_chat_model
    )
    return await asyncio.wait_for(
        litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": goal},
            ],
            temperature=0.3,
            max_tokens=_TITLE_MAX_TOKENS,
            extra_body=deepseek_non_thinking_extra_body(model),
            **({"api_key": api_key} if api_key else {}),
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
    return clean_title(content)
