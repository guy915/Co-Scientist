"""Tests for how web search treats a provider that refuses the key.

A provider that rejects the key is not the same event as a provider that
found nothing, but both used to leave the same trace: an empty dict and a
warning. Brave's free tier was withdrawn in Feb 2026 and the key started
answering 402 with a zero monthly allowance, which read downstream as "the
web had nothing on this" on every run. These pin the distinction, and the
fall-through to a second provider that it makes possible.

Split out of test_web_search.py, which covers normalization and provider
selection; the two halves share no state beyond the module under test.
"""

from typing import Any

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools.web import providers
from mcp_server.tools.web.providers import (
    _clear_credential_error,
    _record_credential_error,
    resolve_provider,
    search_brave,
    search_tavily,
    web_search_credential_error,
)

# The smallest Brave payload that normalizes to a non-empty result, used
# only to prove a working search clears the failure record. Field mapping
# itself is covered in test_web_search.py.
_BRAVE_PAYLOAD: dict[str, Any] = {
    "web": {"results": [{"title": "t", "url": "https://example.com/a"}]}
}


def _status_error(status: int) -> httpx.HTTPStatusError:
    """Build the error httpx raises from ``raise_for_status`` at ``status``."""
    request = httpx.Request("GET", "https://example.invalid/search")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(
        f"{status}", request=request, response=response
    )


@pytest.fixture(autouse=True)
def _clear_credential_state() -> Any:
    """Keep the module-level failure record from leaking between tests."""
    _clear_credential_error()
    yield
    _clear_credential_error()


@pytest.mark.parametrize("status", [401, 402, 403])
async def test_rejected_key_is_recorded_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """A key the provider refuses must be distinguishable from no results."""
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    stub_failure(monkeypatch, _status_error(status))

    assert await search_brave("anything", 5, 0) == {}

    recorded = web_search_credential_error()
    assert recorded is not None
    assert recorded["provider"] == "brave"
    assert recorded["status"] == status


async def test_rate_limit_is_not_a_credential_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 is a healthy key being throttled; it self-heals in seconds."""
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    stub_failure(monkeypatch, _status_error(429))

    assert await search_brave("anything", 5, 0) == {}
    assert web_search_credential_error() is None


async def test_transport_failure_is_not_a_credential_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable provider says nothing about the key."""
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    stub_failure(monkeypatch, httpx.ConnectError("no route"))

    assert await search_brave("anything", 5, 0) == {}
    assert web_search_credential_error() is None


async def test_tavily_rejection_is_recorded_under_its_own_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both providers report through the same record, named separately."""
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    stub_failure(monkeypatch, _status_error(401))

    assert await search_tavily("anything", 5, 0) == {}

    recorded = web_search_credential_error()
    assert recorded is not None and recorded["provider"] == "tavily"


async def test_a_successful_search_clears_the_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restored key must not leave the connector reading as dead."""
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    stub_failure(monkeypatch, _status_error(402))
    await search_brave("anything", 5, 0)
    assert web_search_credential_error() is not None

    stub_responses(monkeypatch, _BRAVE_PAYLOAD)
    assert await search_brave("anything", 5, 0) != {}
    assert web_search_credential_error() is None


async def test_availability_check_follows_the_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The connector probe reports usability, not mere registration."""
    from mcp_server.tools.web.web_search import check_web_search_available

    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    assert await check_web_search_available() is True

    stub_failure(monkeypatch, _status_error(402))
    await search_brave("anything", 5, 0)
    assert await check_web_search_available() is False


async def test_availability_check_is_false_without_a_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key configured is also "not usable", by the same answer."""
    from mcp_server.tools.web.web_search import check_web_search_available

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    assert await check_web_search_available() is False


# --- Falling back to the other provider ------------------------------------
#
# Two free allowances only add up if a refusal on one moves the search to the
# other. Both halves matter: a provider that is out of credit must stop being
# chosen, and a search that genuinely found nothing must NOT spend the other
# provider's quota re-asking.


@pytest.mark.parametrize("status", [432, 433])
async def test_exhausted_credits_count_as_a_rejection(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Tavily answers 432/433 when the monthly credits are gone."""
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    stub_failure(monkeypatch, _status_error(status))

    assert await search_tavily("anything", 5, 0) == {}

    recorded = web_search_credential_error()
    assert recorded is not None and recorded["status"] == status


def test_resolve_provider_skips_a_refused_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With both keys set, a refused provider stops being the choice."""
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    assert (resolved := resolve_provider()) is not None
    assert resolved[0] == "brave"

    _record_credential_error("brave", 402, "quota gone")

    assert (resolved := resolve_provider()) is not None
    assert resolved[0] == "tavily"


def test_an_explicit_provider_is_skipped_once_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WEB_SEARCH_PROVIDER names a preference, not a provider to keep using."""
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    _record_credential_error("tavily", 432, "out of credits")

    assert (resolved := resolve_provider()) is not None
    assert resolved[0] == "brave"


def test_the_preferred_provider_is_retried_when_all_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A record only clears on a success, so something must still be tried.

    Otherwise a monthly reset is invisible: every provider stays marked
    dead until the process restarts.
    """
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    _record_credential_error("brave", 402, "quota gone")
    _record_credential_error("tavily", 432, "out of credits")

    assert (resolved := resolve_provider()) is not None
    assert resolved[0] == "brave"


async def test_search_web_falls_through_to_the_second_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One search survives the moment the first provider runs out."""
    from mcp_server.tools.web.web_search import search_web

    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")

    calls: list[str] = []

    async def _brave(*_: Any) -> dict[str, Any]:
        calls.append("brave")
        _record_credential_error("brave", 402, "quota gone")
        return {}

    async def _tavily(*_: Any) -> dict[str, Any]:
        calls.append("tavily")
        return {"t1": {"title": "found"}}

    monkeypatch.setattr(providers, "search_brave", _brave)
    monkeypatch.setattr(providers, "search_tavily", _tavily)
    monkeypatch.setattr(
        providers,
        "_PROVIDERS",
        {
            "brave": (_brave, "BRAVE_API_KEY"),
            "tavily": (_tavily, "TAVILY_API_KEY"),
        },
    )

    assert await search_web("anything") == {"t1": {"title": "found"}}
    assert calls == ["brave", "tavily"]


async def test_an_empty_result_does_not_spend_the_other_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding nothing is an answer; only a refusal justifies re-asking."""
    from mcp_server.tools.web.web_search import search_web

    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")

    calls: list[str] = []

    async def _brave(*_: Any) -> dict[str, Any]:
        calls.append("brave")
        return {}

    async def _tavily(*_: Any) -> dict[str, Any]:
        calls.append("tavily")
        return {"t1": {"title": "found"}}

    monkeypatch.setattr(
        providers,
        "_PROVIDERS",
        {
            "brave": (_brave, "BRAVE_API_KEY"),
            "tavily": (_tavily, "TAVILY_API_KEY"),
        },
    )

    assert await search_web("anything") == {}
    assert calls == ["brave"]


async def test_availability_is_true_while_any_provider_is_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The connector is usable as long as one key still works."""
    from mcp_server.tools.web.web_search import check_web_search_available

    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    _record_credential_error("brave", 402, "quota gone")

    assert await check_web_search_available() is True

    _record_credential_error("tavily", 432, "out of credits")
    assert await check_web_search_available() is False
