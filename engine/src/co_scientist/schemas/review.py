"""Structured schemas for initial, mature and pairwise hypothesis review."""

from typing import Any

from co_scientist.schemas.builders import obj, str_array

# The five evaluation aspects published ranking-05 tells the panel to
# consider, in the published order: "Potential for correctness/validity",
# "Utility and practical applicability", "Sufficiency of detail and
# specificity", "Novelty and originality", "Desirability for
# implementation". They replace seven clone-invented criteria that had no
# published source. One source for the schema's judgment_explanation
# keys, the aspect-to-key mapping both ranking templates print
# (prompts/templates/ranking_pairwise.md, ranking_debate.md), and the
# parse that collects the assessments onto the match record
# (agents/ranking/ranking_results.py, audit E17).
RANKING_COMPARISON_CRITERIA: tuple[str, ...] = (
    "correctness_comparison",
    "utility_comparison",
    "detail_comparison",
    "novelty_comparison",
    "desirability_comparison",
)

# Ranking schema
# Shapes both ranking prompts' output (ranking_pairwise = published A.4,
# ranking_debate = published A.5), consumed by the pairwise tournament
# comparison in agents/ranking/ranking.py. "winner" drives the Elo update
# (calculate_elo_update) for the pair; judgment_explanation breaks the
# comparison down per published evaluation aspect and is collected onto
# the persisted match record by
# ranking_results._extract_criteria_comparisons. The judge's concluding
# "better idea: <1 or 2>" line in decision_summary is the primary verdict
# (the paper's termination token); "winner" is the machine fallback when
# the line is absent (ranking_debate_turns._parse_matchup_winner).
#
# Echo-free: this schema used to require the model to repeat the research
# goal and both hypothesis texts back, which nothing read and which made
# the reply grow with the pool's text -- the failure mode the root
# CLAUDE.md records for proximity.
RANKING_SCHEMA: dict[str, Any] = {
    "name": "ranking_judgment",
    "strict": False,
    "schema": obj(
        {
            "winner": {
                "type": "string",
                "enum": ["a", "b"],
                "description": "The winning hypothesis (a or b)",
            },
            "judgment_explanation": obj(
                {
                    name: {"type": "string"}
                    for name in RANKING_COMPARISON_CRITERIA
                }
            ),
            "decision_summary": {"type": "string"},
            "confidence_level": {
                "type": "string",
                "enum": ["High", "Medium", "Low"],
            },
        }
    ),
}
# Proximity schema
# Shapes the "proximity" prompt output, consumed by
# agents/proximity/proximity.py to cluster near-duplicate hypotheses
# before deduplication. Each similar_hypotheses entry names its
# hypothesis by the "index" the prompt assigned it, which is how both
# deduplication (proximity_dedup._match_cluster_member) and the
# persisted proximity graph (proximity_graph._resolve_member_id)
# resolve a member; comparing the first 100 characters of an echoed
# "text" is only their shared fallback, since this schema forbids
# that key. Members are then grouped by cluster_id, keeping only the
# strongest of each "high" similarity_degree group.
PROXIMITY_SCHEMA: dict[str, Any] = {
    "name": "proximity_analysis",
    "strict": False,
    "schema": obj(
        {
            "similarity_clusters": {
                "type": "array",
                "items": obj(
                    {
                        "cluster_id": {"type": "string"},
                        "cluster_name": {"type": "string"},
                        "central_theme": {"type": "string"},
                        # Members are identified by the index the prompt
                        # assigns, not by echoing their text back: the echo
                        # scaled the response with the pool and overran the
                        # output budget on a large run, truncating the JSON
                        # and costing five identical retries before
                        # deduplication was skipped entirely.
                        "similar_hypotheses": {
                            "type": "array",
                            "items": obj(
                                {
                                    "index": {"type": "integer"},
                                    "similarity_degree": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                }
                            ),
                        },
                        "synthesis_potential": {"type": "string"},
                    }
                ),
            },
            "diversity_assessment": {"type": "string"},
            "redundancy_assessment": {"type": "string"},
        }
    ),
}


# Deep and full reviews share support values; ranking filters match them.
# Translate display labels only when rendering, without changing stored values.
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


# The full review's own schema, its R14-14 "Reviews summary" block, and
# the assumption-support vocabulary only those two and the deep
# verification schema below use, all live in ``review_full`` -- declaring
# the Reviews summary here took this module past its size budget. Every
# name is re-exported, so importers written against this module (the
# schema registry and package ``__init__`` among them) keep resolving.

# Axis ordering controls model output order; downstream readers use names.
_SCORE_CRITERIA: tuple[str, ...] = (
    "scientific_soundness",  # Correctness (1 of 2)
    "plausibility",  # Correctness (2 of 2)
    "novelty",  # Novelty
    "testability",  # Feasibility
    "potential_impact",  # Impact potential
    "relevance",  # not one of Google's four named axes
    "safety",  # not one of Google's four named axes
    "clarity",  # not one of Google's four named axes
)

# The review rubric's integer range, as both review prompts state it
# ("score 1-10 for each", bands 1-2 "not viable" through 9-10
# "outstanding"). Declared here so the schema bounds and the parse-time
# validation in agents/reflection/review_helpers.py share one source --
# the initial review gate's thresholds (constants/__init__.py) are calibrated
# against these same bands.
REVIEW_SCORE_MINIMUM: int = 1
REVIEW_SCORE_MAXIMUM: int = 10

# Sub-schemas shared by REVIEW_SCHEMA and REVIEW_BATCH_SCHEMA, referenced
# by identity from both (nothing mutates schema dicts at runtime; sharing
# schema objects across registry entries is the established pattern -- see
# GENERATION_SCHEMA's reuse in schemas/__init__.py).
_SCORES_SCHEMA: dict[str, Any] = obj(
    {
        name: {
            "type": "integer",
            "minimum": REVIEW_SCORE_MINIMUM,
            "maximum": REVIEW_SCORE_MAXIMUM,
        }
        for name in _SCORE_CRITERIA
    }
)

# R14-17: same Correctness/Novelty/Feasibility/Impact-first ordering as
# _SCORE_CRITERIA above, over whichever of the eight axes carry prose
# feedback (plausibility and safety do not -- a pre-existing asymmetry,
# not one this ordering change is meant to fix).
_FEEDBACK_DESCRIPTIONS: dict[str, str] = {
    "scientific_soundness": (
        "Specific feedback on theoretical foundation and logical consistency"
    ),
    "novelty": ("Specific feedback on originality and unique contribution"),
    "testability": "Specific feedback on feasibility of testing",
    "potential_impact": "Specific feedback on potential significance",
    "relevance": "Specific feedback on alignment with research goal",
    "clarity": ("Specific feedback on precision and clarity of formulation"),
}

_DETAILED_FEEDBACK_SCHEMA: dict[str, Any] = obj(
    {
        name: {"type": "string", "description": description}
        for name, description in _FEEDBACK_DESCRIPTIONS.items()
    }
)

NOVELTY_REVIEW_MAX_ITEMS = 6

# The novelty review: two named lists distinguishing what the hypothesis
# overlaps with existing work from what it does not (MO-3). The published
# novelty review (see above) is exactly these two lists -- "Aspects already
# explored:" and "Novel Aspects:" -- and no field distinguished them before
# this; the "novelty" score/detailed_feedback pair above stays untouched,
# since it is a different judgment (a 1-10 rating, not an enumeration).
# Shared between REVIEW_SCHEMA and REVIEW_BATCH_SCHEMA by identity, the same
# pattern as _SCORES_SCHEMA/_DETAILED_FEEDBACK_SCHEMA above.
_NOVELTY_REVIEW_SCHEMA: dict[str, Any] = obj(
    {
        "already_explored": {
            **str_array(
                "Aspects of the hypothesis already covered by existing"
                " work known to you, each entry one sentence naming what"
                " is already explored. Leave empty if nothing overlaps."
            ),
            "maxItems": NOVELTY_REVIEW_MAX_ITEMS,
        },
        "novel_aspects": {
            **str_array(
                "Aspects of the hypothesis you have not seen explored"
                " before, each entry one sentence naming what is novel."
                " Leave empty if nothing is novel."
            ),
            "maxItems": NOVELTY_REVIEW_MAX_ITEMS,
        },
    }
)

# Review schema
# Shapes the "review" prompt output, consumed by the single-hypothesis
# review path in agents/reflection/review.py. The scored criteria cover
# the paper's five default output criteria (SSR §1) -- relevance
# (alignment with the goal), plausibility, novelty, testability, and
# safety -- plus scientific_soundness,
# clarity, and potential_impact. Each scored criterion also appears as prose
# feedback under the matching key in detailed_feedback (safety additionally
# has the free-text safety_ethical_concerns field). overall_score is the
# average of the scores in "scores"; agents/reflection/review.py stores it
# as
# hypothesis.score, and it is later surfaced as prompt context for ranking,
# evolution, and meta-review (it does not feed the Elo rating math itself,
# which is driven solely by tournament win/loss outcomes).
REVIEW_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_review",
    "strict": False,
    "schema": obj(
        {
            "hypothesis_text": {
                "type": "string",
                "description": "The hypothesis being reviewed",
            },
            "review_summary": {
                "type": "string",
                "description": "Overall assessment (2-3 sentences)",
            },
            "scores": _SCORES_SCHEMA,
            "detailed_feedback": _DETAILED_FEEDBACK_SCHEMA,
            "constructive_feedback": {
                "type": "string",
                "description": (
                    "Specific, actionable suggestions for improvement"
                ),
            },
            "safety_ethical_concerns": {
                "type": "string",
                "description": "Any ethical or safety concerns",
            },
            "novelty_review": _NOVELTY_REVIEW_SCHEMA,
            "overall_score": {
                "type": "number",
                "description": "Calculated as average of criterion scores",
            },
        }
    ),
}
# Batch review schema - for reviewing multiple hypotheses together
# Shapes the "review_batch" prompt output, consumed by the comparative
# batch review path in agents/reflection/review.py. Per-item structure
# mirrors REVIEW_SCHEMA above (same shared scores/detailed_feedback
# sub-schemas) plus a comparative_notes field.
#
# hypothesis_index identifies which hypothesis an entry belongs to: it is
# the number the prompt assigned (Hypothesis 1, Hypothesis 2, ...), and
# review_helpers._match_batch_entries_to_hypotheses reads it to map
# entries back to hypotheses (falling back to list order only for
# entries whose index is absent, invalid, or duplicated). The hypothesis
# text is deliberately NOT echoed back: echoing scaled the response with
# the batch and is forbidden by the schema contract (see the proximity
# schema's identical rationale).
REVIEW_BATCH_SCHEMA: dict[str, Any] = {
    "name": "hypothesis_batch_review",
    "strict": False,
    "schema": obj(
        {
            "reviews": {
                "type": "array",
                "description": "Array of reviews, one for each hypothesis",
                "items": obj(
                    {
                        "hypothesis_index": {
                            "type": "integer",
                            "description": (
                                "The number assigned to the hypothesis in"
                                " the prompt: 1 for Hypothesis 1, 2 for"
                                " Hypothesis 2, and so on"
                            ),
                        },
                        "review_summary": {
                            "type": "string",
                            "description": "Overall assessment (2-3 sentences)",
                        },
                        "scores": _SCORES_SCHEMA,
                        "detailed_feedback": _DETAILED_FEEDBACK_SCHEMA,
                        "constructive_feedback": {
                            "type": "string",
                            "description": (
                                "Specific, actionable suggestions for"
                                " improvement"
                            ),
                        },
                        "safety_ethical_concerns": {
                            "type": "string",
                            "description": "Any ethical or safety concerns",
                        },
                        "novelty_review": _NOVELTY_REVIEW_SCHEMA,
                        "comparative_notes": {
                            "type": "string",
                            "description": (
                                "Brief note on how this hypothesis compares"
                                " to the others"
                            ),
                        },
                    },
                    optional=("comparative_notes",),
                ),
            }
        }
    ),
}
# Bounds the confirmed-strengths list (audit K8). Model output, so it is
# bounded in the schema itself -- the same policy the deep-verification
# decomposition lists below apply.
REFLECTION_MAX_POSITIVE_OBSERVATIONS = 5

# Reflection schema
# Shapes the "reflection_observations" prompt output, consumed by
# agents/reflection/reflection.py, which checks each hypothesis
# against retrieved
# literature/knowledge-graph evidence. "classification" is a closed enum
# the rest of the pipeline treats as a categorical verdict (e.g. surfaced
# verbatim in reflection notes shown to ranking/evolution).
# "positive_observations" carries the review's confirmed strengths (audit
# K8): the observation review both critiques and confirms, and the paper
# appends positive observations to the hypothesis
# (agents/reflection/observation_feedback.py does the appending).
# Optional, because the review often completes without any important
# findings and a missing field must read as "none found", not as a
# failure.
REFLECTION_SCHEMA: dict[str, Any] = {
    "name": "reflection_observations",
    "strict": False,
    "schema": obj(
        {
            "hypothesis_text": {
                "type": "string",
                "description": "The hypothesis being analyzed",
            },
            "reasoning": {
                "type": "string",
                "description": "Detailed reasoning for the classification",
            },
            "classification": {
                "type": "string",
                "enum": [
                    "already explained",
                    "other explanations more likely",
                    "missing piece",
                    "neutral",
                    "disproved",
                ],
                "description": (
                    "Classification of hypothesis based on literature"
                    " observations"
                ),
            },
            "positive_observations": {
                **str_array(
                    "Observations the hypothesis genuinely explains well:"
                    " confirmed strengths where it provides a superior or"
                    " mechanistically distinct explanation. Leave empty"
                    " when the review found none."
                ),
                "maxItems": REFLECTION_MAX_POSITIVE_OBSERVATIONS,
            },
        },
        optional=("positive_observations",),
    ),
}
# Deep-verification schema
# Shapes the "deep_verification" prompt output, consumed by
# agents/reflection/deep_verification.py. Beyond probing a hypothesis's
# fundamental assumptions with targeted questions, it carries the two
# other defining deep-verification behaviors (audit E4): the hypothesis
# decomposed into sub-assumptions with each one verified, and
# context-bound claims restated in general form (decontextualization).
# "verdict" is a closed enum ("holds"/"weakened"/"undermined") read back
# later by _format_deep_verification_context() in prompts.py to inject
# this hypothesis's verification into subsequent ranking (tournament)
# prompts. The code-side "unverified" verdict (a failed verification,
# audit E9) is never model output, so it is deliberately absent here.

# Bounds the decomposition lists. Both are model output, so they are
# bounded in the schema itself rather than by trimming the hypothesis the
# verifier is asked about.
DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS = 5
DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS = 3

DEEP_VERIFICATION_SCHEMA: dict[str, Any] = {
    "name": "deep_verification",
    "schema": obj(
        {
            "probes": {
                "type": "array",
                "items": obj(
                    {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                        "reasoning": {"type": "string"},
                        "assumption_is_fundamental": {"type": "boolean"},
                        # The question is prose, and the literature back end
                        # is a keyword index that ANDs every term, so the
                        # question itself retrieves nothing. This carries the
                        # few terms a relevant paper would actually contain,
                        # produced by the same call rather than a second one.
                        "search_query": {"type": "string"},
                    }
                ),
            },
            "sub_assumptions": {
                "type": "array",
                "maxItems": DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS,
                "items": obj(
                    {
                        "assumption": {"type": "string"},
                        "verification": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": list(ASSUMPTION_SUPPORT_VALUES),
                        },
                    }
                ),
            },
            "decontextualizations": {
                "type": "array",
                "maxItems": DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS,
                "items": obj(
                    {
                        "context_bound_claim": {"type": "string"},
                        "general_claim": {"type": "string"},
                        "assessment": {"type": "string"},
                    }
                ),
            },
            "verdict": {
                "type": "string",
                "enum": ["holds", "weakened", "undermined"],
            },
            "overall_assessment": {"type": "string"},
        }
    ),
}


# Simulation review (SSR §4): a step-through mental simulation of the proposed
# mechanism (or its test), surfacing the step where it would most likely fail.
# These properties must stay in step with what simulation_review.md asks for:
# the prompt requested a robustness assessment and the decisive step while the
# schema (closed, like every review schema here) declared neither, so the model
# answered with an undeclared `decisive_step`, validation rejected the whole
# response, and the node paid for a second full call to get the same content
# back under a name the schema accepted. Same for full_review.md above.
SIMULATION_REVIEW_SCHEMA: dict[str, Any] = {
    "name": "simulation_review",
    "schema": obj(
        {
            "model": {"type": "string"},
            "steps": {
                "type": "array",
                "items": obj(
                    {
                        "step": {"type": "string"},
                        "plausible": {"type": "boolean"},
                    }
                ),
            },
            "failure_points": str_array(),
            "robustness": {"type": "string"},
            "verdict": {
                "type": "string",
                "enum": ["holds", "partially_holds", "breaks_down"],
            },
            "decisive_step": {"type": "string"},
        }
    ),
}
