"""Offline seam check for the bounded batch-schema qualification probe."""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.claims import AssessorDraft, EntailmentLabel


FOLDER = Path(__file__).resolve().parent


def _probe(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/test-model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.syspath_prepend(str(FOLDER))
    return sys.modules.get("probe_batch_schema") or importlib.import_module(
        "probe_batch_schema"
    )


def test_new_preflight_pins_the_current_batch_schema(monkeypatch) -> None:
    probe = _probe(monkeypatch)
    _, preflight = probe.load_frozen_panel()
    schema_hash = hashlib.sha256(
        json.dumps(probe._BATCH_DRAFT_SCHEMA, sort_keys=True).encode()
    ).hexdigest()

    assert probe.PREFLIGHT.name == "batch-schema-preflight110.json"
    assert preflight["schema_sha256"] == schema_hash


def test_run_batch_uses_one_shared_four_claim_invocation(monkeypatch) -> None:
    """The frozen panel reaches the actual batch boundary without a network call."""
    probe = _probe(monkeypatch)
    dataset, preflight = probe.load_frozen_panel()
    calls = []

    def assessor(claims, passages):
        calls.append((list(claims), list(passages)))
        return [
            AssessorDraft(
                EntailmentLabel(label),
                supporting=((passages[index].evidence_id, passages[index].text),)
                if label in {"partial", "supports"}
                else (),
                contradicting=((passages[index].evidence_id, passages[index].text),)
                if label == "contradicts"
                else (),
                verification_method="model_primary",
            )
            for index, label in enumerate(preflight["expected_labels"])
        ]

    result = probe.run_batch(dataset, assessor, "llm:test-model")

    assert [(len(claims), len(passages)) for claims, passages in calls] == [(4, 4)]
    assert [check["label"] for check in result["checks"]] == preflight[
        "expected_labels"
    ]
    assert all(
        check["verification_method"] == "model_primary" for check in result["checks"]
    )
    assert result["checks"][0]["supporting_spans"][0]["quote"]
    assert result["checks"][3]["contradicting_spans"][0]["quote"]


def test_live_probe_refuses_a_fourth_provider_attempt(monkeypatch, tmp_path) -> None:
    probe = _probe(monkeypatch)
    output = tmp_path / "batch-qualification.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    monkeypatch.setenv("QUALIFICATION_TRIAL", "1")
    monkeypatch.setenv("QUALIFICATION_REVISION", probe.head_revision())
    monkeypatch.setattr(probe, "current_catalog", lambda: {"test-model": {}})
    monkeypatch.setattr(probe, "verify_model", lambda *_args: None)

    from co_scientist.llm_call_budget import record_provider_request

    admitted = []

    def assessor(_claims, _passages):
        for attempt in range(1, 5):
            record_provider_request()
            admitted.append(attempt)

    monkeypatch.setattr(
        probe, "make_llm_batch_assessor", lambda _model: (assessor, "test-assessor")
    )

    assert probe.main() == 1
    assert admitted == [1, 2, 3]
    record = json.loads(output.read_text())
    assert record["error_type"] == "LLMCallBudgetExceededError"
    assert record["batch_invocations"] == [{"claims": 4, "passages": 4}]
    assert record["physical_requests"] == []
    assert record["physical_request_count"] == 0


def test_live_probe_rejects_assessor_hash_drift_before_catalog_or_provider(
    monkeypatch, tmp_path
) -> None:
    probe = _probe(monkeypatch)
    output = tmp_path / "drift.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    monkeypatch.setenv("QUALIFICATION_TRIAL", "1")
    monkeypatch.setenv("QUALIFICATION_REVISION", probe.head_revision())

    actual_sources = probe.assessor_source_hashes()
    drifted_sources = {
        module: dict(source) for module, source in actual_sources.items()
    }
    first_module = next(iter(drifted_sources))
    drifted_sources[first_module]["sha256"] = "0" * 64
    monkeypatch.setattr(probe, "assessor_source_hashes", lambda: drifted_sources)

    catalog_calls = []
    assessor_factory_calls = []
    monkeypatch.setattr(
        probe,
        "current_catalog",
        lambda: catalog_calls.append("catalog") or {"test-model": {}},
    )
    monkeypatch.setattr(probe, "verify_model", lambda *_args: None)
    monkeypatch.setattr(
        probe,
        "make_llm_batch_assessor",
        lambda _model: (
            assessor_factory_calls.append("factory") or (lambda *_args: []),
            "test",
        ),
    )

    @contextmanager
    def capture(*_args, **_kwargs):
        yield {"started": True}

    monkeypatch.setattr(probe, "capture_panel", capture)
    probe.observer._REQUESTS.clear()

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert catalog_calls == []
    assert assessor_factory_calls == []
    assert record["assessor_sources"] == drifted_sources
    assert record["error_type"] == "ValueError"
    assert first_module in record["error"]
    assert record["physical_requests"] == []
    assert record["physical_request_count"] == 0
    assert record["batch_invocations"] == []


@pytest.mark.parametrize(
    ("quote", "label", "method"),
    [
        (
            "Treatment S did not increase migration of adult human fibroblasts after 24 hours",
            "contradicts",
            "lexical_founded",
        ),
        (
            "Treatment S did not increase migration of adult human fibroblasts after 24 hours; it decreased migration.",
            "contradicts",
            "lexical_founded",
        ),
        ("it decreased migration.", "insufficient", "contradiction_guard_rejected"),
    ],
)
def test_run_batch_exercises_the_real_batch_adapter_offline(
    monkeypatch, quote, label, method
) -> None:
    """A schema-shaped provider reply reaches all four recorded checks."""
    probe = _probe(monkeypatch)
    dataset, preflight = probe.load_frozen_panel()
    texts = [item["passages"][0] for item in dataset["items"]]
    replies = []

    async def completion(**_kwargs):
        prompt = "\n".join(message["content"] for message in _kwargs["messages"])
        for requirement in (
            "shortest self-contained verbatim span",
            "explicitly named subject",
            "conditions needed to interpret the finding",
            "Never cite a pronoun-only or otherwise context-dependent fragment",
            "If no self-contained span fits within 200 characters, choose INSUFFICIENT",
        ):
            assert requirement in prompt
        positions = [
            next(i for i in range(1, 5) if f"[{i}] {text}" in prompt) for text in texts
        ]
        replies.append(1)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "verdicts": [
                                    {
                                        "index": 1,
                                        "label": "partial",
                                        "supporting": [
                                            {"passage": positions[0], "quote": texts[0]}
                                        ],
                                        "contradicting": [],
                                    },
                                    {
                                        "index": 2,
                                        "label": "supports",
                                        "supporting": [
                                            {"passage": positions[1], "quote": texts[1]}
                                        ],
                                        "contradicting": [],
                                    },
                                    {
                                        "index": 3,
                                        "label": "insufficient",
                                        "supporting": [],
                                        "contradicting": [],
                                    },
                                    {
                                        "index": 4,
                                        "label": "contradicts",
                                        "supporting": [],
                                        "contradicting": [
                                            {"passage": positions[3], "quote": quote}
                                        ],
                                    },
                                ]
                            }
                        )
                    )
                )
            ]
        )

    import litellm
    from co_scientist import llm_request

    async def allow_request(*_args, **_kwargs):
        return None

    monkeypatch.setattr(litellm, "acompletion", completion)
    monkeypatch.setattr(llm_request, "enforce_free_request", allow_request)
    assessor, assessor_id = probe.make_llm_batch_assessor("deepseek/deepseek-chat")
    result = probe.run_batch(dataset, assessor, assessor_id)

    assert len(replies) == 1
    assert [check["label"] for check in result["checks"]] == [
        *preflight["expected_labels"][:3],
        label,
    ]
    assert result["checks"][3]["verification_method"] == method


def test_main_retains_finalized_panel_evidence_and_redacts_failures(
    monkeypatch, tmp_path
) -> None:
    """A failure inside the panel keeps its final telemetry and hides the key."""
    probe = _probe(monkeypatch)
    output = tmp_path / "failure.json"
    monkeypatch.setenv("QUALIFICATION_OUTPUT", str(output))
    monkeypatch.setenv("QUALIFICATION_TRIAL", "1")
    monkeypatch.setenv(
        "QUALIFICATION_REVISION",
        subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    )
    monkeypatch.setattr(probe, "current_catalog", lambda: {"test-model": {}})
    monkeypatch.setattr(probe, "verify_model", lambda *_args: None)

    @contextmanager
    def capture(*_args, **_kwargs):
        evidence = {"started": True}
        try:
            yield evidence
        finally:
            evidence["finished"] = True

    monkeypatch.setattr(probe, "capture_panel", capture)
    monkeypatch.setattr(
        probe, "make_llm_batch_assessor", lambda *_args: (None, "llm:test")
    )
    monkeypatch.setattr(
        probe,
        "run_batch",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("test-key")),
    )

    assert probe.main() == 1
    record = json.loads(output.read_text())
    assert {
        "app.claim_verifier_batch",
        "app.claims_batch",
        "app.claim_verifier",
        "app.claim_verifier_opposition",
        "app.claims_assessor",
        "app.claims_span",
        "app.claims_gate",
        "co_scientist.llm",
    } <= set(record["assessor_sources"])
    assert record["panel_evidence"] == {"started": True, "finished": True}
    assert record["error"] == "[redacted]"
