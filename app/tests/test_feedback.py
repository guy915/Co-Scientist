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


def test_a_submitter_can_read_back_their_own_notes() -> None:
    """N12: feedback is no longer write-only for the person who sent it."""
    client = make_client()
    owner = {"X-Client-ID": "feedback-owner"}
    other = {"X-Client-ID": "someone-else"}
    client.post(
        "/api/feedback",
        headers=owner,
        json={"message": "My note", "category": "bug"},
    )
    client.post(
        "/api/feedback",
        headers=other,
        json={"message": "Not mine", "category": "bug"},
    )

    response = client.get("/api/feedback", headers=owner)

    assert response.status_code == 200
    messages = [n["message"] for n in response.json()["feedback"]]
    assert messages == ["My note"]


def test_a_submitter_can_delete_their_own_note() -> None:
    client = make_client()
    owner = {"X-Client-ID": "feedback-owner"}
    created = client.post(
        "/api/feedback",
        headers=owner,
        json={"message": "Delete me", "category": "bug"},
    )
    note_id = created.json()["id"]

    response = client.delete(f"/api/feedback/{note_id}", headers=owner)

    assert response.status_code == 204
    assert store.list_feedback() == []


def test_another_client_cannot_delete_someone_elses_note() -> None:
    client = make_client()
    owner = {"X-Client-ID": "feedback-owner"}
    other = {"X-Client-ID": "someone-else"}
    created = client.post(
        "/api/feedback",
        headers=owner,
        json={"message": "Not yours", "category": "bug"},
    )
    note_id = created.json()["id"]

    response = client.delete(f"/api/feedback/{note_id}", headers=other)

    assert response.status_code == 404
    assert len(store.list_feedback()) == 1
