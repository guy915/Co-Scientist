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
like.

**Synthesized, not dropped.** Removing the assistant's message instead
would be tidier and worse: the model asked for something, and a
transcript that hides the request leaves it free to ask again, forever,
with no record of why the last attempt produced nothing. An explicit
aborted result is the only version that can be reasoned about.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from co_scientist.workspace.tool_schemas import WRITE_FILE

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


# What a superseded write's arguments are replaced by. Names the path so
# the model can still see *that* it wrote the file and go read it, and
# says why the text is gone, so an absence reads as bookkeeping rather
# than as the write having failed.
_SUPERSEDED_NOTE = (
    "superseded by a later write to this path; the file on disk holds the"
    " current text, read it if you need it"
)


def _written_path(call: dict[str, Any]) -> str | None:
    """The path a tool call writes whole, or None if it writes nothing.

    Only ``write_file`` qualifies. A patch is an edit *relative to* the
    file it lands on, so an earlier one is not superseded by a later one
    in any sense a reader could rely on -- and patches are small.

    Args:
        call: One entry from an assistant message's ``tool_calls``.

    Returns:
        The path, or None when this call is not a whole-file write or
        its arguments cannot be read.
    """
    function = call.get("function") or {}
    if function.get("name") != WRITE_FILE:
        return None
    try:
        arguments = json.loads(function.get("arguments") or "{}")
    except (TypeError, ValueError):
        return None
    path = arguments.get("path")
    return path if isinstance(path, str) else None


def elide_superseded_writes(messages: list[dict[str, Any]]) -> int:
    """Drops the text of every file write a later write overwrote.

    A tool loop re-sends its whole transcript every turn, so a program
    the model rewrote five times is five full copies of that program in
    every subsequent request -- and four of them describe a file that no
    longer exists in that form. Measured on one simulation that rewrote
    its model five times: 59% of the transcript was superseded program
    text, and dropping it cut the loop's total prompt spend by 37%,
    a fraction that grows with the turn count because each dead copy is
    re-sent by every turn after it.

    Only the *arguments* of the write go; the call keeps its id and name
    and its paired tool result is untouched, because the provider
    rejects a transcript whose calls and results do not pair up. What
    the model loses is text it can read back off disk, which is why this
    is bookkeeping rather than a loss of context.

    Args:
        messages: The running conversation, mutated in place.

    Returns:
        How many writes were elided, for the caller to log.
    """
    latest: dict[str, dict[str, Any]] = {}
    elided = 0
    for message in messages:
        for call in message.get("tool_calls") or ():
            path = _written_path(call)
            if path is None:
                continue
            previous = latest.get(path)
            if previous is not None:
                previous["arguments"] = json.dumps(
                    {"path": path, "note": _SUPERSEDED_NOTE}
                )
                elided += 1
            latest[path] = call["function"]
    return elided


# The fields a paper record is identified by, in preference order. Every
# search tool on this host stamps at least one of them.
_PAPER_ID_FIELDS = ("source_id", "pmid", "doi", "nct_id", "url")

# The heavy fields that make a record worth eliding at all. A record
# carrying none of them is already small, and is left alone -- which is
# what keeps this off the entity lookups, whose whole payload is the
# answer.
_PAPER_BODY_FIELDS = ("abstract", "abstractText", "content", "fulltext")

# What survives elision: enough to cite the record and to judge the
# citation, and nothing else. Author lists are the expensive half of
# what remains once the abstract is gone -- ~200 characters against a
# ~120-character title -- and a draft cites a paper by id.
_ELIDED_MARKER = "elided"
_KEPT_FIELDS = (
    *_PAPER_ID_FIELDS,
    "title",
    "year",
    "journal",
    "is_preprint",
    _ELIDED_MARKER,
)

# What an elided record says about itself. One note, for both reasons a
# record loses its text, because the model can act on them identically:
# it had this record, the text is not in front of it now, and the way
# back is the id. Deliberately *not* "scroll back for it" -- true of a
# duplicate whose original is still in the transcript, and false the
# moment that original ages out in turn.
_ELIDED_NOTE = "full text elided; re-fetch by id if you need it"

# Tools whose whole result is a document the model read once and can ask
# for again. Their payload is one string rather than records, so there is
# nothing inside it worth keeping: the call that produced it stays in the
# transcript, and that is what names the page or the paper.
_REFETCHABLE_TEXT_TOOLS = ("read_url",)

_ELIDED_TEXT = json.dumps(
    "Elided: you read this in full earlier in this conversation. Call the"
    " same tool again with the same arguments if you need it back."
)

# Searches whose results the transcript carries whole. A record has to
# arrive in full -- a gap is judged from an abstract, not from a title
# -- and it has to stay long enough for the model to act on it. Beyond
# that it has been read and either used or passed over, while every
# later turn goes on paying for it.
RECENT_SEARCH_TURNS = 2


def _paper_identity(record: dict[str, Any]) -> str | None:
    """Returns the stable id a paper record carries, or None."""
    for field in _PAPER_ID_FIELDS:
        value = record.get(field)
        if isinstance(value, str) and value:
            return f"{field}:{value}"
    return None


def _has_body(record: dict[str, Any]) -> bool:
    """Whether this record still carries text worth re-sending.

    Load-bearing beyond the obvious. An elided record has no body field
    left at all, so it reads as nothing to elide -- which is what stops
    the duplicate pass from treating an already-elided copy as the
    original and eliding the live copy against it, leaving a transcript
    that holds the paper nowhere and says so nowhere either.
    """
    return any(record.get(field) for field in _PAPER_BODY_FIELDS)


def _elide_record(record: dict[str, Any]) -> int:
    """Cuts one record down to what a citation needs, in place."""
    for key in [key for key in record if key not in _KEPT_FIELDS]:
        del record[key]
    record[_ELIDED_MARKER] = _ELIDED_NOTE
    return 1


def _walk_papers(node: Any, visit: Callable[[dict[str, Any]], int]) -> int:
    """Applies ``visit`` to every paper record anywhere under ``node``.

    Shape-agnostic on purpose: PubMed returns a dict keyed by id, the
    other sources return a ``records`` list, and a future tool will
    return a third thing. Recognising a paper by its own fields rather
    than by the envelope around it means a new source is covered the day
    it is added instead of the day someone remembers this function.
    """
    if isinstance(node, list):
        return sum(_walk_papers(item, visit) for item in node)
    if not isinstance(node, dict):
        return 0
    if _paper_identity(node) is not None and _has_body(node):
        return visit(node)
    return sum(_walk_papers(value, visit) for value in node.values())


def _rewrite_tool_result(
    message: dict[str, Any], transform: Callable[[Any], int]
) -> int:
    """Applies ``transform`` to one tool result's payload, in place."""
    if message.get("role") != "tool":
        return 0
    content = message.get("content")
    if not isinstance(content, str) or not content.startswith(("{", "[")):
        return 0
    try:
        payload = json.loads(content)
    except ValueError:
        return 0
    changed = transform(payload)
    if changed:
        message["content"] = json.dumps(payload)
    return changed


def elide_repeated_papers(messages: list[dict[str, Any]]) -> int:
    """Drops the text of every paper an earlier search already returned.

    A drafting loop searches the literature eight or nine times against
    one goal, and the searches overlap heavily: measured on a live pass,
    94 records came back carrying 61 distinct papers, so **35% were
    abstracts the transcript already held**. Each repeat is ~2.1k
    characters, and the loop re-sends its whole transcript every turn,
    so a duplicate arriving on turn two is paid for by every turn after
    It mattered here more than anywhere else: before anything was
    elided, literature results were 96% of this loop's transcript.

    Runs *after* ``elide_aged_papers`` (see ``_has_body``): an elided
    record is no longer a copy of anything, so a paper found again long
    after its first sighting keeps its new copy instead of being elided
    against a stub of the old one.

    Args:
        messages: The running conversation, mutated in place.

    Returns:
        How many repeated records were elided, for the caller to log.
    """
    seen: set[str] = set()

    def visit(record: dict[str, Any]) -> int:
        identity = str(_paper_identity(record))
        if identity in seen:
            return _elide_record(record)
        seen.add(identity)
        return 0

    return sum(
        _rewrite_tool_result(
            message, lambda payload: _walk_papers(payload, visit)
        )
        for message in messages
    )


def _aged_before(messages: list[dict[str, Any]], turns: int) -> int:
    """Index where the most recent ``turns`` search turns begin.

    Args:
        messages: The running conversation.
        turns: How many recent assistant turns to leave whole.

    Returns:
        The exclusive end of the aged region, or 0 while the
        conversation is still shorter than the window.
    """
    assistants = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "assistant"
    ]
    if len(assistants) < turns:
        return 0
    return assistants[-turns]


def _elide_text_result(message: dict[str, Any]) -> int:
    """Drops the text of one aged document result, in place.

    Kept separate from the record walk because these results have no
    structure to preserve -- a fetched page is one string, and what makes
    it findable again is the call above it, not a field inside it.
    """
    if message.get("name") not in _REFETCHABLE_TEXT_TOOLS:
        return 0
    content = message.get("content")
    if not isinstance(content, str) or content == _ELIDED_TEXT:
        return 0
    message["content"] = _ELIDED_TEXT
    return 1


def _elide_aged_message(message: dict[str, Any]) -> int:
    """Elides every kind of aged evidence in one tool result."""
    if message.get("role") != "tool":
        return 0
    return _rewrite_tool_result(
        message, lambda payload: _walk_papers(payload, _elide_record)
    ) + _elide_text_result(message)


def elide_aged_evidence(
    messages: list[dict[str, Any]], turns: int = RECENT_SEARCH_TURNS
) -> int:
    """Drops the text of evidence the model finished with turns ago.

    Deduplicating repeats bounds how often one paper is carried; it does
    not bound how many distinct papers pile up. Every search adds ~10
    records of ~2.1k characters that the transcript then re-sends on
    every later turn, so a loop's total prompt spend grows with the
    *square* of the searches it runs. That is what ended the drafting
    loop: measured over three research goals, all three stopped on the
    token ceiling at seven to eleven of thirteen turns, with per-turn
    spend climbing monotonically to 45k, 61k and 72k tokens. Ageing
    flattens that curve, and the same three goals then run to their turn
    budget at 296k-363k total.

    Elision is not truncation. Evidence arrives whole and stays whole
    while the model decides what to do with it; only afterwards is it
    cut to what a draft cites it by, or -- for a page or a paper fetched
    whole -- to the call that can fetch it again.

    Args:
        messages: The running conversation, mutated in place.
        turns: How many of the most recent assistant turns keep their
            results whole.

    Returns:
        How many results were elided, for the caller to log.
    """
    cutoff = _aged_before(messages, turns)
    return sum(_elide_aged_message(message) for message in messages[:cutoff])
