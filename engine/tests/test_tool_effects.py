"""Tests for tool effect typing and the concurrency rule it drives.

The property under test throughout is the fail-closed direction: anything
this module cannot positively resolve as non-mutating must serialize. Each
test that asserts a barrier states which way the failure would go if the
default were flipped, because "it still passes" is the failure mode a
fail-open default produces.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from co_scientist import tool_effects
from co_scientist.llm_tool_loop import _execute_tool_calls
from co_scientist.tool_effects import (
    ToolEffect,
    batch_by_effects,
    is_barrier,
    parse_effects,
    resolve_tool_effects,
)


def _call(name: str) -> SimpleNamespace:
    """Builds a litellm-shaped tool call carrying only a function name."""
    return SimpleNamespace(
        id=f"call_{name}", function=SimpleNamespace(name=name, arguments="{}")
    )


def test_parse_effects_combines_known_tokens() -> None:
    assert parse_effects(["read", "network"]) == (
        ToolEffect.READ | ToolEffect.NETWORK
    )


def test_parse_effects_ignores_case_and_surrounding_space() -> None:
    assert parse_effects([" Read ", "NETWORK"]) == (
        ToolEffect.READ | ToolEffect.NETWORK
    )


def test_parse_effects_treats_empty_declaration_as_barrier() -> None:
    # Fail-open would return NONE here, which is not a barrier, and an
    # `effects: []` typo would silently regain full concurrency.
    assert is_barrier(parse_effects([]))


def test_parse_effects_treats_unknown_token_as_barrier() -> None:
    # A misspelled "exec" must not be dropped and leave the tool looking
    # read-only; the whole declaration degrades to a barrier.
    assert is_barrier(parse_effects(["read", "exec"]))


def test_is_barrier_covers_write_append_and_process() -> None:
    assert is_barrier(ToolEffect.WRITE)
    assert is_barrier(ToolEffect.APPEND)
    assert is_barrier(ToolEffect.PROCESS)


def test_remote_reads_are_not_barriers() -> None:
    # Every tool on this host today. If this became a barrier, literature
    # search would silently serialize and every generation call would slow.
    assert not is_barrier(ToolEffect.READ | ToolEffect.NETWORK)


def test_resolve_reads_declared_effects_from_the_registry() -> None:
    """Goes through the real registry against the real shipped config."""
    from co_scientist.config.registry import get_tool_registry

    tools = get_tool_registry().get_enabled_tools()
    mcp_names = [tool.mcp_tool_name for tool in tools.values()]
    assert mcp_names, "expected the shipped config to declare tools"
    assert not any(is_barrier(resolve_tool_effects(n)) for n in mcp_names)


def test_resolve_treats_an_unregistered_tool_as_a_barrier() -> None:
    # The load-bearing case: a tool the model can call but nobody declared.
    assert is_barrier(resolve_tool_effects("no_such_tool_anywhere"))


def test_resolve_treats_a_broken_registry_as_a_barrier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import co_scientist.config.registry as registry

    def _boom() -> Any:
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(registry, "get_tool_registry", _boom)
    assert is_barrier(resolve_tool_effects("pubmed_search"))


def _patch_effects(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, list[str]]
) -> None:
    """Points effect resolution at an explicit name -> tokens mapping."""
    monkeypatch.setattr(
        tool_effects,
        "resolve_tool_effects",
        lambda name: parse_effects(mapping.get(name, [])),
    )


def test_batch_groups_all_reads_into_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(monkeypatch, {"a": ["read"], "b": ["read"]})
    batches = batch_by_effects([_call("a"), _call("b")])
    assert len(batches) == 1
    assert len(batches[0]) == 2


def test_batch_isolates_a_barrier_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(
        monkeypatch, {"r1": ["read"], "w": ["process"], "r2": ["read"]}
    )
    batches = batch_by_effects([_call("r1"), _call("w"), _call("r2")])
    assert [[c.function.name for c in b] for b in batches] == [
        ["r1"],
        ["w"],
        ["r2"],
    ]


def test_batch_preserves_order_and_loses_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_effects(
        monkeypatch,
        {"a": ["read"], "b": ["read"], "w": ["write"], "c": ["read"]},
    )
    names = ["a", "b", "w", "c"]
    batches = batch_by_effects([_call(n) for n in names])
    flattened = [c.function.name for batch in batches for c in batch]
    assert flattened == names


def test_batch_isolates_an_undeclared_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "mystery" is absent from the mapping, so it resolves to the
    # fail-closed default and must not share a batch with the reads.
    _patch_effects(monkeypatch, {"r1": ["read"], "r2": ["read"]})
    batches = batch_by_effects([_call("r1"), _call("mystery"), _call("r2")])
    assert len(batches) == 3


@pytest.mark.asyncio
async def test_barrier_tool_never_overlaps_a_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A process-spawning tool must not run while a read is in flight."""
    _patch_effects(
        monkeypatch,
        {"read_a": ["read"], "spawn": ["process"], "read_b": ["read"]},
    )
    in_flight = 0
    overlapped_with_barrier = False

    async def executor(tool_call: Any) -> dict[str, Any]:
        nonlocal in_flight, overlapped_with_barrier
        name = tool_call.function.name
        in_flight += 1
        if name == "spawn" and in_flight > 1:
            overlapped_with_barrier = True
        # Yield so a genuinely concurrent sibling would be observed.
        await asyncio.sleep(0)
        in_flight -= 1
        return {"role": "tool", "content": name}

    results = await _execute_tool_calls(
        [_call("read_a"), _call("spawn"), _call("read_b")], executor
    )

    assert not overlapped_with_barrier
    assert [r["content"] for r in results] == ["read_a", "spawn", "read_b"]


@pytest.mark.asyncio
async def test_reads_still_run_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Effect typing must not cost the concurrency the loop already had."""
    _patch_effects(monkeypatch, {"a": ["read"], "b": ["read"]})
    peak = 0
    in_flight = 0

    async def executor(tool_call: Any) -> dict[str, Any]:
        nonlocal peak, in_flight
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return {"role": "tool", "content": tool_call.function.name}

    await _execute_tool_calls([_call("a"), _call("b")], executor)
    assert peak == 2


def test_every_declared_tool_declares_its_effects() -> None:
    """The shipped config must not rely on the fail-closed default.

    Relying on it would be silently correct and silently slow: every
    literature call would serialize.
    """
    from co_scientist.config.registry import get_tool_registry

    serialized = [
        tool_id
        for tool_id, tool in get_tool_registry().get_enabled_tools().items()
        if is_barrier(parse_effects(tool.effects))
    ]
    assert serialized == []
