"""Tests for the synthesis-stage helpers in validate_synthesis.py.

These are the batch/retry/parsing helpers behind the validation synthesis
stage; each is exercised directly with a stub ``call_synthesis`` callable
rather than through the full ``validate_hypotheses`` pipeline, so failure
and retry branches can be forced deterministically.
"""

from typing import Any, cast

import pytest

from co_scientist import config as config_mod
from co_scientist.agents.generation.literature_tools.validate_synthesis import (
    _log_synthesis_tool_call_summary,
    _parse_synthesis_response,
    _retry_failed_synthesis_batches,
    _retry_one_hypothesis,
    _run_synthesis_batches,
    _setup_validation_tool_provider,
    _SynthesisRetryState,
)
from co_scientist.exceptions import ResponseParseError
from co_scientist.tools.provider import MCPToolProvider

# -----------------------------------------------------------------------------
# _setup_validation_tool_provider
# -----------------------------------------------------------------------------


class _FakeGlobalRegistry:
    """Minimal registry stand-in for the "resolve global registry" branch."""

    def get_tools_for_workflow(self, _workflow: str) -> list[str]:
        """Return one configured tool id."""
        return ["search_tool"]

    def get_mcp_tool_names(self, _tool_ids: list[str]) -> list[str]:
        """Return the resolved MCP tool names for the given tool ids."""
        return ["mcp_search_tool"]


def test_setup_validation_tool_provider_resolves_global_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tool_registry=None resolves the global registry's whitelist."""
    fake_registry = cast(Any, _FakeGlobalRegistry())
    monkeypatch.setattr(config_mod, "get_tool_registry", lambda: fake_registry)

    # A None mcp_client is safe here: MCPToolProvider.get_tools degrades to
    # an empty tools dict when no client is configured, so this only
    # exercises the registry-resolution branches under test.
    provider, openai_tools, resolved_registry, max_iterations = (
        _setup_validation_tool_provider(None, None, 3)
    )

    assert resolved_registry is fake_registry
    assert isinstance(provider, MCPToolProvider)
    assert openai_tools == []
    assert max_iterations > 0


# -----------------------------------------------------------------------------
# _log_synthesis_tool_call_summary
# -----------------------------------------------------------------------------


def test_log_synthesis_tool_call_summary_logs_when_calls_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-empty call-count map logs a per-tool summary line."""
    caplog.set_level("INFO")
    _log_synthesis_tool_call_summary("1", {"search": 2, "read": 1})
    assert "3 tool calls" in caplog.text


def test_log_synthesis_tool_call_summary_silent_when_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A zero-call-count map logs nothing."""
    caplog.set_level("INFO")
    _log_synthesis_tool_call_summary("1", {})
    assert "tool calls" not in caplog.text


# -----------------------------------------------------------------------------
# _parse_synthesis_response
# -----------------------------------------------------------------------------


def test_parse_synthesis_response_raises_on_unparseable() -> None:
    """A response with no recoverable JSON raises ResponseParseError."""
    with pytest.raises(ResponseParseError):
        _parse_synthesis_response("no json anywhere in this text", "1")


def test_parse_synthesis_response_repairs_truncated_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A truncated-but-repairable response logs a repair warning."""
    caplog.set_level("WARNING")
    truncated = '{"hypotheses": [{"hypothesis": "x"}'
    result = _parse_synthesis_response(truncated, "1")
    assert result == [{"hypothesis": "x"}]
    # The warning names the batch, so a log reader can still tell which
    # synthesis phase needed repairing.
    assert "required major repairs" in caplog.text
    assert "batch 1" in caplog.text


# -----------------------------------------------------------------------------
# _run_synthesis_batches
# -----------------------------------------------------------------------------


async def test_run_synthesis_batches_isolates_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One batch raising does not prevent the others from succeeding."""
    caplog.set_level("WARNING")

    async def call_synthesis(
        batch: list[dict[str, Any]],
        label: str,
        _texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        if label == "1":
            raise RuntimeError("batch one exploded")
        return [{"hypothesis": f"h-{label}"}]

    batches = [[{"a": 1}], [{"b": 2}]]
    validated, failed = await _run_synthesis_batches(batches, call_synthesis)

    assert validated == [{"hypothesis": "h-2"}]
    assert failed == [(0, batches[0])]
    assert "will retry hypotheses individually" in caplog.text


# -----------------------------------------------------------------------------
# _retry_one_hypothesis
# -----------------------------------------------------------------------------


async def test_retry_one_hypothesis_success_accumulates_text() -> None:
    """A successful retry extends both the result list and text context."""

    async def call_synthesis(
        batch: list[dict[str, Any]],
        label: str,
        texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        assert label == "1_retry_1"
        assert texts == ["prior hypothesis"]
        return [{"hypothesis": "retried hypothesis"}]

    accumulated_texts = ["prior hypothesis"]
    all_validated: list[dict[str, Any]] = []

    await _retry_one_hypothesis(
        0,
        0,
        {"draft": "x"},
        _SynthesisRetryState(all_validated, accumulated_texts, call_synthesis),
    )

    assert all_validated == [{"hypothesis": "retried hypothesis"}]
    assert accumulated_texts == ["prior hypothesis", "retried hypothesis"]


async def test_retry_one_hypothesis_skips_empty_text_result() -> None:
    """A result without a hypothesis text is not added to the text context."""

    async def call_synthesis(
        _batch: list[dict[str, Any]],
        _label: str,
        _texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        return [{"other_field": "no hypothesis key"}]

    accumulated_texts: list[str] = []
    all_validated: list[dict[str, Any]] = []

    await _retry_one_hypothesis(
        0,
        0,
        {"draft": "x"},
        _SynthesisRetryState(all_validated, accumulated_texts, call_synthesis),
    )

    assert all_validated == [{"other_field": "no hypothesis key"}]
    assert accumulated_texts == []


async def test_retry_one_hypothesis_failure_drops_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A retry that raises is dropped, leaving the accumulators unchanged."""
    caplog.set_level("ERROR")

    async def call_synthesis(
        _batch: list[dict[str, Any]],
        _label: str,
        _texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        raise RuntimeError("still failing")

    accumulated_texts: list[str] = []
    all_validated: list[dict[str, Any]] = []

    await _retry_one_hypothesis(
        1,
        2,
        {"draft": "y"},
        _SynthesisRetryState(all_validated, accumulated_texts, call_synthesis),
    )

    assert all_validated == []
    assert accumulated_texts == []
    assert "Individual retry failed" in caplog.text


# -----------------------------------------------------------------------------
# _retry_failed_synthesis_batches
# -----------------------------------------------------------------------------


async def test_retry_failed_synthesis_batches_seeds_context_and_retries() -> (
    None
):
    """Retries run per-hypothesis, seeded with already-validated texts."""
    calls: list[tuple[str, list[str] | None]] = []

    async def call_synthesis(
        batch: list[dict[str, Any]],
        label: str,
        texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        calls.append((label, list(texts) if texts else None))
        hyp_data = batch[0]
        if hyp_data.get("fail"):
            raise RuntimeError("nope")
        return [{"hypothesis": hyp_data["draft"]}]

    failed_batches: list[tuple[int, list[dict[str, Any]]]] = [
        (0, [{"draft": "a"}, {"draft": "b", "fail": True}]),
    ]
    all_validated: list[dict[str, Any]] = [{"hypothesis": "seed"}]

    await _retry_failed_synthesis_batches(
        failed_batches, all_validated, call_synthesis
    )

    assert {"hypothesis": "a"} in all_validated
    assert len(all_validated) == 2
    assert len(calls) == 2
    # The pre-existing validated hypothesis seeds the first retry's context.
    assert calls[0] == ("1_retry_1", ["seed"])
