"""Goal Report markdown: the document renderer and its section modules.

``render_report_markdown`` assembles the whole document from
:class:`ReportMarkdownInputs`; every other module in this package renders one
section (header, hypotheses, review block, meta-review, tournament, ...) as
pure functions of the data passed in, and is package-private.
"""

from app.report.markdown.documents import (
    ReportMarkdownInputs,
    render_report_markdown,
)

__all__ = ["ReportMarkdownInputs", "render_report_markdown"]
