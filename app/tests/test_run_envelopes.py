"""Per-tier call envelopes, measured on the deterministic offline backend.

Each tier runs end to end through the durable worker with a fake MCP server and a
position-consistent judge (`_envelope_fakes`), so retrieval, observation, claim
and debate paths take the branches a production run takes. An in-memory tracer
attributes every physical request to its task and prompt.

The ceilings sit about 8% above the largest of repeated runs: hypothesis ids
and fan-out order vary between runs, and the counts move with them by a few
percent. Lower a ceiling when a change lowers its tier; never raise one to make
a regression pass. Set METER_OUT to a directory to write each tier's breakdown
as JSON for before/after comparisons.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import os
import re
from typing import Any

import pytest
from co_scientist.platform.db import runs
from co_scientist.platform.db.models import RunStatus
from co_scientist.platform.llm.offline import llm as offline_llm
from co_scientist.platform.llm.request import backend
from co_scientist.platform.telemetry import tracing
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests._store_helpers import drive_offline_run, seed_run

from ._envelope_fakes import FakeMCPClient, mcp_tool_names, realistic_answer
from ._llm_fake_backend import load_engine_fake
from ._process_mode_helpers import FakeProcessMode


@dataclasses.dataclass(frozen=True)
class Envelope:
    calls: int
    max_tokens: int


# Lane E targets on live runs: Express <= 50 calls and <= 500k tokens, Standard
# <= 2M tokens, Ultra <= 15M tokens. These offline ceilings fall as the work lands.
CEILINGS: dict[str, Envelope] = {
    "express": Envelope(calls=100, max_tokens=1_150_000),
    "standard": Envelope(calls=180, max_tokens=2_000_000),
    "extended": Envelope(calls=280, max_tokens=3_150_000),
    "ultra": Envelope(calls=420, max_tokens=4_600_000),
}

# Owner's phase split for the final-check Express run.
_PHASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claims", ("claim_verifier",)),
    ("plan_literature", ("supervisor", "literature_review")),
    ("generation", ("generation", "generate")),
    ("critique", ("reflection", "review", "verification", "safety")),
    ("tournament", ("ranking",)),
    ("loop", ("meta_review", "evolve", "proximity", "orchestrator")),
    ("overview", ("research_overview",)),
)
_UUID = re.compile(r"_[0-9a-f]{8}-[0-9a-f-]+$")
_INDEX = re.compile(r"(_\d+)+(?=_|$)")


def _phase(node: str, prompt: str) -> str:
    for phase, markers in _PHASES:
        if any(marker in prompt or marker in node for marker in markers):
            return phase
    return "other"


@pytest.fixture(autouse=True)
def _isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backend, "_installed", backend._installed)
    monkeypatch.setattr(offline_llm, "_installed", False)


class _RecordingBackend:
    """Records prompt size per attempt and makes the double's answers realistic."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.prompt_chars: dict[int, int] = {}

    async def complete(self, **kwargs: Any) -> Any:
        messages = kwargs.get("messages") or [{}]
        prompt = str(messages[-1].get("content") or "")
        attempt = trace.get_current_span().get_span_context().span_id
        self.prompt_chars[attempt] = sum(len(str(m.get("content") or "")) for m in messages)
        response = await self._inner.complete(**kwargs)
        schema = (kwargs.get("response_format") or {}).get("json_schema") or {}
        message = response.choices[0].message
        message.content = realistic_answer(prompt, message.content, str(schema.get("name") or ""))
        return response

    def supports_json_schema(self, model_name: str) -> bool:
        return bool(self._inner.supports_json_schema(model_name))


def _install_production_shape(
    monkeypatch: pytest.MonkeyPatch, process: FakeProcessMode
) -> tuple[InMemorySpanExporter, _RecordingBackend]:
    from co_scientist.core.config import settings
    from co_scientist.platform.retrieval import mcp_client

    for field in ("provider_client_calls_per_day", "provider_host_calls_per_day"):
        monkeypatch.setattr(settings, field, 100_000)
    for field in ("provider_client_tokens_per_day", "provider_host_tokens_per_day"):
        monkeypatch.setattr(settings, field, 10**12)
    monkeypatch.setattr(settings, "semantic_safety_model", offline_llm.DEFAULT_OFFLINE_MODEL)
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "1")
    # Claim and safety assessors take their model path only outside offline
    # mode; the run's offline model still answers every call.
    process.online(credential=True)

    async def _escaped(**kwargs: Any) -> Any:
        raise AssertionError(f"a call escaped the offline router: {kwargs.get('model')!r}")

    load_engine_fake().install_fake_backend(monkeypatch, _escaped)
    offline_llm.install_offline_router()
    recorder = _RecordingBackend(backend.active_backend())
    backend.install_backend(recorder)

    FakeMCPClient.names = mcp_tool_names()
    monkeypatch.setattr(mcp_client, "MultiServerMCPClient", FakeMCPClient)
    mcp_client.reset_mcp_client()

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_provider", provider)
    return exporter, recorder


def _ancestor(span: ReadableSpan | None, prefix: str, spans: dict[int, ReadableSpan]) -> Any:
    while span is not None:
        if span.name.startswith(prefix):
            return span
        span = spans.get(span.parent.span_id) if span.parent else None
    return None


@dataclasses.dataclass
class _Usage:
    calls: int = 0
    max_tokens: int = 0
    prompt_chars: int = 0


def _measure(exporter: InMemorySpanExporter, recorder: _RecordingBackend) -> dict[str, Any]:
    spans = {span.context.span_id: span for span in exporter.get_finished_spans()}
    by_call: dict[tuple[str, str, str], _Usage] = collections.defaultdict(_Usage)
    for span in spans.values():
        if not span.name.startswith("chat "):
            continue
        task = _ancestor(span, "task.execute", spans)
        call = _ancestor(span, "llm.call", spans)
        node = str(task.attributes.get("co_scientist.task.node", "")) if task else ""
        prompt = str(call.attributes.get("co_scientist.llm.prompt_name", "")) if call else ""
        prompt = _INDEX.sub("", _UUID.sub("", prompt)) or "unnamed"
        node = node.removeprefix("engine.")
        usage = by_call[(_phase(node, prompt), node, prompt)]
        usage.calls += 1
        budget = (span.attributes or {}).get("gen_ai.request.max_tokens", 0)
        usage.max_tokens += budget if isinstance(budget, int) else 0
        parent = span.parent.span_id if span.parent else 0
        usage.prompt_chars += recorder.prompt_chars.get(parent, 0)
    phases: dict[str, _Usage] = collections.defaultdict(_Usage)
    for (phase, _, _), usage in by_call.items():
        phases[phase].calls += usage.calls
        phases[phase].max_tokens += usage.max_tokens
        phases[phase].prompt_chars += usage.prompt_chars
    return {
        "calls": sum(u.calls for u in phases.values()),
        "max_tokens": sum(u.max_tokens for u in phases.values()),
        "prompt_chars": sum(u.prompt_chars for u in phases.values()),
        "phases": {name: dataclasses.asdict(u) for name, u in sorted(phases.items())},
        "calls_by_prompt": [
            [phase, node, prompt, u.calls, u.max_tokens, u.prompt_chars]
            for (phase, node, prompt), u in sorted(by_call.items())
        ],
    }


@pytest.mark.parametrize("tier", list(CEILINGS))
def test_offline_run_stays_inside_its_tier_envelope(
    tier: str,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    fake_process_mode: FakeProcessMode,
) -> None:
    exporter, recorder = _install_production_shape(monkeypatch, fake_process_mode)
    run = seed_run(
        "Explain how molecular crowding changes the folding pathway of protein X.",
        profile=tier,
        provider="mock",
        config={"tier": tier, "llm_backend": "offline"},
        client_id=f"envelope-{tier}",
        llm_backend="offline",
        db_path=isolated_db,
    )

    drive_offline_run(run, db_path=isolated_db, worker=f"envelope-{tier}")

    final = runs.get_run(run.id, db_path=isolated_db)
    assert final is not None
    assert final.status == RunStatus.COMPLETED.value, "an unfinished run measures nothing"
    measured = _measure(exporter, recorder)
    nodes = {node for _, node, *_ in measured["calls_by_prompt"]}
    assert "literature_review" in nodes, "the fake MCP server went unused; the meter is blind"
    if out := os.environ.get("METER_OUT"):
        with open(os.path.join(out, f"{tier}.json"), "w") as handle:
            json.dump({"tier": tier, **measured}, handle, indent=1)
    ceiling = CEILINGS[tier]
    breakdown = json.dumps(measured["phases"], indent=1)
    assert measured["calls"] <= ceiling.calls, f"{tier} calls by phase:\n{breakdown}"
    assert measured["max_tokens"] <= ceiling.max_tokens, f"{tier} budget by phase:\n{breakdown}"
