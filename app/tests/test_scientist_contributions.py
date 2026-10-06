from __future__ import annotations

from typing import Any

import pytest

from tests._client import create_run as _create_run
from tests._client import make_client as _client


def _new_run(client: Any, headers: dict[str, str] | None = None) -> str:
    res = _create_run(client, "Scientist-in-the-loop goal", headers=headers)
    return str(res.json()["id"])


def test_scientist_hypothesis_admitted_with_authorship(
    isolated_db: str,
) -> None:
    # Attribute contributions to caller identity, not a spoofable author field
    # in the request body.
    headers = {"X-Client-ID": "dr-smith"}
    client = _client()
    run_id = _new_run(client, headers)

    res = client.post(
        f"/api/runs/{run_id}/hypotheses",
        headers=headers,
        json={
            "statement": "Inhibiting kinase X reduces AML growth by apoptosis.",
            "author": "dr-smith",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["admitted"] is True
    assert body["author"] == "dr-smith"

    hyps = client.get(f"/api/runs/{run_id}/hypotheses", headers=headers).json()[
        "hypotheses"
    ]
    manual = next(h for h in hyps if h["id"] == body["id"])
    assert manual["created_by_agent"] == "scientist_manual"
    assert manual["author"] == "dr-smith"
    assert manual["safety_status"] == "allow"
    pending = client.get(
        f"/api/runs/{run_id}/messages", headers=headers
    ).json()["messages"]
    assert pending[-1]["kind"] == "steering"
    assert pending[-1]["meta"]["kind"] == "manual_hypothesis"


def test_scientist_unsafe_hypothesis_is_blocked_not_persisted(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(
        f"/api/runs/{run_id}/hypotheses",
        json={
            "statement": (
                "Weaponize the pathogen to enhance transmissibility in humans."
            ),
            "author": "bad-actor",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["admitted"] is False
    assert body["safety"]["outcome"] == "prohibited"

    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    assert all(h["created_by_agent"] != "scientist_manual" for h in hyps)


def test_scientist_review_lands_in_reviews_table(isolated_db: str) -> None:
    headers = {"X-Client-ID": "dr-lee"}
    client = _client()
    run_id = _new_run(client, headers)
    hyp = client.post(
        f"/api/runs/{run_id}/hypotheses",
        headers=headers,
        json={"statement": "A safe, testable hypothesis.", "author": "dr-lee"},
    ).json()

    res = client.post(
        f"/api/runs/{run_id}/reviews",
        headers=headers,
        json={
            "hypothesis_id": hyp["id"],
            "author": "dr-lee",
            "verdict": "support",
            "critique": "Well grounded; suggest a control arm.",
        },
    )
    assert res.status_code == 200
    assert res.json()["recorded"] is True

    reviews = client.get(f"/api/runs/{run_id}/reviews", headers=headers).json()[
        "reviews"
    ]
    scientist = [r for r in reviews if r["reviewer_agent"] == "scientist"]
    assert len(scientist) == 1
    assert "dr-lee" in scientist[0]["summary"]
    messages = client.get(
        f"/api/runs/{run_id}/messages", headers=headers
    ).json()["messages"]
    assert messages[-1]["meta"]["kind"] == "human_review"
    assert messages[-1]["applied"] is False


@pytest.mark.parametrize(
    ("verdict", "target", "status"),
    [
        ("maybe", "own", 422),
        ("support", "missing", 404),
        ("support", "other", 404),
    ],
)
def test_scientist_review_rejects_bad_verdict_and_foreign_hypotheses(
    isolated_db: str, verdict: str, target: str, status: int
) -> None:
    client = _client()
    run_a = _new_run(client)
    run_b = _new_run(client)
    statement = {"statement": "A safe, testable hypothesis.", "author": "x"}
    hosts = {"own": run_a, "other": run_b}
    hyp = "does-not-exist"
    if target in hosts:
        posted = client.post(
            f"/api/runs/{hosts[target]}/hypotheses", json=statement
        )
        hyp = posted.json()["id"]

    res = client.post(
        f"/api/runs/{run_a}/reviews",
        json={
            "hypothesis_id": hyp,
            "author": "dr-lee",
            "verdict": verdict,
            "critique": "",
        },
    )

    assert res.status_code == status
    assert client.get(f"/api/runs/{run_a}/reviews").json()["reviews"] == []
