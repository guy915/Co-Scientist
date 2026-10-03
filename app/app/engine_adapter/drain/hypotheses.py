"""Evidence and hypothesis persistence for the engine final-state drain."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, NamedTuple

from co_scientist.models import Hypothesis

import app.citations as citation_resolver
import app.store as store
from app.citations import (
    CitationMetadata,
    Resolvability,
    Resolver,
    SourceType,
    classify_source_type,
    offline_resolver,
)
from app.config import settings
from app.elo import INITIAL_ELO
from app.engine_adapter.drain.reviews import (
    _CitationSink,
    _persist_engine_citations,
    _persist_engine_reviews,
)
from app.text_utils import first_sentence

logger = logging.getLogger(__name__)

_PUBMED_URL_PMID = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


@dataclass(frozen=True)
class ResolvedArticle:
    """One article's persisted identity, availability, and source type.

    ``retracted`` is reported alongside ``available`` rather than folded
    into it: a retracted source and a merely-unresolvable one both persist
    as ``available=False`` (every gate that reads ``available`` -- citation
    classification, claim grounding -- keeps treating them alike), but they
    are different facts for a reader, who should be told which one it was.
    ``source_type`` gates nothing at all: a preprint is a perfectly usable
    source, and withholding one would be a research decision this check has
    no business making.
    """

    doi: str | None
    pmid: str | None
    available: bool
    retracted: bool = False
    source_type: str = SourceType.UNKNOWN.value


def _article_doi(art: dict[str, Any]) -> str:
    return str(art.get("doi") or "").strip()


def _article_pmid(art: dict[str, Any]) -> str:
    """Return the article's PMID, from its source id or a PubMed URL.

    ``source_id`` is the PMID verbatim for a PubMed-sourced article (see
    ``build_article_from_metadata``); other sources carry no PMID unless
    their URL happens to be a PubMed link.
    """
    if str(art.get("source") or "").lower() == "pubmed":
        source_id = str(art.get("source_id") or "").strip()
        if source_id.isdigit():
            return source_id
    match = _PUBMED_URL_PMID.search(str(art.get("url") or ""))
    return match.group(1) if match else ""


def _article_retracted(art: dict[str, Any]) -> bool:
    return bool(art.get("is_retracted")) or (
        str(art.get("correction_status") or "").lower() == "retracted"
    )


def _article_year(art: dict[str, Any]) -> int | None:
    """Read the article's publication year, tolerating a string value."""
    try:
        return int(art["year"])
    except (KeyError, TypeError, ValueError):
        return None


def _article_metadata(art: dict[str, Any]) -> CitationMetadata:
    """Extract one article's citation metadata, the check's only input."""
    return CitationMetadata(
        url=str(art.get("url") or ""),
        doi=_article_doi(art),
        pmid=_article_pmid(art),
        retracted=_article_retracted(art),
        source=str(art.get("source") or ""),
        publication_type=str(art.get("publication_type") or ""),
        year=_article_year(art),
    )


def _configured_resolver() -> Resolver:
    """Return the ``Resolver`` this deployment resolves citations through."""
    if settings.evidence_resolver == "live":
        return citation_resolver.live_resolver
    return offline_resolver


def _resolved_article(
    meta: CitationMetadata, verdict: Resolvability
) -> ResolvedArticle:
    """Build one article's persisted row from its metadata and verdict.

    The verdict is already RETRACTED for both retraction sources -- the
    article's own metadata flag and, on the live path, the resolver's
    independent ``retraction_set`` lookup -- so it alone decides both
    flags, and the retraction fact is carried through rather than
    collapsed into plain unavailability.
    """
    return ResolvedArticle(
        doi=meta.doi or None,
        pmid=meta.pmid or None,
        available=verdict is Resolvability.RESOLVABLE,
        retracted=verdict is Resolvability.RETRACTED,
        source_type=classify_source_type(meta).value,
    )


def resolve_articles(
    articles: list[dict[str, Any]],
) -> list[ResolvedArticle]:
    """Resolve every article's identity and availability, in input order.

    Live mode (``settings.evidence_resolver == "live"``, the production
    default) dereferences each identifier against the real web; offline
    mode (the hermetic test default) judges availability from metadata
    alone and never performs network I/O. Both go through the same
    ``assess_resolvability`` seam.

    Args:
        articles: The engine's retrieved articles (``Article.to_dict()``
            payloads).

    Returns:
        One :class:`ResolvedArticle` per article, same order as ``articles``.
    """
    metas = [_article_metadata(art) for art in articles]
    verdicts = citation_resolver.resolve_many(
        metas, resolver=_configured_resolver()
    )
    return [
        _resolved_article(meta, verdict)
        for meta, verdict in zip(metas, verdicts, strict=True)
    ]


@dataclass(frozen=True)
class _HypothesisSink:
    """The drain's hypothesis lookups, mutated in place as rows are written.

    Attributes:
        citations: Evidence/abstract/citation-count lookups the citation
            pass reads and updates.
        store_id_by_engine_id: Persisted row id per engine hypothesis id.
        persisted_engine_ids: Every engine id this drain is persisting, so a
            child's parent reference is only kept when the parent is stored.
    """

    citations: _CitationSink
    store_id_by_engine_id: dict[str, str]
    persisted_engine_ids: set[str]


class _HypIdentity(NamedTuple):
    """An engine hypothesis's persistence identity and lineage.

    Bundles the fields the drain derives once from an engine hypothesis dict
    and threads into the store row: the statement text, a derived title, and
    the explicit lineage (generation, creating agent, engine id, parent id,
    and the full multi-parent list), plus the author a scientist-
    contributed hypothesis carries through the checkpoint (see
    ``engine_tasks.inputs.SCIENTIST_AUTHOR_MARK``).
    """

    text: str
    title: str
    generation: int
    agent: str
    engine_id: str | None
    parent_id: str | None
    parent_ids: list[str] | None
    author: str


def _article_coalesced_fields(
    art: dict[str, Any],
) -> tuple[str, list[str], str]:
    """Extract an article's (url, authors, abstract), each falling back.

    Isolates the fields whose raw value needs an empty-default fallback (as
    opposed to the fields below that already have a `dict.get` default), so
    the persistence loop stays free of branching.
    """
    url = art.get("url") or ""
    authors = art.get("authors") or []
    abstract = art.get("abstract") or ""
    return url, authors, abstract


def _persist_engine_evidence(
    run_id: str,
    articles: list[dict[str, Any]],
    resolved: list[ResolvedArticle],
    citations: _CitationSink,
    conn: sqlite3.Connection,
) -> None:
    """Persist retrieved articles as evidence rows.

    Fills the sink's (evidence id by title, abstract by title) lookups the
    hypothesis/citation pass needs: the citation_map carries no abstract of
    its own, so a cited source is classified against its evidence row's
    abstract via this title-keyed map.

    Args:
        run_id: Run the evidence belongs to.
        articles: The engine's retrieved articles.
        resolved: Each article's identity/availability, same order as
            ``articles`` (see ``drain.evidence_resolution.resolve_articles``
            -- must be computed before any transaction opens, since it may
            perform network I/O).
        citations: The drain's citation lookups, filled in place.
        conn: Open connection of the caller's transaction.
    """
    ev_id_by_title = citations.ev_id_by_title
    abstract_by_title = citations.abstract_by_title
    for art, res in zip(articles, resolved, strict=True):
        url, authors, abstract = _article_coalesced_fields(art)
        ev_id = store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title=art.get("title", "Untitled"),
                source=art.get("source", "engine"),
                url=url,
                authors=authors,
                year=art.get("year"),
                abstract=abstract,
                available=res.available,
                retracted=res.retracted,
                source_type=res.source_type,
                doi=res.doi,
                pmid=res.pmid,
                retrieved_at=art.get("retrieved_at"),
                retrieval_score=art.get("retrieval_score"),
                retrieval_rationale=art.get("retrieval_rationale"),
                retriever_version=art.get("retriever_version"),
                retrieval_call_id=art.get("retrieval_call_id"),
            ),
            conn=conn,
        )
        ev_id_by_title[art.get("title", "")] = ev_id
        abstract_by_title[art.get("title", "")] = abstract


class ResolvedEvidenceBatch(NamedTuple):
    """A run's retrieved articles paired with their resolved availability.

    Bundled into one parameter (rather than two positional lists callers
    must keep in step) so ``_persist_evidence_and_hypotheses`` stays inside
    the five-parameter limit.
    """

    articles: list[dict[str, Any]]
    resolved: list[ResolvedArticle]


def _persist_evidence_and_hypotheses(
    run_id: str,
    evidence: ResolvedEvidenceBatch,
    hyps_parents_first: list[dict[str, Any]],
    sink: _HypothesisSink,
    conn: sqlite3.Connection,
) -> None:
    """Persist retrieved evidence, then hypotheses parents before children.

    Mutates the sink in place (see `_persist_engine_hypothesis`).

    Args:
        run_id: Run the drained state belongs to.
        evidence: The engine's retrieved articles and their resolved
            identity/availability (see ``_persist_engine_evidence``).
        hyps_parents_first: Hypotheses ordered so parents insert first.
        sink: The drain's hypothesis and citation lookups.
        conn: Open connection of the caller's transaction.
    """
    _persist_engine_evidence(
        run_id, evidence.articles, evidence.resolved, sink.citations, conn
    )
    for h in hyps_parents_first:
        _persist_engine_hypothesis(run_id, h, sink, conn)


def _derive_hypothesis_identity(h: dict[str, Any]) -> _HypIdentity:
    """Derive an engine hypothesis's statement, title, and explicit lineage.

    Reads the engine's explicit lineage fields (``parent_id``/``generation``/
    ``origin``) rather than reconstructing lineage from ``evolution_history``.
    Pre-lineage cached payloads (which lack these keys) fall
    back to the old ``evolution_history`` inference so old runs still drain.
    The title prefers the LLM-authored ``title`` field (R14-12), falling
    back to the first sentence of the statement (see ``_authored_title``).

    Returns:
        The hypothesis's persistence identity and lineage.
    """
    text = h.get("text", "")
    title = _authored_title(h, text)
    engine_id = h.get("id") or None

    if "generation" in h or "parent_id" in h or "origin" in h:
        # Explicit lineage from a current engine payload.
        generation = int(h.get("generation", 0))
        parent_id = h.get("parent_id") or None
        agent = str(h.get("origin") or "generation")
    else:
        # Legacy fallback: infer from evolution_history (pre-lineage cache).
        is_evolved = bool(h.get("evolution_history"))
        generation = 1 if is_evolved else 0
        parent_id = None
        agent = "evolution" if is_evolved else "generation"

    return _HypIdentity(
        text,
        title,
        generation,
        agent,
        engine_id,
        parent_id,
        _payload_parent_ids(h),
        _payload_author(h),
    )


def _payload_author(h: dict[str, Any]) -> str:
    """The scientist who authored this hypothesis, or the empty string.

    Only a contributed hypothesis carries one, stamped on the engine
    payload's ``enrichments`` by the durable merge so the attribution
    survives the checkpoint rather than living only in the store row the
    endpoint wrote (``engine_tasks.inputs.SCIENTIST_AUTHOR_MARK``).
    """
    enrichments = h.get("enrichments")
    if not isinstance(enrichments, dict):
        return ""
    return str(enrichments.get("scientist_author") or "")


def _payload_parent_ids(h: dict[str, Any]) -> list[str] | None:
    """Extract a payload's multi-parent lineage list, or None.

    Only a combination child carries ``parent_ids``; every other hypothesis
    (and any pre-multi-parent payload) reads back as None, which keeps
    ``parent_id`` the sole lineage signal. Non-string entries are dropped
    defensively rather than persisted.
    """
    raw = h.get("parent_ids")
    if not isinstance(raw, list):
        return None
    parent_ids = [pid for pid in raw if isinstance(pid, str) and pid]
    return parent_ids or None


# Excluded from the ranked report, but not by a judgement on the idea: a
# duplicate is archived by proximity because a higher-ranked idea already
# says the same thing. Kept apart from the engine's blocking dispositions so
# the two reach the reader as different words -- lumping them told a
# scientist their ideas had been rejected on the merits when most had simply
# been deduplicated. One run showed twenty "Disqualified" ideas on that
# basis. Note the engine's own predicate also leaves "duplicate" out of
# BLOCKING_REVIEW_DISPOSITIONS, for the same reason.
DEDUPLICATED_REVIEW_DISPOSITION = "duplicate"


def _payload_is_rankable(h: dict[str, Any]) -> bool:
    """Ask the engine whether a drained payload may enter the tournament.

    The drain works on serialized hypothesis dicts, so the two fields
    ``Hypothesis.is_rankable`` reads are lifted into a bare ``Hypothesis``
    and the engine's own predicate answers. The predicate lives there so the
    persisted status and the tournament agree about what a run may publish
    -- the app previously restated both the blocking-disposition set and the
    predicate over it, and a disposition added to only one side would make an
    idea unrankable in the engine while the app still stored it ``active``
    and published it.

    Args:
        h: An engine hypothesis payload from the drained final state.

    Returns:
        Whether the engine would admit this hypothesis to the tournament.
    """
    return bool(
        Hypothesis(
            text="",
            review_disposition=h.get("review_disposition"),
            deep_verification_verdict=h.get("deep_verification_verdict"),
        ).is_rankable()
    )


def _hypothesis_status(h: dict[str, Any]) -> str:
    """Return the persisted status for a drained hypothesis.

    Three outcomes the UI must be able to tell apart:

    - ``rejected``: excluded from the tournament on merit -- whatever the
      engine's ``Hypothesis.is_rankable`` refuses, which today is a
      blocking review disposition.
    - ``duplicate``: archived by proximity as redundant, not judged.
    - ``active``: everything else, including ideas the initial review
      flagged as needing revision and ideas deep verification undermined --
      those still rank and publish.

    An undermined idea used to land in ``rejected`` here. It is now
    ``active``, which is why ``verification_verdict`` is persisted beside
    this status: the doubt has to reach the reader on its own column, or a
    published idea looks indistinguishable from a sound one.
    """
    if h.get("review_disposition") == DEDUPLICATED_REVIEW_DISPOSITION:
        return "duplicate"
    if not _payload_is_rankable(h):
        return "rejected"
    return "active"


def _mean_review_novelty(h: dict[str, Any]) -> float | None:
    """Mean of the reviewers' own novelty scores, or None if none scored it.

    ``hypothesis_state.novelty_score`` used to be filled from ``h["score"]``,
    the engine's *overall* score, so the column held a different quantity
    than its name (K10). Reviewers score novelty on their own axis
    (``HypothesisReview.scores["novelty"]``), which is what the name
    promises, so read that instead. Averaging across reviews rather than
    taking the newest keeps a single harsh or generous reviewer from
    defining the value on its own.
    """
    scores = [
        float(value)
        for review in h.get("reviews") or []
        if isinstance(review, dict)
        for value in [(review.get("scores") or {}).get("novelty")]
        if isinstance(value, (int, float)) and value
    ]
    return sum(scores) / len(scores) if scores else None


def _persist_hypothesis_state(
    hyp_id: str, h: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist a hypothesis's mutable state: Elo rating, wins, losses, score."""
    store.update_hypothesis_state(
        hyp_id,
        store.HypothesisStateChanges(
            elo_rating=int(h.get("elo_rating", INITIAL_ELO)),
            win_delta=int(h.get("win_count", 0)),
            loss_delta=int(h.get("loss_count", 0)),
            novelty=_mean_review_novelty(h),
            status=_hypothesis_status(h),
            verification_verdict=h.get("deep_verification_verdict"),
        ),
        conn=conn,
    )


def _resolve_persisted_parent_id(
    identity: _HypIdentity, persisted_engine_ids: set[str]
) -> str | None:
    """Return the parent id to persist, dropping references to pruned parents.

    The parent was pruned (e.g. by proximity) whenever it is absent from
    ``persisted_engine_ids``, in which case persisting it would violate the
    ``hypotheses.parent_id`` foreign key, so the child is stored as a root
    with a logged, broken lineage edge instead.
    """
    parent_id = identity.parent_id
    if parent_id is not None and parent_id not in persisted_engine_ids:
        logger.warning(
            "hypothesis %s references pruned parent %s; storing as root",
            identity.engine_id,
            parent_id,
        )
        return None
    return parent_id


def _resolve_persisted_parent_ids(
    identity: _HypIdentity,
    parent_id: str | None,
    persisted_engine_ids: set[str],
) -> list[str] | None:
    """Return the multi-parent list to persist, or None.

    Drops any parent pruned before the drain (absent from
    ``persisted_engine_ids``) and keeps the resolved ``parent_id`` leading,
    so the stored list agrees with the primary-parent column. Returns None
    when a single parent remains (``parent_id`` already conveys it, and the
    column is reserved for genuine multi-parent lineage) or when the primary
    parent was itself pruned (``parent_id`` resolved to None), since the
    child is then stored as a root with no lineage anchor.
    """
    if parent_id is None or not identity.parent_ids:
        return None
    kept = [pid for pid in identity.parent_ids if pid in persisted_engine_ids]
    if parent_id not in kept:
        kept.insert(0, parent_id)
    return kept if len(kept) > 1 else None


def _persist_engine_hypothesis_row(
    run_id: str,
    h: dict[str, Any],
    persisted_engine_ids: set[str],
    conn: sqlite3.Connection,
) -> tuple[str, str | None]:
    """Persist one engine hypothesis's row and mutable state (Elo/wins/losses).

    The engine's stable hypothesis id is passed straight through as the store
    row id, so identity holds end-to-end (engine -> DB -> API -> UI) and
    matchups resolve by id rather than by fragile text-prefix matching.
    ``parent_id`` is carried through (store rows share the engine id, so a
    child's engine parent_id already equals the parent's store row id) via
    ``_resolve_persisted_parent_id``; the multi-parent ``parent_ids`` list is
    resolved the same way.

    Returns:
        A tuple of (persisted store row id, the engine's own id or None).
    """
    identity = _derive_hypothesis_identity(h)
    parent_id = _resolve_persisted_parent_id(identity, persisted_engine_ids)
    parent_ids = _resolve_persisted_parent_ids(
        identity, parent_id, persisted_engine_ids
    )
    hyp_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title=identity.title,
            statement=identity.text,
            hypothesis_id=identity.engine_id,
            parent_id=parent_id,
            parent_ids=parent_ids,
            generation=identity.generation,
            # Authoring-cycle ordinal (int|None from the engine); 0 is a real
            # cycle, so pass it through directly rather than `or None`.
            creation_iteration=h.get("creation_iteration"),
            category=h.get("category") or None,
            mechanism=h.get("literature_grounding") or "",
            expected_effect=h.get("explanation") or "",
            experimental_context=h.get("experiment") or "",
            introduction=h.get("introduction") or "",
            recent_findings=h.get("recent_findings") or "",
            safety_and_toxicity=h.get("safety_and_toxicity") or "",
            created_by_agent=identity.agent,
            author=identity.author,
        ),
        conn=conn,
    )
    _persist_hypothesis_state(hyp_id, h, conn)
    return hyp_id, identity.engine_id


def _persist_engine_hypothesis(
    run_id: str,
    h: dict[str, Any],
    sink: _HypothesisSink,
    conn: sqlite3.Connection,
) -> None:
    """Persist one engine hypothesis: its row, state, reviews, and citations.

    Mutates the sink in place: `store_id_by_engine_id` (engine id ->
    persisted row id), `citations.ev_id_by_title` (a citation may add
    evidence for its source on the fly), and `citations.citation_summary`
    (running citation-state counts).

    Args:
        run_id: Run the hypothesis belongs to.
        h: The engine's raw hypothesis payload.
        sink: The drain's hypothesis and citation lookups.
        conn: Open connection of the caller's transaction.
    """
    hyp_id, engine_id = _persist_engine_hypothesis_row(
        run_id, h, sink.persisted_engine_ids, conn
    )
    if engine_id:
        sink.store_id_by_engine_id[engine_id] = hyp_id
    _persist_engine_reviews(run_id, hyp_id, h, conn)
    _persist_engine_citations(run_id, hyp_id, h, sink.citations, conn)


def _hypotheses_with_proximity_archive(
    active: list[dict[str, Any]], removed: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return active hypotheses plus full proximity-pruned archive records."""
    archived: dict[str, dict[str, Any]] = {}
    for record in removed:
        hypothesis = record.get("hypothesis")
        if not isinstance(hypothesis, dict) or not hypothesis.get("id"):
            # Legacy checkpoints retained only a text audit entry. They cannot
            # safely reconstruct stable identity or lineage after the fact.
            continue
        archived_hypothesis = dict(hypothesis)
        archived_hypothesis["review_disposition"] = "duplicate"
        archived[str(archived_hypothesis["id"])] = archived_hypothesis

    # An active row wins if an old audit record and the current pool ever share
    # an id; the archive exists only for hypotheses absent from active ranking.
    by_id = dict(archived)
    by_id.update(
        {
            str(hypothesis["id"]): hypothesis
            for hypothesis in active
            if hypothesis.get("id")
        }
    )
    return list(by_id.values())


# Mirrors schemas.generation.MAX_TITLE_CHARS in the engine (raised 100 ->
# 120 after production run b82f9162 -- see that constant's own comment).
# Kept as its own constant rather than a cross-package import -- the app has
# no existing import from co_scientist.schemas, and a json_object-downgraded
# response is not bound by the schema's maxLength anyway, so this cap has to
# hold regardless of what the engine's own copy says.
_TITLE_DISPLAY_CAP = 120


def _authored_title(h: dict[str, Any], text: str) -> str:
    """The hypothesis's display title: an authored title, or a fallback.

    The single point where an LLM-authored ``title`` (R14-12: a compact
    noun phrase, matching the published pattern) is preferred over the
    mechanical ``first_sentence(text)`` fallback that predates it. Every
    other reader of a drained hypothesis (report renderers, the Ideas tab,
    the share payload) reads the persisted ``title`` column this function
    feeds, so none of them need a fallback of their own.

    Falls back to ``first_sentence(text)`` -- unchanged from before this
    field existed -- whenever the raw ``title`` is missing, not a string,
    or blank after stripping: a run predating this field, or a
    ``json_object`` downgrade whose response omits, mistypes, or empties
    it. An over-length authored title is clipped rather than discarded --
    a too-long authored name still reads better than a truncated sentence.

    Args:
        h: The raw engine hypothesis payload.
        text: The hypothesis statement, already read from ``h`` by the
            caller (see ``drain.hypotheses._derive_hypothesis_identity``).

    Returns:
        The title to persist onto the store row.
    """
    raw = h.get("title")
    if isinstance(raw, str):
        authored = raw.strip()
        if authored:
            return authored[:_TITLE_DISPLAY_CAP]
    return first_sentence(text)
