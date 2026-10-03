"""Generate optional run titles and narrative goal restatements.

Both texts depend only on the goal and run off the create critical path.
Titles fall back to a goal clause; unavailable restatements are omitted from
the Goal Report (GOAL-RESTATEMENT-001). Each operation keeps its own call
budget while sharing provider admission, thinking limits and one retry for a
completion that spent its reasoning allowance without writing an answer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app import credentials, llm_request, offline_guard
from app.config import (
    deepseek_thinking_kwargs,
    settings,
    thinking_off_kwargs,
    thinking_safe_max_tokens,
    thinking_safe_timeout,
)
from app.llm_scope import budgeted

logger = logging.getLogger(__name__)

_MAX_TITLE_CHARS = 80
_MAX_RESTATEMENT_CHARS = 800

# Adapted from the Gemini Enterprise chat-naming prompt, captured 2026-06
# at references/ui-ux/gemini-enterprise/chat-naming-prompt.md (git history).
# Conversation-history, attachment and assistant-identity rules do not apply
# to a single goal. Its 30-character sidebar ceiling is also omitted because
# our recents show the title above the full goal.
_TITLE_PROMPT = (
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

_RESTATEMENT_PROMPT = (
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


@dataclass(frozen=True)
class _TextRequest:
    """Prompt and answer-sized limits for one goal-text operation."""

    purpose: str
    system_prompt: str
    max_tokens: int
    timeout_seconds: float
    temperature: float


_TITLE = _TextRequest("run titling", _TITLE_PROMPT, 24, 15.0, 0.3)
_RESTATEMENT = _TextRequest(
    "goal restatement", _RESTATEMENT_PROMPT, 200, 20.0, 0.4
)


def _clean_text(raw: str, max_chars: int, punctuation: str = "") -> str | None:
    text = " ".join(raw.strip().split()).strip("\"'").strip()
    if punctuation:
        text = text.rstrip(punctuation).strip()
    return text if text and len(text) <= max_chars else None


def clean_title(raw: str) -> str | None:
    """Collapse whitespace, strip quotes and punctuation, and cap length."""
    return _clean_text(raw, _MAX_TITLE_CHARS, ".!?,;:")


def clean_restatement(raw: str) -> str | None:
    """Normalize a quoted response to one paragraph, rejecting long essays."""
    return _clean_text(raw, _MAX_RESTATEMENT_CHARS)


async def _request_completion(
    goal: str, request: _TextRequest, *, thinking_enabled: bool = True
) -> Any:
    """Use the scoped credential and raise answer limits for reasoning.

    The goal is sent verbatim, so forced-offline admission precedes request
    construction. Token and timeout floors apply to both attempts; the retry
    only disables thinking, preserving the existing provider request policy.
    """
    offline_guard.require_remote_chat(request.purpose)
    model, api_key = credentials.byok_model_and_key(
        settings.effective_chat_model
    )
    thinking_kwargs = (
        deepseek_thinking_kwargs(model)
        if thinking_enabled
        else thinking_off_kwargs(model)
    )
    return await asyncio.wait_for(
        llm_request.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": goal},
            ],
            temperature=request.temperature,
            max_tokens=thinking_safe_max_tokens(model, request.max_tokens),
            **thinking_kwargs,
            api_key=api_key,
        ),
        timeout=thinking_safe_timeout(model, request.timeout_seconds),
    )


async def _generate_text(goal: str, request: _TextRequest) -> str | None:
    """Treat request failures as unavailable and retry thinking-only once."""
    goal = goal.strip()
    if not goal:
        return None
    try:
        response = await _request_completion(goal, request)
    except Exception as exc:
        logger.warning("%s generation failed: %s", request.purpose, exc)
        return None
    content = _response_content(response)
    if not content.strip() and _reasoned_with_no_answer(response):
        logger.warning(
            "%s call reasoned and wrote no answer; retrying once "
            "with thinking off",
            request.purpose,
        )
        try:
            response = await _request_completion(
                goal, request, thinking_enabled=False
            )
        except Exception as exc:
            logger.warning(
                "%s retry without thinking failed: %s", request.purpose, exc
            )
            return None
        content = _response_content(response)
    return content


@budgeted("title")
async def generate_run_title(goal: str) -> str | None:
    """Return a short title, or None to keep the goal-clause fallback."""
    content = await _generate_text(goal, _TITLE)
    return clean_title(content) if content is not None else None


@budgeted("goal_restatement")
async def generate_goal_restatement(goal: str) -> str | None:
    """Return a narrative goal restatement, or None to omit the paragraph."""
    content = await _generate_text(goal, _RESTATEMENT)
    return clean_restatement(content) if content is not None else None


def _response_content(response: Any) -> str:
    """The first choice's message text, or an empty string when absent."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    return str(choices[0].message.content or "")


def _reasoned_with_no_answer(response: Any) -> bool:
    """Read the same reasoning usage field as the engine's retry ladder."""
    usage = getattr(response, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = getattr(details, "reasoning_tokens", None) or 0
    return bool(reasoning_tokens > 0)
