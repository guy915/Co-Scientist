"""LLM (NLI) entailment assessor — the swappable semantic claim verifier.

``app/claims.py`` defines the pure entailment machinery and a deterministic
default assessor; this module supplies the real one: an LLM prompted as a
natural-language-inference judge that classifies a claim against retrieved
evidence and cites the exact verbatim quote justifying its verdict. The quote
is located back in the source passage by ``claims.assess_claim`` (with an
anti-hallucination downgrade when it cannot be found), so a verified claim's
support is always traceable to a real span in a real source.

Design choices (documented clone decisions — Google publishes neither model nor
thresholds, SSR §12):
- Temperature 0 so the eval and the golden run are reproducible.
- Schema'd JSON output via the engine's ``call_llm_json`` seam; any
  parse/schema/timeout/provider failure falls back to the deterministic
  assessor rather than failing the grounding pass (best-effort, mirroring
  ``title_gen``/``qa``).
- The public ``Assessor`` protocol (``app.claims_assessor.Assessor``) stays
  synchronous -- both claim-assessment paths run many claims at once on a
  plain ``ThreadPoolExecutor`` (``app.claim_grounding_assess``), so the
  entailment call bridges to the engine's async seam via
  ``app.async_bridge.run_coroutine_sync`` rather than making every assessor
  in the codebase async for this one caller.

Routing through ``co_scientist.llm.call_llm_json`` (rather than calling
``litellm`` directly, as this module used to) means every entailment call
now shares the engine's response cache, per-phase telemetry
(``co_scientist.llm_telemetry.scoped_telemetry`` -- the gate opens
``"claim_gate"``, the finalize grounding pass opens ``"claim_grounding"``),
run-scoped call-budget enforcement (``co_scientist.llm_call_budget``, so
``LLMCallBudgetExceededError`` terminates a run over-spending on claims the
same way it does an engine node), and the thinking-token floor
(``co_scientist.llm_thinking``) -- see the root AGENTS.md finding this
module's docstring used to warn about, now closed.

This module is exercised end-to-end by the golden run (P0.6); the offline
suite fakes ``litellm.acompletion`` (the engine's own completion boundary) to
prove prompt/parse/guard behavior.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from co_scientist.llm import call_llm_json
from co_scientist.llm_json_lists import coerce_json_list
from co_scientist.llm_types import CompletionSpec, LLMCallOptions
from co_scientist.schemas.builders import obj

from app.async_bridge import run_coroutine_sync
from app.claims import (
    Assessor,
    AssessorDraft,
    EntailmentLabel,
    EvidencePassage,
    deterministic_assessor,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a strict natural-language-inference judge for scientific claims. "
    "Given a CLAIM and numbered EVIDENCE passages, decide whether the evidence "
    "SUPPORTS, PARTIALLY supports, CONTRADICTS, or is INSUFFICIENT for the "
    "claim. Rules: judge only from the passages, never outside knowledge. A "
    "passage SUPPORTS only if it entails the claim. It is PARTIAL when it "
    "directly addresses the claim and is consistent with it -- evidence for a "
    "related mechanism, an adjacent finding, or the claim under narrower "
    "conditions -- but does not fully entail it; partial is for genuine "
    "near-misses, not for passages merely sharing a topic. It CONTRADICTS only "
    "if it entails the claim's negation. Otherwise the claim is INSUFFICIENT. "
    "For a supports, partial, or contradicts verdict you MUST cite the exact "
    "VERBATIM quote (copied character-for-character from the passage) that "
    "justifies it, together with that passage's evidence_id; put a partial "
    'verdict\'s quote in "supporting". Do not paraphrase quotes. Respond with '
    "a single JSON object and nothing else."
)

# A ceiling, not a reservation: the verdict JSON is short, and the generous
# cap only matters for an unusually long quote. The chain of thought is not
# funded from here -- the engine's own thinking floor
# (``co_scientist.llm_thinking``) raises whatever budget a thinking model is
# sent with, so reasoning cannot eat the answer's share.
_MAX_TOKENS = 6000

_CITATION_ITEM = obj(
    {
        "evidence_id": {"type": "string"},
        "quote": {"type": "string"},
    }
)

# Accepts a bare citation object as well as the requested array: under the
# json_object downgrade (no server-side schema enforcement -- see the
# gateway model note in the root AGENTS.md) a model can plausibly write a
# single citation unwrapped rather than as a one-element list, and the
# engine's own local schema validation runs even then (see the "Under the
# json_object downgrade" gotcha) -- a plain ``array`` type would reject
# that shape before ``_coerce_pairs`` below ever gets a chance to recover
# it, silently losing a real verdict to the deterministic fallback.
_CITATION_LIST = {
    "oneOf": [{"type": "array", "items": _CITATION_ITEM}, _CITATION_ITEM]
}

# The assessor's raw verdict shape (``AssessorDraft``), enforced server-side
# where the model supports json_schema and reshaped into conformance by the
# engine's json_object downgrade path otherwise (see llm_json._backfill_
# required_fields / _prune_unknown_properties).
_ENTAILMENT_DRAFT_SCHEMA = obj(
    {
        "label": {
            "type": "string",
            "enum": [label.value for label in EntailmentLabel],
        },
        "supporting": _CITATION_LIST,
        "contradicting": _CITATION_LIST,
    }
)


def _render_passages(passages: Sequence[EvidencePassage]) -> str:
    """Render candidate passages as an id-tagged, numbered prompt block."""
    return "\n\n".join(
        f"[{i}] evidence_id={p.evidence_id}\n{p.text}"
        for i, p in enumerate(passages, start=1)
    )


def _coerce_pairs(items: Any, site: str) -> tuple[tuple[str, str], ...]:
    """Coerce a parsed ``[{evidence_id, quote}]``-shaped value to pairs.

    Even under schema enforcement, a single citation can plausibly arrive
    as a bare object rather than wrapped in a one-element list;
    ``coerce_json_list`` recovers that shape before the per-item dict
    fields are read.
    """
    pairs: list[tuple[str, str]] = []
    for item in coerce_json_list(items, element="dict", site=site):
        evidence_id = str(item.get("evidence_id") or "")
        quote = str(item.get("quote") or "")
        if evidence_id and quote:
            pairs.append((evidence_id, quote))
    return tuple(pairs)


def _parse_draft(data: dict[str, Any]) -> AssessorDraft | None:
    """Parse the model's validated JSON reply into an :class:`AssessorDraft`.

    Returns None when the shape is still unusable (an empty/invalid label)
    so the caller can fall back rather than trusting a partial parse --
    defensive even though ``call_llm_json`` has already reshaped the reply
    to satisfy the schema.
    """
    raw_label = str(data.get("label") or "").strip().lower()
    try:
        label = EntailmentLabel(raw_label)
    except ValueError:
        return None
    return AssessorDraft(
        label=label,
        supporting=_coerce_pairs(
            data.get("supporting"), "claim_verifier.supporting"
        ),
        contradicting=_coerce_pairs(
            data.get("contradicting"), "claim_verifier.contradicting"
        ),
    )


def _entailment_prompt(claim: str, passages: Sequence[EvidencePassage]) -> str:
    """Build the single-string prompt the engine's LLM seam sends.

    Evidence is rendered before the claim, not after. This does not help
    the engine's own response cache -- it keys on the full prompt string
    (``cache_llm._generate_cache_key``), so a different claim is a
    different key regardless of where it sits. It matters for
    provider-side prompt-prefix caching (e.g. context/prompt caching a
    gateway model may offer), which only credits a request for the literal
    prefix it shares with a prior one: with the claim (which changes every
    call) first, two calls citing the exact same evidence chunks shared no
    cacheable prefix at all, since the varying part came first. Evidence
    chunks recur across many claims in a run (production measured a 6.9%
    cache hit rate under claim-first ordering, though that number reflects
    whole-article passages rather than chunks -- see
    ``app.evidence_chunking``), so putting the stable part first is what
    lets consecutive calls actually share one.
    """
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"EVIDENCE:\n{_render_passages(passages)}\n\nCLAIM:\n{claim}"
    )


async def _call_llm_entailment_async(
    model: str, claim: str, passages: Sequence[EvidencePassage]
) -> dict[str, Any]:
    """Await one entailment judgement through the engine's LLM seam.

    A scoped bring-your-own-key credential overrides the model and the
    deployment credential, exactly as the direct-litellm call this
    replaces did.
    """
    from app import credentials

    resolved_model, api_key = credentials.byok_model_and_key(model)
    spec = CompletionSpec(
        model_name=resolved_model,
        max_tokens=_MAX_TOKENS,
        temperature=0,
        json_schema=_ENTAILMENT_DRAFT_SCHEMA,
        api_key=api_key,
    )
    result: dict[str, Any] = await call_llm_json(
        _entailment_prompt(claim, passages),
        spec,
        max_attempts=2,
        options=LLMCallOptions(prompt_name="claim_verifier"),
    )
    return result


def _call_llm_entailment(
    model: str,
    claim: str,
    passages: Sequence[EvidencePassage],
) -> dict[str, Any] | None:
    """Call the LLM entailment judge and return its parsed reply, or None.

    Returns None (and logs a warning) on any provider/parse failure, so the
    caller can fall back to the deterministic assessor. Runs on whatever
    thread the (synchronous) ``Assessor`` protocol is invoked from --
    typically one of ``claim_grounding_assess``'s pool workers -- and
    bridges to the engine's async ``call_llm_json`` via
    ``run_coroutine_sync``.

    A run's LLM-call budget being exhausted is not a provider failure to
    swallow: falling back silently would hide the exact blindness the
    engine seam exists to close (the ceiling could not see these calls
    before this module routed through it). It is left to propagate and
    terminate the run, like any other engine call over budget.

    A platform-wide rate-limit cap is the same shape for the opposite
    reason: falling back to the deterministic assessor here would answer
    every claim for the rest of this task against a cap that has not
    reset, silently downgrading a run's evidence grounding instead of
    parking the task until the cap does reset (see
    ``co_scientist.exceptions.LLMRateLimitParkError`` and
    ``task_worker_outcomes._park_rate_limited_task``).
    """
    try:
        return run_coroutine_sync(
            lambda: _call_llm_entailment_async(model, claim, passages)
        )
    except (LLMCallBudgetExceededError, LLMRateLimitParkError):
        raise
    except Exception as exc:
        logger.warning(
            "LLM claim assessor failed (%s); falling back to "
            "deterministic assessor",
            exc,
        )
        return None


def make_llm_assessor(model: str) -> tuple[Assessor, str]:
    """Build a synchronous LLM entailment assessor and its provenance id.

    Args:
        model: The litellm model id (e.g. ``deepseek/deepseek-chat``).

    Returns:
        ``(assessor, assessor_id)`` where ``assessor`` matches the
        :data:`app.claims.Assessor` protocol and ``assessor_id`` is the
        provenance string recorded on each edge (``"llm:<model>"``).
    """
    assessor_id = f"llm:{model}"

    def _assessor(
        claim: str, passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        if not passages:
            return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)
        data = _call_llm_entailment(model, claim, passages)
        if data is None:
            return deterministic_assessor(claim, passages)
        draft = _parse_draft(data)
        if draft is None:
            logger.warning(
                "LLM claim assessor returned unparseable output; falling "
                "back to deterministic assessor. Reply began: %.200r",
                data,
            )
            return deterministic_assessor(claim, passages)
        return draft

    return _assessor, assessor_id
