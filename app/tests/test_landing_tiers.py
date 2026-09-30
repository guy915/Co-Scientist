"""The landing page's tier figures must match the tiers the backend runs.

The landing page under the chat home (`frontend/src/workbench/pages/
home_landing_content.ts`) shows each run tier's seed ideas, evolution
cycles, and largest pool as hard-coded numbers, because the page renders
before any API call. Nothing else binds those numbers to
`RUN_TIER_DEFAULTS`, so a tier retune would leave the page advertising a
run the product no longer performs. This reads them back out of the
TypeScript source and compares.
"""

from __future__ import annotations

import pathlib
import re

from app.run_modes import RUN_TIER_DEFAULTS

_CONTENT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "frontend/src/workbench/pages/home_landing_content.ts"
)
_TIER = re.compile(
    r"\{name: '(\w+)', seeds: (\d+), cycles: (\d+), maxIdeas: (\d+)\}"
)


def test_landing_tiers_match_run_tier_defaults() -> None:
    """Every tier row on the landing page equals the backend's own."""
    rows = _TIER.findall(_CONTENT.read_text(encoding="utf-8"))
    shown = {
        name.lower(): (int(seeds), int(cycles), int(max_ideas))
        for name, seeds, cycles, max_ideas in rows
    }
    expected = {
        tier: (
            values["initial_hypotheses_count"],
            values["max_iterations"],
            values["max_ideas"],
        )
        for tier, values in RUN_TIER_DEFAULTS.items()
    }
    assert shown == expected
