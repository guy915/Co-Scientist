"""Citation metadata and resolvability, judged apart from claim support.

Whether a cited source *resolves* -- and what kind of source it is, and
whether it carries a usable date -- is a different question from whether it
supports the claim citing it. A retracted paper whose abstract states the
claim verbatim is maximally supporting and completely unusable; only a check
that never reads the claim can say so. This module is that check, and it is
the single implementation of it: the drain resolves every retrieved article
through :func:`assess_resolvability` (see
``engine_adapter/drain/evidence_resolution.py``), and the report's
bibliography classifies every rendered reference through
:func:`classify_source_type` / :func:`classify_date`.

Split out of :mod:`app.claims.gate`, which owned resolvability beside the
entailment verdict and the publication gate -- three concerns, and the file
was near its size budget. :mod:`app.claims` re-exports the public names
callers use exactly as before.

The check has two halves, and they differ in where they can run:

*Resolvability* needs the network to mean anything, so it is reached through
a swappable :data:`Resolver`. :func:`offline_resolver` reads back the
metadata a source already claimed (the deterministic default, and what CI
runs); ``app.citations.resolver.live_resolver`` -- the production default --
actually dereferences the DOI/PMID/URL and checks the DOI against the
offline Retraction Watch extract (``app.retraction_set``). Before this
module the two were parallel implementations, and only the live one ran:
the seam existed, with its own tests, reached by nothing.

*Source type and date* are pure judgements over metadata already in hand, so
they need no seam at all. They are separated from resolvability rather than
folded into it: a preprint resolves perfectly well and an undated paper may
be the run's best evidence -- neither is a reason to withhold a source, only
a fact its reader is owed. Nothing here gates anything.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import enum
from collections.abc import Callable

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
# ``app.citations.resolver.live_resolver``, which dereferences the identifier.
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
