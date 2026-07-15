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
    "SUPPORTS, CONTRADICTS, or is INSUFFICIENT for the claim. Rules: judge "
    "only from the passages, never outside knowledge; a passage supports only "
    "if it entails the claim, contradicts only if it entails the claim's "
    "negation, otherwise the claim is insufficiently supported. For a supports "
    "or contradicts verdict you MUST cite the exact VERBATIM quote (copied "
    "character-for-character from the passage) that justifies it, together "
    "with that passage's evidence_id. Do not paraphrase quotes. Respond with "
    "single JSON object and nothing else, shaped exactly: "
    '{"label": "supports|contradicts|insufficient", '
    '"supporting": [{"evidence_id": "...", "quote": "..."}], '
    '"contradicting": [{"evidence_id": "...", "quote": "..."}]}.'
)

_DEFAULT_TIMEOUT_SECONDS = 30.0
_MAX_TOKENS = 400


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
        try:
            import litellm

            response = litellm.completion(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"CLAIM:\n{claim}\n\nEVIDENCE:\n"
                            f"{_render_passages(passages)}"
                        ),
                    },
                ],
                temperature=0,
                max_tokens=_MAX_TOKENS,
                timeout=timeout,
                response_format={"type": "json_object"},
                extra_body=deepseek_non_thinking_extra_body(model),
            )
            content = response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning(
                "LLM claim assessor failed (%s); falling back to "
                "deterministic assessor",
                exc,
            )
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
