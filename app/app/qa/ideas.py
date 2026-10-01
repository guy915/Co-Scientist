"""The idea search tool the grounded-Q&A model calls for idea bodies.

The Q&A prompt carries an index of every idea a run holds (title, Elo,
status) but none of their bodies: one idea's statement, mechanism, expected
effect and experimental context together run to thousands of characters,
and a real run has dozens of ideas, so putting them all in the prompt
crowds out the evidence, the progress and the conversation itself. This
module is the other half of that trade -- a tool the model calls with the
terms it cares about, which returns a handful of matching ideas in full.

Also holds the tool-call plumbing that ``app.qa`` dispatches to: the
declaration sent to the provider, the accumulator that reassembles
streamed tool-call fragments, and the executor.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Tool name, in the model's vocabulary.
SEARCH_IDEAS_TOOL = "search_ideas"

# Bounds on one tool result. The point of the tool is to keep the prompt
# small, so a search that returns half the run is the failure it exists to
# prevent: the model is expected to ask again with better terms rather than
# be handed the pool.
_MAX_RESULTS = 5
_DEFAULT_RESULTS = 3
_FIELD_MAX_CHARS = 1200

_WORD_RE = re.compile(r"[a-z0-9]+")

# The fields an idea's body is assembled from, in the order they read.
_BODY_FIELDS: tuple[tuple[str, str], ...] = (
    ("statement", "Statement"),
    ("mechanism", "Mechanism"),
    ("expected_effect", "Expected effect"),
    ("experimental_context", "Experimental context"),
)


def tool_declaration() -> dict[str, Any]:
    """Return the provider-facing declaration of the idea search tool."""
    return {
        "type": "function",
        "function": {
            "name": SEARCH_IDEAS_TOOL,
            "description": (
                "Look up the full text of this run's ideas by topic. The "
                "conversation carries only an index of idea titles, so call "
                "this whenever the answer needs what an idea actually says "
                "-- its statement, mechanism, expected effect or "
                "experimental context. Search with the terms of the "
                "question, or with words from an idea's title in the index."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Topic words to match against the ideas, or an "
                            "idea title from the index."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"How many ideas to return "
                            f"(1-{_MAX_RESULTS}, default {_DEFAULT_RESULTS})."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    }


def _tokenize(text: str) -> frozenset[str]:
    """Split text into lowercase word tokens, dropping short noise words."""
    return frozenset(t for t in _WORD_RE.findall(text.lower()) if len(t) > 3)


def _searchable_text(hyp: dict[str, Any]) -> str:
    """Join the idea fields a query is matched against."""
    parts = [str(hyp.get("title") or ""), str(hyp.get("category") or "")]
    parts += [str(hyp.get(field) or "") for field, _ in _BODY_FIELDS]
    return " ".join(parts)


def _score(query_tokens: frozenset[str], hyp: dict[str, Any]) -> int:
    """Score one idea against the query's terms.

    Title matches count double: a query naming an idea should return that
    idea, not whichever body happens to repeat the words most.
    """
    title_tokens = _tokenize(str(hyp.get("title") or ""))
    body_tokens = _tokenize(_searchable_text(hyp))
    return 2 * len(query_tokens & title_tokens) + len(
        query_tokens & body_tokens
    )


def _clip(text: str) -> str:
    """Bound one rendered field so a single long idea cannot fill the reply."""
    text = text.strip()
    if len(text) <= _FIELD_MAX_CHARS:
        return text
    return text[:_FIELD_MAX_CHARS].rstrip() + "…"


def _render_idea(hyp: dict[str, Any]) -> dict[str, Any]:
    """Render one idea as the tool's result entry."""
    body = {
        label: _clip(str(hyp.get(field) or ""))
        for field, label in _BODY_FIELDS
        if str(hyp.get(field) or "").strip()
    }
    return {
        "title": hyp.get("title") or "Untitled",
        "elo": hyp.get("elo_rating"),
        "status": hyp.get("status") or "active",
        "verification": hyp.get("verification_verdict"),
        "generation": hyp.get("generation"),
        **body,
    }


def _clamp_limit(raw: Any) -> int:
    """Clamp a model-supplied result limit into the allowed range."""
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RESULTS
    return max(1, min(_MAX_RESULTS, limit))


def search_ideas(
    hypotheses: list[dict[str, Any]],
    query: str,
    limit: Any = None,
) -> list[dict[str, Any]]:
    """Return the ideas best matching ``query``, in full.

    Args:
        hypotheses: The run's ideas, already ordered by Elo descending.
        query: The model's search terms.
        limit: Requested result count; clamped into range, defaulted when
            absent or unparseable.

    Returns:
        Up to ``limit`` rendered ideas. A query matching nothing falls back
        to the top-ranked ideas rather than an empty result: the model asked
        because it needs idea text, and "nothing found" for a run that has
        ideas reads to it as a run with no ideas.
    """
    count = _clamp_limit(limit)
    tokens = _tokenize(query or "")
    if tokens:
        scored = sorted(
            enumerate(hypotheses),
            key=lambda pair: (-_score(tokens, pair[1]), pair[0]),
        )
        matches = [hyp for _, hyp in scored if _score(tokens, hyp) > 0]
        if matches:
            return [_render_idea(hyp) for hyp in matches[:count]]
    return [_render_idea(hyp) for hyp in hypotheses[:count]]


def _tool_arguments(raw: str) -> dict[str, Any]:
    """Parse a tool call's JSON arguments, tolerating a malformed blob.

    A model that streams a truncated or non-JSON argument string still gets
    a search rather than an error: the raw text is a usable query on its
    own, which is better than failing the turn over punctuation.
    """
    try:
        parsed = json.loads(raw or "{}")
    except ValueError:
        return {"query": raw}
    return parsed if isinstance(parsed, dict) else {"query": str(parsed)}


def run_tool_call(
    call: dict[str, Any], hypotheses: list[dict[str, Any]]
) -> str:
    """Execute one accumulated tool call and return its JSON result.

    Args:
        call: The accumulated ``{id, name, arguments}`` tool call.
        hypotheses: The run's ideas, ordered by Elo descending.

    Returns:
        The tool result as a JSON string, ready to send back as a ``tool``
        message. An unknown tool name returns an error object rather than
        raising -- the answer continues without it.
    """
    if call.get("name") != SEARCH_IDEAS_TOOL:
        logger.warning("Q&A model called unknown tool %s", call.get("name"))
        return json.dumps({"error": f"unknown tool {call.get('name')}"})
    args = _tool_arguments(str(call.get("arguments") or ""))
    results = search_ideas(
        hypotheses, str(args.get("query") or ""), args.get("limit")
    )
    return json.dumps({"ideas": results})


def accumulate_tool_calls(
    accumulated: dict[int, dict[str, Any]], delta: Any
) -> None:
    """Merge one streamed chunk's tool-call fragments into ``accumulated``.

    Providers stream a tool call the way they stream text: the name arrives
    in one chunk and the arguments in pieces across the next several, keyed
    only by the call's index in the list. Reassembling by index is what
    turns those fragments back into a call.

    Args:
        accumulated: Calls so far, keyed by their index in the response.
        delta: The chunk's ``delta`` object.
    """
    for fragment in getattr(delta, "tool_calls", None) or []:
        index = int(getattr(fragment, "index", 0) or 0)
        call = accumulated.setdefault(
            index, {"id": None, "name": None, "arguments": ""}
        )
        if getattr(fragment, "id", None):
            call["id"] = fragment.id
        function = getattr(fragment, "function", None)
        if function is None:
            continue
        if getattr(function, "name", None):
            call["name"] = function.name
        call["arguments"] += getattr(function, "arguments", None) or ""


def assistant_tool_message(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Render the assistant turn that requested ``calls``.

    The provider requires the call it is about to be given results for to
    appear in the transcript first, in its own message.
    """
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
            }
            for call in calls
        ],
    }
