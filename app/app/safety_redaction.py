"""Applying a redact decision to the content it was recorded against.

A ``redact`` decision used to be a label: the gate persisted the verdict and
then published the same goal and the same report markdown, so the original was
still readable through the database, the API, the SSE stream and the public
share. These helpers remove the matched spans from every copy the app is about
to persist or emit.

Only the spans the policy actually matched are removed. Redaction is
span-scoped rather than whole-document so a run stays usable and the audit
record stays meaningful; a decision that names no span cannot be applied at
all, which ``safety.ensure_redactable`` turns into a hold rather than a pass.
"""

from __future__ import annotations

import re
from typing import Any

from co_scientist.safety import REDACTED_PLACEHOLDER

__all__ = [
    "REDACTED_PLACEHOLDER",
    "redact_matched_spans",
    "redact_payload_text",
]


def redact_matched_spans(text: str, matches: list[str]) -> str:
    """Replace every occurrence of each matched span with the placeholder.

    Matching is case-insensitive and literal: the spans come back from the
    policy as the text it matched, and the same phrase elsewhere in the
    document is the same disclosure.

    Args:
        text: The content to scrub.
        matches: The spans the safety policy matched.

    Returns:
        The content with every matched span replaced.
    """
    if not text:
        return text
    out = text
    for span in matches:
        if not span:
            continue
        out = re.sub(re.escape(span), REDACTED_PLACEHOLDER, out, flags=re.I)
    return out


def redact_payload_text(value: Any, matches: list[str]) -> Any:
    """Redact matched spans throughout a nested JSON-shaped payload.

    The report payload and the report markdown are two renderings of the same
    content, so scrubbing one and publishing the other would leave the
    original readable through the API and the report event.

    Args:
        value: A payload value: dict, list, string, or scalar.
        matches: The spans the safety policy matched.

    Returns:
        The value with every string leaf redacted; scalars are returned as-is.
    """
    if isinstance(value, str):
        return redact_matched_spans(value, matches)
    if isinstance(value, dict):
        return {
            key: redact_payload_text(item, matches)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_payload_text(item, matches) for item in value]
    return value
