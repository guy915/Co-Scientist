"""The agentic draft path is funded by tier, not switched on globally.

Tool-calling generation spends one LLM round-trip per tool call and
carries every prior tool result into the next prompt, so a hypothesis
costs roughly nine calls on prompts that grow past 12k tokens -- per
hypothesis, per cycle. Live telemetry had it as the single largest line
in an express run's token budget, which is not the trade express offers.
The engine treats the flag as an explicit request; these tests pin which
runs make it.
"""

from typing import Any

import pytest

from app.engine_adapter.opts import _resolve_tool_calling_generation_toggle


def _cfg(tier: str | None) -> dict[str, Any]:
    """A resolved run config carrying only the tier under test."""
    return {"tier": tier}


@pytest.mark.parametrize("tier", ["extended", "ultra"])
def test_deep_tiers_fund_the_agentic_draft_path(tier: str) -> None:
    """A scientist choosing depth over turnaround gets the tool loop."""
    assert _resolve_tool_calling_generation_toggle(_cfg(tier)) is True


@pytest.mark.parametrize("tier", ["express", "standard"])
def test_fast_tiers_do_not(tier: str) -> None:
    """Express and standard promise a fast answer and keep that promise."""
    assert _resolve_tool_calling_generation_toggle(_cfg(tier)) is False


def test_an_unset_tier_falls_back_to_the_default_tier() -> None:
    """A config without a tier resolves through normalize_run_tier.

    ``resolved_run_config`` always seeds a tier, so this covers older
    persisted rows and direct API callers -- which land on ``standard``
    and therefore must not silently inherit the expensive path.
    """
    assert _resolve_tool_calling_generation_toggle(_cfg(None)) is False
    assert _resolve_tool_calling_generation_toggle({}) is False


def test_a_legacy_tier_name_resolves_before_the_gate() -> None:
    """'advanced' migrates forward to ultra, so it funds the path."""
    assert _resolve_tool_calling_generation_toggle(_cfg("advanced")) is True
