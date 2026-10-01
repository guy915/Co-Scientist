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
(``co_scientist.llm.telemetry.scoped_telemetry`` -- the gate opens
``"claim_gate"``, the finalize grounding pass opens ``"claim_grounding"``),
run-scoped call-budget enforcement (``co_scientist.llm.admission.call_budget``,
so ``LLMCallBudgetExceededError`` terminates a run over-spending on claims the
same way it does an engine node), and the thinking-token floor
(``co_scientist.llm.request.thinking``) -- see the root AGENTS.md finding this
module's docstring used to warn about, now closed.

``app.claim_verifier_batch`` holds the same judge asked to assess a whole
group's (hypothesis's) claims in one call rather than one call per claim --
see ``app.claims.assess_claims_batch``. A production ultra run measured 218
claims assessed one at a time across 13 hypotheses in a single pass,
repeated before every ranking wave (~1,000 calls/run); the batch path costs
one call per hypothesis instead (13, or 26 if a hypothesis's claim count
forces a split). Split into its own module (rather than living here
alongside ``make_llm_assessor``) to keep this module within the size
budget; it imports the citation-pair schema/coercion and evidence-rendering
helpers back from here, never the reverse, so the two cannot form a cycle.

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
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
    coerce_json_list,
    record_deterministic_fallback,
)
from co_scientist.schemas.builders import obj

from app.async_bridge import run_coroutine_sync
from app.claim_verifier_opposition import guard_contradictions
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
    "passage SUPPORTS only if it entails the claim. PARTIAL requires evidence "
    "within the scope asserted by the claim that establishes only part of "
    "its result, mechanism, or effect magnitude. "
    "When the stated population, model, intervention or dose, outcome, and "
    "observation time match, evidence establishing the claimed direction "
    "but leaving its asserted extent unreported is PARTIAL. Unreported "
    "extent is not a contradiction; measured extent is contradictory only "
    "when it entails the claim's negation. "
    "An established component "
    "of a compound claim can be PARTIAL when that component's own defining "
    "conditions match. An untested component is not a contradicted one. "
    "Partial support is not a substitute for "
    "testing a claim-defining condition. Evidence is INSUFFICIENT if it "
    "substitutes or leaves untested an explicitly required population or "
    "model, intervention or dose, outcome or endpoint, or observation time. "
    "An adjacent mechanism, surrogate endpoint, or different experimental "
    "context cannot supply that missing condition. A narrower setting may "
    "provide PARTIAL support only when it remains within the claim's stated "
    "scope; do not invent scope restrictions absent from the claim. Mere "
    "topic overlap is INSUFFICIENT. It CONTRADICTS only "
    "if it entails the claim's negation: the passage must be about the same "
    "molecule, target, or population as the claim AND must assert the "
    "opposite of what the claim asserts about it. A passage about a different "
    "molecule, target, or population is never a contradiction, however "
    "similar the topic -- apply the same scope rule for INSUFFICIENT or "
    "PARTIAL. A passage that states or agrees with the claim is "
    "not a contradiction either, even if it also discusses caveats or other "
    "mechanisms. When in doubt between CONTRADICTS and INSUFFICIENT, choose "
    "INSUFFICIENT. Otherwise the claim is INSUFFICIENT. For a supports, "
    "partial, or contradicts verdict you MUST cite the exact VERBATIM quote "
    "(copied character-for-character from the passage) that justifies it, "
    "together with the bracketed number shown before that passage (e.g. 3) "
    '-- not its contents; put a partial verdict\'s quote in "supporting". '
    "Do not paraphrase quotes. Respond with a single JSON object and "
    "nothing else."
)

# A ceiling, not a reservation: the verdict JSON is short, and the generous
# cap only matters for an unusually long quote. The chain of thought is not
# funded from here -- the engine's own thinking floor
# (``co_scientist.llm.request.thinking``) raises whatever budget a thinking
# model is sent with, so reasoning cannot eat the answer's share.
_MAX_TOKENS = 6000

# ``passage`` is the judge's cited passage number -- the bracketed integer
# ``_render_passages`` prints before each passage, sent back either as a
# JSON integer or (a model formats it differently) a short numeric string
# such as ``"3"``; ``claims_span._resolve_span`` normalizes either form the
# same way, and also still accepts a full evidence id here for a model
# that cites one anyway (a legacy id, not the number it was shown, is the
# fallback path, not the contract). See the module docstring for why a
# number replaced the id that production run bc77950f lost most of a
# run's verdicts echoing.
_CITATION_ITEM = obj(
    {
        "passage": {"type": ["integer", "string"]},
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
# engine's json_object downgrade path otherwise (see
# llm.structured.validate._backfill_ required_fields /
# _prune_unknown_properties).
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
    """Render candidate passages as a bracket-numbered prompt block.

    No evidence id is shown. It used to be, so the judge could cite it
    back; production run bc77950f lost most of its entailment verdicts
    because a 36-character id (a UUID plus ``#chunk`` suffix) is exactly
    the kind of token a fallback model reformats in transit, and the
    resolution step required an exact echo. The judge now cites the
    bracketed number instead (see ``_CITATION_ITEM`` and
    ``claims_span.py``), which is short enough to reproduce reliably, so
    the id has nothing left to do in the prompt.
    """
    return "\n\n".join(
        f"[{i}] {p.text}" for i, p in enumerate(passages, start=1)
    )


def _coerce_pairs(items: Any, site: str) -> tuple[tuple[str, str], ...]:
    """Coerce a parsed ``[{passage, quote}]``-shaped value to pairs.

    ``passage`` is read as a string regardless of whether it arrived as a
    JSON integer or a string -- ``claims_span._resolve_span`` normalizes
    either form the same way. Even under schema enforcement, a single
    citation can plausibly arrive as a bare object rather than wrapped in
    a one-element list; ``coerce_json_list`` recovers that shape before
    the per-item dict fields are read.
    """
    if isinstance(items, dict):
        # One citation as a bare object is the expected shape above and loses
        # nothing, so it is wrapped here rather than logged as a coercion.
        items = [items]
    pairs: list[tuple[str, str]] = []
    for item in coerce_json_list(items, element="dict", site=site):
        cited = str(item.get("passage") or "")
        quote = str(item.get("quote") or "")
        if cited and quote:
            pairs.append((cited, quote))
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
    draft = AssessorDraft(
        label=label,
        verification_method="model_primary",
        cites_evidence_ids=False,
        supporting=_coerce_pairs(
            data.get("supporting"), "claim_verifier.supporting"
        ),
        contradicting=_coerce_pairs(
            data.get("contradicting"), "claim_verifier.contradicting"
        ),
    )
    return draft


def _entailment_prompt(claim: str, passages: Sequence[EvidencePassage]) -> str:
    """Build the single-string prompt the engine's LLM seam sends.

    Evidence is rendered before the claim, not after. This does not help
    the engine's own response cache -- it keys on the full prompt string
    (``cache.llm._generate_cache_key``), so a different claim is a
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

    Thinking is *requested* off from the first attempt: judging a claim
    against a handful of evidence passages is a classification task, not
    one that benefits from a chain of thought, and a free reasoning model
    given room to think took it -- a production run measured 21054
    reasoning tokens against an 18000-token budget and answered nothing
    (run b82f9162, 2026-09-06). What actually reaches the wire is the
    engine's decision, not this flag's: the deployed free chain's models
    reject a disabled-reasoning request outright ("Reasoning is mandatory
    for this endpoint and cannot be disabled" -- the same run's recovered
    finalize, every batched call failing identically on both attempts), so
    ``co_scientist.llm.request.thinking`` sends the smallest reasoning tier the
    gateway exposes instead of a bare disable for a model declared unable
    to honour one, and funds that with the thinking-token floor exactly as
    it would a normal thinking call -- see
    ``ModelProfile.reasoning_can_disable`` and
    ``effective_thinking_enabled``. ``max_attempts=3`` (not the historical
    2) keeps a plain re-ask available for a schema or parse failure now
    that no rung of the escalation ladder needs to spend an attempt
    turning thinking off -- it already is requested off; whether the wire
    actually goes out that way is the model's call, not this one's.
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
        max_attempts=3,
        options=LLMCallOptions(
            prompt_name="claim_verifier", enable_thinking=False
        ),
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
            return AssessorDraft(
                label=EntailmentLabel.INSUFFICIENT,
                verification_method="no_evidence",
            )
        data = _call_llm_entailment(model, claim, passages)
        if data is None:
            record_deterministic_fallback(model, "claim_single")
            return deterministic_assessor(claim, passages)
        draft = _parse_draft(data)
        if draft is None:
            logger.warning(
                "LLM claim assessor returned unparseable output; falling "
                "back to deterministic assessor. Reply began: %.200r",
                data,
            )
            record_deterministic_fallback(model, "claim_single")
            return deterministic_assessor(claim, passages)
        guarded = guard_contradictions(model, [claim], passages, [draft])[0]
        assert guarded is not None
        return guarded

    return _assessor, assessor_id
