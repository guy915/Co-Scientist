"""arXiv/bioRxiv response envelopes reach both search paths that use them.

Literature review's ``normalize_search_response`` and validation's
``ResponseParser`` both read the same ``results_path``/``field_mapping``
config, so a tool with none declared fails each differently -- loudly on
literature review (an AttributeError against a bare string), silently on
validation (the parser logs and skips a titleless item, reading as "found
nothing"). These drive a real envelope, shaped exactly like the reference
MCP server's ``search_arxiv``/``search_biorxiv``, through both paths using
the shipped default ``tools.yaml`` config -- not a synthetic fixture -- so
a regression in either tool's ``response_format`` fails here.
"""

from typing import Any

import pytest

from co_scientist.agents.generation.literature_tools.validate_search import (
    _NoveltySearchContext,
    _search_papers_via_tool_config,
)
from co_scientist.config import ToolConfig, ToolRegistry
from co_scientist.evidence.search_support import (
    normalize_search_response,
)
from tests._mcp import FakeCallToolClient


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    """The shipped default tool/workflow configuration."""
    return ToolRegistry(skip_user_config=True)


def _arxiv_envelope() -> dict[str, Any]:
    """A response shaped exactly like the reference server's search_arxiv."""
    return {
        "source": "arXiv",
        "query": "resistance reversal",
        "records": [
            {
                "source_id": "2401.01234",
                "title": "A Model of Resistance Reversal",
                "abstract": "An abstract.",
                "year": 2024,
                "authors": ["Jane Doe"],
                "doi": None,
                "is_preprint": True,
                "url": "http://arxiv.org/abs/2401.01234v2",
            }
        ],
    }


def _biorxiv_envelope() -> dict[str, Any]:
    """A response shaped exactly like the reference server's search_biorxiv."""
    return {
        "source": "bioRxiv",
        "query": "resistance reversal",
        "records": [
            {
                "source_id": "PPR/42387642",
                "title": "PKMYT1 in Cancer",
                "abstract": "PKMYT1 has emerged as a target.",
                "year": "2026",
                "authors": "Li Y, Chen X.",
                "doi": "10.1002/gcc.70151",
                "is_preprint": True,
                "url": "https://doi.org/10.1002/gcc.70151",
            }
        ],
    }


def _tool(registry: ToolRegistry, tool_id: str) -> ToolConfig:
    tool_config = registry.get_tool(tool_id)
    assert tool_config is not None, f"{tool_id} must be configured"
    return tool_config


@pytest.mark.parametrize(
    ("tool_id", "envelope", "expected_source_id"),
    [
        ("arxiv_search", _arxiv_envelope(), "2401.01234"),
        ("biorxiv_search", _biorxiv_envelope(), "PPR/42387642"),
    ],
)
def test_the_envelope_normalizes_for_literature_review(
    registry: ToolRegistry,
    tool_id: str,
    envelope: dict[str, Any],
    expected_source_id: str,
) -> None:
    """Phase 2's normalizer re-keys the envelope's records by source_id.

    Without ``results_path: "records"`` the three envelope keys
    (source/query/records) would be taken for paper ids and every real
    record dropped.
    """
    normalized = normalize_search_response(envelope, _tool(registry, tool_id))

    assert expected_source_id in normalized
    assert normalized[expected_source_id]["title"]


@pytest.mark.parametrize(
    ("tool_id", "envelope", "expected_title"),
    [
        ("arxiv_search", _arxiv_envelope(), "A Model of Resistance Reversal"),
        ("biorxiv_search", _biorxiv_envelope(), "PKMYT1 in Cancer"),
    ],
)
async def test_the_envelope_parses_for_validation(
    registry: ToolRegistry,
    tool_id: str,
    envelope: dict[str, Any],
    expected_title: str,
) -> None:
    """Validation's ResponseParser reads the same envelope to a paper dict.

    Unlike literature review, a missing/wrong results_path here degrades
    silently: the parser logs and skips a titleless item rather than
    raising, so a broken config would just report "nothing found" instead
    of failing loudly -- this drives the actual production call path
    (``_search_papers_via_tool_config``) rather than the parser alone.
    """
    mcp_client = FakeCallToolClient(envelope)

    papers = await _search_papers_via_tool_config(
        _tool(registry, tool_id),
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=None,
            shared_slug="slug-1",
            run_id="run-1",
        ),
        max_papers=5,
    )

    assert papers, "a real envelope must not parse to zero papers"
    (paper,) = papers.values()
    assert paper["title"] == expected_title
