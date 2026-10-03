"""Citation classification."""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
import functools
import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

import app.retraction_set as retraction_set

logger = logging.getLogger(__name__)

# --- Resolvability (independent of support) ---------------------------------


class Resolvability(str, enum.Enum):
    """Whether a citation's *source* resolves — separate from claim support."""

    RESOLVABLE = "resolvable"
    UNRESOLVABLE = "unresolvable"
    RETRACTED = "retracted"


class SourceType(str, enum.Enum):
    """What kind of source a citation points at.

    ``PEER_REVIEWED`` and ``PREPRINT`` are the distinction that matters to
    a reader: both resolve, and only one has been reviewed. ``DATABASE`` is
    a curated record (ChEMBL, UniProt, a trial registry) rather than a
    publication, ``DOCUMENT`` is a document the user attached to the run,
    and ``UNKNOWN`` is an honest gap -- never a guess.
    """

    PEER_REVIEWED = "peer_reviewed"
    PREPRINT = "preprint"
    DATABASE = "database"
    WEB = "web"
    DOCUMENT = "document"
    UNKNOWN = "unknown"

    @property
    def is_publication(self) -> bool:
        """Whether a source of this kind is expected to carry a date.

        A paper without a publication year has a metadata defect; a
        database record, a web page or an attached document has no
        publication date to be missing, and reporting one as absent
        invents a defect on a row where none exists.
        """
        return self in (SourceType.PEER_REVIEWED, SourceType.PREPRINT)


class DateState(str, enum.Enum):
    """Whether a citation carries a usable publication date."""

    PRESENT = "present"
    MISSING = "missing"
    IMPLAUSIBLE = "implausible"


@dataclasses.dataclass(frozen=True)
class CitationMetadata:
    """Source metadata the citation check inspects (never claim support).

    Attributes:
        url: The source-supplied URL, when it has one.
        doi: Canonical DOI, when the source has one.
        pmid: Canonical PubMed id, when applicable.
        available: Whether the source already declared itself reachable.
        retracted: Whether the source already flagged a retraction. A live
            resolver checks this *and* an independent offline dataset,
            since retraction propagation between indexes lags by months.
        source: The retrieval source's own name ('pubmed', 'biorxiv',
            'attachment', ...) -- see ``config/tools.yaml``.
        publication_type: The publisher-declared type ('Journal Article',
            'Preprint', ...). The strongest source-type signal there is,
            and the only one the evidence table cannot re-derive later,
            which is why the drain classifies at persist time.
        year: Publication year, when the source states one.
    """

    url: str = ""
    doi: str = ""
    pmid: str = ""
    available: bool = True
    retracted: bool = False
    source: str = ""
    publication_type: str = ""
    year: int | None = None

    @property
    def has_identifier(self) -> bool:
        """Whether the source carries anything that could be dereferenced."""
        return bool(self.doi or self.pmid or self.url)


# A resolver maps citation metadata to a resolvability verdict. The offline
# default reads the supplied metadata back; the production implementation is
# ``app.citations.live_resolver``, which dereferences the identifier.
Resolver = Callable[[CitationMetadata], Resolvability]


def offline_resolver(meta: CitationMetadata) -> Resolvability:
    """Judge resolvability from supplied metadata only (no network).

    Retraction dominates (a retracted source is unusable even if
    reachable), then whether the source carries any identifier at all. A
    bare DOI or PMID counts: it is an identifier a live resolver can
    dereference, and requiring a URL alongside it would reclassify every
    doi/pmid-only citation as unresolvable on this path -- a gate-decision
    change, since ``available`` feeds citation classification and claim
    grounding.
    """
    if meta.retracted:
        return Resolvability.RETRACTED
    if not meta.available or not meta.has_identifier:
        return Resolvability.UNRESOLVABLE
    return Resolvability.RESOLVABLE


def assess_resolvability(
    meta: CitationMetadata, *, resolver: Resolver = offline_resolver
) -> Resolvability:
    """Judge whether a citation source resolves, independent of claim support.

    Delegates to the (swappable) ``resolver``; every production verdict is
    computed here, whichever resolver the deployment configures.

    Args:
        meta: The citation's own metadata. Deliberately carries no claim
            and no evidence text -- this check cannot consult support even
            by accident.
        resolver: How to decide reachability (offline metadata by default,
            a live dereference in production).

    Returns:
        The source's :class:`Resolvability`.
    """
    return resolver(meta)


# --- Source type ------------------------------------------------------------

# Keyed on the retrieval-source names a run can actually persist: the
# literal `source:` values in engine `config/tools.yaml`, that file's
# `source_type` fallback for a tool declaring no literal one, and the app's
# own attachment source. A name absent here resolves UNKNOWN rather than to
# a guessed neighbour.
_SOURCE_TYPE_BY_NAME = {
    "pubmed": SourceType.PEER_REVIEWED,
    "europepmc": SourceType.PEER_REVIEWED,
    "openalex": SourceType.PEER_REVIEWED,
    "academic": SourceType.PEER_REVIEWED,
    "arxiv": SourceType.PREPRINT,
    "biorxiv": SourceType.PREPRINT,
    "medrxiv": SourceType.PREPRINT,
    "preprint": SourceType.PREPRINT,
    "preprints": SourceType.PREPRINT,
    "scientific_database": SourceType.DATABASE,
    # A knowledge-graph statement (INDRA et al.) is a curated record, not a
    # publication -- see agents/generation/citations.py, which stamps this
    # as the citation's `type`.
    "knowledge_graph": SourceType.DATABASE,
    "web": SourceType.WEB,
    "attachment": SourceType.DOCUMENT,
}

# Publisher-declared types, matched as substrings of a lowercased value.
# "preprint" is checked first: PubMed indexes preprints and declares them
# as such, and that declaration is the only thing distinguishing them from
# the journal articles beside them.
_PUBLICATION_TYPE_MARKERS = (
    ("preprint", SourceType.PREPRINT),
    ("journal article", SourceType.PEER_REVIEWED),
    ("review", SourceType.PEER_REVIEWED),
    ("clinical trial", SourceType.PEER_REVIEWED),
    ("meta-analysis", SourceType.PEER_REVIEWED),
)

_PREPRINT_HOSTS = ("biorxiv.org", "medrxiv.org", "arxiv.org", "chemrxiv.org")


def _type_from_publication_type(publication_type: str) -> SourceType | None:
    """Classify from the publisher's own declared type, or return None."""
    text = publication_type.strip().lower()
    if not text:
        return None
    for marker, source_type in _PUBLICATION_TYPE_MARKERS:
        if marker in text:
            return source_type
    return None


def classify_source_type(meta: CitationMetadata) -> SourceType:
    """Classify what kind of source a citation points at.

    Precedence runs strongest signal first: the publisher's own declared
    publication type, then the retrieval source's name, then a preprint
    host in the URL. Reversing the first two would file every preprint
    PubMed indexes as peer reviewed, which is exactly the case the
    distinction exists for.

    Args:
        meta: The citation's metadata.

    Returns:
        The :class:`SourceType`, ``UNKNOWN`` when no signal identifies it.
    """
    declared = _type_from_publication_type(meta.publication_type)
    if declared is not None:
        return declared
    named = _SOURCE_TYPE_BY_NAME.get(meta.source.strip().lower())
    if named is not None:
        return named
    url = meta.url.lower()
    if any(host in url for host in _PREPRINT_HOSTS):
        return SourceType.PREPRINT
    return SourceType.UNKNOWN


# --- Publication date -------------------------------------------------------

# Philosophical Transactions, the first scientific journal, 1665. A year
# below it is a parse artifact rather than a very old citation.
_EARLIEST_PLAUSIBLE_YEAR = 1665


def classify_date(
    meta: CitationMetadata, *, today_year: int | None = None
) -> DateState:
    """Judge whether a citation's publication date is usable.

    Next year is plausible: an accepted paper carries its forthcoming
    issue's year, not today's. Anything further ahead, or older than the
    first scientific journal, is bad metadata rather than an unusual
    source.

    Args:
        meta: The citation's metadata.
        today_year: Override for the current year (tests pin it so the
            plausible window cannot drift with the calendar).

    Returns:
        The :class:`DateState`.
    """
    year = meta.year
    if not year:
        return DateState.MISSING
    latest = (today_year or dt.date.today().year) + 1
    if year < _EARLIEST_PLAUSIBLE_YEAR or year > latest:
        return DateState.IMPLAUSIBLE
    return DateState.PRESENT


# A run's evidence budget is a few dozen items at most; this bounds how many
# sockets are open at once without serializing the whole set behind the
# slowest single request.
_RESOLVE_CONCURRENCY = 6
_RESOLVE_TIMEOUT_SECONDS = 8.0

_PUBMED_ESUMMARY_URL = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
)


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{doi.strip()}"


def _reachable(client: httpx.Client, url: str) -> bool:
    """Dereference one URL by status code, tolerant of HEAD-averse servers."""
    try:
        response = client.head(url, follow_redirects=True)
        if response.status_code in (403, 405):
            # Some hosts (doi.org among them) reject HEAD outright; a GET
            # without reading the body still proves the address resolves.
            response = client.get(url, follow_redirects=True)
        return response.status_code < 400
    except httpx.HTTPError as exc:
        logger.debug("dereference failed for %s: %s", url, exc)
        return False


def _pmid_found(client: httpx.Client, pmid: str) -> bool:
    """Look up a PMID via NCBI's ESummary API (see the module docstring)."""
    try:
        response = client.get(
            _PUBMED_ESUMMARY_URL,
            params={"db": "pubmed", "id": pmid, "retmode": "json"},
        )
        if response.status_code >= 400:
            return False
        record = response.json().get("result", {}).get(pmid, {})
        return bool(record) and "error" not in record
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("PMID lookup failed for %s: %s", pmid, exc)
        return False


def _resolve_with_client(
    client: httpx.Client | None, check: Callable[[httpx.Client], bool]
) -> Resolvability:
    """Run one check, opening a client only when the caller has none."""
    owns_client = client is None
    active = client or httpx.Client(timeout=_RESOLVE_TIMEOUT_SECONDS)
    try:
        found = check(active)
    finally:
        if owns_client:
            active.close()
    return Resolvability.RESOLVABLE if found else Resolvability.UNRESOLVABLE


def _resolve_doi(doi: str, client: httpx.Client | None) -> Resolvability:
    """Resolve a DOI: offline retraction set first, then a live dereference."""
    if retraction_set.is_known_retracted(doi):
        return Resolvability.RETRACTED
    return _resolve_with_client(client, lambda c: _reachable(c, _doi_url(doi)))


def resolve_one(
    *,
    doi: str,
    pmid: str,
    url: str,
    retracted: bool,
    client: httpx.Client | None = None,
) -> Resolvability:
    """Dereference one evidence identifier against the live web.

    Retraction is decided first from metadata (the source already flagged
    it), then, for a DOI the source did not flag, from a second and
    independent offline check (see ``app.retraction_set``) -- source
    databases can take months to propagate a retraction, so this is the
    only defense against one they have not (yet) caught. Neither check
    dereferences anything. A DOI is preferred over a PMID (resolves
    through its own registry regardless of which URL the source attached),
    a PMID over a bare source-supplied URL, and everything else is judged
    by actually resolving the identifier, never by inspecting whether a URL
    string happens to be non-empty.

    Args:
        doi: The article's DOI, or empty.
        pmid: The article's PMID, or empty.
        url: A source-supplied URL, used only when neither identifier above
            is present.
        retracted: Whether the source already flagged this as retracted.
        client: Optional client to reuse (single-threaded callers only).

    Returns:
        RETRACTED without any network call when ``retracted`` is set or the
        DOI is in the offline retraction set, otherwise RESOLVABLE or
        UNRESOLVABLE from the live check.
    """
    if retracted:
        return Resolvability.RETRACTED
    if doi:
        return _resolve_doi(doi, client)
    if pmid:
        return _resolve_with_client(client, lambda c: _pmid_found(c, pmid))
    if url:
        return _resolve_with_client(client, lambda c: _reachable(c, url))
    return Resolvability.UNRESOLVABLE


def live_resolver(meta: CitationMetadata) -> Resolvability:
    """Resolve one citation's metadata by dereferencing its identifier.

    The production ``Resolver`` (``settings.evidence_resolver == "live"``),
    passed to ``citation_metadata.assess_resolvability`` rather than called
    around it, so the live and offline paths differ only in this argument.

    Args:
        meta: The citation's metadata.

    Returns:
        The source's :class:`Resolvability`.
    """
    return resolve_one(
        doi=meta.doi,
        pmid=meta.pmid,
        url=meta.url,
        retracted=meta.retracted,
    )


def resolve_many(
    metas: Iterable[CitationMetadata], *, resolver: Resolver
) -> list[Resolvability]:
    """Assess many citations concurrently, in input order.

    Each verdict still comes from
    ``citation_metadata.assess_resolvability``; this adds only the bounded
    fan-out a live resolver needs, and is looked up on the module (not
    bound at import) so a test can substitute the seam. An offline
    resolver runs through the same pool -- once per run, over a few dozen
    pure calls -- rather than earning a second code path for the saving.

    Args:
        metas: The citations to assess.
        resolver: The resolver every verdict goes through.

    Returns:
        One :class:`Resolvability` per citation, same order as ``metas``.
    """
    items = list(metas)
    if not items:
        return []
    assess = functools.partial(assess_resolvability, resolver=resolver)
    with ThreadPoolExecutor(
        max_workers=min(_RESOLVE_CONCURRENCY, len(items))
    ) as pool:
        return list(pool.map(assess, items))


class CitationState(str, enum.Enum):
    """States the UI surfaces for a single citation."""

    VERIFIED = "verified"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


ALL_STATES: tuple[CitationState, ...] = (
    CitationState.VERIFIED,
    CitationState.PARTIAL,
    CitationState.UNSUPPORTED,
    CitationState.UNAVAILABLE,
)

# Strength rank per state (higher = stronger support), derived from the
# strongest-to-weakest ordering of ALL_STATES.
STATE_RANK: dict[str, int] = {
    state.value: len(ALL_STATES) - 1 - i for i, state in enumerate(ALL_STATES)
}


def empty_citation_summary() -> dict[str, int]:
    """Return a zeroed state -> count summary covering every citation state."""
    return {state.value: 0 for state in ALL_STATES}


@dataclass
class CitationRecord:
    """Inputs the classifier expects per evidence row."""

    url: str = ""
    abstract: str = ""
    claim: str = ""  # the inline claim cited from this source
    available: bool = True


@functools.lru_cache(maxsize=256)
def _content_tokens(text: str) -> frozenset[str]:
    """Cache the token set for a string.

    Claims repeat across a hypothesis's citations, so this collapses their
    re-tokenization to a single pass.
    """
    # Words of length <= 3 (articles, prepositions, etc.) are dropped as noise
    # that would inflate overlap without indicating real semantic match.
    return frozenset(t for t in text.lower().split() if len(t) > 3)


def _token_overlap(claim: str, abstract: str) -> float:
    """How much of the claim's vocabulary the source actually states.

    Coverage (intersection over the *claim's* tokens), not Jaccard. The two
    texts are deliberately asymmetric -- a one-sentence claim against a
    whole abstract -- and Jaccard divides by the union, which the longer
    side dominates. That caps the score near ``len(claim) / len(abstract)``
    however perfectly the source supports the claim: an abstract quoting the
    claim verbatim scored 0.18, below the 0.35 "verified" line, and a
    relevant abstract paraphrasing it scored 0.078, below the 0.10 "partial"
    line. Both upper states were unreachable, so every citation in a real
    run classified "unsupported" (one production run: 0 verified, 0 partial,
    47 unsupported) and the citation audit reported nothing but failure.

    Coverage asks the question the four states are actually about -- what
    fraction of what the claim asserts appears in the cited source -- and is
    invariant to how much else the abstract discusses.
    """
    if not claim or not abstract:
        return 0.0
    a = _content_tokens(claim)
    b = _content_tokens(abstract)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def classify_citation(record: CitationRecord) -> CitationState:
    """Classify a single citation deterministically.

    Rules:
    - No URL or `available=False` → unavailable.
    - Claim coverage in the abstract >= 0.60 → verified.
    - Coverage >= 0.30 → partial.
    - Otherwise → unsupported.

    The thresholds are stated against coverage (see `_token_overlap`);
    porting the old Jaccard numbers across would have kept both upper states
    unreachable in practice.
    """
    # Availability is checked first so an unresolved source short-circuits
    # before spending a token-overlap computation on it.
    if not record.available or not record.url:
        return CitationState.UNAVAILABLE
    overlap = _token_overlap(record.claim, record.abstract)
    if overlap >= 0.60:
        return CitationState.VERIFIED
    if overlap >= 0.30:
        return CitationState.PARTIAL
    return CitationState.UNSUPPORTED
