"""Tests for the INDRA CoGex shared client helpers and cross-tool contract.

Every INDRA CoGex tool is built on the helpers in
``mcp_server.tools.indra_cogex.client``: ``parse_id``/``maybe_parse_agent``
normalize identifiers, ``indra_post`` makes the one HTTP call every tool
issues, and ``run_indra_tool`` is what turns any failure -- a bad
identifier, a validation error, a network fault -- into the
``{"error", "query"}`` shape every tool promises its caller. This module
pins those helpers directly, then exercises the promise through all eight
real tool entrypoints under a simulated transport failure, since the
promise is only as good as its weakest caller.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import pytest
from mcp_server.tools.indra_cogex.associations import (
    query_gene_codependents,
    query_gene_disease_network,
)
from mcp_server.tools.indra_cogex.client import (
    INDRA_BASE_URL,
    cap_results,
    indra_post,
    maybe_parse_agent,
    parse_id,
    run_indra_tool,
    tool_error,
)
from mcp_server.tools.indra_cogex.drug_clinical import (
    query_clinical_trials,
    query_drug_info,
)
from mcp_server.tools.indra_cogex.enrichment import run_enrichment_analysis
from mcp_server.tools.indra_cogex.pathways import (
    query_causal_subnetwork,
    query_pathways,
)
from mcp_server.tools.indra_cogex.statements import (
    query_mechanistic_statements,
)


class _StubResponse:
    """A canned httpx.Response standing in for a real CoGex reply."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        """Represent a 2xx response: never raises."""

    def json(self) -> Any:
        """Return the fixture payload."""
        return self._payload


class _StubClient:
    """A canned httpx.AsyncClient returning one response or raising once."""

    def __init__(
        self,
        response: _StubResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[str, Any]] = []

    async def __aenter__(self) -> "_StubClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def post(self, url: str, json: Any = None) -> _StubResponse:
        """Record the call, then return the stub response or raise."""
        self.calls.append((url, json))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


# --- parse_id / maybe_parse_agent -------------------------------------


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("HGNC:6407", ["HGNC", "6407"]),
        ("MESH:D002289", ["MESH", "D002289"]),
        # A second colon belongs to the id portion, not a new field.
        ("CHEBI:CHEBI:27690", ["CHEBI", "CHEBI:27690"]),
    ],
)
def test_parse_id_splits_on_first_colon(
    identifier: str, expected: list[str]
) -> None:
    assert parse_id(identifier) == expected


@pytest.mark.parametrize(
    "identifier", ["no-colon-here", ":missing-namespace", "missing-id:"]
)
def test_parse_id_rejects_malformed_identifiers(identifier: str) -> None:
    with pytest.raises(ValueError, match="invalid identifier"):
        parse_id(identifier)


def test_maybe_parse_agent_parses_a_curie() -> None:
    assert maybe_parse_agent("HGNC:6407") == ["HGNC", "6407"]


def test_maybe_parse_agent_keeps_a_plain_name() -> None:
    assert maybe_parse_agent("KRAS") == "KRAS"


def test_maybe_parse_agent_does_not_parse_urls() -> None:
    url = "http://example.com/a:b"
    assert maybe_parse_agent(url) == url


def test_maybe_parse_agent_falls_back_on_unparseable_curie() -> None:
    # No namespace before the colon, so parse_id would raise; the agent
    # helper is more permissive and returns the original string instead.
    assert maybe_parse_agent(":no-namespace") == ":no-namespace"


# --- tool_error / cap_results -------------------------------------------


def test_tool_error_carries_message_and_query() -> None:
    assert tool_error("boom", {"q": 1}) == {"error": "boom", "query": {"q": 1}}


def test_cap_results_truncates_and_reports_the_original_total() -> None:
    capped, total = cap_results([1, 2, 3, 4], 2)
    assert capped == [1, 2]
    assert total == 4


def test_cap_results_passes_non_lists_through_unchanged() -> None:
    # Some CoGex endpoints return an error dict instead of a list; capping
    # that would be wrong, so it is returned as-is with a zero total. The
    # declared return type is list[Any], since that's the typical case;
    # cast documents that this call deliberately exercises the fallback.
    passthrough, total = cap_results({"error": "bad"}, 2)
    assert cast(Any, passthrough) == {"error": "bad"}
    assert total == 0


# --- indra_post -----------------------------------------------------------


async def test_indra_post_returns_parsed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _StubClient(response=_StubResponse({"ok": True}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)

    result = await indra_post("/api/x", {"a": 1})

    assert result == {"ok": True}
    assert client.calls == [(f"{INDRA_BASE_URL}/api/x", {"a": 1})]


async def test_indra_post_does_not_catch_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # indra_post itself is a raising function; catching is run_indra_tool's
    # job, one layer up. If indra_post started swallowing errors too, every
    # caller would double-handle them.
    client = _StubClient(error=httpx.ConnectError("boom"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)

    with pytest.raises(httpx.ConnectError):
        await indra_post("/api/x", {"a": 1})


# --- run_indra_tool ---------------------------------------------------


async def test_run_indra_tool_returns_the_body_result_on_success() -> None:
    async def body() -> dict[str, Any]:
        return {"ok": True}

    result = await run_indra_tool(
        logging.getLogger("test"), "my_tool", {"q": 1}, body()
    )
    assert result == {"ok": True}


async def test_run_indra_tool_converts_a_raised_exception_to_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def body() -> dict[str, Any]:
        raise ValueError("boom")

    with caplog.at_level(logging.ERROR):
        result = await run_indra_tool(
            logging.getLogger("mcp_server.tools.indra_cogex.test"),
            "my_tool",
            {"q": 1},
            body(),
        )

    assert result == {"error": "boom", "query": {"q": 1}}
    assert "my_tool failed: boom" in caplog.text


# --- cross-tool degrade contract ---------------------------------------

# One minimal, valid call per real tool entrypoint, exercised end to end
# (not just against the shared helper in isolation) so a tool that stopped
# routing through run_indra_tool -- the exact way the four enum branches
# once drifted -- would be caught here even if its own family's test file
# only exercised its happier paths.
_ALL_TOOLS: dict[
    str, tuple[Callable[..., Awaitable[dict[str, Any]]], dict[str, Any]]
] = {
    "gene_disease_network": (
        query_gene_disease_network,
        {"identifier": "HGNC:6407", "entity_type": "gene"},
    ),
    "gene_codependents": (
        query_gene_codependents,
        {"gene_id": "HGNC:6407"},
    ),
    "drug_info": (
        query_drug_info,
        {"identifier": "CHEBI:CHEBI:27690", "query_type": "targets"},
    ),
    "clinical_trials": (
        query_clinical_trials,
        {"identifier": "MESH:D000544", "entity_type": "disease"},
    ),
    "pathways": (query_pathways, {"gene_ids": ["HGNC:6407"]}),
    "causal_subnetwork": (
        query_causal_subnetwork,
        {"node_ids": ["HGNC:6407", "HGNC:5173"]},
    ),
    "mechanistic_statements": (
        query_mechanistic_statements,
        {"agent": "KRAS"},
    ),
    "enrichment": (
        run_enrichment_analysis,
        {"gene_list": ["HGNC:6407"], "analysis_type": "discrete"},
    ),
}


@pytest.mark.parametrize(
    "tool_fn,kwargs", _ALL_TOOLS.values(), ids=list(_ALL_TOOLS)
)
async def test_every_tool_degrades_on_transport_failure(
    tool_fn: Callable[..., Awaitable[dict[str, Any]]],
    kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _StubClient(error=httpx.ConnectError("connection refused"))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)

    result = await tool_fn(**kwargs)

    assert set(result) == {"error", "query"}
    assert "connection refused" in result["error"]
    assert isinstance(result["query"], dict)
