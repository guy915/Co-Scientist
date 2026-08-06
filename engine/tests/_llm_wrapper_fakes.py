"""Litellm-shaped response fakes shared by the LLM-wrapper test files.

The wrapper tests (``test_llm_wrappers*.py``) all monkeypatch
``litellm.acompletion`` -- the single seam every ``co_scientist.llm`` entry
point funnels through -- with an async fake returning a litellm-shaped
response object (a ``SimpleNamespace`` tree mirroring
``response.choices[0].message.{role,content,tool_calls}``). These builders
construct those response trees and install the queued fake; no network is
touched.
"""

from types import SimpleNamespace
from typing import Any

import pytest


def make_message(
    content: str | None,
    tool_calls: list[Any] | None = None,
    role: str = "assistant",
) -> SimpleNamespace:
    """Build a litellm-shaped ``choices[0].message`` object.

    Args:
        content: The assistant message text (``None`` mirrors an empty
            completion).
        tool_calls: Optional list of tool-call namespaces; ``None`` ends the
            tool loop because the wrapper guards with
            ``and message.tool_calls``.
        role: The message role echoed back into the message history.

    Returns:
        A ``SimpleNamespace`` exposing ``role``, ``content``, and
        ``tool_calls``.
    """
    return SimpleNamespace(role=role, content=content, tool_calls=tool_calls)


def make_usage(
    prompt_tokens: int, completion_tokens: int, reasoning_tokens: int = 0
) -> SimpleNamespace:
    """Build a litellm-shaped ``response.usage`` object.

    Args:
        prompt_tokens: Prompt tokens to report.
        completion_tokens: Completion tokens to report.
        reasoning_tokens: Reasoning tokens to report under
            ``completion_tokens_details.reasoning_tokens``; 0 omits nothing
            (the field is still present, just zero).

    Returns:
        A namespace exposing ``prompt_tokens``, ``completion_tokens``, and
        ``completion_tokens_details.reasoning_tokens``.
    """
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        completion_tokens_details=SimpleNamespace(
            reasoning_tokens=reasoning_tokens
        ),
    )


def make_completion(
    message: SimpleNamespace, usage: SimpleNamespace | None = None
) -> SimpleNamespace:
    """Wrap a message in the ``choices[0].message`` envelope litellm returns.

    Args:
        message: The message namespace from :func:`make_message`.
        usage: Optional token-usage namespace from :func:`make_usage`;
            omitted (``None``) mirrors a response with no usage reported.

    Returns:
        A response namespace with a single choice carrying ``message``,
        plus ``usage`` when given.
    """
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)], usage=usage
    )


def make_tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    """Build a litellm-shaped tool-call namespace.

    Args:
        call_id: The tool-call id echoed into the message history.
        name: The function name the wrapper reads via ``tc.function.name``.
        arguments: The raw JSON argument string (kept opaque by the wrapper).

    Returns:
        A namespace exposing ``id`` and ``function.{name,arguments}``.
    """
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def patch_acompletion(
    monkeypatch: pytest.MonkeyPatch, responses: list[SimpleNamespace]
) -> dict[str, int]:
    """Patch ``litellm.acompletion`` to return queued responses in order.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        responses: Completion namespaces to return on successive calls.

    Returns:
        A mutable dict whose ``"calls"`` key counts how many times the fake ran.
    """
    state = {"calls": 0}
    queue = iter(responses)

    async def fake_acompletion(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        state["calls"] += 1
        return next(queue)

    monkeypatch.setattr(
        "co_scientist.llm.litellm.acompletion", fake_acompletion
    )
    return state


# The tool schema shared verbatim by every call_llm_with_tools test; the
# wrapper only reads it (passes it through to the fake acompletion), never
# mutates it, so sharing one instance across tests is safe.
SEARCH_TOOL: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "search"}}
]
