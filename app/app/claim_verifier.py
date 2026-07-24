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
- Strict JSON output; any parse/timeout/provider failure falls back to the
  deterministic assessor rather than failing the grounding pass (best-effort,
  mirroring ``title_gen``/``qa``).
- The assessor is *synchronous* (uses ``litellm.completion``) because grounding
  runs inside the synchronous drain / mock-stage persistence path.

This module is exercised end-to-end by the golden run (P0.6); the offline suite
fakes ``litellm.completion`` to prove prompt/parse/guard behavior.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from app.claims import (
    Assessor,
    AssessorDraft,
    EntailmentLabel,
    EvidencePassage,
    deterministic_assessor,
)
from app.config import deepseek_non_thinking_extra_body

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
    "a single JSON object and nothing else, shaped exactly: "
    '{"label": "supports|partial|contradicts|insufficient", '
    '"supporting": [{"evidence_id": "...", "quote": "..."}], '
    '"contradicting": [{"evidence_id": "...", "quote": "..."}]}.'
)

_DEFAULT_TIMEOUT_SECONDS = 30.0
# A ceiling, not a reservation: the verdict JSON is short, and the generous cap
# only matters for an unusually long quote.
_MAX_TOKENS = 2000


def _render_passages(passages: Sequence[EvidencePassage]) -> str:
    """Render candidate passages as an id-tagged, numbered prompt block."""
    lines = []
    for i, p in enumerate(passages, start=1):
        lines.append(f"[{i}] evidence_id={p.evidence_id}\n{p.text}")
    return "\n\n".join(lines)


def _coerce_pairs(items: Any) -> tuple[tuple[str, str], ...]:
    """Coerce a parsed ``[{evidence_id, quote}]`` list to (id, quote) pairs."""
    pairs: list[tuple[str, str]] = []
    if not isinstance(items, list):
        return ()
    for item in items:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or "")
        quote = str(item.get("quote") or "")
        if evidence_id and quote:
            pairs.append((evidence_id, quote))
    return tuple(pairs)


def _parse_draft(content: str) -> AssessorDraft | None:
    """Parse the model's JSON reply into an :class:`AssessorDraft`.

    Returns None on malformed output so the caller can fall back rather than
    trusting a partial parse.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    raw_label = str(data.get("label") or "").strip().lower()
    try:
        label = EntailmentLabel(raw_label)
    except ValueError:
        return None
    return AssessorDraft(
        label=label,
        supporting=_coerce_pairs(data.get("supporting")),
        contradicting=_coerce_pairs(data.get("contradicting")),
    )


def _entailment_messages(
    claim: str, passages: Sequence[EvidencePassage]
) -> list[dict[str, str]]:
    """Build the system/user chat messages for the entailment judge."""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"CLAIM:\n{claim}\n\nEVIDENCE:\n{_render_passages(passages)}"
            ),
        },
    ]


# Entailment judgements issued in this process. This assessor calls
# litellm directly rather than going through the engine's ``call_llm``, so
# nothing folded these into a run's metrics -- and grounding issues one per
# extracted claim per hypothesis, which is hundreds of calls in a real run.
# The tier's ``max_llm_calls`` is a runaway backstop, and it was blind to
# the single largest source of calls the app makes.
_entailment_calls = 0


def entailment_call_count() -> int:
    """Return how many entailment judgements this process has issued."""
    return _entailment_calls


def _call_llm_entailment(
    model: str,
    claim: str,
    passages: Sequence[EvidencePassage],
    timeout: float,
) -> str | None:
    """Call the LLM entailment judge and return its raw reply, or None.

    Returns None (and logs a warning) on any provider failure, so the caller
    can fall back to the deterministic assessor.
    """
    global _entailment_calls
    _entailment_calls += 1
    try:
        import litellm

        response = litellm.completion(
            model=model,
            messages=_entailment_messages(claim, passages),
            temperature=0,
            max_tokens=_MAX_TOKENS,
            timeout=timeout,
            response_format={"type": "json_object"},
            # One of the two high-frequency call sites that opt out of
            # thinking: grounding runs this judge once per extracted claim
            # per hypothesis, so it is the app-side counterpart to the
            # engine's ranking tournament. The NLI verdict is a lookup
            # against supplied passages -- the prompt already forbids
            # outside knowledge and demands a verbatim quote -- so there is
            # little for reasoning to add.
            extra_body=deepseek_non_thinking_extra_body(model),
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning(
            "LLM claim assessor failed (%s); falling back to "
            "deterministic assessor",
            exc,
        )
        return None


def make_llm_assessor(
    model: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> tuple[Assessor, str]:
    """Build a synchronous LLM entailment assessor and its provenance id.

    Args:
        model: The litellm model id (e.g. ``deepseek/deepseek-chat``).
        timeout: Per-call timeout in seconds.

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
        content = _call_llm_entailment(model, claim, passages, timeout)
        if content is None:
            return deterministic_assessor(claim, passages)
        draft = _parse_draft(content)
        if draft is None:
            logger.warning(
                "LLM claim assessor returned unparseable output; falling back "
                "to deterministic assessor"
            )
            return deterministic_assessor(claim, passages)
        return draft

    return _assessor, assessor_id
