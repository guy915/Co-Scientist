"""Tests for the pure helpers in ``reflection_helpers``.

These cover the network-free heuristics: the all-caps gene/protein name
extractor, the workflow-to-MCP-tool-name resolver (which gates whether any
INDRA calls happen at all), the JSON tool-result parser, and the evidence
formatters. ``fetch_indra_evidence`` is only exercised on its
``tool_registry=None`` short-circuit, which returns before any MCP I/O.
"""

from typing import Any, cast

from co_scientist.config import ToolRegistry
from co_scientist.nodes.reflection_helpers import _build_enrichment_items
from co_scientist.nodes.reflection_helpers import _ev_count_str
from co_scientist.nodes.reflection_helpers import _format_single_statement
from co_scientist.nodes.reflection_helpers import _normalize_entity
from co_scientist.nodes.reflection_helpers import _parse_tool_result
from co_scientist.nodes.reflection_helpers import extract_entity_names
from co_scientist.nodes.reflection_helpers import fetch_indra_evidence
from co_scientist.nodes.reflection_helpers import get_kg_tools_for_workflow


class _FakeRegistry:
    """Minimal duck-typed stand-in for the two ToolRegistry methods used.

    ``get_kg_tools_for_workflow`` only calls ``get_tools_for_workflow`` and
    ``get_mcp_tool_names``, so the test fake implements just those. Either
    method may be configured to raise, to exercise the helper's exception
    swallow.
    """

    def __init__(
        self,
        tool_ids: list[str],
        mcp_names: list[str],
        raise_on_workflow: bool = False,
    ) -> None:
        self._tool_ids = tool_ids
        self._mcp_names = mcp_names
        self._raise_on_workflow = raise_on_workflow

    def get_tools_for_workflow(self, workflow_name: str) -> list[str]:
        """Return configured tool IDs, or raise if asked to."""
        del workflow_name
        if self._raise_on_workflow:
            raise RuntimeError("boom")
        return self._tool_ids

    def get_mcp_tool_names(self, tool_ids: list[str]) -> list[str]:
        """Return configured MCP tool names for the given IDs."""
        del tool_ids
        return self._mcp_names


def _fake(
    tool_ids: list[str],
    mcp_names: list[str],
    raise_on_workflow: bool = False,
) -> ToolRegistry:
    """Build a fake registry typed as ToolRegistry for the helper signature."""
    return cast(
        ToolRegistry,
        _FakeRegistry(tool_ids, mcp_names, raise_on_workflow),
    )


# --- extract_entity_names -------------------------------------------------


def test_extract_entity_names_basic() -> None:
    """All-caps tokens and hyphenated bio names are extracted and normalized."""
    result = extract_entity_names("IL-6 activates TREM2 in microglia")
    # IL-6 -> IL6 (hyphen stripped, captured in pass 1); TREM2 in pass 2.
    assert result == ["IL6", "TREM2"]


def test_extract_entity_names_requires_all_caps() -> None:
    """Title/lowercase gene names are not extracted: the rule is all-caps."""
    assert extract_entity_names("Kras drives growth") == []


def test_extract_entity_names_no_entities_returns_empty() -> None:
    """Ordinary prose with no all-caps tokens yields an empty list."""
    assert extract_entity_names("the quick brown fox jumps") == []


def test_extract_entity_names_filters_stopwords() -> None:
    """All-caps non-gene abbreviations in the stop set are dropped."""
    # DNA and RNA are both in _STOP; AND is too.
    assert extract_entity_names("DNA and RNA bind") == []


def test_extract_entity_names_skips_mutation_notation() -> None:
    """Standalone tokens whose 2nd char is a digit (e.g. G12C) are skipped."""
    # KRAS survives; the mutation notation G12C is dropped.
    assert extract_entity_names("KRAS G12C variant") == ["KRAS"]


def test_extract_entity_names_digit_skip_precedes_alias() -> None:
    """P53 is dropped by the pass-2 digit-skip before alias mapping runs."""
    # Second char of "P53" is a digit, so it is skipped before _ALIAS_MAP
    # (P53 -> TP53) would ever apply.
    assert extract_entity_names("P53 pathway") == []


def test_extract_entity_names_applies_alias_map() -> None:
    """Known informal aliases are mapped to canonical symbols (RAGE -> AGER)."""
    assert extract_entity_names("RAGE signaling") == ["AGER"]


def test_extract_entity_names_two_letter_only_via_hyphen() -> None:
    """Two-letter symbols match only through the hyphenated form, not in prose.

    The standalone regex requires >=3 chars, so a bare "IL" never matches; the
    "IL" inside "IL-6" is captured (as IL6) and its prefix is marked seen.
    """
    assert extract_entity_names("IL-6 and IL together") == ["IL6"]


def test_extract_entity_names_deduplicates() -> None:
    """A repeated hyphenated name yields a single normalized entry."""
    # YKL-40 -> CHI3L1 via alias; the duplicate is collapsed.
    assert extract_entity_names("YKL-40 and YKL-40 again") == ["CHI3L1"]


def test_extract_entity_names_respects_max_entities_cap() -> None:
    """The final result is capped at max_entities."""
    text = "KRAS TREM2 APOE TP53 BRAF"
    assert extract_entity_names(text, max_entities=2) == ["KRAS", "TREM2"]
    assert len(extract_entity_names(text, max_entities=4)) == 4


# --- _normalize_entity ----------------------------------------------------


def test_normalize_entity_strips_hyphen() -> None:
    """Hyphens are removed from bio names with no alias entry."""
    assert _normalize_entity("IL-6") == "IL6"


def test_normalize_entity_applies_alias() -> None:
    """An informal name is rewritten to its canonical symbol."""
    assert _normalize_entity("RAGE") == "AGER"


# --- get_kg_tools_for_workflow --------------------------------------------


def test_get_kg_tools_none_registry_returns_empty() -> None:
    """No registry configured means no KG tools, so the gate stays closed."""
    assert get_kg_tools_for_workflow(None, "reflection") == []


def test_get_kg_tools_no_tool_ids_returns_empty() -> None:
    """A registry that lists no tools for the workflow returns an empty list."""
    registry = _fake(tool_ids=[], mcp_names=["unused"])
    assert get_kg_tools_for_workflow(registry, "reflection") == []


def test_get_kg_tools_returns_mcp_names() -> None:
    """With configured tools, the resolved MCP tool names are returned."""
    registry = _fake(
        tool_ids=["indra_a", "indra_b"],
        mcp_names=["get_relations", "get_complexes"],
    )
    assert get_kg_tools_for_workflow(registry, "reflection") == [
        "get_relations",
        "get_complexes",
    ]


def test_get_kg_tools_swallows_exception() -> None:
    """A registry that raises is caught and yields an empty list."""
    registry = _fake(tool_ids=["x"], mcp_names=["y"], raise_on_workflow=True)
    assert get_kg_tools_for_workflow(registry, "reflection") == []


# --- fetch_indra_evidence short-circuit -----------------------------------


async def test_fetch_indra_evidence_none_registry_short_circuits() -> None:
    """With no registry the coroutine returns the empty result without I/O."""
    result = await fetch_indra_evidence("KRAS drives tumor growth",
                                        tool_registry=None)
    assert result == {"prompt_text": "", "enrichment_items": []}


# --- _parse_tool_result ---------------------------------------------------


def test_parse_tool_result_valid_json_string() -> None:
    """A JSON string is decoded into a dict."""
    assert _parse_tool_result('{"statements": [1, 2]}') == {
        "statements": [1, 2]
    }


def test_parse_tool_result_invalid_json_string() -> None:
    """A non-JSON string falls back to an empty dict."""
    assert _parse_tool_result("not json") == {}


def test_parse_tool_result_dict_passthrough() -> None:
    """An already-parsed dict is returned unchanged."""
    payload: dict[str, Any] = {"statements": []}
    assert _parse_tool_result(payload) == payload


def test_parse_tool_result_other_type_returns_empty() -> None:
    """A non-string, non-dict input yields an empty dict."""
    assert _parse_tool_result(42) == {}


# --- _ev_count_str --------------------------------------------------------


def test_ev_count_str_below_limit() -> None:
    """Counts below the fetch limit render as a plain number."""
    assert _ev_count_str(24) == "24"


def test_ev_count_str_at_limit_marks_truncation() -> None:
    """Counts at or above the limit gain a trailing '+' to signal truncation."""
    assert _ev_count_str(25) == "25+"


# --- _format_single_statement ---------------------------------------------


def test_format_single_statement_subject_object() -> None:
    """A subj/obj statement renders as a directed relationship line."""
    line = _format_single_statement({
        "type": "Activation",
        "belief": 0.9,
        "evidence": [1, 2],
        "subj": {"name": "KRAS"},
        "obj": {"name": "BRAF"},
    })
    assert line == "- KRAS --[Activation]--> BRAF (belief: 0.90, 2 papers)"


def test_format_single_statement_complex_members() -> None:
    """A members-only statement renders as a Complex(...) line."""
    line = _format_single_statement({
        "type": "Complex",
        "belief": 0.8,
        "evidence": [],
        "members": [{"name": "A"}, {"name": "B"}],
    })
    assert line == "- Complex(A, B) [Complex] (belief: 0.80, 0 papers)"


def test_format_single_statement_empty_when_no_agents() -> None:
    """A statement with neither subj/obj nor members renders as empty."""
    assert _format_single_statement({"type": "Unknown"}) == ""


# --- _build_enrichment_items ----------------------------------------------


def test_build_enrichment_items_injects_queried_entities_on_first() -> None:
    """Only the first item carries the queried_entities annotation."""
    items = _build_enrichment_items(
        [
            {
                "type": "Activation",
                "belief": 0.9,
                "evidence": [1, 2],
                "subj": {"name": "KRAS"},
                "obj": {"name": "BRAF"},
            },
            {
                "type": "Complex",
                "belief": 0.8,
                "evidence": [],
                "members": [{"name": "A"}, {"name": "B"}],
            },
        ],
        ["KRAS", "TREM2"],
    )
    assert len(items) == 2
    assert items[0]["relationship"] == "KRAS → BRAF"
    assert items[0]["belief"] == "90%"
    assert items[0]["evidence_count"] == "2"
    assert items[0]["queried_entities"] == "KRAS, TREM2"
    assert items[1]["relationship"] == "Complex(A, B)"
    assert "queried_entities" not in items[1]


def test_build_enrichment_items_empty_input_returns_empty() -> None:
    """No statements (or only unconvertible ones) yields an empty list."""
    assert _build_enrichment_items([], ["KRAS"]) == []
    assert _build_enrichment_items([{"type": "X"}], ["KRAS"]) == []
