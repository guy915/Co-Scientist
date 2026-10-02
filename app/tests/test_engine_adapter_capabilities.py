"""Run tiers fund expensive capabilities together at the engine boundary."""

from typing import Any

import pytest

from app.engine_adapter.opts import build_engine_opts


@pytest.mark.parametrize(
    ("tier", "resolved", "funded"),
    [
        ("express", "express", False),
        ("standard", "standard", False),
        ("extended", "extended", True),
        ("ultra", "ultra", True),
        ("advanced", "ultra", True),
        (None, "standard", False),
    ],
)
def test_tier_funding_reaches_every_expensive_capability(
    isolated_db: str, tier: str | None, resolved: str, funded: bool
) -> None:
    opts = build_engine_opts({"tier": tier}, "unused-run", isolated_db)
    assert opts["research_tier"] == resolved
    assert opts["enable_tool_calling_generation"] is funded
    assert opts["enable_simulation_execution"] is funded
    assert opts["enable_overview_review"] is funded


def test_default_config_keeps_the_existing_capabilities(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FORCE_LITERATURE_REVIEW", raising=False)
    opts = build_engine_opts({}, "unused-run", isolated_db)
    assert opts["research_tier"] == "standard"
    assert opts["enable_tool_calling_generation"] is False
    assert opts["enable_simulation_execution"] is False
    assert opts["enable_overview_review"] is False
    assert opts["enable_literature_review_node"] is True
    assert opts["enable_meta_review"] is True
    assert opts["generation_strategy"] == ""


@pytest.mark.parametrize("enabled", [False, True])
def test_literature_kill_switch_overrides_the_connector(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    cfg = {"enable_literature_review": enabled}
    monkeypatch.delenv("FORCE_LITERATURE_REVIEW", raising=False)
    opts = build_engine_opts(cfg, "unused-run", isolated_db)
    assert opts["enable_literature_review_node"] is enabled
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    opts = build_engine_opts(cfg, "unused-run", isolated_db)
    assert opts["enable_literature_review_node"] is False


@pytest.mark.parametrize("enabled", [False, True, None, 0])
@pytest.mark.parametrize("strategy", ["debate", "unknown", None, 12])
def test_ablation_requests_keep_their_existing_normalization(
    isolated_db: str, enabled: Any, strategy: Any
) -> None:
    opts = build_engine_opts(
        {"enable_meta_review": enabled, "generation_strategy": strategy},
        "unused-run",
        isolated_db,
    )
    assert opts["enable_meta_review"] is (enabled is not False)
    assert opts["generation_strategy"] == (
        strategy if isinstance(strategy, str) else ""
    )
