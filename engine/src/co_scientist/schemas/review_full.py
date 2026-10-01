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
# only `drain/reviews.py::_ASSUMPTION_SUPPORT_LABELS` translates it
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
# (app/app/report/markdown/review_block.py), the same split every other
# published-vocabulary field uses.
#
# Declared on the full review rather than on REVIEW_SCHEMA's own
# ``review_summary`` (which the audit proposed promoting to an object):
# that field travels as ``HypothesisReview.review_summary: str`` and is
# read as a string by the ranking/evolution prompt projections and by
# app.engine_tasks.inputs's scientist-review marker test, so widening it
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


# R14-17 (15/19 published files): each axis of the published
# ``All reviews:`` appendix carries its own fixed sub-schema rather than
# one shared score+feedback template. Counted across the 19 published
# hypothesis documents, the sub-headings that recur are Correctness's
# Related Article Abstracts (11), Detailed Assumptions (14), Comparison
# with Knowledge Base (10), Strength of Evidence (14), Suggested
# Improvements (14) and Goal Requirement(s) Assessment (12); Feasibility's
# Steps to Test the Idea (13) and its reasoning paragraph (13); and Impact
# potential's Overall Impact Potential (13).
#
# Five of those had no field anywhere in this codebase. They are declared
# HERE, on the full review, and nowhere else -- deliberately not on
# ``REVIEW_SCHEMA``'s ``_SCORES_SCHEMA``/``_DETAILED_FEEDBACK_SCHEMA``,
# which ``REVIEW_BATCH_SCHEMA`` shares *by identity*: growth there
# multiplies by pool size on the one call that reviews the whole pool in
# a single turn (+6660 output tokens for 15 hypotheses at the maximal
# shape). The full review already runs once per mature hypothesis, so the
# same content costs the same call it always did and nothing new
# multiplies. ``test_schemas.py::
# test_per_axis_sub_structure_stays_off_the_batch_review_schema`` is the
# guard that keeps it that way.
#
# The published Correctness axis's own "Related Article Abstracts" part is
# absent on purpose and cannot be added here: it is a literal echo of the
# articles the prompt already supplied, and a structured-output schema
# that echoes its input scales the response with the input and truncates
# identically on every retry (the trap ``proximity_dedup`` hit). The
# renderer attaches it instead, from the citation/evidence rows the
# hypothesis already carries (``report.markdown.review_axes``).
PER_AXIS_REVIEW_PARTS: tuple[str, ...] = (
    "comparison_with_knowledge_base",
    "goal_requirements_assessment",
    "feasibility_steps",
    "feasibility_reasoning",
    "impact_assessment",
)

# Bounds the published "Steps to Test the Idea" list (model output, so
# bounded in the schema itself). The published exemplars print three to
# five numbered steps.
FEASIBILITY_STEPS_MAX_ITEMS = 5

_PER_AXIS_REVIEW_SCHEMA: dict[str, Any] = {
    "comparison_with_knowledge_base": {
        "type": "string",
        "description": (
            "How the hypothesis sits against established knowledge in"
            " the field: what it agrees with, what it contradicts."
        ),
    },
    "goal_requirements_assessment": {
        "type": "string",
        "description": (
            "Whether the hypothesis meets each requirement the research"
            " goal states, naming any requirement it does not meet."
        ),
    },
    "feasibility_steps": {
        **str_array(
            "The concrete steps that would test this hypothesis, each"
            " entry one step, in the order they would be run."
        ),
        "maxItems": FEASIBILITY_STEPS_MAX_ITEMS,
    },
    "feasibility_reasoning": {
        "type": "string",
        "description": (
            "Why those steps are or are not practical: the resources,"
            " techniques and time a decisive result would take."
        ),
    },
    "impact_assessment": {
        "type": "string",
        "description": (
            "What changes in the field if the hypothesis holds, and how"
            " much: the overall impact potential."
        ),
    },
}


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
            # R14-17: the five published per-axis sub-parts this codebase
            # had no field for. Declared on the full review only -- see
            # PER_AXIS_REVIEW_PARTS above for why the batch review's
            # shared sub-schemas are the wrong home.
            **_PER_AXIS_REVIEW_SCHEMA,
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
            # nothing else in this codebase (report.markdown.hypothesis's
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
            # Only the Go/No-Go pair stays optional: Google's own
            # published files carry it in 8 of 19, so a review that omits
            # it is not a malformed one.
            #
            # ``reviews_summary`` used to sit here for the same reason,
            # and the reason turned out to be the defect: optional *and*
            # unnamed by full_review.md, nothing ever asked for it. A
            # field the prompt does not mention and the schema does not
            # require is a declaration, not an output.
            #
            # That is a structural argument, not a measured one, and the
            # distinction matters. No local store holds a provider-backed
            # full review produced after the block shipped (2026-09-07
            # 09:38 UTC): every local ``full_review`` row either predates
            # the block and the drain that lifts it, or belongs to a
            # curated demo fixture. The fill rate is therefore unmeasured
            # -- do not read the local 0-of-36 as evidence about a model.
            #
            # Required now, and full_review.md names it and its eight
            # parts, which is the pairing that makes a required field
            # safe: requiring one the prompt never mentions rejects a
            # prompt-faithful answer and buys the same review a second
            # time (the failure test_review_types.py exists to prevent).
            "go_no_go_recommendation",
            "time_to_verdict",
        ),
    ),
}
