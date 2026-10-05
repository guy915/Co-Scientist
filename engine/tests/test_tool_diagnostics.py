from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from co_scientist.llm.tools.loop import _execute_logged_tool
from tests._llm_fake import make_tool_call


@pytest.mark.parametrize("outcome", ["returned", "failed", "cancelled"])
async def test_tool_diagnostics_preserve_outcome_without_arguments_or_output(
    caplog: pytest.LogCaptureFixture, outcome: str
) -> None:
    call = make_tool_call("call-id", "search_literature", "private request")
    calls: list[Any] = []

    async def execute(value: Any) -> dict[str, Any]:
        calls.append(value)
        if outcome == "failed":
            raise ValueError("private error")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        return {"role": "tool", "content": "private result"}

    with caplog.at_level(logging.INFO, logger="co_scientist.llm.tools.loop"):
        if outcome == "failed":
            with pytest.raises(ValueError):
                await _execute_logged_tool(call, execute)
        elif outcome == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await _execute_logged_tool(call, execute)
        else:
            assert await _execute_logged_tool(call, execute) == {
                "role": "tool",
                "content": "private result",
            }
    assert calls == [call]
    assert "name=search_literature" in caplog.text
    assert (
        f"outcome={outcome}" in caplog.text
        and "duration_seconds=" in caplog.text
    )
    assert "private" not in caplog.text
