"""Localization plumbing: geo detection, language round-trip, report labels."""
# pylint: disable=unused-argument
from __future__ import annotations

import asyncio
import time

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.geo import detect_locale
from app.i18n import (is_rtl, language_name, milestone_labels, report_labels)
from app.mock_workflow import resolved_config


def _client() -> TestClient:
    from app.main import app  # pylint: disable=import-outside-toplevel

    return TestClient(app)


def _wait_for(predicate: Callable[[], bool],
              *,
              timeout: float = 10.0,
              interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_language_name_maps_known_locales() -> None:
    assert language_name("he") == "Hebrew"
    assert language_name("he-IL") == "Hebrew"
    assert language_name("en") is None
    assert language_name(None) is None
    assert language_name("xx") is None


def test_is_rtl() -> None:
    assert is_rtl("he") is True
    assert is_rtl("he-IL") is True
    assert is_rtl("en") is False
    assert is_rtl(None) is False


def test_report_and_milestone_labels_fall_back_to_english() -> None:
    he = report_labels("he")
    en = report_labels("en")
    assert he["top_hypotheses"] != en["top_hypotheses"]
    # Unknown locale falls back entirely to English.
    assert report_labels("xx") == en
    ms = milestone_labels("he")
    assert ms["meta_review"] == "מטא-סקירה הושלמה"
    # Template still interpolates.
    assert "3" in ms["evolve"].format(count=3, itr=1)


def test_resolved_config_preserves_language() -> None:
    cfg = resolved_config("standard", {"language": "he", "max_iterations": 2})
    assert cfg["language"] == "he"
    assert cfg["max_iterations"] == 2
    assert isinstance(cfg["max_iterations"], int)


def test_detect_locale_from_country_header() -> None:
    assert asyncio.run(detect_locale({"cf-ipcountry": "IL"}, None)) == {
        "country": "IL",
        "locale": "he",
    }
    assert asyncio.run(detect_locale({"x-vercel-ip-country": "US"}, None)) == {
        "country": "US",
        "locale": None,
    }


def test_detect_locale_skips_private_ip() -> None:
    assert asyncio.run(detect_locale({"x-forwarded-for": "10.0.0.1"},
                                     None)) == {
                                         "country": None,
                                         "locale": None,
                                     }


def test_geo_endpoint(isolated_db: str) -> None:
    client = _client()
    res = client.get("/api/geo", headers={"cf-ipcountry": "IL"})
    assert res.status_code == 200
    assert res.json() == {"country": "IL", "locale": "he"}


def test_create_run_round_trips_language(isolated_db: str) -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Investigate ferroptosis in cancer",
            "profile": "standard",
            "language": "he",
        },
    )
    assert res.status_code == 200
    run_id = res.json()["id"]
    got = client.get(f"/api/runs/{run_id}")
    assert got.json()["config"]["language"] == "he"


def test_create_run_rejects_bad_language(isolated_db: str) -> None:
    client = _client()
    res = client.post(
        "/api/runs",
        json={
            "research_goal": "Investigate ferroptosis in cancer",
            "profile": "standard",
            "language": "not-a-locale",
        },
    )
    assert res.status_code == 422
