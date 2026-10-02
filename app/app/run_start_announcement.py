"""The Agent's spoken confirmation that a research session has started.

Starting a run is the one transition in the chat that used to answer itself:
the timeline printed two fixed sentences over a card, so the reply to the
scientist's own "Start research" was the only turn in the conversation the
Agent had not written. This module makes it a turn like any other -- a real
prompt persisted on the run, a streamed reply with its chain of thought, and
the session card attached below it the way the plan card attaches to the
interview's completing turn.

The exchange is stored as two ``start``-kind message rows so a reopened chat
rebuilds it in the right order (``chat_session_qa_transcript.ts`` splits them
out of the run's Q&A rows); the run's grounded Q&A endpoint is deliberately
not reused, since at this moment the run has no hypotheses to ground an
answer in.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from app import credentials, offline_guard, store
from app.config import (
    THINKING_FLOOR_TIMEOUT_SECONDS,
    deepseek_thinking_kwargs,
    settings,
    thinking_off_kwargs,
    thinking_safe_max_tokens,
)
from app.execution_policy import (
    CAMPAIGN,
    campaign_model_for_config,
    scoped_execution_policy,
)
from app.llm_scope import budgeted_stream
from app.llm_stream import stream_chunks
from app.sse import sse_frame
from app.store.models import RunRow

logger = logging.getLogger(__name__)

# The ``kind`` both rows of one announcement carry, apart from 'qa' (a
# grounded question about the run) and 'steering' (work queued for the
# engine). The client reads it to tell the run's opening exchange from the
# questions that follow it.
START_KIND = "start"

# Two sentences, plus the headroom a thinking model spends before writing
# them (see thinking_safe_max_tokens: a budget sized for the answer alone is
# what returns an empty completion).
_ANNOUNCEMENT_MAX_TOKENS = 600
# Silence, not duration, is what marks the stream as lost; the reply is
# relayed as it is written, so a long reasoning pass is visible progress.
_STALL_SECONDS = 45.0
_TOTAL_SECONDS = THINKING_FLOOR_TIMEOUT_SECONDS + 60.0

# What the scientist reads when no model wrote the announcement: forced
# offline, no provider credential, a provider that failed, or a turn the
# scientist stopped. The run started either way, so this says exactly what
# the live reply says rather than reporting a failure the scientist can
# neither see nor act on. Two paragraphs, matching the shape a model reply
# renders in.
FALLBACK_ANNOUNCEMENT = (
    "Your session has been started and Co-Scientist has started research!"
    "\n\n"
    "You can view and interact with your session at any time, but note that "
    "it might take a few minutes for the first ideas to be ready to view."
)

_SYSTEM_PROMPT = """You are the Agent in Google Hypothesis Generation.

The scientist has just started a research session. The multi-agent system is
already exploring their goal on its own, and a card naming the session --
with every action available on it -- is shown directly beneath your reply.

Write exactly two sentences telling them so.

- The first says the session has started and that research on their goal is
  under way. Name the goal in a clause of your own words; never quote it back
  in full, and never restate the plan.
- The second says they can open the session and interact with it whenever
  they like, and that it takes a few minutes before the first ideas are ready
  to view.

Rules:
- Plain prose, and nothing else. No headings, no lists, no bold, no emoji.
- Ask no question and offer nothing further. The interview is over, and the
  card below your reply carries what happens next.
- Address the scientist directly, in the same language they wrote in.
- Two sentences, under 60 words in total."""


def _announcement_prompt(run: RunRow) -> str:
    """Render the started run as the model's user turn.

    Only what the two sentences may draw on: the goal being explored and the
    label the session carries. The plan's own fields are deliberately absent
    -- the card below the reply already shows them, and a model given them
    recites them instead of writing a confirmation.
    """
    context: dict[str, Any] = {"research_goal": run.research_goal}
    if run.title:
        context["session_title"] = run.title
    return json.dumps(context, ensure_ascii=False)


def _delta_text(chunk: Any) -> tuple[str, str]:
    """Split one stream chunk into its reasoning and prose fragments.

    DeepSeek emits a whole chain of thought as ``reasoning_content`` deltas
    before the first ``content`` delta; a provider without one simply never
    sets the field.
    """
    if not chunk.choices:
        return "", ""
    delta = chunk.choices[0].delta
    reasoning = getattr(delta, "reasoning_content", None) or ""
    return str(reasoning), str(delta.content or "")


async def _stream_model_fragments(
    run: RunRow, *, thinking_enabled: bool = True
) -> AsyncGenerator[tuple[str, str], None]:
    """Stream the announcement, yielding ``(frame type, fragment)`` pairs.

    Args:
        run: The run whose announcement is being written.
        thinking_enabled: False for the one retry a turn that reasoned and
            wrote nothing gets; see ``stream_announcement``.

    Raises:
        OfflineModeError: When this process makes no external requests, which
            is the same branch an absent or failing provider takes -- the
            caller answers all three with the deterministic announcement.
    """
    from app import llm_request

    # Refuse before the request is shaped, not after: the prompt carries the
    # scientist's research goal verbatim.
    offline_guard.require_remote_chat("the session announcement")
    model, api_key = credentials.byok_model_and_key(
        settings.effective_chat_model
    )
    thinking_kwargs = (
        deepseek_thinking_kwargs(model)
        if thinking_enabled
        else thinking_off_kwargs(model)
    )
    response = await llm_request.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _announcement_prompt(run)},
        ],
        temperature=0.7,
        max_tokens=thinking_safe_max_tokens(model, _ANNOUNCEMENT_MAX_TOKENS),
        timeout=_TOTAL_SECONDS,
        stream=True,
        **thinking_kwargs,
        api_key=api_key,
    )
    async for chunk in stream_chunks(
        response, stall_seconds=_STALL_SECONDS, total_seconds=_TOTAL_SECONDS
    ):
        reasoning, prose = _delta_text(chunk)
        if reasoning:
            yield "reasoning", reasoning
        if prose:
            yield "chunk", prose


def persist_prompt(run_id: str, prompt: str) -> store.MessageRow:
    """Persist the scientist's own start request, before anything is written.

    Persisted by the route rather than the stream, so the message survives a
    reply that never lands -- the same reason a Q&A question is written
    before its answer streams.
    """
    return store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content=prompt, kind=START_KIND
        )
    )


def _persist_announcement(
    run_id: str, text: str, reasoning: str, fallback: bool
) -> None:
    """Persist the Agent's reply, with the thinking that produced it.

    The reasoning rides in ``meta`` so a reopened chat shows the same
    disclosure the live turn did, exactly as an interview turn keeps its own.
    """
    meta: dict[str, Any] = {}
    if reasoning:
        meta["reasoning"] = reasoning
    if fallback:
        meta["fallback"] = True
    store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender="system",
            content=text,
            kind=START_KIND,
            meta=meta or None,
        )
    )


async def _relay_announcement(
    run: RunRow,
    prose: list[str],
    reasoning: list[str],
    *,
    thinking_enabled: bool = True,
) -> AsyncGenerator[str, None]:
    """Stream one attempt's fragments into ``prose``/``reasoning`` and SSE."""
    async for kind, fragment in _stream_model_fragments(
        run, thinking_enabled=thinking_enabled
    ):
        (reasoning if kind == "reasoning" else prose).append(fragment)
        yield sse_frame({"type": kind, "content": fragment})


async def _announcement_attempts(
    run: RunRow,
    byok: credentials.ByokCredential | None,
    prose: list[str],
    reasoning: list[str],
) -> AsyncGenerator[str, None]:
    """Run the model attempt(s) and yield their SSE frames.

    A second attempt, with thinking off, follows a first that ended
    normally having spent reasoning tokens and written no answer at all --
    not a provider failure, so ``stream_announcement``'s caller-visible
    fallback is reserved for when this really has nothing to show; see
    ``interviews.model._stream_interview_content`` for the same shape on
    the interview's own stream.
    """
    with (
        scoped_execution_policy(
            run.execution_policy,
            campaign_model_name=(
                campaign_model_for_config(run.config)
                if run.execution_policy == CAMPAIGN
                else None
            ),
        ),
        credentials.scoped_byok(byok),
    ):
        async for frame in _relay_announcement(run, prose, reasoning):
            yield frame
        if "".join(prose).strip() or not "".join(reasoning).strip():
            return
        logger.info(
            "session announcement for run %s reasoned and wrote nothing; "
            "retrying without thinking",
            run.id,
        )
        async for frame in _relay_announcement(
            run, prose, reasoning, thinking_enabled=False
        ):
            yield frame


@budgeted_stream("announcement")
async def stream_announcement(
    run: RunRow,
    prompt_message_id: int,
    byok: credentials.ByokCredential | None = None,
) -> AsyncGenerator[str, None]:
    """Stream the announcement as SSE frames and persist the reply.

    Emits ``reasoning`` and ``chunk`` fragments as the model writes them,
    then one terminal ``done`` frame carrying the persisted prompt's id and
    whether the deterministic announcement stood in.

    There is no ``error`` frame. The run has started by the time this runs,
    and no failure here changes that, so a provider this call cannot reach
    ends in the deterministic announcement rather than in an error the
    scientist would read as the run not having started.

    Yields:
        SSE ``data:`` frames.
    """
    prose: list[str] = []
    reasoning: list[str] = []
    try:
        async for frame in _announcement_attempts(run, byok, prose, reasoning):
            yield frame
    except Exception as exc:
        logger.info(
            "session announcement for run %s falls back: %s", run.id, exc
        )
    text = "".join(prose).strip()
    fallback = not text
    if fallback:
        text = FALLBACK_ANNOUNCEMENT
        yield sse_frame({"type": "chunk", "content": text})
    _persist_announcement(run.id, text, "".join(reasoning).strip(), fallback)
    yield sse_frame(
        {"type": "done", "prompt_id": prompt_message_id, "fallback": fallback}
    )
