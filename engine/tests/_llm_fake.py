"""Fakes for the ``litellm.acompletion`` boundary.

Also exposes ``disable_llm_cache``, a small shared helper that patches
``co_scientist.llm.precall.get_cache`` (the module where the shared
pre-call sequence ``_prepare_llm_call`` lives) to a disabled cache so the
llm-wrapper and capability-shim unit tests always exercise the real
completion path.

Used by the integration and system tests to run the *real* compiled
LangGraph workflow end-to-end with only the network boundary faked.
Patches ``litellm.acompletion`` directly -- the single external call every
``co_scientist.llm`` entry point (``call_llm``, ``call_llm_json``) funnels
through -- rather than patching individual node modules' imported
``call_llm``/``call_llm_json`` references (the idiom used by the
node-level unit tests, and available here as ``stub_call_llm_json``). This
keeps one patch point instead of one per node module, and it exercises the
real JSON extraction, schema validation, and retry logic in
``co_scientist.llm`` rather than bypassing it.

For a schema'd call (``response_format={"type": "json_schema", ...}``),
``_fill_schema`` builds a minimal value that satisfies the schema: every
"required" property (or, absent a "required" list, every declared
property) is filled recursively, with enums resolved to their first
allowed value -- so closed-vocabulary fields like ranking's "winner" or
deep verification's "verdict" always get a valid, deterministic choice.
Every string leaf gets a unique, incrementing suffix so hypothesis text and
other identity-bearing fields never collide across calls; this matters
because ``co_scientist.state.deduplicate_hypotheses`` merges hypotheses
with equal normalized text, and evolution rejects a refinement that is
identical to (or a near-duplicate of) the original text. A call with no
schema (e.g. a debate's free-form intermediate turn) gets a unique
plain-text reply instead.

Two schemas need an array filled to a length other than the generic
filler's default of one item. The comparative batch-review response's
"reviews" array must have exactly one entry per hypothesis in the batch,
since ``review_node`` maps entries back to hypotheses (by their
``hypothesis_index`` when valid, else by array position) and counts a
short response as failed reviews. The research overview's
"research_directions" array is filled past the report's directions-
preview gate instead of to a prompt-derived count -- see
``co_scientist.offline_llm``'s comment on the two. ``_ARRAY_LENGTH_HINTS``
(imported from ``co_scientist.offline_llm``) wires each by schema name.

The schema-filling traversal (``_fill_schema``, ``_FillHints``) lives in
``co_scientist.offline_schema_fill``; the ``supervisor_allocation``
prompt-flag branch (``_supervisor_allocation_response``) and the
response/prompt shape helpers (``_build_response``, ``_prompt_text``)
live in ``co_scientist.offline_llm``. Both are shared with the production
offline-model router; this module supplies its own leaf-value strategy
(``_next_leaf``, backed by a process-global counter reset only per test
process) rather than the router's per-call seeded RNG, since existing
tests rely on every fake call in a run drawing from one shared sequence,
not just leaves within a single response.
"""

import itertools
import json
import types
from typing import Any

import pytest

from co_scientist import cache
from co_scientist.cache import LLMCache
from co_scientist.generator import GeneratorOptions, HypothesisGenerator
from co_scientist.llm import precall
from co_scientist.offline_llm import (
    _ARRAY_LENGTH_HINTS,
    _prompt_text,
    _supervisor_allocation_response,
)
from co_scientist.offline_llm import (
    _build_response as _fake_response,
)
from co_scientist.offline_schema_fill import _fill_schema, _FillHints

# Shared across every fake call in a test run so no two generated leaves
# (hypothesis text, free-form turns, etc.) ever collide.
_counter = itertools.count(1)


def _next_leaf(_field: str = "") -> str:
    """Returns the next process-wide-unique fake string leaf.

    Takes (and ignores) the property name ``_fill_schema`` now passes: the
    runtime router varies its prose by field, but tests want short,
    obviously-fake, globally unique values instead.

    Returns:
        ``"stub-<n>"`` for the next value of the shared ``_counter``.
    """
    return f"stub-{next(_counter)}"


def disable_llm_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``llm.precall.get_cache`` to hand back a disabled cache.

    A disabled ``LLMCache`` returns ``None`` from ``get`` and no-ops in
    ``set``, so the completion path always runs and nothing leaks between
    tests.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    monkeypatch.setattr(precall, "get_cache", lambda: LLMCache(enabled=False))


def stub_call_llm_json(
    monkeypatch: pytest.MonkeyPatch,
    module: types.ModuleType,
    response: dict[str, Any],
) -> list[dict[str, Any]]:
    """Patch one node module's ``call_llm_json`` to a fixed response.

    The node-level unit-test idiom (see the module docstring): a node
    imports ``call_llm_json`` into its own namespace, so patching that name
    on the node's module replaces its only LLM dependency. The same
    ``response`` comes back regardless of arguments, so in a parallel path
    every item receives an identical result.

    Every invocation is recorded, which callers that only need the stub can
    ignore.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        module: The node module whose imported ``call_llm_json`` to patch.
        response: The dict the stub returns for every call.

    Returns:
        A list the stub appends each call's kwargs to, for spy assertions.
    """
    calls: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return response

    monkeypatch.setattr(module, "call_llm_json", fake)
    return calls


def make_test_generator() -> HypothesisGenerator:
    """Builds a small, fast HypothesisGenerator for the end-to-end tests.

    Sized so a full run stays quick: one iteration, two initial
    hypotheses, two evolution slots, and a two-pair tournament, with the
    LLM cache off so the faked completions above are never replayed from
    an earlier test's on-disk entries.

    Returns:
        A HypothesisGenerator over the fake ``"fake/model"`` name.
    """
    return HypothesisGenerator(
        model_name="fake/model",
        max_iterations=1,
        initial_hypotheses_count=2,
        evolution_max_count=2,
        options=GeneratorOptions(
            tournament_pairs=2,
            enable_cache=False,
        ),
    )


async def _fake_acompletion(**kwargs: Any) -> Any:
    """Stands in for ``litellm.acompletion``: schema-true JSON or free text.

    Args:
        **kwargs: The completion arguments built by
            ``co_scientist.llm._build_completion_args`` (model, messages,
            response_format, ...); only ``response_format`` and the
            outgoing prompt text are inspected.

    Returns:
        A fake completion response exposing
        ``.choices[0].message.content``.
    """
    response_format = kwargs.get("response_format")
    if response_format and response_format.get("type") == "json_schema":
        json_schema = response_format["json_schema"]
        schema = json_schema["schema"]
        if json_schema.get("name") == "supervisor_allocation":
            # Exercise model-directed scheduling with a stable adaptive
            # portfolio: improve leaders first, then explore new regions.
            content = _supervisor_allocation_response(_prompt_text(kwargs))
            return _fake_response(content)
        length_hint = _ARRAY_LENGTH_HINTS.get(json_schema.get("name", ""))
        hints = _FillHints(
            array_lengths=(
                length_hint(_prompt_text(kwargs)) if length_hint else {}
            )
        )
        content = json.dumps(_fill_schema(schema, _next_leaf, hints))
    elif response_format and response_format.get("type") == "json_object":
        # No production call site reaches this branch (every call site
        # that requests JSON also supplies a schema), but it is kept as a
        # safe, schema-less fallback.
        content = "{}"
    else:
        content = f"free-form response {next(_counter)}"
    return _fake_response(content)


def install_fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patches the LLM and cache boundaries for a fast, deterministic run.

    Patches ``litellm.acompletion`` (see module docstring) and forces LLM
    caching off. The cache override resets the process-wide singleton in
    ``co_scientist.cache`` in addition to setting the env var: the
    singleton is memoized on first use and other test modules may have
    already initialized it as enabled earlier in the same pytest process,
    a state a plain env-var override cannot undo.

    Also forces every schema'd call onto the native "json_schema" response
    format, regardless of the (made-up) test model name: real litellm's
    provider registry does not recognize it and reports no json_schema
    support, which would otherwise route every call through the
    json_object provider-capability shim (schema restated as prompt text
    instead of structured ``response_format``) -- a real production path,
    but not the one this fake speaks, since it builds its response from
    the structured schema rather than parsing it back out of prompt text.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    import litellm

    from co_scientist.llm.request import completion

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(
        completion,
        "_supports_json_schema_response_format",
        lambda _model_name: True,
    )
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "false")
    monkeypatch.setattr(cache, "_global_cache", None)


# A schema with a nested required object, shared by the capability-shim
# tests (prompt injection) and the back-fill tests (recursion into
# nested objects) so both exercise the same shape.
NESTED_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_test",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "assessment": {
                "type": "object",
                "properties": {
                    "verdict": {
                        "type": "string",
                        "enum": ["holds", "weakened"],
                    },
                    "notes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["verdict", "notes"],
            },
        },
        "required": ["summary", "assessment"],
    },
}
