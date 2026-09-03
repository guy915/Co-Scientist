"""Evidence-row seeding for one curated demo scenario.

Split out of ``seed_scenario`` to keep that module within the size cap;
mirrors the sibling split modules (``seed_config_synthesis``,
``seed_overview``, ``seed_review_detail``), which likewise take the
lower-level curated values directly rather than the ``_CuratedSeed``
bundle, avoiding a circular import back into ``seed_scenario``.
"""

from __future__ import annotations

import re

from app import store
from app.demo_seed_data import DemoEvidence

# Every curated source is a real PubMed record (see demo_seed_data_evidence
# / demo_seed_data_scenarios); the pmid rides along in the url the fixture
# already carries rather than as a separately authored field, so the
# run-wide bibliography section (R12-12) can show the real identifier
# instead of inventing one.
_PUBMED_URL_PMID = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


def _pmid_from_url(url: str) -> str | None:
    """Extract a PubMed id from a curated evidence url, when present."""
    match = _PUBMED_URL_PMID.search(url)
    return match.group(1) if match else None


def insert_scenario_evidence(
    run_id: str,
    evidence: tuple[DemoEvidence, ...],
    db_path: str | None,
) -> list[str]:
    """Persist a scenario's sources and return their new row ids."""
    return [
        store.add_evidence(
            store.NewEvidence(
                run_id=run_id,
                title=item.title,
                source="pubmed",
                url=item.url,
                authors=item.authors,
                year=item.year,
                abstract=item.abstract,
                pmid=_pmid_from_url(item.url),
            ),
            db_path=db_path,
        )
        for item in evidence
    ]
