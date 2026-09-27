"""Batched LLM entailment: judge a whole hypothesis's claims in one call.

Split out of :mod:`app.claim_verifier` to keep that module within the
size budget. ``make_llm_assessor`` there judges one claim per call; this
module's ``make_llm_batch_assessor`` is the same underlying judge asked
to assess a whole group's (hypothesis's) claims at once -- see
``app.claims.assess_claims_batch``, which retrieves each claim's own
evidence unchanged and only batches the judgement.

A production ultra run measured 218 entailment calls in a single pass
across 13 hypotheses (one call per atomic claim), repeated before every
ranking wave. Batched, the same pass costs one call per hypothesis (13,
or 26 if a hypothesis's claim count forces a split).

The batch reply is keyed by the claim's numeric position, never by
echoing its text back (see the root AGENTS.md "Structured-output schemas
must not echo input back" gotcha) -- an echoing schema would scale the
reply with the pool and risk the same truncation that broke proximity
dedup. Each verdict's own citations carry the same fix one level down:
the judge cites a passage by the bracketed number EVIDENCE showed it,
not by echoing its evidence id -- see :mod:`app.claim_verifier`'s
``_CITATION_ITEM`` for why (production run bc77950f).

Depends on :mod:`app.claim_verifier` for the citation-pair schema/coercion
and the evidence-rendering helper it shares with the single-claim path
(one-directional: this module imports from there, never the reverse, so
the two cannot form an import cycle).
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
from app.claim_verifier import (
    _CITATION_LIST,
    _coerce_pairs,
    _render_passages,
)
from app.claim_verifier_opposition import guard_contradictions
from app.claims import (
    AssessorDraft,
    BatchAssessor,
    EntailmentLabel,
    EvidencePassage,
)

logger = logging.getLogger(__name__)

_BATCH_SYSTEM_PROMPT = (
    "You are a strict natural-language-inference judge for scientific claims. "
    "Given numbered EVIDENCE passages and a numbered list of CLAIMS, decide "
    "for EACH claim whether the evidence SUPPORTS, PARTIALLY supports, "
    "CONTRADICTS, or is INSUFFICIENT for it. Rules: judge each claim only "
    "from the passages, never outside knowledge, and independently of every "
    "other claim. A passage SUPPORTS only if it entails the claim. PARTIAL "
    "requires evidence within the scope asserted by the claim that "
    "establishes only part of its result, mechanism, or effect magnitude. "
    "When the stated population, model, intervention or dose, outcome, and "
    "observation time match, evidence establishing the claimed direction "
    "but leaving its asserted extent unreported is PARTIAL. Unreported "
    "extent is not a contradiction; measured extent is contradictory only "
    "when it entails the claim's negation. "
    "An established component of a compound claim can be PARTIAL when that "
    "component's own defining conditions match. An untested component is not "
    "a contradicted one. Partial support is not a substitute for testing a "
    "claim-defining condition. Evidence "
    "is INSUFFICIENT if it substitutes or leaves untested an explicitly "
    "required population or model, intervention or dose, outcome or "
    "endpoint, or observation time. An adjacent mechanism, surrogate "
    "endpoint, or different experimental context cannot supply that missing "
    "condition. A narrower setting may provide PARTIAL support only when "
    "it remains within the claim's stated scope; do not invent scope "
    "restrictions absent from the claim. Mere topic overlap is INSUFFICIENT. "
    "It CONTRADICTS only if it entails the claim's negation: the passage must "
    "be about the same molecule, target, or population as the claim AND "
    "must assert the opposite of what the claim asserts about it. A passage "
    "about a different molecule, target, or population is never a "
    "contradiction, however similar the topic -- apply the same scope rule "
    "for INSUFFICIENT or PARTIAL. A passage that states or "
    "agrees with the claim is not a contradiction either, even if it also "
    "discusses caveats or other mechanisms. When in doubt between "
    "CONTRADICTS and INSUFFICIENT, choose INSUFFICIENT. Otherwise the claim "
    "is INSUFFICIENT. For a supports, partial, or contradicts verdict you "
    "MUST cite the exact VERBATIM quote (copied character-for-character "
    "from the passage) that justifies it, together with the bracketed "
    "number shown before that passage in EVIDENCE (e.g. 3) -- not its "
    "contents, and not the claim's own number below; put a partial "
    'verdict\'s quote in "supporting". Keep each '
    "quote SHORT -- at most 200 characters. Use the shortest self-contained "
    "verbatim span that justifies the verdict. Retain the explicitly named "
    "subject (molecule, intervention, target, or population) and any "
    "conditions needed to interpret the finding. Never cite a pronoun-only "
    "or otherwise context-dependent fragment. If no self-contained span "
    "fits within 200 characters, choose INSUFFICIENT. Do not paraphrase "
    "quotes. Respond with a single JSON object holding one verdict per "
    "claim, each carrying the claim's own number as its index -- never the "
    "claim's text -- and nothing else."
)

# A ceiling, not a reservation, sized for a full batch of claims (up to
# ``claims._BATCH_CLAIM_SPLIT``) each carrying a label and a short quote --
# larger than the single-claim ceiling because the reply now holds many
# verdicts, not one, but still bounded: the schema returns only an index,
# a label, and quotes per claim, never the claim text back (see the root
# AGENTS.md "Structured-output schemas must not echo input back" gotcha),
# so the reply does not scale with the *prompt's* size, only with how many
# claims are in this one batch.
_BATCH_MAX_TOKENS = 12000

_BATCH_VERDICT_ITEM = obj(
    {
        "index": {"type": "integer"},
        "label": {
            "type": "string",
            "enum": [label.value for label in EntailmentLabel],
        },
        "supporting": _CITATION_LIST,
        "contradicting": _CITATION_LIST,
    }
)

_BATCH_DRAFT_SCHEMA = obj(
    {"verdicts": {"type": "array", "items": _BATCH_VERDICT_ITEM}}
)


def _render_claims(claims: Sequence[str]) -> str:
    """Render claims as a 1-based numbered block matching the verdict index."""
    return "\n".join(f"[{i}] {c}" for i, c in enumerate(claims, start=1))


def _batch_entailment_prompt(
    claims: Sequence[str], passages: Sequence[EvidencePassage]
) -> str:
    """Build the single-string prompt for one hypothesis's batched judgement.

    Evidence still precedes the variable part (now the whole claim list, not
    one claim) for the same provider-side prefix-caching reason
    ``claim_verifier._entailment_prompt`` documents.
    """
    return (
        f"{_BATCH_SYSTEM_PROMPT}\n\n"
        f"EVIDENCE:\n{_render_passages(passages)}\n\n"
        f"CLAIMS:\n{_render_claims(claims)}"
    )


def _parse_batch_drafts(
    data: dict[str, Any], claims: Sequence[str]
) -> list[AssessorDraft | None]:
    """Fan a batch reply's verdicts back out to per-claim drafts, by index.

    A verdict's ``index`` is the claim's 1-based position in the prompt
    (see ``_render_claims``); a missing, out-of-range, duplicate, or
    unparseable verdict leaves that position ``None`` rather than raising,
    so the caller (``claims.assess_claims_batch``) falls only that one
    claim back to the deterministic assessor instead of losing the whole
    batch to one bad entry. The caller then guards contradictions against
    located source quotes, exactly like the single-claim path.
    """
    num_claims = len(claims)
    drafts: list[AssessorDraft | None] = [None] * num_claims
    for item in coerce_json_list(
        data.get("verdicts"),
        element="dict",
        site="claim_verifier.batch_verdicts",
    ):
        try:
            position = int(item.get("index")) - 1
        except (TypeError, ValueError):
            continue
        if not (0 <= position < num_claims):
            continue
        raw_label = str(item.get("label") or "").strip().lower()
        try:
            label = EntailmentLabel(raw_label)
        except ValueError:
            continue
        draft = AssessorDraft(
            label=label,
            verification_method="model_primary",
            cites_evidence_ids=False,
            supporting=_coerce_pairs(
                item.get("supporting"), "claim_verifier.batch_supporting"
            ),
            contradicting=_coerce_pairs(
                item.get("contradicting"), "claim_verifier.batch_contradicting"
            ),
        )
        drafts[position] = draft
    return drafts


async def _call_llm_batch_entailment_async(
    model: str, claims: Sequence[str], passages: Sequence[EvidencePassage]
) -> dict[str, Any]:
    """Await one batched entailment judgement through the engine's LLM seam.

    Thinking is *requested* off from the first attempt: a production ultra
    run (b82f9162, 2026-09-06) burned its whole budget on a free reasoning
    model reasoning about a batch of ~17 claims -- 21054 reasoning tokens
    against an 18000-token budget, then 26332 against a raised 24000 on
    the retry -- and answered nothing either time, so every claim in the
    batch fell back to the deterministic assessor. Judging claims against
    evidence chunks is classification, not a task a chain of thought
    earns its keep on. What actually reaches the wire is the engine's
    decision, not this flag's: the deployed free chain's models reject a
    disabled-reasoning request outright ("Reasoning is mandatory for this
    endpoint and cannot be disabled" -- the same run's recovered finalize,
    every batched call failing identically on both attempts), so
    ``co_scientist.llm_thinking`` sends the smallest reasoning tier the
    gateway exposes instead, funded by the same thinking-token floor a
    normal thinking call gets -- see ``GatewayModel.reasoning_can_disable``
    and ``effective_thinking_enabled``. ``max_attempts=3`` (not the
    historical 2) keeps a plain re-ask available for a schema or parse
    failure now that no rung of the escalation ladder needs to spend an
    attempt turning thinking off -- it already is requested off; whether
    the wire actually goes out that way is the model's call, not this
    one's.
    """
    from app import credentials

    resolved_model, api_key = credentials.byok_model_and_key(model)
    spec = CompletionSpec(
        model_name=resolved_model,
        max_tokens=_BATCH_MAX_TOKENS,
        temperature=0,
        json_schema=_BATCH_DRAFT_SCHEMA,
        api_key=api_key,
    )
    result: dict[str, Any] = await call_llm_json(
        _batch_entailment_prompt(claims, passages),
        spec,
        max_attempts=3,
        options=LLMCallOptions(
            prompt_name="claim_verifier_batch", enable_thinking=False
        ),
    )
    return result


def _call_llm_batch_entailment(
    model: str,
    claims: Sequence[str],
    passages: Sequence[EvidencePassage],
) -> dict[str, Any] | None:
    """Call the batch entailment judge and return its parsed reply, or None.

    Same failure contract as ``claim_verifier._call_llm_entailment``: a
    run's LLM-call budget being exhausted, or a platform-wide rate-limit
    park, propagates rather than falling back (see that function's
    docstring for why); any other provider/parse failure returns None so
    every claim in this batch falls back to the deterministic assessor.
    """
    try:
        return run_coroutine_sync(
            lambda: _call_llm_batch_entailment_async(model, claims, passages)
        )
    except (LLMCallBudgetExceededError, LLMRateLimitParkError):
        raise
    except Exception as exc:
        logger.warning(
            "LLM batch claim assessor failed (%s); falling back to "
            "deterministic assessor for this hypothesis's claims",
            exc,
        )
        return None


def make_llm_batch_assessor(
    model: str, *, call_counter: list[int] | None = None
) -> tuple[BatchAssessor, str]:
    """Build a batch-capable LLM entailment assessor and its provenance id.

    Judges an entire group's (hypothesis's) claims in one call instead of
    one call per claim -- see ``app.claims.assess_claims_batch`` and its
    module-level comment for why. This is an additional, swappable path
    alongside ``claim_verifier.make_llm_assessor``, not a replacement of
    it: callers that only have the per-claim ``Assessor`` protocol keep
    working unchanged.

    Args:
        model: The litellm model id (e.g. ``deepseek/deepseek-chat``).
        call_counter: Counts logical primary and verification requests.
            Physical retries are counted separately by completion telemetry.

    Returns:
        ``(batch_assessor, assessor_id)`` where ``assessor_id`` matches
        ``make_llm_assessor``'s provenance string for the same model, since
        both are the same underlying judge.
    """
    assessor_id = f"llm:{model}"

    def _batch_assessor(
        claims: Sequence[str], passages: Sequence[EvidencePassage]
    ) -> Sequence[AssessorDraft | None]:
        if not claims:
            return []
        if call_counter is not None:
            call_counter[0] += 1
        data = _call_llm_batch_entailment(model, claims, passages)
        if data is None:
            return [None] * len(claims)
        return guard_contradictions(
            model,
            claims,
            passages,
            _parse_batch_drafts(data, claims),
            call_counter=call_counter,
        )

    return _batch_assessor, assessor_id
