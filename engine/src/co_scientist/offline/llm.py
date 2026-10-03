"""Deterministic offline completions grounded in the supplied prompt and schema.

The local router installs only when explicitly requested. It produces stable
answers for offline models without invoking a provider.
"""

import hashlib
import itertools
import json
import logging
import random
import re
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from co_scientist.llm.request.backend import (
    CompletionBackend,
    active_backend,
    install_backend,
)

logger = logging.getLogger(__name__)


_STOPWORDS = frozenset(
    [
        "about",
        "above",
        "after",
        "against",
        "agent",
        "agents",
        "all",
        "also",
        "and",
        "are",
        "based",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "both",
        "but",
        "can",
        "could",
        "designed",
        "does",
        "drive",
        "driven",
        "during",
        "each",
        "either",
        "evolution",
        "from",
        "further",
        "generate",
        "generation",
        "goal",
        "had",
        "has",
        "have",
        "having",
        "help",
        "here",
        "how",
        "however",
        "hypotheses",
        "hypothesis",
        "identify",
        "into",
        "its",
        "itself",
        "meta-review",
        "might",
        "more",
        "most",
        "much",
        "must",
        "new",
        "novel",
        "only",
        "other",
        "over",
        "own",
        "particular",
        "potential",
        "propose",
        "proximity",
        "ranking",
        "reflection",
        "research",
        "review",
        "reviews",
        "same",
        "should",
        "since",
        "some",
        "such",
        "suggest",
        "supervisor",
        "task",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "under",
        "until",
        "use",
        "used",
        "using",
        "very",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "why",
        "will",
        "with",
        "within",
        "would",
        "you",
        "your",
    ]
)

# Field-name fragments mapped to the sentence shape that field should carry.
# Matched as substrings against the property name, longest first, so
# "constructive_feedback" resolves as feedback rather than as a bare noun.
_TITLE_TEMPLATES = (
    "{term_a} modulation of {term_b}",
    "{term_a}-dependent control of {term_b}",
    "Rerouting {term_b} via {term_a}",
    "{term_a} as a rate-limiting constraint on {term_b}",
    "{term_b} under sustained {term_a} load",
    "Decoupling {term_a} from {term_b}",
)

_STATEMENT_TEMPLATES = (
    "Sustained modulation of {term_a} suppresses {term_b} in the "
    "conditions described, producing a measurable, dose-dependent shift "
    "relative to untreated controls",
    "{term_a} constrains {term_b} through a feedback loop that becomes "
    "rate-limiting once the upstream pool is depleted",
    "Perturbing {term_a} redirects flux away from {term_b}, and the "
    "effect persists after the initial stimulus is withdrawn",
    "{term_b} is set by the residence time of {term_a}, so slowing "
    "turnover raises the threshold at which the response appears",
    "Two routes converge on {term_b}; closing the {term_a} route "
    "unmasks the second rather than abolishing the output",
    "The dependence of {term_b} on {term_a} inverts above a threshold, "
    "which is why partial and full loss give opposite readouts",
)

_MECHANISM_TEMPLATES = (
    "{term_a} acts upstream of {term_b}, so the effect appears only "
    "once the intermediate pool is depleted",
    "Binding at {term_a} shifts the equilibrium toward {term_b} without "
    "changing total abundance",
    "The pathway routes through {term_a}; blocking it forces "
    "compensatory flux into {term_b}",
    "{term_a} occupies the site {term_b} needs, so the two compete "
    "rather than acting in series",
    "Turnover of {term_a} sets how long {term_b} stays available, "
    "making the timing of the perturbation decisive",
    "A slow conformational step gates {term_a}, and {term_b} reports "
    "that step rather than the binding event itself",
)

_EXPERIMENT_TEMPLATES = (
    "Titrate {term_a} across a five-point range and read out {term_b} at "
    "24 and 72 hours against a vehicle control",
    "Knock down {term_a} in matched lines and compare {term_b} with a "
    "rescue arm to confirm on-target effect",
    "Measure {term_b} under {term_a} perturbation, with a discriminating "
    "negative control that should show no shift",
    "Stage the {term_a} perturbation before and after the {term_b} "
    "window, since order separates cause from correlate",
    "Pair a chemical and a genetic route to {term_a}, and accept the "
    "{term_b} result only where the two agree",
    "Track {term_b} continuously through a single {term_a} pulse "
    "instead of sampling endpoints",
)

_CRITIQUE_TEMPLATES = (
    "The link to {term_a} is plausible but under-specified; the "
    "proposal would be stronger with a stated effect size",
    "Novelty is moderate -- {term_b} is well covered, though this "
    "framing of {term_a} is less explored",
    "The experiment tests {term_b} but not the {term_a} step it depends "
    "on, so a negative result would be hard to interpret",
    "Two mechanisms predict this {term_b} result equally well, and "
    "nothing here separates them from the {term_a} side",
    "The {term_a} claim rests on one readout; a second, orthogonal "
    "measure of {term_b} would carry most of the weight",
    "Scope is the weakness rather than logic -- the {term_a} argument "
    "holds only where {term_b} is already saturated",
)

_SUMMARY_TEMPLATES = (
    "Centres on {term_a} as the tractable handle on {term_b}",
    "A {term_a}-first account of {term_b}, testable in a single arm",
    "Argues {term_b} follows from {term_a} rather than the reverse",
    "Treats {term_b} as the readout and {term_a} as the lever",
    "Puts the decisive step between {term_a} and {term_b}",
    "Separates the {term_a} contribution to {term_b} from its context",
)

# Short, standalone labels, not critique-shaped prose: FULL_REVIEW_SCHEMA's
# go_no_go_recommendation/time_to_verdict and META_REVIEW_SCHEMA's
# phase_label/recommended_idea/time_estimate render beside a UI label
# ("Verdict:", a roadmap step prefix), so leaf_text's _STANDALONE_TEMPLATES
# check below exempts them from the trailing _SCOPE_CLAUSES sentence every
# other field gets -- unexempted, they fell through to _SUMMARY_TEMPLATES
# and read as a stray argument next to a label meant to hold a phrase.
_GO_NO_GO_TEMPLATES = (
    "Go -- pursue the {term_a} experiment given the {term_b} evidence",
    "Go -- advance to validation, using {term_a} as the primary readout",
    "No-Go -- {term_a} remains unresolved without further {term_b} data",
    "Hold -- revisit once the {term_b} step clarifies {term_a}",
)

_TIME_ESTIMATE_TEMPLATES = (
    "Short (1-2 weeks)",
    "2-4 weeks",
    "1-2 months",
    "2-3 months",
    "One quarter",
)

_PHASE_LABEL_TEMPLATES = ("Phase A", "Phase B", "Phase C", "Stage 1", "Stage 2")

_RECOMMENDED_IDEA_TEMPLATES = (
    "Hypothesis 1",
    "Hypothesis 2",
    "Hypothesis 3",
    "Hypothesis 1, building on Hypothesis 2",
)

# One of these is appended to every non-title leaf, and it is what keeps two
# ideas in the same run from reading as the same idea.
#
# The near-duplicate guard compares *token coverage*, not strings, so
# swapping term_a for term_b buys nothing -- the bag of words is identical.
# The distinct-bag count was therefore only ``templates * C(terms, 2)``,
# which is 18 for a four-term goal: each evolved child had a 58% chance of
# matching a peer and being discarded, so a demo could finish showing no
# evolved ideas at all. Multiplying by a clause drawn independently is what
# lifts that space by an order of magnitude; ``test_offline_content.py``
# pins the floor.
#
# The vocabulary is deliberately about study design rather than biology.
# Every word here is excluded from term extraction below, so a clause
# sharing a word with a research goal would delete that word from the
# subject pool -- and shrinking the pool shrinks the very space this exists
# to widen.
_SCOPE_CLAUSES = (
    "in vehicle-matched replicates",
    "against a prespecified threshold",
    "once the washout period is complete",
    "at the low end of the titration",
    "before the compensatory arm engages",
    "with the readout blinded to condition",
    "across independently prepared batches",
    "holding the remaining variables fixed",
    "in the regime where the assay stays linear",
    "after the first exposure rather than the last",
    "where the baseline drift is smallest",
    "on the timescale the pathway actually turns over",
    "using a second, orthogonal readout",
    "with the confound removed by design",
    "restricted to the responders",
    "under the more conservative of two corrections",
    "and the direction survives the sensitivity analysis",
    "though the margin narrows in the replication arm",
    "with the effect concentrated in the earliest window",
    "which the pilot data already hint at",
    "though a ceiling appears at the top dose",
    "and nothing comparable is seen in the sham arm",
)

_FIELD_TEMPLATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Exact field names, ahead of the generic fragments below, so a
    # standalone-label field can never be shadowed by a broader match.
    ("go_no_go_recommendation", _GO_NO_GO_TEMPLATES),
    ("time_to_verdict", _TIME_ESTIMATE_TEMPLATES),
    ("time_estimate", _TIME_ESTIMATE_TEMPLATES),
    ("phase_label", _PHASE_LABEL_TEMPLATES),
    ("recommended_idea", _RECOMMENDED_IDEA_TEMPLATES),
    ("experiment", _EXPERIMENT_TEMPLATES),
    ("feedback", _CRITIQUE_TEMPLATES),
    ("critique", _CRITIQUE_TEMPLATES),
    ("reasoning", _CRITIQUE_TEMPLATES),
    ("rationale", _CRITIQUE_TEMPLATES),
    ("comparison", _CRITIQUE_TEMPLATES),
    ("weakness", _CRITIQUE_TEMPLATES),
    ("strength", _SUMMARY_TEMPLATES),
    ("mechanism", _MECHANISM_TEMPLATES),
    ("explanation", _MECHANISM_TEMPLATES),
    ("summary", _SUMMARY_TEMPLATES),
    ("overview", _SUMMARY_TEMPLATES),
    ("title", _TITLE_TEMPLATES),
    ("name", _TITLE_TEMPLATES),
    ("hypothesis", _STATEMENT_TEMPLATES),
    ("statement", _STATEMENT_TEMPLATES),
    ("text", _STATEMENT_TEMPLATES),
)

# Only reached when the goal yields fewer than two usable terms. Kept out of
# the pool otherwise: mixed in with real terms they were drawn often enough
# to swamp the subject, and a run about pancreatic cancer read as being
# about "the downstream effector". No leading article, because the templates
# supply their own ("the {term_a} step").
_FALLBACK_TERMS = (
    "upstream regulation",
    "rate-limiting control",
    "downstream signalling",
    "pathway flux",
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z-]{3,}")

# This module's own vocabulary, excluded from term extraction so generated
# text can never be mined as if it were subject matter. It can be: the
# evolution prompt hands over a parent hypothesis this module wrote, so
# without the exclusion the output feeds on itself and compounds
# ("Sustained modulation of modulation suppresses conditions"). Derived from
# the templates rather than listed by hand, so editing a template cannot
# leave a stale exclusion behind.
#
# The four standalone-label template tuples (_GO_NO_GO_TEMPLATES and its
# siblings, see _STANDALONE_TEMPLATES below) are deliberately left out of
# this derivation. Their words -- "evidence", "data", "validation",
# "primary", "step", "phase", "stage", "hold" -- are exactly the kind of
# term a real research goal carries, so excluding them would strip real
# subject terms for no protection: none of these five fields is ever read
# back as a parent hypothesis or otherwise mined by _goal_text/subject_terms
# (full-review fields are display-only; meta-review's roadmap items sit
# under their own heading, not "Research Goal"/"Original Hypothesis").
_GENERATED_VOCABULARY = frozenset(
    word.lower()
    for template in (
        *_TITLE_TEMPLATES,
        *_STATEMENT_TEMPLATES,
        *_MECHANISM_TEMPLATES,
        *_EXPERIMENT_TEMPLATES,
        *_CRITIQUE_TEMPLATES,
        *_SUMMARY_TEMPLATES,
        *_FALLBACK_TERMS,
        *_SCOPE_CLAUSES,
    )
    for word in _WORD_RE.findall(template)
)

# The goal's heading, in the forms the prompt templates use for it
# ("## Research Goal", "**Research Goal:**", "Research Goal: ..."). Anchored
# to the start of a line so the phrase appearing mid-sentence elsewhere
# ("Relevance to Research Goal") cannot be mistaken for it.
#
# "Original Hypothesis" is the evolution prompt's equivalent: it never
# states the goal, but the parent hypothesis it hands over is about the same
# subject, so an evolved idea stays on-topic instead of falling back to
# generic prose. "Original Conceptualization" is the same slot under the
# label published evolution-06 gives it (templates/evolution_feasibility.md);
# without it every offline feasibility refinement fell back to generic
# prose while its siblings stayed on topic. Tried in order, first match
# wins.
_GOAL_HEADING_RE = re.compile(
    r"^[ \t]*(?:#+[ \t]*|\*\*)?"
    r"(?:research goal|original hypothesis|original conceptualization)"
    r"\b[:*]*[ \t]*",
    re.IGNORECASE | re.M,
)

# The goal ends at the next blank line or section heading. Without a bound
# the scan runs straight on into the surrounding boilerplate, and since a
# goal is one or two sentences the boilerplate wins: offline runs came out
# talking about "author-year", "meta-review" and "requirements" whatever
# they were actually about. The cap is a backstop for a prompt with no such
# break.
_GOAL_END_RE = re.compile(r"\n\s*\n|\n[ \t]*(?:#+|\*\*|-|\d+\.)")
_GOAL_SCAN_CHARS = 600


def _goal_text(prompt: str) -> str:
    """The research-goal span of a prompt, or "" when it states no goal.

    An unlabelled prompt yields nothing rather than falling back to the
    prompt head: the head is the agent's own title and role description, so
    mining it produces terms about the machinery instead of the science
    ("Agent constrains evolution ..."). Generic-but-clean beats that, and
    :func:`subject_terms` supplies it.
    """
    heading = _GOAL_HEADING_RE.search(prompt)
    if heading is None:
        return ""
    span = prompt[heading.end() : heading.end() + _GOAL_SCAN_CHARS]
    end = _GOAL_END_RE.search(span)
    return span[: end.start()] if end else span


def subject_terms(prompt: str) -> tuple[str, ...]:
    """Salient subject terms lifted from a prompt's research goal.

    Deliberately a naive keyword pass: this only has to make offline prose
    read as if it is about the run's topic, so a wrong term costs nothing
    and the simplicity keeps the backend dependency-free and fast.

    Args:
        prompt: The outgoing prompt text.

    Returns:
        Distinct lower-cased terms in first-seen order, or the generic
        fallbacks when the goal yields fewer than the two a template needs.
    """
    seen: list[str] = []
    for match in _WORD_RE.findall(_goal_text(prompt)):
        word = match.lower()
        if word in _STOPWORDS or word in _GENERATED_VOCABULARY:
            continue
        if word in seen:
            continue
        seen.append(word)
    return tuple(seen) if len(seen) >= 2 else _FALLBACK_TERMS


def _templates_for(field: str) -> tuple[str, ...]:
    """Return the sentence shapes appropriate to one property name."""
    lowered = field.lower()
    for fragment, templates in _FIELD_TEMPLATES:
        if fragment in lowered:
            return templates
    return _SUMMARY_TEMPLATES


# Already a complete, short label -- a _SCOPE_CLAUSES sentence appended to
# "Phase A" or "2-4 weeks" would turn a label into a run-on.
_STANDALONE_TEMPLATES: tuple[tuple[str, ...], ...] = (
    _GO_NO_GO_TEMPLATES,
    _TIME_ESTIMATE_TEMPLATES,
    _PHASE_LABEL_TEMPLATES,
    _RECOMMENDED_IDEA_TEMPLATES,
)


def leaf_text(
    rng: random.Random,
    ordinal: int,
    field: str,
    terms: tuple[str, ...],
) -> str:
    """Build one deterministic, field-appropriate, goal-grounded leaf.

    Args:
        rng: The per-call seeded RNG. Every draw advances the shared
            sequence, so identical inputs reproduce byte-identical output
            while later leaves in the same response read differently.
        ordinal: 1-based position of this leaf within the current response.
            Two leaves can otherwise collide on the same template and terms,
            and ``state.deduplicate_hypotheses`` collapses hypotheses whose
            normalized text is equal -- so a run would silently lose ideas.
            Titles carry it visibly, because readers expect distinct
            headings and a title is too short to hide a clause in.
        field: The property name being filled, or "" when unknown.
        terms: Subject vocabulary from :func:`subject_terms`.

    Returns:
        A sentence suitable for that field.
    """
    templates = _templates_for(field)
    template = templates[rng.randrange(len(templates))]
    # _FALLBACK_TERMS guarantees at least two draws even for a caller that
    # passes a short list directly.
    pool = terms if len(terms) >= 2 else terms + _FALLBACK_TERMS
    term_a, term_b = rng.sample(pool, 2)
    text = template.format(term_a=term_a, term_b=term_b)
    if templates is _TITLE_TEMPLATES:
        return f"{text[:1].upper()}{text[1:]} ({ordinal})"
    if templates in _STANDALONE_TEMPLATES:
        return f"{text[:1].upper()}{text[1:]}"
    # Drawn after the terms, so the clause varies independently of them --
    # see _SCOPE_CLAUSES for why an independent draw is the whole point.
    clause = _SCOPE_CLAUSES[rng.randrange(len(_SCOPE_CLAUSES))]
    joiner = " " if clause.startswith("and ") else ", "
    return f"{text[:1].upper()}{text[1:]}{joiner}{clause}."


# Placeholder values for scalar schema types this filler special-cases.
_SCALAR_DEFAULTS: dict[str, Any] = {
    "integer": 4,
    "number": 4.0,
    "boolean": True,
}


@dataclass(frozen=True)
class _FillHints:
    """Per-call hints threaded through the schema-filling traversal.

    Bundled into one object, rather than two parameters, because
    ``_fill_array`` already sits at the five-parameter ceiling (schema,
    count, leaf_fn, hints, field) -- see the repo's PLR0913 convention.

    Attributes:
        array_lengths: Property-name -> item-count map; an array property
            whose name is a key here is filled to that length instead of
            the default one item. See ``offline.llm._ARRAY_LENGTH_HINTS``.
        scalar_values: Property-name -> override value for a scalar leaf,
            read ahead of ``_SCALAR_DEFAULTS``. See
            ``offline.llm._SCALAR_VALUE_HINTS``.
        optional_fields: Property names to fill even though their object
            node's schema marks them optional. Empty by default -- an
            optional property is normally left absent, the same way a real
            provider genuinely omits one. See
            ``offline.llm._OPTIONAL_FIELD_HINTS``, which is the only
            producer of a non-empty set here: it is scoped per schema name,
            not a blanket "fill every optional" switch.
    """

    array_lengths: dict[str, int] = field(default_factory=dict)
    scalar_values: dict[str, Any] = field(default_factory=dict)
    optional_fields: frozenset[str] = frozenset()


def _scalar_leaf_value(schema_type: str, field: str, hints: _FillHints) -> Any:
    """Resolves one scalar leaf, honoring a per-field value override.

    Args:
        schema_type: The scalar's JSON Schema "type" (a key in
            ``_SCALAR_DEFAULTS``).
        field: The property name this scalar fills.
        hints: The call's array-length and scalar-value hints.

    Returns:
        ``hints.scalar_values[field]`` when set, else the generic
        ``_SCALAR_DEFAULTS[schema_type]`` placeholder.
    """
    if field in hints.scalar_values:
        return hints.scalar_values[field]
    return _SCALAR_DEFAULTS[schema_type]


def _fill_schema(
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    hints: _FillHints | None = None,
    field: str = "",
) -> Any:
    """Builds a minimal value satisfying one JSON-schema node.

    Args:
        schema: A JSON Schema fragment (object, array, or scalar).
        leaf_fn: Callable taking the property name being filled and
            returning the next string-leaf value; called once per string
            leaf encountered. Callers choose the uniqueness strategy (a
            seeded RNG for the runtime router, a process-global counter for
            the test fake).
        hints: Optional array-length and scalar-value hints (see
            ``_FillHints``); defaults to no hints.
        field: Name of the property this node is filling, passed to
            ``leaf_fn`` so a leaf can read as the field it lands in.
            Empty at the schema root.

    Returns:
        A value satisfying ``schema``: object properties filled
        recursively, array items filled per ``hints.array_lengths``
        (default one), an enum's first allowed value, or a scalar
        placeholder (per ``hints.scalar_values``, else the generic
        default).
    """
    hints = hints or _FillHints()

    if "enum" in schema:
        return schema["enum"][0]

    schema_type = schema.get("type", "object")

    if schema_type == "object":
        return _fill_object(schema, leaf_fn, hints)

    if schema_type == "array":
        return _fill_array(schema, 1, leaf_fn, hints, field)

    if schema_type in _SCALAR_DEFAULTS:
        return _scalar_leaf_value(schema_type, field, hints)

    # string, or any type this filler does not special-case.
    return leaf_fn(field)


def _fill_object(
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    hints: _FillHints,
) -> dict[str, Any]:
    """Fills every required property, plus any hinted optional ones.

    Args:
        schema: The object's JSON Schema fragment.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        hints: Array-length, scalar-value, and optional-field hints,
            threaded into each property's fill. ``hints.optional_fields``
            is empty by default, so a property this node's own schema
            marks optional stays absent unless a caller named it.

    Returns:
        A dict mapping each filled property name to its value.
    """
    properties = schema.get("properties", {})
    required = schema.get("required") or list(properties.keys())
    return {
        name: _fill_property(name, prop_schema, leaf_fn, hints)
        for name, prop_schema in properties.items()
        if name in required or name in hints.optional_fields
    }


def _fill_property(
    name: str,
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    hints: _FillHints,
) -> Any:
    """Fills one object property, honoring an array-length hint by name.

    Args:
        name: The property name, checked against ``hints.array_lengths``.
        schema: The property's own JSON Schema fragment.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        hints: Array-length and scalar-value hints.

    Returns:
        The filled property value.
    """
    if schema.get("type") == "array" and name in hints.array_lengths:
        return _fill_array(
            schema, hints.array_lengths[name], leaf_fn, hints, name
        )
    return _fill_schema(schema, leaf_fn, hints, name)


def _fill_array(
    schema: dict[str, Any],
    count: int,
    leaf_fn: Callable[[str], Any],
    hints: _FillHints,
    field: str = "",
) -> list[Any]:
    """Fills an array schema with ``count`` (at least one) filled items.

    Args:
        schema: The array's JSON Schema fragment (reads "items").
        count: Desired item count; clamped up to one.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        hints: Array-length and scalar-value hints, threaded into each
            item's fill so length hints apply at any nesting depth.
        field: Name of the array property, passed down so an item reads as
            the field it belongs to.

    Returns:
        A list of ``max(count, 1)`` filled items.
    """
    item_schema = schema.get("items", {"type": "string"})
    return [
        _fill_schema(item_schema, leaf_fn, hints, field)
        for _ in range(max(count, 1))
    ]


OFFLINE_MODEL_PREFIX = "offline/"
DEFAULT_OFFLINE_MODEL = f"{OFFLINE_MODEL_PREFIX}deterministic"


def is_offline_model(model_name: str) -> bool:
    """Checks whether a model name is routed to the offline responder.

    Args:
        model_name: Model name in litellm format.

    Returns:
        True if ``model_name`` starts with ``OFFLINE_MODEL_PREFIX``.
    """
    return model_name.startswith(OFFLINE_MODEL_PREFIX)


_HYPOTHESIS_MARKER_RE = re.compile(r"\*\*Hypothesis \d+:\*\*")


def _batch_review_length(prompt: str) -> dict[str, int]:
    """Counts the "**Hypothesis N:**" markers in a batch-review prompt.

    Args:
        prompt: The rendered batch-review prompt text.

    Returns:
        ``{"reviews": count}`` sized to the number of hypotheses in the
        batch (at least one), matching the property name in
        ``REVIEW_BATCH_SCHEMA``.
    """
    count = len(_HYPOTHESIS_MARKER_RE.findall(prompt))
    return {"reviews": max(count, 1)}


_CANDIDATE_MARKER_RE = re.compile(r"\*\*Candidate \d+:\*\*")


def _relevance_batch_length(prompt: str) -> dict[str, int]:
    """Counts the "**Candidate N:**" markers in a relevance-batch prompt.

    Args:
        prompt: The rendered literature-relevance-batch prompt text.

    Returns:
        ``{"judgments": count}`` sized to the number of candidates in the
        batch (at least one), matching the property name in
        ``LITERATURE_RELEVANCE_BATCH_SCHEMA``. Without this hint the
        generic filler defaults every array to one item, which would
        leave every candidate past the first unjudged on the offline
        backend even though a real batch call judges all of them.
    """
    count = len(_CANDIDATE_MARKER_RE.findall(prompt))
    return {"judgments": max(count, 1)}


# Unlike the batch-review count above, a research overview's directions
# have no 1:1 correspondence with anything the prompt declares -- the
# model freely decides how many major directions a hypothesis pool
# resolves into. This hook is therefore a fixed count, not a prompt
# reading: enough to clear the report's directions-preview gate
# (report/markdown/overview.py::_render_directions_preview renders
# nothing below two named directions), so an offline run reads as having
# found several directions worth pursuing rather than exactly one.
_RESEARCH_DIRECTIONS_COUNT = 3

# Task B: sized to the schema's own maxItems
# (RESEARCH_OVERVIEW_MAX_UNEXPECTED_DIRECTIONS) rather than the bare
# one-item default, so an offline run's demo reads as having found
# several unexpected directions -- matching MASH's own published
# exemplar, which carries exactly three.
_UNEXPECTED_DIRECTIONS_COUNT = 3


def _research_overview_directions_length(_prompt: str) -> dict[str, int]:
    """Sizes both research-overview direction arrays past their defaults.

    Args:
        _prompt: The rendered research-overview prompt (unused; both
            counts are fixed rather than derived from prompt content --
            see the module-level comments on ``_RESEARCH_DIRECTIONS_COUNT``
            and ``_UNEXPECTED_DIRECTIONS_COUNT``).

    Returns:
        ``{"research_directions": _RESEARCH_DIRECTIONS_COUNT,
        "unexpected_research_directions": _UNEXPECTED_DIRECTIONS_COUNT}``.
    """
    return {
        "research_directions": _RESEARCH_DIRECTIONS_COUNT,
        "unexpected_research_directions": _UNEXPECTED_DIRECTIONS_COUNT,
    }


# Per-schema-name hooks that compute a {property_name: item_count} map from
# the prompt text, for the few schemas whose array length must match a
# count baked into the prompt rather than the generic filler's default of
# one item per array.
_ARRAY_LENGTH_HINTS: dict[str, Callable[[str], dict[str, int]]] = {
    "hypothesis_batch_review": _batch_review_length,
    "research_overview": _research_overview_directions_length,
    "literature_relevance_batch": _relevance_batch_length,
}

# The review rubric's eight scored axes (schemas/review.py's private
# _SCORE_CRITERIA, mirrored here rather than imported across that privacy
# boundary) plus the descriptive overall_score. Every offline review's
# every score otherwise defaults through _SCALAR_DEFAULTS to exactly
# NEEDS_REVISION_SCORE (constants/__init__.py, currently 4), which the initial
# review gate reads with a <=, not a <: every offline-reviewed hypothesis
# therefore lands in "needs_revision", never "viable" --
# review_gate._disposition_for -- and only a "viable" hypothesis reaches
# Reflection's full/simulation/recurrent cascade
# (mature_reviews.reviews_needed), so that cascade never fires on the
# offline backend. This override lands every score comfortably inside the
# rubric's "good" band instead, clear of that boundary, without touching
# NEEDS_REVISION_SCORE itself or any other schema's integer fields --
# every other integer this filler fills is a pool index (a batch review's
# hypothesis_index, a proximity cluster member's index, ...), not a
# score, and stays at the generic default.
_REVIEW_SCORE_FIELDS: tuple[str, ...] = (
    "scientific_soundness",
    "plausibility",
    "novelty",
    "testability",
    "potential_impact",
    "relevance",
    "safety",
    "clarity",
    "overall_score",
)
_REVIEW_SCORE_VALUE = 7

# Per-schema-name {property_name: value} overrides for a scalar leaf,
# read ahead of _SCALAR_DEFAULTS. Both REVIEW_SCHEMA and
# REVIEW_BATCH_SCHEMA share the same scored-axis vocabulary (via
# schemas/review.py's _SCORES_SCHEMA), so both schema names get the same
# override table.
_SCALAR_VALUE_HINTS: dict[str, dict[str, Any]] = {
    "hypothesis_review": dict.fromkeys(
        _REVIEW_SCORE_FIELDS, _REVIEW_SCORE_VALUE
    ),
    "hypothesis_batch_review": dict.fromkeys(
        _REVIEW_SCORE_FIELDS, _REVIEW_SCORE_VALUE
    ),
}

# Per-schema-name optional properties the filler fills anyway, despite the
# schema marking them optional (see offline.schema_fill._FillHints.
# optional_fields). Deliberately scoped, not a global "fill every optional"
# switch: a real provider genuinely omits optional fields, so defaulting to
# filling them everywhere would change offline output broadly and stop
# representing that. Only a schema named here, for only the properties
# named here, is filled -- every other optional property across every
# other schema stays absent, as it did before this hint existed.
#
# Both entries below were found dark (docs/decisions/2026-09-02-offline-
# optional-field-reach.md): FULL_REVIEW_SCHEMA's go_no_go_recommendation/
# time_to_verdict feed drain.reviews._verdict_detail, which
# ideas_detail_review_findings.tsx's VerdictLines never renders without
# them; META_REVIEW_SCHEMA's strategic_recommendations[] time_estimate/
# phase_label/recommended_idea feed report.markdown.meta_review's
# _render_recommendation the same way. Both are plain free-text fields --
# no value needs to reference another part of the response -- so a name
# list alone is enough; see the ADR for the optional fields left out
# because they need more than that (a value with particular structure, or
# are blocked upstream by a required field).
_OPTIONAL_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "full_review": (
        # ``reviews_summary`` used to be listed here. It is required on
        # the schema now (full_review.md names it and its eight parts),
        # so the generic filler fills it like any other required field
        # and hinting it would only duplicate that -- the drift guard in
        # test_offline_optional_fields.py pins this tuple to the
        # schema's *optional* properties exactly.
        "go_no_go_recommendation",
        "time_to_verdict",
    ),
    "meta_review": (
        "time_estimate",
        "phase_label",
        "recommended_idea",
        "points",
    ),
}


def _build_response(content: str) -> Any:
    """Builds the nested object a litellm completion response exposes.

    Args:
        content: The text ``_extract_completion_content`` should return.

    Returns:
        An object shaped like ``litellm.acompletion``'s return value, as
        far as ``co_scientist.llm`` reads it
        (``response.choices[0].message.content``).
    """
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


def _prompt_text(completion_args: dict[str, Any]) -> str:
    """Extracts the outgoing prompt text from completion call kwargs.

    Args:
        completion_args: The completion arguments built by
            ``co_scientist.llm.request.completion._build_completion_args``.

    Returns:
        The last message's content, or "" if there are no messages.
    """
    messages = completion_args.get("messages") or []
    if not messages:
        return ""
    return str(messages[-1].get("content", ""))


def _seed_for(model: str, prompt: str, schema_name: str) -> int:
    """Derives a deterministic RNG seed from a call's identity.

    Args:
        model: The requested model name.
        prompt: The outgoing prompt text.
        schema_name: The response schema's "name" field, or "" when the
            call is schema-less.

    Returns:
        An integer seed: identical for identical (model, prompt,
        schema_name) triples, and (with overwhelming probability)
        different otherwise.
    """
    digest = hashlib.sha256(
        "\x00".join((model, prompt, schema_name)).encode("utf-8")
    ).digest()
    return int.from_bytes(digest, byteorder="big")


def _supervisor_allocation_response(prompt: str) -> str:
    """Builds a deterministic ``supervisor_allocation`` decision.

    Exercises model-directed scheduling with a stable adaptive portfolio:
    improve leaders first, then explore new regions. Reads flags baked into
    the planning prompt by ``_planning_prompt`` rather than drawing from the
    schema filler, since the scheduling decision must react to run state
    rather than being an arbitrary valid value.

    Args:
        prompt: The rendered supervisor-allocation planning prompt.

    Returns:
        JSON text satisfying the ``supervisor_allocation`` schema.
    """
    needs_proximity = '"pool_grew_since_proximity": true' in prompt
    first_cycle = '"iteration": 0' in prompt
    next_task = (
        "proximity"
        if needs_proximity
        else ("evolve" if first_cycle else "generate")
    )
    reason = (
        "Refresh the scientific similarity landscape."
        if needs_proximity
        else (
            "Improve reviewed leaders."
            if first_cycle
            else "Explore an underdeveloped direction."
        )
    )
    return json.dumps({"next_task": next_task, "reason": reason})


def _schema_response(
    model: str, prompt: str, json_schema: dict[str, Any]
) -> Any:
    """Builds a fake completion response for a schema'd offline call.

    Args:
        model: The requested model name.
        prompt: The outgoing prompt text.
        json_schema: The ``response_format["json_schema"]`` payload (name
            and schema).

    Returns:
        A fake completion response exposing
        ``.choices[0].message.content``.
    """
    schema_name = json_schema.get("name", "")

    if schema_name == "supervisor_allocation":
        return _build_response(_supervisor_allocation_response(prompt))

    rng = random.Random(_seed_for(model, prompt, schema_name))
    ordinals = itertools.count(1)
    terms = subject_terms(prompt)

    def leaf_fn(field: str) -> str:
        return leaf_text(rng, next(ordinals), field, terms)

    schema = json_schema["schema"]
    length_hint = _ARRAY_LENGTH_HINTS.get(schema_name)
    hints = _FillHints(
        array_lengths=length_hint(prompt) if length_hint else {},
        scalar_values=_SCALAR_VALUE_HINTS.get(schema_name, {}),
        optional_fields=frozenset(_OPTIONAL_FIELD_HINTS.get(schema_name, ())),
    )
    content = json.dumps(_fill_schema(schema, leaf_fn, hints))
    return _build_response(content)


async def offline_acompletion(**completion_args: Any) -> Any:
    """Stands in for ``litellm.acompletion`` for ``offline/`` models.

    Builds schema-true JSON for a schema'd call, or deterministic free text
    otherwise. See the module docstring for the determinism contract.

    Args:
        **completion_args: The completion arguments built by
            ``co_scientist.llm.request.completion._build_completion_args``
            (model, messages, response_format, ...); only "model",
            "response_format", and the outgoing prompt text are inspected.

    Returns:
        A fake completion response exposing
        ``.choices[0].message.content``.
    """
    model = str(completion_args.get("model") or DEFAULT_OFFLINE_MODEL)
    prompt = _prompt_text(completion_args)
    response_format = completion_args.get("response_format")

    if response_format and response_format.get("type") == "json_schema":
        return _schema_response(model, prompt, response_format["json_schema"])

    if response_format and response_format.get("type") == "json_object":
        # No production call site reaches this branch (every call site
        # that requests JSON also supplies a schema), but it is kept as a
        # safe, schema-less fallback.
        return _build_response("{}")

    rng = random.Random(_seed_for(model, prompt, ""))
    return _build_response(leaf_text(rng, 1, "", subject_terms(prompt)))


_installed = False


class OfflineRouter:
    """Completion backend that answers ``offline/`` models locally.

    Every other model is handed to ``inner``, the backend that was installed
    when the router was, so real-model traffic and its capability answers are
    untouched.
    """

    def __init__(self, inner: CompletionBackend) -> None:
        """Wraps ``inner``, the backend every non-offline model goes to."""
        self._inner = inner

    async def complete(self, **completion_args: Any) -> Any:
        """Answers an offline model locally; passes any other through."""
        model_name = str(completion_args.get("model") or "")
        if is_offline_model(model_name):
            return await offline_acompletion(**completion_args)
        return await self._inner.complete(**completion_args)

    def supports_json_schema(self, model_name: str) -> bool:
        """Says yes for an offline model; asks ``inner`` for any other."""
        if is_offline_model(model_name):
            return True
        return self._inner.supports_json_schema(model_name)


def install_offline_router() -> None:
    """Installs ``OfflineRouter`` as the completion backend.

    Idempotent: a second call is a no-op, so callers (app startup, test
    fixtures) can call it unconditionally without risking a nested chain of
    routers. ``offline/``-prefixed models are answered by
    ``offline_acompletion``; every other model's call passes through
    untouched to the backend that was installed at the time. Its capability
    answer says an offline model takes a native json_schema response format,
    so schema'd offline calls take that branch in
    ``co_scientist.llm.request.completion._apply_response_format`` rather than
    the
    json_object provider-capability shim.
    """
    global _installed

    if _installed:
        return

    install_backend(OfflineRouter(active_backend()))
    _installed = True
    logger.debug("offline llm router installed")
