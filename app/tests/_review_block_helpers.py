"""Shared review-row builders for the report review-block tests.

The per-idea review block is rendered by several sibling test modules
(the axis/``All reviews`` block, the ``Reviews summary`` and its
``Critiques`` rollup, deep verification), which each keep the file under
the line ceiling. The row builders they share live here so the split
does not duplicate them.
"""

from __future__ import annotations

import json
from typing import Any


def _row(agent: str, detail: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """One persisted review row carrying structured detail."""
    return {
        "hypothesis_id": "h1",
        "reviewer_agent": agent,
        "detail_json": json.dumps(detail),
        **extra,
    }


def _summary_row() -> dict[str, Any]:
    """A full review carrying every part of the eight-part summary."""
    return _row(
        "full_review",
        {
            "reviews_summary": {
                "executive_verdict": "The index is well conceived.",
                "critical_flaws": ["The pore benchmark is wrong."],
                "addressed_objections": ["Modelling reliability was met."],
                "validated_risks": ["Parameter covariance is untreated."],
                "supporting_arguments": ["The theoretical basis is right."],
                "alignment_and_novelty": ["Squarely on the goal."],
                "feasibility_assessment": ["Moderate resource intensity."],
                "conclusion": "Recalibrate before testing.",
            }
        },
    )
