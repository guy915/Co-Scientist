"""Tests for run renaming: PATCH /api/runs/{run_id}."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import store

from ._client import make_client

_OWNER = {"X-Client-ID": "rename-owner"}
_OTHER = {"X-Client-ID": "someone-else"}

_TITLE = "Sequential Senolytic Conditioning for Cryogenic Biostasis"


def _draft_run(
    client: TestClient, goal: str = "Extend healthy lifespan"
) -> str:
    """Create a draft run owned by _OWNER and return its id."""
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={"research_goal": goal, "tier": "express"},
    )
    assert created.status_code == 200, created.text
    return str(created.json()["id"])


def test_renames_the_run_and_returns_its_details() -> None:
    client: TestClient = make_client()
    run_id = _draft_run(client)

    response = client.patch(
        f"/api/runs/{run_id}", headers=_OWNER, json={"title": _TITLE}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == _TITLE
    # The same shape as GET, so a caller can render straight from it.
    assert body["id"] == run_id
    assert "summary" in body


def test_the_new_title_is_what_later_reads_return() -> None:
    client: TestClient = make_client()
    run_id = _draft_run(client)

    client.patch(f"/api/runs/{run_id}", headers=_OWNER, json={"title": _TITLE})

    fetched = client.get(f"/api/runs/{run_id}", headers=_OWNER).json()
    assert fetched["title"] == _TITLE
    listed = client.get("/api/runs", headers=_OWNER).json()["runs"]
    assert [r["title"] for r in listed if r["id"] == run_id] == [_TITLE]


def test_the_research_goal_is_left_alone() -> None:
    client: TestClient = make_client()
    run_id = _draft_run(client, goal="Extend healthy lifespan")

    renamed = client.patch(
        f"/api/runs/{run_id}", headers=_OWNER, json={"title": _TITLE}
    ).json()

    # Renaming relabels; it must not rewrite the input every hypothesis
    # and tournament judgment was produced against.
    assert renamed["research_goal"] == "Extend healthy lifespan"


def test_surrounding_whitespace_is_collapsed() -> None:
    client: TestClient = make_client()
    run_id = _draft_run(client)

    body = client.patch(
        f"/api/runs/{run_id}",
        headers=_OWNER,
        json={"title": "  Cryogenic   Biostasis\n"},
    ).json()

    assert body["title"] == "Cryogenic Biostasis"


def test_a_blank_title_is_refused() -> None:
    client: TestClient = make_client()
    run_id = _draft_run(client)

    empty = client.patch(
        f"/api/runs/{run_id}", headers=_OWNER, json={"title": ""}
    )
    spaces = client.patch(
        f"/api/runs/{run_id}", headers=_OWNER, json={"title": "   "}
    )

    assert empty.status_code == 422
    assert spaces.status_code == 422


def test_an_overlong_title_is_refused() -> None:
    client: TestClient = make_client()
    run_id = _draft_run(client)

    response = client.patch(
        f"/api/runs/{run_id}", headers=_OWNER, json={"title": "x" * 81}
    )

    assert response.status_code == 422


def test_another_client_cannot_rename_it() -> None:
    client: TestClient = make_client()
    run_id = _draft_run(client)

    response = client.patch(
        f"/api/runs/{run_id}", headers=_OTHER, json={"title": _TITLE}
    )

    # 404, not 403: a non-owner must not learn the run exists.
    assert response.status_code == 404
    run = store.get_run(run_id)
    assert run is not None and run.title != _TITLE


def test_the_shared_demo_run_cannot_be_renamed() -> None:
    client: TestClient = make_client()
    demo_id = _draft_run(client)
    # Re-own it as the shared demo fixture rather than depending on one
    # having been seeded, which would leave this case silently skipped.
    with store.connect() as conn:
        conn.execute(
            "UPDATE runs SET client_id=? WHERE id=?",
            (store.DEMO_CLIENT_ID, demo_id),
        )

    response = client.patch(
        f"/api/runs/{demo_id}", headers=_OWNER, json={"title": _TITLE}
    )

    # The ownership middleware exempts demo runs so everyone can read them,
    # which would otherwise let anyone rename the shared fixture.
    assert response.status_code == 403


def test_renaming_an_unknown_run_is_a_404() -> None:
    client: TestClient = make_client()

    response = client.patch(
        "/api/runs/no-such-run", headers=_OWNER, json={"title": _TITLE}
    )

    assert response.status_code == 404
