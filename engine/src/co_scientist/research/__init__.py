"""Deep research as a capability, owned by no agent in particular.

An agent hands over a goal, a budget and two adapters; it gets back
every question asked, every search made, every finding bound to its
source, and why the search stopped. What it does with that -- ground a
hypothesis, challenge an assumption, widen a review -- is the caller's
business.

The shape is deliberate. The system already searches: once, early, from
the research goal. What nothing does is read something, notice what it
leaves unanswered, and go looking again. That loop is the whole of this
package, and it is built standalone so that assigning it to Generation,
to a Reflection review, or to something not yet written is an adapter
rather than a rewrite -- the same reason the execution harness was built
before it had a caller.

Three ideas here are borrowed rather than invented, from
`references/deep-research/_analysis/`: arithmetic budget decay and
follow-ups-become-the-next-query from `gpt-researcher`, overflow that
answers instead of failing from `open_deep_research`, and evidence
identity that includes the question that fetched it from `storm`.
"""

from co_scientist.research.artifacts import (
    CallStatus,
    Finding,
    Question,
    ResearchResult,
    SearchCall,
    SourceHit,
    StopReason,
    ThreadRecord,
    ThreadStatus,
    content_id,
    dedupe_findings,
)
from co_scientist.research.budget import (
    DEFAULT_BREADTH_FLOOR,
    ResearchBudget,
)
from co_scientist.research.loop import SEED_STANCE, conduct_research
from co_scientist.research.ports import (
    Document,
    ExtractedFinding,
    Extraction,
    ResearchModelPort,
    RetrievalError,
    RetrievalPort,
)
from co_scientist.research.serialization import (
    result_from_dict,
    result_to_dict,
)

__all__ = [
    "DEFAULT_BREADTH_FLOOR",
    "SEED_STANCE",
    "CallStatus",
    "Document",
    "ExtractedFinding",
    "Extraction",
    "Finding",
    "Question",
    "ResearchBudget",
    "ResearchModelPort",
    "ResearchResult",
    "RetrievalError",
    "RetrievalPort",
    "SearchCall",
    "SourceHit",
    "StopReason",
    "ThreadRecord",
    "ThreadStatus",
    "conduct_research",
    "content_id",
    "dedupe_findings",
    "result_from_dict",
    "result_to_dict",
]
