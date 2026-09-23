"""Reference-server campaign restrictions apply at each registered call."""

from typing import Any

import pytest
from mcp_server.tool_logging import with_call_logging


@pytest.mark.parametrize(
    "name", ["search_web", "query_drug_info", "read_url", "new_tool"]
)
async def test_campaign_rejects_unqualified_registered_calls(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    reached = []

    async def tool() -> dict[str, Any]:
        reached.append(name)
        return {}

    wrapped = with_call_logging(tool, name)
    # Cover a tool registered before campaign mode was enabled.
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        await wrapped()
    assert reached == []


def test_campaign_rejects_sync_registered_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tool() -> str:
        raise AssertionError("unqualified sync tool ran")

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        with_call_logging(tool, "unqualified")()


async def test_campaign_retains_public_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def tool() -> str:
        return "public evidence"

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    assert await with_call_logging(tool, "search_pubmed")() == "public evidence"
