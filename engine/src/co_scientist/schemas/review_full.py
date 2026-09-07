"""The full review's schema, and what only it declares.

Split out of :mod:`co_scientist.schemas.review`, which reached its
module-size budget when the published "Reviews summary" block (R14-14)
was declared on this schema. Three things travel together here: that
block, the full review itself, and the assumption-support vocabulary the
two of them and deep verification share -- the vocabulary lives with the
schema that defines the fuller of its two uses, and ``review`` re-exports
every name, so importers written against that module keep resolving.
"""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

# The one vocabulary for "does the evidence back this assumption",
# shared by deep verification's sub_assumptions[].status and full
# review's assumptions[].support -- the same judgement asked twice, by
# two different reflection nodes. A single source keeps them from
# drifting into two enums that disagree again; change it here to change
# both schemas (and their prompt templates -- see
# test_prompts_schema_parity.py, which pins every enum value to be named
# in its own prompt's prose).
#
# R12-15/MO-4: Google's own published prose ("Plausible:", etc.) is a
# *display* decision, not a stored-value one -- mature_reviews.py's
# `assumptions_likely_false` filter matches the literal enum string, so
# only `drain_reviews.py::_ASSUMPTION_SUPPORT_LABELS` translates it
# (docs/PARITY.md REVIEW-ASSUMPTION-WORDING-001).
ASSUMPTION_SUPPORT_VALUES: tuple[str, ...] = (
    "supported",
    "uncertain",
    "likely_false",
)

# R14-14: the published per-hypothesis "Reviews summary" block, in the
# eight numbered parts every populated file of the 19-hypothesis
# published run prints (references/core/google-co-scientist/research/
# supplements/ai-guided-discovery-of-atypical-protein-assemblies/
# hypotheses/, e.g. development-seven-parameter-sni-*.md lines 137-183:
# "1. Executive Verdict" ... "8. Conclusion"). Keys are this codebase's
# snake_case; the reader-facing headings live with the renderer
# (app/app/report_markdown_review_block.py), the same split every other
# published-vocabulary field uses.
#
# Declared on the full review rather than on REVIEW_SCHEMA's own
# ``review_summary`` (which the audit proposed promoting to an object):
# that field travels as ``HypothesisReview.review_summary: str`` and is
# read as a string by the ranking/evolution prompt projections and by
# app.engine_tasks_inputs's scientist-review marker test, so widening it
# is a typed change across several agents. A full review's whole raw
# response reaches the report drain verbatim through
# ``hypothesis.enrichments[review_type.value]``, so declaring the block
# here needs no plumbing at all. The cost is coverage: the mature
# cascade reaches only the reviewed slice of the pool, so an entry with
# no full review carries no Reviews summary.
REVIEWS_SUMMARY_PARTS: tuple[str, ...] = (
    "executive_verdict",
    "critical_flaws",
    "addressed_objections",
    "validated_risks",
    "supporting_arguments",
    "alignment_and_novelty",
    "feasibility_assessment",
    "conclusion",
)

# Bounds each bulleted part (model output, so bounded in the schema
# itself). The published exemplars print two to four bullets per part.
REVIEWS_SUMMARY_MAX_ITEMS = 5

# Parts 2-7 are bulleted lists in every published exemplar; only the
# opening verdict and the closing conclusion are prose. Asking for prose
# where the published shape is a list invites a raw newline inside a JSON
# string value, which discards the whole response.
_REVIEWS_SUMMARY_LISTS: dict[str, str] = {
    "critical_flaws": (
        "Each entry one flaw that would sink the hypothesis if left"
        " unaddressed, naming the specific claim it breaks."
    ),
    "addressed_objections": (
        "Each entry one objection raised during review that the"
        " hypothesis or its evidence answers, and how."
    ),
    "validated_risks": (
        "Each entry one risk or limitation that survives review: real,"
        " but not on its own disqualifying."
    ),
    "supporting_arguments": (
        "Each entry one argument or piece of evidence that motivates the"
        " hypothesis."
    ),
    "alignment_and_novelty": (
        "Each entry one statement on how the hypothesis aligns with the"
        " research goal, or on what is genuinely new in it."
    ),
    "feasibility_assessment": (
        "Each entry one feasibility consideration -- resource"
        " intensity, technical complexity, or time to a decisive"
        " result."
    ),
}

REVIEWS_SUMMARY_SCHEMA: dict[str, Any] = obj(
    {
        "executive_verdict": {
            "type": "string",
            "description": (
                "A paragraph stating what the hypothesis proposes and"
                " whether it stands, ending in an explicit verdict."
            ),
        },
        **{
            name: {
                **str_array(description),
                "maxItems": REVIEWS_SUMMARY_MAX_ITEMS,
            }
            for name, description in _REVIEWS_SUMMARY_LISTS.items()
        },
        "conclusion": {
            "type": "string",
            "description": (
                "A closing paragraph: what the hypothesis is worth, and"
                " what would have to change for it to be worth testing."
            ),
        },
    }
)


# Full review (SSR §4): an in-depth correctness/quality/novelty review that
# also surfaces the hypothesis's key assumptions, distinct from the quick
# initial screen (REVIEW_SCHEMA).
FULL_REVIEW_SCHEMA: dict[str, Any] = {
    "name": "full_review",
    "schema": obj(
        {
            "correctness": {"type": "string"},
            # R14-14: the published executive block, above the per-axis
            # appendix. Filled by the same call as every other field
            # here -- no extra call, roughly +700 output tokens against
            # this node's own EXTENDED_MAX_TOKENS budget.
            "reviews_summary": REVIEWS_SUMMARY_SCHEMA,
            "assumptions": {
                "type": "array",
                "items": obj(
                    {
                        "assumption": {"type": "string"},
                        # MO-9: the published full review (e.g.
                        # docs/CORPUS-EXTRACTION.md,
                        # validated-outputs/kira6-detailed-output-validated.md
                        # -- 220 lines, sha256 b5a22b590874, "Reasoning about
                        # assumptions") prints a free-text paragraph beside
                        # every assumption; deep verification's
                        # sub_assumptions[].verification already carries this
                        # prose, but the full review previously carried only
                        # the closed enum below, so a hypothesis reviewed
                        # through full review alone lost the reasoning
                        # entirely.
                        "reasoning": {
                            "type": "string",
                            "description": (
                                "2-4 sentences of free-text reasoning for"
                                " why the evidence does or does not back"
                                " this assumption, referencing specific"
                                " evidence where available."
                            ),
                        },
                        "support": {
                            "type": "string",
                            "enum": list(ASSUMPTION_SUPPORT_VALUES),
                        },
                    }
                ),
            },
            "quality_and_novelty": {"type": "string"},
            "literature_grounding": {"type": "string"},
            "verdict": {
                "type": "string",
                "enum": ["sound", "needs_revision", "rejected"],
            },
            "justification": {"type": "string"},
            # R14-15: Google's published full review carries a bolded
            # free-text testing recommendation ("Verdict: <recommendation>",
            # wording varies -- not a closed enum) and an estimated
            # timeframe to a decisive result. Distinct from `verdict`
            # above, which is this review's own sound/needs_revision/
            # rejected disposition and the one field
            # `mature_reviews.apply_mature_review_disposition` reads to
            # gate the tournament -- these two are display-only, read by
            # nothing else in this codebase (report_markdown_hypothesis's
            # renderer is their only consumer). Optional: Google's own
            # published files carry this in only 8 of 19, so a review that
            # omits it is not a malformed one.
            "go_no_go_recommendation": {
                "type": "string",
                "description": (
                    "A short free-text testing recommendation, e.g. 'Go —"
                    " pursue wet-lab validation' or 'No-Go — mechanism"
                    " unsupported'. Advisory framing for the reader; it"
                    " does not replace verdict above."
                ),
            },
            "time_to_verdict": {
                "type": "string",
                "description": (
                    "A brief estimated timeframe to reach a decisive"
                    " experimental result, e.g. 'Short', '2-4 weeks', or"
                    " '2-3 months'."
                ),
            },
        },
        optional=(
            # Declared but not required, exactly as the Go/No-Go pair
            # above: full_review.md's numbered instructions do not ask
            # for this block (the schema appended to the prompt is what
            # names it), and a closed object that *requires* a field the
            # prompt never mentions rejects a prompt-faithful answer and
            # buys the same review a second time -- the failure
            # test_review_types.py exists to prevent.
            "reviews_summary",
            "go_no_go_recommendation",
            "time_to_verdict",
        ),
    ),
}
