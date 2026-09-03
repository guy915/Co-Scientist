"""The mature cascade's structured display detail (R14-22 / R14-15).

``_review_detail_json`` is what lets the markdown renderer show the
simulation review's numbered failure points and the full review's
Go/No-Go framing without re-parsing the flattened ``critique`` text.
These tests cover the populated, empty, and malformed (json_object
downgrade) shapes for both review kinds, plus that the drain actually
persists the column end to end.
"""

from __future__ import annotations

import asyncio
import json

from app import store
from app.engine_adapter.drain_reviews import (
    _review_detail_json,
    _simulation_detail,
    _verdict_detail,
)
from tests._drain_helpers import (
    _build_report_ranking,
    _final_state_with_features,
    _persist_and_finalize,
)


def test_simulation_detail_renders_points_and_decisive_step() -> None:
    points = ["Off-target editing risk.", "Delivery inefficiency."]
    review = {
        "failure_points": points,
        "decisive_step": "Step 3: enzyme binds substrate.",
        "verdict": "breaks_down",
    }
    assert _simulation_detail(review) == {
        "failure_points": points,
        "decisive_step": "Step 3: enzyme binds substrate.",
    }


def test_simulation_detail_empty_when_mechanism_holds() -> None:
    """A ``holds`` verdict legitimately names no failure point."""
    review = {"failure_points": [], "decisive_step": "", "verdict": "holds"}
    assert _simulation_detail(review) == {}


def test_simulation_detail_degrades_on_malformed_shapes() -> None:
    """json_object downgrade: wrong types never crash the drain."""
    review = {
        "failure_points": "not a list",
        "decisive_step": 42,
    }
    detail = _simulation_detail(review)
    # A non-list failure_points is dropped entirely rather than iterated
    # character by character.
    assert "failure_points" not in detail
    assert detail["decisive_step"] == "42"


def test_simulation_detail_caps_item_count_and_length() -> None:
    review = {
        "failure_points": [f"point {i}" for i in range(20)],
        "decisive_step": "x" * 1000,
    }
    detail = _simulation_detail(review)
    assert len(detail["failure_points"]) == 10
    assert len(detail["decisive_step"]) == 200


def test_verdict_detail_renders_go_no_go_and_timeframe() -> None:
    review = {
        "go_no_go_recommendation": "Go — pursue wet-lab validation.",
        "time_to_verdict": "2-4 weeks",
    }
    assert _verdict_detail(review) == {
        "go_no_go": "Go — pursue wet-lab validation.",
        "time_to_verdict": "2-4 weeks",
    }


def test_verdict_detail_empty_when_absent() -> None:
    assert _verdict_detail({"verdict": "sound"}) == {}


def test_review_detail_json_dispatches_by_key() -> None:
    simulation = {"failure_points": ["A flaw."], "decisive_step": "Step 1."}
    full = {"go_no_go_recommendation": "Go", "time_to_verdict": "Short"}

    sim_json = _review_detail_json("simulation", simulation)
    full_json = _review_detail_json("full", full)
    recurrent_json = _review_detail_json("recurrent", full)

    assert sim_json is not None
    assert json.loads(sim_json)["decisive_step"] == "Step 1."
    assert full_json is not None
    assert json.loads(full_json)["go_no_go"] == "Go"
    assert recurrent_json == full_json


def test_review_detail_json_none_when_nothing_structured() -> None:
    assert _review_detail_json("simulation", {"verdict": "holds"}) is None
    assert _review_detail_json("full", {"verdict": "sound"}) is None
    # Every other reviewer key (deep verification, initial review) carries
    # no structured detail at all.
    assert _review_detail_json("deep_verification", {"anything": "x"}) is None


def test_drain_persists_detail_json_on_the_review_row(
    isolated_db: str,
) -> None:
    """The column survives the real drain path, not just the unit helper."""
    state = _final_state_with_features()
    state["hypotheses"][0]["enrichments"] = {
        "full": {
            "verdict": "sound",
            "go_no_go_recommendation": "Go",
            "time_to_verdict": "Short",
        },
        "simulation": {
            "verdict": "breaks_down",
            "failure_points": ["Substrate saturation."],
            "decisive_step": "Step 4.",
        },
    }
    run = store.create_run("detail-json goal", "standard", "engine", {})
    _persist_and_finalize(run, state, isolated_db)

    rows = store.list_reviews(run.id, db_path=isolated_db)
    reviews = {r["reviewer_agent"]: r for r in rows}
    full_detail = json.loads(reviews["full_review"]["detail_json"])
    sim_detail = json.loads(reviews["simulation_review"]["detail_json"])
    assert full_detail == {"go_no_go": "Go", "time_to_verdict": "Short"}
    assert sim_detail == {
        "failure_points": ["Substrate saturation."],
        "decisive_step": "Step 4.",
    }
    # Deep verification (a different reviewer_agent on the same drain)
    # carries no structured detail_json of its own.
    dv = [
        r
        for r in store.list_reviews(run.id, db_path=isolated_db)
        if r["reviewer_agent"] == "deep_verification"
    ]
    assert dv and dv[0]["detail_json"] is None

    # The whole point of persisting detail_json: the Goal Report markdown
    # -- built fresh from the DB, not the fixture -- actually shows it.
    # This is the one test that drives drain -> store -> markdown end to
    # end; the renderer's own unit tests stop at hand-built review dicts,
    # and a rename of either side's hardcoded reviewer_agent string
    # ("simulation_review"/"full_review") would render nothing and pass
    # every other test in this file.
    # The simulation-review subsection renders on the Top Ranking
    # Hypotheses document (R14-11), not the Research Overview one.
    # A plain sync test (see the module note above on why): the rest of
    # this test drives ``_persist_and_finalize``'s own internal
    # ``asyncio.run``, so this call gets the same wrapper rather than
    # making the whole test async and nesting one event loop inside
    # another.
    _payload, markdown = asyncio.run(_build_report_ranking(run, isolated_db))
    assert "#### Simulation review" in markdown
    assert "**Verdict:** Go" in markdown
    assert "**Time to Verdict:** Short" in markdown
    assert "1. **Failure point:** Substrate saturation." in markdown
