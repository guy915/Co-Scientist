"""JSON schema for the meta-review stage.

Split out of schemas/planning.py (R14 wave) to stay under the
repo's 500-line file ceiling -- the supervisor and meta-review
schemas share no symbols, so the split is a pure move.
"""

from typing import Any, Final

from co_scientist.schemas.builders import obj, str_array

# Meta-review schema
# Shapes the "meta_review" prompt output, consumed by
# agents/meta_review/meta_review.py after a full review pass across
# all hypotheses.
# Synthesizes cross-hypothesis patterns (recurring_themes, strengths,
# weaknesses), assesses each pipeline stage (process_assessment), and
# proposes both concrete next-iteration guidance
# (strategic_recommendations) and cross-hypothesis synthesis opportunities
# (potential_connections). Downstream nodes re-inject this output as
# guidance text for later prompts via _format_meta_review_context() in
# prompts.py (review, ranking, reflection, research-overview, and debate
# generation prompts all accept it).
#
# candidate_comparison/existing_solutions_comparison (R12-9): the
# published report's per-idea comparison and its comparison against
# existing solutions belong here rather than on research_overview because
# they compare the *whole* reviewed pool (this call already sees every
# hypothesis with a review, not just the published top-k research_overview
# synthesizes from) and because Google's own analogous document
# (top-ranking-hypotheses.md, R14-11) bundles these comparisons with the
# recommendation section this schema already produces
# (strategic_recommendations, R12-11). Ideas are identified by the same
# hypothesis_index convention the prompt already establishes for
# potential_connections ("Hypothesis N: <subject>"), never by echoing a
# hypothesis's full text -- see AGENTS.md on echoing-input schemas. Both
# arrays are capped (_MAX_CANDIDATE_COMPARISON_IDEAS/_MAX_EXISTING_
# SOLUTIONS_ROWS) so a large reviewed pool cannot scale the response
# unboundedly, the same caution RESEARCH_OVERVIEW_MAX_SUB_TOPICS documents.
#
# The comparison axes (e.g. "computational scalability") used to be a fixed
# field set, which read as filler whenever a run's own discipline had no
# use for one of them -- a wet-lab biology idea has no "computational
# scalability" to report. `axes` lets the model name 2-5 axes that fit
# *this* run's subject matter, and each idea/row's `values` rates it on
# those same axes positionally (values[i] answers axes[i]) rather than
# against a fixed vocabulary -- so the table's shape follows the goal, not
# the schema. `report/markdown/meta_review.py` on the app side still
# renders the older fixed-field shape a run persisted before this existed;
# see its module docstring for that fallback.
_MAX_CANDIDATE_COMPARISON_IDEAS: Final = 10
_MAX_EXISTING_SOLUTIONS_ROWS: Final = 6
_MAX_COMPARISON_AXES: Final = 5

# MO-2: recurring_themes is a nested taxonomy, three levels deep, because
# Google's published meta-review critique
# (references/core/.../meta-review-critiques/als-meta-review-critique.md)
# is one -- five Roman-numbered themes, each holding named critique points
# ("Primary Driver vs. Consequence", "Specificity"), several of which hold
# their own guidance sub-points. It was flattened to {theme, description,
# frequency} in 69d10874 as an accepted adaptation; the nesting is back
# because the published shape is the target.
#
# Note what the artifact does NOT carry, so this schema does not invent it:
# a theme is a bare title (no description or frequency of its own in the
# published text -- ours keeps both, since they were already computed and
# rendered), a point narrates its frequency in its own prose rather than
# in a count field, and nothing anywhere cites example reviews. A
# sub-theme therefore has no `frequency` of its own: a second such field
# per sub-theme grows every entry to restate what its description says.
#
# The caps are the artifact's own maxima, not round numbers: it carries
# five themes, eight points under theme V ("General Advice Based on Common
# Critiques"), and five sub-points under theme I's "Specificity". A cap
# below any of those would have reshape_json_output silently clip a
# taxonomy shaped exactly like the exemplar (test_meta_review_themes.py::
# test_schema_caps_do_not_clip_the_published_taxonomy pins this).
_MAX_RECURRING_THEMES: Final = 6
_MAX_SUB_THEMES: Final = 8
_MAX_SUB_THEME_POINTS: Final = 5

META_REVIEW_SCHEMA: dict[str, Any] = {
    "name": "meta_review",
    "strict": False,
    "schema": obj(
        {
            "meta_review_summary": {
                "type": "string",
                "description": "Overall summary of meta-review analysis",
            },
            "recurring_themes": {
                "type": "array",
                "maxItems": _MAX_RECURRING_THEMES,
                "description": (
                    "A taxonomy of the recurring critiques, not a flat"
                    " list: a handful of broad themes, each holding the"
                    " named critique points that recur under it, each of"
                    " those holding the concrete guidance a future"
                    " proposal should follow."
                ),
                "items": obj(
                    {
                        "theme": {
                            "type": "string",
                            "description": (
                                "A broad critique theme spanning several"
                                " reviews, e.g. 'Core Hypothesis and"
                                " Mechanism' or 'Experimental Design and"
                                " Feasibility'."
                            ),
                        },
                        "description": {
                            "type": "string",
                            "description": (
                                "One or two sentences on what this theme"
                                " covers across the reviewed pool."
                            ),
                        },
                        "frequency": {
                            "type": "string",
                            "description": (
                                "How often this theme recurs, in the"
                                " reviews' own terms, e.g. 'very common'"
                                " or 'raised on most hypotheses'."
                            ),
                        },
                        "sub_themes": {
                            "type": "array",
                            "maxItems": _MAX_SUB_THEMES,
                            "description": (
                                "The named critique points recurring"
                                " under this theme. Empty only when the"
                                " theme genuinely has none."
                            ),
                            "items": obj(
                                {
                                    "theme": {
                                        "type": "string",
                                        "description": (
                                            "The critique point's own"
                                            " short name, e.g. 'Primary"
                                            " Driver vs. Consequence' or"
                                            " 'Model System"
                                            " Limitations'."
                                        ),
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": (
                                            "What reviewers said, and how"
                                            " widely -- state the"
                                            " prevalence in this prose"
                                            " ('a very common critique',"
                                            " 'several ideas') rather"
                                            " than as a count."
                                        ),
                                    },
                                    "points": {
                                        "type": "array",
                                        "maxItems": _MAX_SUB_THEME_POINTS,
                                        "items": {"type": "string"},
                                        "description": (
                                            "Concrete guidance a future"
                                            " proposal should follow to"
                                            " answer this critique. One"
                                            " short sentence each. Empty"
                                            " where the point needs no"
                                            " breakdown."
                                        ),
                                    },
                                },
                                optional=("points",),
                            ),
                        },
                    }
                ),
            },
            "strengths": str_array(),
            "weaknesses": str_array(),
            "process_assessment": obj(
                {
                    "generation_process": {"type": "string"},
                    "review_process": {"type": "string"},
                    "evolution_process": {"type": "string"},
                }
            ),
            "strategic_recommendations": {
                "type": "array",
                "items": obj(
                    {
                        "focus_area": {"type": "string"},
                        "recommendation": {"type": "string"},
                        "justification": {"type": "string"},
                        # R14-8: the published roadmap's richer step
                        # shape -- a time estimate, an optional lettered
                        # sub-phase, and which reviewed idea a step
                        # selects. All three are empty on most steps
                        # (only some published phases carry a letter),
                        # so none can be required.
                        "time_estimate": {
                            "type": "string",
                            "description": (
                                "This step's timeline, in the run's own"
                                " units, e.g. 'Weeks 1-2' or 'Month 3+'."
                                " Empty when this step carries no"
                                " explicit timeline."
                            ),
                        },
                        "phase_label": {
                            "type": "string",
                            "description": (
                                "A lettered sub-phase name when this"
                                " step splits into parts, e.g."
                                " 'Phase A'. Empty otherwise."
                            ),
                        },
                        "recommended_idea": {
                            "type": "string",
                            "description": (
                                "Names which reviewed idea(s) this step"
                                " selects, by the same hypothesis_index"
                                " convention as candidate_comparison."
                                "ideas (e.g. 'Hypothesis 1, building on"
                                " Hypothesis 4'). Refer to ideas by"
                                " number only -- never restate their"
                                " text. Empty when this step does not"
                                " single out one idea."
                            ),
                        },
                    },
                    optional=(
                        "time_estimate",
                        "phase_label",
                        "recommended_idea",
                    ),
                ),
            },
            "potential_connections": {
                "type": "array",
                "items": obj(
                    {
                        "related_hypotheses": str_array(),
                        "connection_type": {"type": "string"},
                        "synthesis_opportunity": {"type": "string"},
                    }
                ),
            },
            "candidate_comparison": obj(
                {
                    "thematic_summary": {
                        "type": "string",
                        "description": (
                            "How the candidate hypotheses group into"
                            " mechanistic themes, and which is best"
                            " supported by the reviewed evidence."
                        ),
                    },
                    "axes": {
                        "type": "array",
                        "maxItems": _MAX_COMPARISON_AXES,
                        "items": {"type": "string"},
                        "description": (
                            "2-5 short axis names to compare the ideas"
                            " on, chosen to fit THIS run's own"
                            " discipline -- e.g. 'Off-target risk' for a"
                            " chemical-biology goal, 'Cohort"
                            " availability' for a clinical-epidemiology"
                            " one. Do not default to generic"
                            " engineering/computational vocabulary"
                            " ('scalability', 'implementation"
                            " complexity') for a wet-lab biology"
                            " question it does not fit."
                        ),
                    },
                    "ideas": {
                        "type": "array",
                        "maxItems": _MAX_CANDIDATE_COMPARISON_IDEAS,
                        "items": obj(
                            {
                                "idea": {
                                    "type": "string",
                                    "description": (
                                        "The hypothesis_index and its"
                                        " subject, e.g. 'Hypothesis 3:"
                                        " LILRB4 blockade' -- never the"
                                        " full hypothesis text."
                                    ),
                                },
                                "values": str_array(
                                    "One rating per entry in `axes`, in"
                                    " the same order -- values[i]"
                                    " answers axes[i] for this idea."
                                ),
                            }
                        ),
                    },
                }
            ),
            "existing_solutions_comparison": obj(
                {
                    "summary": {
                        "type": "string",
                        "description": (
                            "How current standard-of-care approaches"
                            " compare to the candidate hypotheses as a"
                            " group. Leave this and `rows` empty when"
                            " this goal has no established"
                            " standard-of-care or existing-solutions"
                            " landscape to compare against (e.g. a basic"
                            " mechanism question) rather than inventing"
                            " one."
                        ),
                    },
                    "axes": {
                        "type": "array",
                        "maxItems": _MAX_COMPARISON_AXES,
                        "items": {"type": "string"},
                        "description": (
                            "2-5 short axis names to compare each"
                            " existing approach against the candidate"
                            " ideas on, chosen to fit this run's own"
                            " discipline -- see candidate_comparison"
                            "'s axes for the same guidance."
                        ),
                    },
                    "rows": {
                        "type": "array",
                        "maxItems": _MAX_EXISTING_SOLUTIONS_ROWS,
                        "items": obj(
                            {
                                "method": {
                                    "type": "string",
                                    "description": (
                                        "Name of the existing approach"
                                        " or standard-of-care baseline"
                                        " being compared."
                                    ),
                                },
                                "values": str_array(
                                    "One rating per entry in `axes`, in"
                                    " the same order -- values[i]"
                                    " answers axes[i] for this method."
                                ),
                            }
                        ),
                    },
                }
            ),
            # R14-27: the report's own "Main Research Directions" section --
            # narrative prose weaving the run's directions together, not a
            # second copy of any itemized array. Google's published ranking
            # report (top-ranking-hypotheses.md:24-28) carries exactly two
            # paragraphs, cross-cutting the run's candidate ideas the way
            # the two comparison fields above already do -- see
            # report/markdown/meta_review.py for the render and its
            # placement (report/markdown/__init__.py), immediately before
            # Top hypotheses, matching the published "before Candidate
            # Ideas" order. Required, like meta_review_summary, rather than
            # optional: every run has directions worth naming, so there is
            # no legitimate case for the model to leave this empty by
            # design (contrast existing_solutions_comparison.summary
            # above, which genuinely can be).
            "main_research_directions": {
                "type": "string",
                "description": (
                    "A narrative synthesis of this run's main research"
                    " directions, distinct from any itemized"
                    " per-direction list. Write exactly two flowing prose"
                    " paragraphs, separated by a blank line -- never a"
                    " bullet list. Name each direction inline in **bold**"
                    " the first time it appears (e.g. '**Metabolic State"
                    " as an Intervention Point**'), explain briefly why"
                    " it matters, and close the second paragraph with an"
                    " unanticipated observation that cuts across more"
                    " than one direction (e.g. 'Unexpectedly, recent"
                    " synthesis suggests ...'). Mirrors the published"
                    ' report\'s own "Main Research Directions" section:'
                    " connected narrative prose, not a restatement of"
                    " strategic_recommendations above."
                ),
            },
        }
    ),
}
