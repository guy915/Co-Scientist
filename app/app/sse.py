"""Server-Sent Events wire format, shared by every streaming endpoint.

The run event stream (``app.runs.events``), the goal interview
(``app.interviews``), and grounded Q&A (``app.qa``) all frame their payloads
the same way; the encoder lives here rather than in any one of them so a
transport detail is not owned by a domain module. ``app.qa`` re-exports
:func:`sse_frame` for callers that still import it from there.
"""

from __future__ import annotations

import json
from typing import Any


def sse_frame(event: dict[str, Any]) -> str:
    """Format an event dict as a Server-Sent Events data frame."""
    return f"data: {json.dumps(event)}\n\n"
