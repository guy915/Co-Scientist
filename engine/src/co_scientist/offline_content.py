"""Human-presentable leaf text for the deterministic offline backend.

``offline_llm`` fills a response schema; this module decides what a single
string leaf inside it says. Two properties matter, and neither is served by
one generic sentence:

- **Which field it is.** ``_fill_schema`` visits a title, a mechanism, a
  reviewer's critique and a ranking rationale through the same code path.
  Emitting the same shape of sentence into all of them makes a rendered run
  read as filler no matter how plausible the individual phrase is.
- **What the run is about.** The offline backend answers the same schema
  for every research goal, so without grounding, a run about biofilms and a
  run about synaptic pruning produce interchangeable prose. Salient terms
  are lifted out of the prompt's research goal and woven back in, which
  costs nothing and makes each run read about its own subject.

Both are cosmetic by construction -- nothing here is a scientific claim, and
offline runs exist to exercise the pipeline, not to produce findings. The
point is that a demo or e2e run should be recognisable as the kind of output
the product makes.
"""

import random
import re

# Words that carry no subject meaning but survive a naive keyword pass over a
# research goal ("What mechanisms drive antibiotic resistance in ..."), plus
# the agent/prompt scaffolding vocabulary. Every prompt opens with its
# agent's name, and a prompt that never labels the goal (evolution.md, say)
# is scanned from the top -- without these, evolved ideas came out reading
# "Agent constrains evolution ...".
_STOPWORDS = frozenset(
    {
        "about",
        "above",
        "after",
        "against",
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
        "from",
        "further",
        "generate",
        "goal",
        "task",
        "meta-review",
        "reviews",
        "review",
        "proximity",
        "supervisor",
        "reflection",
        "ranking",
        "generation",
        "evolution",
        "agents",
        "agent",
        "had",
        "has",
        "have",
        "having",
        "hypotheses",
        "hypothesis",
        "help",
        "here",
        "how",
        "however",
        "identify",
        "into",
        "its",
        "itself",
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
        "research",
        "same",
        "should",
        "since",
        "some",
        "such",
        "suggest",
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
    }
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
# generic prose. Tried in order, first match wins.
_GOAL_HEADING_RE = re.compile(
    r"^[ \t]*(?:#+[ \t]*|\*\*)?"
    r"(?:research goal|original hypothesis)\b[:*]*[ \t]*",
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
    # Drawn after the terms, so the clause varies independently of them --
    # see _SCOPE_CLAUSES for why an independent draw is the whole point.
    clause = _SCOPE_CLAUSES[rng.randrange(len(_SCOPE_CLAUSES))]
    joiner = " " if clause.startswith("and ") else ", "
    return f"{text[:1].upper()}{text[1:]}{joiner}{clause}."
