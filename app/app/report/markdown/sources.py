"""Report section naming the data sources a run actually consulted.

Two independent facts feed one "## Data sources" heading: the
science skills the run invoked (``skills_used``, an attribution the
harness owes -- see the docstring on ``_render_data_source_notice``),
and the literature searches the deep-research capability made
(``retrieval_calls``, written by ``app.research_provenance`` and read
back here with no new recording). Neither implies the other, and either
alone is enough to render the heading; only when both are empty does the
section vanish, matching the precedent's own "return [] when there is
nothing to say" contract.
"""

from __future__ import annotations

from typing import Any


def _aggregate_retrieval_calls(
    calls: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Group a run's searches by source: how many, and what they served.

    Args:
        calls: Rows shaped like ``store.list_retrieval_calls`` returns --
            one per search, each carrying ``source``, ``question`` and
            ``question_id``.

    Returns:
        Mapping of source -> ``{"count": int, "questions": [str, ...]}``.
        ``count`` is how many searches were issued to that source
        (distinct from how many distinct questions they served, which
        ``questions`` gives deduplicated in first-seen order).
    """
    aggregated: dict[str, dict[str, Any]] = {}
    seen_by_source: dict[str, set[str]] = {}
    for call in calls:
        source = str(call.get("source") or "")
        if not source:
            continue
        bucket = aggregated.setdefault(source, {"count": 0, "questions": []})
        bucket["count"] += 1
        question = str(call.get("question") or "").strip()
        # question_id is TEXT NOT NULL, which permits '' -- an empty id
        # must never read as "the same question already seen", so
        # dedup falls back to the question text itself rather than
        # collapsing every id-less row from one source into the first.
        dedup_key = str(call.get("question_id") or "") or question
        seen = seen_by_source.setdefault(source, set())
        if question and dedup_key not in seen:
            seen.add(dedup_key)
            bucket["questions"].append(question)
    return aggregated


def _render_retrieval_summary(calls: list[dict[str, Any]]) -> list[str]:
    """Render per-source search counts and the questions they served.

    Not a firehose of every query issued -- queries are source-shaped
    machine strings and mostly noise, while the questions they served
    are human-readable and few, so those are what a reader sees.

    Args:
        calls: A run's retrieval-call rows, or empty when the run made
            none (e.g. it ran below the extended/ultra tier, the only
            ones the research loop populates this table from).

    Returns:
        Markdown lines for a "Literature searches" block, or ``[]``.
    """
    aggregated = _aggregate_retrieval_calls(calls)
    if not aggregated:
        return []
    lines = ["**Literature searches:**", ""]
    for source in sorted(aggregated):
        bucket = aggregated[source]
        count = bucket["count"]
        noun = "search" if count == 1 else "searches"
        lines.append(f"- {source}: {count} {noun}")
        lines.extend(f"  - {q}" for q in bucket["questions"])
    lines.append("")
    return lines


def _render_data_source_notice(skills_used: dict[str, int]) -> list[str]:
    """Name the third-party databases this run queried, and their terms.

    Not a result -- an attribution the run owes. The science skills reach
    sources whose terms are separate from the bundle's Apache licence,
    and most of them require the user be notified of those terms. The
    harness satisfies the skills' own literal condition by seeding a
    notice file into the workspace, but a workspace is deleted and
    reaches nobody; this is the surface a person reads. Only the sources
    actually queried are named, because a blanket list of everything
    installed would attribute work to databases the run never touched.
    """
    if not skills_used:
        return []
    named = ", ".join(sorted(skills_used))
    return [
        f"This run queried the following third-party sources: {named}. "
        "Their terms of use are separate from this system's licence and "
        "are listed per source in `vendor/science-skills/"
        "SKILL_LICENSES.md`. Review them before relying on or "
        "redistributing these results.",
        "",
    ]


def _render_data_sources_section(
    skills_used: dict[str, int], retrieval_calls: list[dict[str, Any]]
) -> list[str]:
    """Render the combined 'Data sources' section, or nothing when empty.

    Joins the skill-attribution notice and the literature-search summary
    under one heading rather than two competing ones -- both answer the
    same reader question, "what did this run actually consult", from two
    independently populated stores.

    Args:
        skills_used: Science skill name -> invocations, or empty.
        retrieval_calls: The run's retrieval-call rows, or empty.

    Returns:
        Markdown lines for the section, or ``[]`` when neither source
        has anything to report.
    """
    body = _render_data_source_notice(skills_used)
    body += _render_retrieval_summary(retrieval_calls)
    if not body:
        return []
    return ["", "## Data sources", "", *body]
