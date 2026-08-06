"""Tests for tool-based generation phases 1 (draft) and 2 (validate).

``draft_hypotheses`` runs a tool-calling agent (``call_llm_with_tools``) and
parses the final JSON response into draft dicts; these tests stub that single
LLM seam and exercise the real fence-stripping / ``attempt_json_repair`` parsing
logic. ``validate_hypotheses`` runs a per-paper novelty pass
(``call_llm_json``), a synthesis pass (``call_llm_with_tools``), and assembles
``Hypothesis`` objects; these tests stub both LLM seams plus the MCP paper
search so the deterministic assembly logic is asserted directly.

Shared seams stubbed in both phases:
  * ``call_llm_with_tools`` / ``call_llm_json`` -- the LLM calls. Prompt
    saving lives inside the real wrappers, so stubbing them also keeps the
    prompt debug files off the filesystem.
  * ``co_scientist.config.get_tool_registry`` -- patched to raise so the
    ``tool_registry=None`` "no registry" fallback path is taken (otherwise the
    real global default registry would load config from disk). With no
    whitelist the ``MCPToolProvider`` skips MCP and yields zero tools.
``attempt_json_repair`` is deliberately *not* stubbed: the tests rely on its
real behavior.
"""

import json
from typing import Any

import pytest

from co_scientist import config as config_mod
from co_scientist.agents.generation.literature_tools import (
    draft as draft_mod,
)
from co_scientist.agents.generation.literature_tools import (
    validate as validate_mod,
)
from co_scientist.agents.generation.literature_tools.draft import (
    draft_hypotheses,
)
from co_scientist.agents.generation.literature_tools.validate import (
    validate_hypotheses,
)
from co_scientist.constants import corpus_slug
from co_scientist.exceptions import ResponseParseError
from co_scientist.models import GenerationMethod, Hypothesis
from tests._mcp import FakeCallToolClient
from tests._state import make_state

# -----------------------------------------------------------------------------
# Shared fixtures / fakes
# -----------------------------------------------------------------------------


# The MCP client here is the shared ``FakeCallToolClient``, which
# implements ``call_tool`` and nothing else. That is enough because
# ``MCPToolProvider`` only reaches for ``get_tools``/``execute_tool_call``
# when a whitelist is supplied; with the registry disabled neither runs,
# leaving ``call_tool`` (the legacy paper-search fallback) as the only
# method under test. Its canned response is the papers dict a search
# returns.


class _FakeReferenceIndex:
    """Stand-in for a citation reference index (``.text`` / ``.sources``)."""

    def __init__(self, text: str, sources: dict[str, dict[str, Any]]) -> None:
        self.text = text
        self.sources = sources


def _disable_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the no-registry fallback in both generation phases.

    ``get_tool_registry`` is imported locally (``from co_scientist.config
    import get_tool_registry``) so it is patched at its source module; making it
    raise drives both phases down the documented "No tool registry" branch.
    """

    def _raise(*_: Any, **__: Any) -> Any:
        raise RuntimeError("registry disabled for test")

    monkeypatch.setattr(config_mod, "get_tool_registry", _raise)


def _stub_draft_llm(
    monkeypatch: pytest.MonkeyPatch, final_response: str
) -> None:
    """Stub ``draft.call_llm_with_tools`` to return a fixed final response."""

    async def fake(**_: Any) -> tuple[str, list[Any]]:
        return final_response, []

    monkeypatch.setattr(draft_mod, "call_llm_with_tools", fake)


# -----------------------------------------------------------------------------
# draft_hypotheses
# -----------------------------------------------------------------------------


async def test_draft_parses_plain_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare JSON object yields the parsed list of draft dicts verbatim."""
    _disable_registry(monkeypatch)
    drafts = [
        {
            "text": "alpha gates the pathway",
            "gap_reasoning": "no prior work on alpha",
            "literature_sources": "Smith 2020",
        },
        {
            "text": "beta inhibits the pathway",
            "gap_reasoning": "beta understudied",
            "literature_sources": "Jones 2021",
        },
    ]
    _stub_draft_llm(monkeypatch, json.dumps({"drafts": drafts}))

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=2,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == drafts
    assert result[0]["text"] == "alpha gates the pathway"
    assert result[1]["gap_reasoning"] == "beta understudied"


async def test_draft_strips_json_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ```json fenced response is unwrapped before parsing."""
    _disable_registry(monkeypatch)
    drafts = [{"text": "fenced hypothesis", "gap_reasoning": "gap"}]
    fenced = "```json\n" + json.dumps({"drafts": drafts}) + "\n```"
    _stub_draft_llm(monkeypatch, fenced)

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=1,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == drafts


async def test_draft_repairs_trailing_comma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed response with a trailing comma is repaired, not rejected."""
    _disable_registry(monkeypatch)
    # Trailing comma after the array element -- invalid JSON that
    # attempt_json_repair fixes via its minor-repair path.
    malformed = '{"drafts": [{"text": "repaired hypothesis"},]}'
    _stub_draft_llm(monkeypatch, malformed)

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=1,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == [{"text": "repaired hypothesis"}]


async def test_draft_missing_drafts_key_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed object lacking a 'drafts' key defaults to an empty list."""
    _disable_registry(monkeypatch)
    _stub_draft_llm(monkeypatch, json.dumps({"notes": "no drafts here"}))

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=2,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == []


async def test_draft_unparseable_response_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response surviving every repair attempt raises ResponseParseError."""
    _disable_registry(monkeypatch)
    # No braces anywhere: attempt_json_repair cannot recover a dict.
    _stub_draft_llm(monkeypatch, "the agent failed to emit any json output")

    with pytest.raises(ResponseParseError):
        await draft_hypotheses(
            state=make_state(),
            count=1,
            mcp_client=FakeCallToolClient({}),
            tool_registry=None,
        )


def test_corpus_slug_is_deterministic() -> None:
    """Draft and validation derive the same corpus slug from the goal."""
    slug = corpus_slug("cure the common cold")
    assert slug == corpus_slug("cure the common cold")
    assert slug.startswith("research_")
    # Deterministic: derived from research_goal via md5, length "research_" + 8.
    assert len(slug) == len("research_") + 8


# -----------------------------------------------------------------------------
# validate_hypotheses
# -----------------------------------------------------------------------------


def _stub_synthesis_llm(
    monkeypatch: pytest.MonkeyPatch, hypotheses: list[dict[str, Any]]
) -> None:
    """Stub ``validate.call_llm_with_tools`` (the synthesis pass)."""

    async def fake(**_: Any) -> tuple[str, list[Any]]:
        return json.dumps({"hypotheses": hypotheses}), []

    monkeypatch.setattr(validate_mod, "call_llm_with_tools", fake)


_TWO_HYPOTHESIS_SYNTHESIS: list[dict[str, Any]] = [
    {
        "hypothesis": "alpha kinase drives resistance",
        "explanation": "the mechanism fits",
        "literature_grounding": "grounded in prior work",
        "experiment": "run the kinase assay",
        "novelty_validation": "no exact prior match found",
    },
    {
        "hypothesis": "beta receptor modulates response",
        "explanation": "downstream signalling",
        "literature_grounding": None,
        "experiment": "knock out beta",
        "novelty_validation": "partially novel",
    },
]


async def test_validate_builds_literature_tools_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis output is assembled into LITERATURE_TOOLS Hypothesis objects.

    Papers search returns empty, so the novelty pass is skipped and only the
    synthesis seam is exercised -- the clean synthesis-only path.
    """
    _disable_registry(monkeypatch)
    _stub_synthesis_llm(monkeypatch, _TWO_HYPOTHESIS_SYNTHESIS)
    drafts = [
        {"text": "draft one", "gap_reasoning": "gap a"},
        {"text": "draft two", "gap_reasoning": "gap b"},
    ]

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=drafts,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert len(result) == 2
    assert all(isinstance(h, Hypothesis) for h in result)
    assert all(
        h.generation_method == GenerationMethod.LITERATURE_TOOLS for h in result
    )
    assert result[0].text == "alpha kinase drives resistance"
    assert result[0].experiment == "run the kinase assay"
    assert result[0].novelty_validation == "no exact prior match found"
    assert result[1].literature_grounding is None
    # No reference index -> citation_map stays empty.
    assert result[0].citation_map == {}


_PRIOR_ALPHA_PAPERS: dict[str, Any] = {
    "p1": {
        "title": "Prior alpha study",
        "authors": ["Smith"],
        "year": 2020,
        "fulltext": "some body text about alpha",
    }
}

_VALIDATED_ALPHA_SYNTHESIS: list[dict[str, Any]] = [
    {
        "hypothesis": "alpha hypothesis validated",
        "explanation": "fits",
        "experiment": "assay",
    }
]


async def test_validate_runs_novelty_pass_when_papers_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A populated paper search drives the parallel per-paper novelty pass.

    This exercises ``call_llm_json`` (the novelty seam) for real, which the
    empty-papers path never reaches.
    """
    _disable_registry(monkeypatch)
    novelty_calls: list[bool] = []

    async def fake_novelty(**_: Any) -> dict[str, Any]:
        novelty_calls.append(True)
        return {"novelty_assessment": "novel", "key_findings": "kf"}

    monkeypatch.setattr(validate_mod, "call_llm_json", fake_novelty)
    _stub_synthesis_llm(monkeypatch, _VALIDATED_ALPHA_SYNTHESIS)

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=[{"text": "alpha draft"}],
        mcp_client=FakeCallToolClient(_PRIOR_ALPHA_PAPERS),
        tool_registry=None,
    )

    # The novelty pass ran once for the single found paper.
    assert novelty_calls == [True]
    assert len(result) == 1
    assert result[0].text == "alpha hypothesis validated"
    assert result[0].generation_method == GenerationMethod.LITERATURE_TOOLS


async def test_validate_empty_drafts_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No drafts means no synthesis batches and an empty result list."""
    _disable_registry(monkeypatch)

    called: list[bool] = []

    async def fake_synth(**_: Any) -> tuple[str, list[Any]]:
        called.append(True)
        return json.dumps({"hypotheses": []}), []

    monkeypatch.setattr(validate_mod, "call_llm_with_tools", fake_synth)

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=[],
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == []
    # Zero batches -> the synthesis LLM is never invoked.
    assert called == []


async def test_validate_text_fallback_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis output using 'text' (not 'hypothesis') is still assembled."""
    _disable_registry(monkeypatch)
    _stub_synthesis_llm(
        monkeypatch,
        [
            {
                "text": "fallback-keyed hypothesis",
                "explanation": "uses text key",
            }
        ],
    )

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=[{"text": "d"}],
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert len(result) == 1
    assert result[0].text == "fallback-keyed hypothesis"
    assert result[0].experiment is None


async def test_validate_resolves_citation_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A [C*] key in the grounding resolves against the reference index."""
    _disable_registry(monkeypatch)
    _stub_synthesis_llm(
        monkeypatch,
        [
            {
                "hypothesis": "cited hypothesis",
                "explanation": "fits",
                "literature_grounding": "as shown in [C1] the effect holds",
                "experiment": "assay",
            }
        ],
    )
    ref_index = _FakeReferenceIndex(
        text="[C1] Smith 2020",
        sources={"C1": {"type": "paper", "title": "Smith 2020"}},
    )

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=[{"text": "d"}],
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
        reference_index=ref_index,
    )

    assert len(result) == 1
    assert result[0].citation_map == {
        "C1": {"type": "paper", "title": "Smith 2020"}
    }
