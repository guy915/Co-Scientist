"""Per-axis sub-structure for the published ``All reviews:`` appendix.

R14-17 (15 of the 19 published hypothesis documents): each review axis
carries its own fixed sub-schema rather than one shared score+feedback
template. Correctness is the richest at 7-8 parts, Feasibility the
leanest at 3. Ours had the axis *ordering* already; what a reader never
saw was any sub-structure below Correctness and Novelty.

Homed apart from ``report_markdown_review_block`` because that module is
the per-idea assembly point and was already two thirds of the way to the
size ceiling; the two halves are re-exported from ``report_markdown`` so
that namespace keeps resolving.

Two conventions this file keeps, both learned elsewhere in this repo:

* **Related Article Abstracts is attached, never asked for.** It is the
  one published sub-part that is a literal echo of the articles the
  prompt already supplied, and a structured-output schema that echoes
  its input scales the response with the input and truncates identically
  on every retry (``schemas/proximity``'s own rationale). The evidence
  rows the hypothesis already cites carry the abstract, so the renderer
  joins them back here at zero model cost.
* **Omit rather than print an empty heading** (R14-23), the same as
  every other block in the review surface.

An article's display label is ``report_markdown_references``'s own
``_reference_label``, not a second one: the entry's References section
and these per-axis lists name the same source from the same row, and two
label builders would eventually disagree about the same paper in one
document.
"""

from __future__ import annotations

from typing import Any

from app.report_markdown_references import _reference_label

# How many cited articles one axis lists. The published exemplars print
# two to five; the cap is what keeps a heavily-cited idea from turning
# one axis into a bibliography.
_MAX_RELATED_ARTICLES = 6

# One abstract's printed length. Google prints a one-to-two-sentence
# relevance note rather than the abstract in full, and the rows here hold
# whole abstracts, so they are cut to roughly that.
_MAX_ABSTRACT_CHARS = 400

Reference = tuple[str, dict[str, Any]]


def _abstract_excerpt(source: dict[str, Any]) -> str:
    """The article's abstract, flattened and cut to a published-length note."""
    text = " ".join(str(source.get("abstract") or "").split())
    if len(text) <= _MAX_ABSTRACT_CHARS:
        return text
    return text[:_MAX_ABSTRACT_CHARS].rstrip() + "..."


def _related_articles(
    references: list[Reference], with_abstracts: bool
) -> list[str]:
    """The published ``Related Article Abstracts`` list for one axis.

    Google prints the full abstract note under Correctness and, in five
    of the 19 files, a bare ``Related Article Abstract Titles`` list
    under the leaner axes. That split is the reason for the flag: the
    same abstract repeated under all four axes would quadruple the
    longest block in the entry without telling a reader anything new.

    Args:
        references: This hypothesis's resolvable (citation key, evidence
            row) pairs -- the same index the entry's References section
            prints from.
        with_abstracts: Whether to print each article's abstract excerpt
            beneath its label, or the label alone.

    Returns:
        The rendered lines, or nothing when the hypothesis cites nothing.
    """
    entries = references[:_MAX_RELATED_ARTICLES]
    if not entries:
        return []
    label = (
        "**Related Article Abstracts**"
        if with_abstracts
        else "**Related Article Abstract Titles**"
    )
    lines = [label, ""]
    for key, source in entries:
        line = f"- **[{key}]** {_reference_label(source)}"
        if with_abstracts and (excerpt := _abstract_excerpt(source)):
            line += f": {excerpt}"
        lines.append(line)
    return [*lines, ""]


def _prose(label: str, value: Any) -> list[str]:
    """A labeled prose paragraph, or nothing when the field is empty."""
    text = str(value or "").strip()
    return [f"**{label}**", "", text, ""] if text else []


def _steps(label: str, items: Any) -> list[str]:
    """The published numbered ``Steps to Test the Idea`` list."""
    entries = [
        text
        for item in (items if isinstance(items, list) else [])
        if (text := str(item).strip())
    ]
    if not entries:
        return []
    numbered = [f"{n}. {text}" for n, text in enumerate(entries, start=1)]
    return [f"**{label}**", "", *numbered, ""]


def feasibility_extras(mature: dict[str, Any]) -> list[str]:
    """The published Feasibility axis's own two judged parts.

    Steps to Test the Idea -> Reasoning about Feasibility. With the
    related-article list its caller attaches, that is the leanest of the
    four published axes (3 parts) and the shape 13 of the 19 files print.
    """
    return [
        *_steps("Steps to Test the Idea", mature.get("feasibility_steps")),
        *_prose(
            "Reasoning about Feasibility", mature.get("feasibility_reasoning")
        ),
    ]


def impact_extras(mature: dict[str, Any]) -> list[str]:
    """The published Impact potential axis's own closing assessment.

    Google also reprints Detailed Assumptions and Suggested Improvements
    under this axis; both are already printed once under Correctness from
    the single field each has here, and printing the same paragraph twice
    in one entry reads as a rendering fault rather than as fidelity.
    """
    return _prose("Overall Impact Potential", mature.get("impact_assessment"))


def related_article_abstracts(references: list[Reference]) -> list[str]:
    """Correctness's ``Related Article Abstracts``, abstracts included.

    The one axis that prints them in full: it is the axis whose judgment
    is *about* whether the evidence backs the hypothesis, so the abstract
    is the thing being weighed rather than a pointer to it.
    """
    return _related_articles(references, with_abstracts=True)


def related_article_titles(references: list[Reference]) -> list[str]:
    """The leaner ``Related Article Abstract Titles`` list (5/19 files)."""
    return _related_articles(references, with_abstracts=False)
