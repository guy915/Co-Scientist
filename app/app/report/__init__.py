"""The Goal Report: payload, markdown, release gate, and the finalize pipeline.

One package for the document a run ends in. ``finalize`` is the publish
pipeline (final safety gate, persistence, report/completed events); ``build``
gathers a run's data into the payload/markdown pair; ``content`` derives the
leaderboard, buckets and topics it shows; ``gates`` decides which ideas the
report may release (contradicted and unsafe ideas are withheld, merely
unsupported ones are published as Unverified); ``payload`` shapes the JSON the
frontend reads; ``notify`` schedules the completion email; and ``markdown``
renders the document from its section modules.

This ``__init__`` is the interface; the submodules are package-private.
``engine_adapter`` imports ``format_deep_verification_critique`` from here
while ``finalize`` reaches ``engine_tasks_support`` (and through it
``engine_adapter``), so ``finalize`` imports ``engine_tasks_support`` inside
the functions that need it -- hoisting that import is an import cycle.
"""

from app.report.build import ReportRequest, build_report_content
from app.report.content import released_claim_evidence
from app.report.finalize import finalize_report
from app.report.gates import (
    exclude_unsafe_hypotheses,
    unverified_hypothesis_ids,
)
from app.report.payload import format_deep_verification_critique

__all__ = [
    "ReportRequest",
    "build_report_content",
    "exclude_unsafe_hypotheses",
    "finalize_report",
    "format_deep_verification_critique",
    "released_claim_evidence",
    "unverified_hypothesis_ids",
]
