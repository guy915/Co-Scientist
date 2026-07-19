"""Tests for the pilot feedback endpoint and its store."""

from __future__ import annotations

from app import store
from tests._client import make_client


def test_submit_stores_the_note() -> None:
    client = make_client()

    response = client.post(
        "/api/feedback",
        json={
            "message": "The tournament view is confusing.",
            "category": "question",
            "audience": "sbi_ucd",
        },
    )

    assert response.status_code == 201
    note = response.json()
    assert note["message"] == "The tournament view is confusing."
    assert note["category"] == "question"
    assert note["audience"] == "sbi_ucd"
    assert note["id"] > 0

    stored = store.list_feedback()
    assert [n["message"] for n in stored] == [
        "The tournament view is confusing."
    ]


def test_missing_audience_defaults_to_general() -> None:
    client = make_client()

    response = client.post(
        "/api/feedback",
        json={"message": "Nice work.", "category": "suggestion"},
    )

    assert response.status_code == 201
    assert response.json()["audience"] == "general"


def test_message_is_trimmed() -> None:
    client = make_client()

    response = client.post(
        "/api/feedback",
        json={"message": "  padded  ", "category": "bug"},
    )

    assert response.json()["message"] == "padded"


def test_rejects_unknown_category() -> None:
    client = make_client()

    response = client.post(
        "/api/feedback",
        json={"message": "hi", "category": "complaint"},
    )

    assert response.status_code == 422


def test_rejects_empty_message() -> None:
    client = make_client()

    response = client.post(
        "/api/feedback",
        json={"message": "", "category": "bug"},
    )

    assert response.status_code == 422


def test_rejects_oversized_message() -> None:
    client = make_client()

    response = client.post(
        "/api/feedback",
        json={"message": "x" * 4001, "category": "bug"},
    )

    assert response.status_code == 422


def test_notes_are_listed_newest_first() -> None:
    client = make_client()
    for message in ("first", "second"):
        client.post(
            "/api/feedback",
            json={"message": message, "category": "suggestion"},
        )

    assert [n["message"] for n in store.list_feedback()] == [
        "second",
        "first",
    ]
