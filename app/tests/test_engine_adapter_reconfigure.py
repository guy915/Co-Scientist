"""Two runs in one process must each execute their own tool topology.

The app runs several runs concurrently in one worker process, each with its
own connector toggles, so "the first run's configuration is the process's
configuration" would be a cross-run correctness failure rather than a
stale-cache annoyance: a run with web search off would still search the web.

Nothing here is expected to fail today -- ``_build_generator`` constructs a
fresh generator, and therefore a fresh ``ToolRegistry``, per durable task.
That is the property, though, and it is one refactor away from being lost
(the engine's registry and MCP-client singletons both default to "first
caller wins"), so it is pinned rather than assumed.
"""

from __future__ import annotations

from typing import Any

from app.engine_adapter.opts import _build_generator
from app.engine_adapter.provider import _import_hypothesis_generator
from app.run_modes import resolved_run_config


def _generator_for(**overrides: Any) -> Any:
    """Build a generator through the app's real per-run construction path."""
    return _build_generator(
        _import_hypothesis_generator(),
        resolved_run_config(dict(overrides)),
    )


def _enabled_tools(generator: Any) -> set[str]:
    """Return the tool ids the generator's own registry leaves enabled."""
    return set(generator._tool_registry.get_enabled_tools())


def _search_sources(generator: Any) -> set[str]:
    """Return the literature sources this run would actually search.

    Read from the workflow rather than the tool table because the
    multi-source pipeline selects on ``SearchSourceConfig.enabled`` alone; a
    source left enabled over a disabled tool keeps being searched.
    """
    workflow = generator._tool_registry.get_workflow("literature_review")
    return {source.tool for source in workflow.get_enabled_search_sources()}


def test_second_run_gets_its_own_connector_toggles() -> None:
    """A web-search toggle flipped between two runs takes effect on both."""
    without = _generator_for(enable_web_search=False)
    with_web = _generator_for(enable_web_search=True)

    assert "web_search" not in _enabled_tools(without)
    assert "web_search" in _enabled_tools(with_web)
    assert "web_search" not in _search_sources(without)
    assert "web_search" in _search_sources(with_web)


def test_toggle_order_does_not_decide_the_topology() -> None:
    """Building the enabled run first must not leak into the disabled one."""
    _generator_for(enable_web_search=True)
    without = _generator_for(enable_web_search=False)

    assert "web_search" not in _enabled_tools(without)
    assert "web_search" not in _search_sources(without)


def test_each_run_holds_a_registry_of_its_own() -> None:
    """Two runs must not share the registry object their nodes read."""
    first = _generator_for(enable_web_search=True)
    second = _generator_for(enable_web_search=True)

    assert first._tool_registry is not second._tool_registry
