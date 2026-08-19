"""Building a tool transcript, and repairing one cut off mid-turn.

A tool-calling conversation has a shape the provider enforces: every
`tool_calls` entry on an assistant message must be answered by a
`tool` message carrying the same id, and every `tool` message must
answer a call that was made. Break either rule and the request is
rejected outright -- which reads, in a log, as the model having failed
rather than as the conversation having been rebuilt wrong.

The loop appends the assistant's message and *then* the results, so
anything that interrupts between the two leaves exactly that broken
shape. Nothing did, while every tool call was a bounded MCP read that
either returned or raised inside the same await. `command_session`
changes that: a command now outlives the call that started it, a poll
can be cancelled with the command still running, and a worker restart
ends every session it held. So an interrupted turn is no longer a
theoretical state, and the resumed conversation has to say what
happened to the call rather than omit it.

Building one belongs here too: what an assistant message has to carry
to be replayable is the same knowledge as what a valid pairing looks
like, and `llm_tool_loop` imports the name back so it stays patchable
where it always was.

**Synthesized, not dropped.** Removing the assistant's message instead
would be tidier and worse: the model asked for something, and a
transcript that hides the request leaves it free to ask again, forever,
with no record of why the last attempt produced nothing. An explicit
aborted result is the only version that can be reasoned about.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# What a call gets when its result never arrived. Deliberately says the
# call may have run: an aborted `run_command` can have had every effect
# it was going to have, and a model told "this did not happen" would
# repeat it.
ABORTED_RESULT = {
    "error": "aborted",
    "detail": (
        "This call was interrupted before its result was recorded. It "
        "may have run and had effects. Check the current state before "
        "repeating it."
    ),
}


def _message_to_history_dict(message: Any) -> dict[str, Any]:
    """Converts a litellm assistant message into a plain history dict.

    litellm's message object is a Pydantic model, not a plain dict; this
    converts it so it can be cached and replayed as message history, with
    tool_calls included when present.
    """
    message_dict: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }

    # DeepSeek thinking returns the chain of thought as reasoning_content, and
    # the API requires it to be echoed back on any assistant message that
    # carries tool_calls -- omitting it 400s the next iteration. Preserve it so
    # the replayed history stays valid; harmless for non-thinking models, which
    # never populate the field.
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        message_dict["reasoning_content"] = reasoning

    # Add tool calls if present
    if hasattr(message, "tool_calls") and message.tool_calls:
        message_dict["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]

    return message_dict


def _answered_ids(messages: list[dict[str, Any]]) -> set[str]:
    """Ids of calls that already have a tool-role result."""
    return {
        str(message.get("tool_call_id"))
        for message in messages
        if message.get("role") == "tool" and message.get("tool_call_id")
    }


def _requested_ids(messages: list[dict[str, Any]]) -> set[str]:
    """Ids of every call any assistant message asked for."""
    ids = set()
    for message in messages:
        for call in message.get("tool_calls") or ():
            if isinstance(call, dict) and call.get("id"):
                ids.add(str(call["id"]))
    return ids


def _aborted_for(call: dict[str, Any]) -> dict[str, Any]:
    """Builds the tool-role message a missing result is replaced by."""
    function = call.get("function") or {}
    return {
        "role": "tool",
        "tool_call_id": str(call.get("id")),
        "name": str(function.get("name") or "unknown"),
        "content": json.dumps(ABORTED_RESULT),
    }


def _with_results(
    message: dict[str, Any], answered: set[str]
) -> list[dict[str, Any]]:
    """One assistant message plus a result for each call it left open."""
    missing = [
        call
        for call in message.get("tool_calls") or ()
        if isinstance(call, dict) and str(call.get("id")) not in answered
    ]
    if not missing:
        return [message]
    logger.info(
        "Synthesizing %s aborted tool result(s) for an interrupted turn",
        len(missing),
    )
    return [message, *(_aborted_for(call) for call in missing)]


def normalize_tool_transcript(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Returns a transcript the provider will accept.

    Two repairs, both of which leave a valid conversation where an
    interrupted one would be rejected:

    * a call with no result gets an explicit aborted one, appended
      directly after the message that made it, so the pairing the
      provider checks holds positionally as well as by id;
    * a result answering no call is dropped, since it cannot be paired
      with anything and is what remains when an assistant message was
      lost rather than its results.

    Args:
        messages: The conversation as it stands, possibly cut mid-turn.

    Returns:
        A new list. The input is not modified -- it may be a cached
        value shared with another caller.
    """
    answered = _answered_ids(messages)
    requested = _requested_ids(messages)
    repaired: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "tool":
            if str(message.get("tool_call_id")) in requested:
                repaired.append(message)
            else:
                logger.info("Dropping a tool result answering no call")
            continue
        repaired.extend(_with_results(message, answered))
    return repaired
