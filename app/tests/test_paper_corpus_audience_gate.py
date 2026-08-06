"""End-to-end: the corpus audience requires a verified researcher session.

N6: the audience was self-declared with no server-side check, so any caller
could claim ``sbi_ucd`` and have the committed paper corpus injected into
every model surface. ``paper_corpus.verified_audience`` closes that at the
three points a self-declared audience first enters the system -- run
creation, a Q&A question, and interview creation (see ``runs_crud.py``,
``runs_chat.py``, ``interviews.py``). These tests drive the real HTTP
endpoints, not the pure config-resolution helpers, since the gate lives one
level above those.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app import paper_corpus
from app.config import settings
from tests._client import make_client
from tests._interviews_helpers import _interview_payload


def _write_corpus(tmp_path: Path) -> Path:
    """Install a one-paper corpus whose title is easy to search for."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / paper_corpus.CATALOG_FILENAME).write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "paper_id": "sentinel-paper",
                        "title": "The Sentinel Kinase Feedback Paper",
                        "abstract": "A finding that must never reach an "
                        "unverified caller.",
                        "core": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return corpus


@pytest.fixture()
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(
        paper_corpus.CORPUS_ENV_VAR, str(_write_corpus(tmp_path))
    )
    paper_corpus.load_catalog.cache_clear()
    yield
    paper_corpus.load_catalog.cache_clear()


def _configure_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "required")
    monkeypatch.setattr(settings, "auth_secret", "test-signing-secret")
    monkeypatch.setattr(
        settings,
        "researcher_access_codes",
        '{"researcher-a":"invite-a"}',
    )


def _bearer_headers(client: Any) -> dict[str, str]:
    """Exchange the configured invite for a verified researcher session."""
    response = client.post(
        "/api/auth/exchange", json={"access_code": "invite-a"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- run creation (runs_crud.py::create_run) --------------------------------


def test_unverified_caller_cannot_reach_corpus_via_run_creation(
    corpus: None,
) -> None:
    """An X-Client-ID caller claiming sbi_ucd gets the honest downgrade."""
    client = make_client()
    created = client.post(
        "/api/runs",
        headers={"X-Client-ID": "anyone"},
        json={"research_goal": "goal", "audience": "sbi_ucd"},
    )
    assert created.status_code == 200
    config = created.json()["config"]
    assert config.get("audience") != "sbi_ucd"
    assert "Sentinel Kinase" not in json.dumps(config)


def test_verified_researcher_still_reaches_the_corpus_via_run_creation(
    corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real researcher session is not collateral damage from the gate."""
    _configure_auth(monkeypatch)
    client = make_client()
    created = client.post(
        "/api/runs",
        headers=_bearer_headers(client),
        json={"research_goal": "goal", "audience": "sbi_ucd"},
    )
    assert created.status_code == 200
    config = created.json()["config"]
    assert config["audience"] == "sbi_ucd"
    assert "Sentinel Kinase" in json.dumps(config)


# --- interview creation (interviews.py::create_interview) -------------------


def test_unverified_caller_cannot_reach_corpus_via_interview(
    corpus: None,
) -> None:
    client = make_client()
    created = client.post(
        "/api/interviews",
        headers={"X-Client-ID": "anyone"},
        json={"research_challenge": "goal", "audience": "sbi_ucd"},
    )
    assert created.status_code == 200
    interview_id = _interview_payload(created)["id"]

    stored = client.get(
        f"/api/interviews/{interview_id}", headers={"X-Client-ID": "anyone"}
    )
    assert stored.json()["audience"] != "sbi_ucd"


def test_verified_researcher_still_reaches_the_corpus_via_interview(
    corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_auth(monkeypatch)
    client = make_client()
    headers = _bearer_headers(client)
    created = client.post(
        "/api/interviews",
        headers=headers,
        json={"research_challenge": "goal", "audience": "sbi_ucd"},
    )
    assert created.status_code == 200
    interview_id = _interview_payload(created)["id"]

    stored = client.get(f"/api/interviews/{interview_id}", headers=headers)
    assert stored.json()["audience"] == "sbi_ucd"


# --- Q&A (runs_chat.py::ask_question) ---------------------------------------


def test_unverified_caller_cannot_reach_corpus_via_qa(
    corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catalog built into the Q&A system prompt honors the same gate."""
    captured: dict[str, Any] = {}

    async def _fake_stream_answer(
        run_id: str, question: Any, system_prompt: str, manifest: Any, **kw: Any
    ) -> Any:
        captured["system_prompt"] = system_prompt
        if False:
            yield ""  # pragma: no cover - makes this an async generator

    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-placeholder-for-shape-test")
    from app import qa

    monkeypatch.setattr(qa, "stream_answer", _fake_stream_answer)

    client = make_client()
    created = client.post(
        "/api/runs",
        headers={"X-Client-ID": "anyone"},
        json={"research_goal": "goal"},
    )
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/messages/ask",
        headers={"X-Client-ID": "anyone"},
        json={"question": "what does the group know?", "audience": "sbi_ucd"},
    )
    assert response.status_code == 200
    assert "Sentinel Kinase" not in captured["system_prompt"]


def test_verified_researcher_still_reaches_the_corpus_via_qa(
    corpus: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_stream_answer(
        run_id: str, question: Any, system_prompt: str, manifest: Any, **kw: Any
    ) -> Any:
        captured["system_prompt"] = system_prompt
        if False:
            yield ""  # pragma: no cover

    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-placeholder-for-shape-test")
    from app import qa

    monkeypatch.setattr(qa, "stream_answer", _fake_stream_answer)
    _configure_auth(monkeypatch)

    client = make_client()
    headers = _bearer_headers(client)
    created = client.post(
        "/api/runs", headers=headers, json={"research_goal": "goal"}
    )
    run_id = created.json()["id"]

    response = client.post(
        f"/api/runs/{run_id}/messages/ask",
        headers=headers,
        json={"question": "what does the group know?", "audience": "sbi_ucd"},
    )
    assert response.status_code == 200
    assert "Sentinel Kinase" in captured["system_prompt"]
