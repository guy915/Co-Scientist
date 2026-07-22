"""Harvest the Kholodenko/Rukhlenko group's papers from PubMed into the corpus.

This is the bulk counterpart to ``app.corpus_ingest``: where that ingests a
folder of PDFs, this pulls the group's published record straight from PubMed
and PubMed Central and writes one markdown file per paper into
``corpus/sbi_ucd/``. Run ``dev/build_catalog.py`` afterwards to rebuild the
catalog from what it wrote.

What it collects, and why it is bounded the way it is:

  * One PubMed author search per group member. A member's surname alone is
    not selective -- "Robertson S" matches thousands of unrelated authors --
    so every name but the two PIs and the director is intersected with an
    institutional clause (Systems Biology Ireland / UCD, or PI co-authorship).
  * Only papers Kholodenko or Rukhlenko actually authored are kept. The group
    is defined by the two PIs; a junior member's unrelated prior work is not
    the group's, and the director's 290 solo papers are a different body of
    work. This is the "whose papers" decision, and it lives here.
  * Errata and superseded preprints are dropped: an erratum repeats its
    article's title and states no finding, and a bioRxiv preprint is
    superseded by the journal version when both are present.
  * Full text is taken from PubMed Central where the publisher releases it in
    XML (about a quarter of the record); everything else is title + abstract.
    PMC XML is structured, so its sections and paragraphs are read directly
    with no PDF sanitation.

The fifteen hand-curated core papers already in the corpus are left alone:
their files are skipped by paper id and by title so re-running never clobbers
a reviewed extraction.

Requires only the standard library plus ``defusedxml``. Network access to
NCBI E-utilities; no API key needed at three requests per second.

Run: python app/dev/harvest_group_pubmed.py
"""

from __future__ import annotations

import collections
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import defusedxml.ElementTree as DET

CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "sbi_ucd"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PAUSE = 0.36  # NCBI allows three requests per second without an API key.

# Restricts a common surname to the group. Without it "Robertson S" alone
# returns thousands of papers by unrelated authors.
GROUP_CLAUSE = (
    '("Systems Biology Ireland"[Affiliation] '
    'OR "University College Dublin"[Affiliation] '
    "OR Kholodenko BN[Author] OR Rukhlenko OS[Author] OR Kolch W[Author])"
)

# (display name, PubMed author term, whether to intersect with GROUP_CLAUSE).
# The two PIs and the director are selective enough on their own; everyone
# else is a common name that must be constrained. Add a new member here.
MEMBERS = [
    ("Boris N. Kholodenko", "Kholodenko BN[Author]", False),
    ("Oleksii S. Rukhlenko", "Rukhlenko OS[Author]", False),
    ("Walter Kolch", "Kolch W[Author]", False),
    ("Hiroaki Imoto", "Imoto H[Author]", True),
    ("Sorour Nemati", "Nemati S[Author]", True),
    ("Thomas Sevrin", "Sevrin T[Author]", True),
    ("Sarah Robertson", "Robertson S[Author]", True),
    ("Anna Tuliakova", "Tuliakova A[Author]", True),
    ("Ciardha Carmody", "Carmody C[Author]", True),
    ("Sergiy Borodin", "Borodin S[Author]", True),
    ("Eugene Kashdan", "Kashdan E[Author]", True),
]

# The group is defined by its two principal investigators: a paper is the
# group's if one of them is on it. The director co-authors constantly but his
# solo work is a separate body, so he is not an anchor.
ANCHORS = {"kholodenko bn", "rukhlenko os"}

# Servers that host a paper before a journal does.
PREPRINT_SERVERS = ("biorxiv", "medrxiv", "arxiv", "res sq", "research square")

_SLUG_KEEP = set("abcdefghijklmnopqrstuvwxyz0123456789")
# JATS blocks that are not prose: tables and figures flatten unreadably and
# the reference list states no finding.
_DROP_TAGS = {
    "ref-list", "table-wrap", "fig", "graphic", "media", "table",
    "disp-formula", "inline-formula", "tex-math", "supplementary-material",
    "author-notes", "fn-group", "ack", "back", "front", "journal-meta",
}


def _get(url: str) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as handle:
                return handle.read()
        except Exception as exc:  # noqa: BLE001 - retry any transport error
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1}: {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def slugify(name: str) -> str:
    """Match app.corpus_ingest.slugify so ids are stable across both paths."""
    out = [c if c in _SLUG_KEEP else "-" for c in name.lower()]
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:80]


def clean_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title).strip().rstrip(".").strip()


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_title(title).lower()).strip()


def esearch(query: str) -> list[str]:
    pmids: list[str] = []
    retstart = 0
    while True:
        params = urllib.parse.urlencode(
            {"db": "pubmed", "term": query, "retmode": "json",
             "retmax": 500, "retstart": retstart}
        )
        result = json.loads(_get(f"{EUTILS}/esearch.fcgi?{params}"))[
            "esearchresult"
        ]
        batch = result.get("idlist", [])
        pmids.extend(batch)
        retstart += len(batch)
        time.sleep(PAUSE)
        if retstart >= int(result.get("count", 0)) or not batch:
            return pmids


def _text(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def parse_article(art) -> dict | None:
    medline = art.find("MedlineCitation")
    article = medline.find("Article") if medline is not None else None
    pmid = _text(medline.find("PMID")) if medline is not None else ""
    if article is None or not pmid:
        return None

    year = ""
    for path in ("Journal/JournalIssue/PubDate/Year", "ArticleDate/Year"):
        year = _text(article.find(path))
        if year:
            break
    if not year:
        medline = article.find("Journal/JournalIssue/PubDate/MedlineDate")
        year = _text(medline)[:4]

    doi = ""
    for eid in art.findall(".//ArticleId"):
        if eid.get("IdType") == "doi":
            doi = _text(eid)
            break

    authors = []
    for author in article.findall(".//AuthorList/Author"):
        last, initials = _text(author.find("LastName")), _text(
            author.find("Initials")
        )
        if last:
            authors.append(f"{last} {initials}".lower().strip())

    return {
        "pmid": pmid,
        "doi": doi,
        "title": _text(article.find("ArticleTitle")),
        "abstract": " ".join(
            _text(p) for p in article.findall(".//Abstract/AbstractText")
        ).strip(),
        "journal": _text(article.find("Journal/ISOAbbreviation")),
        "year": year,
        "pub_types": [
            _text(t)
            for t in article.findall(".//PublicationTypeList/PublicationType")
        ],
        "author_keys": authors,
        "pmc": _pmc_id(art),
    }


def _pmc_id(art) -> str:
    for eid in art.findall(".//ArticleId"):
        if eid.get("IdType") == "pmc":
            return _text(eid)
    return ""


def efetch(pmids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for start in range(0, len(pmids), 150):
        chunk = pmids[start : start + 150]
        params = urllib.parse.urlencode(
            {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"}
        )
        root = DET.fromstring(_get(f"{EUTILS}/efetch.fcgi?{params}"))
        for art in root.findall(".//PubmedArticle"):
            rec = parse_article(art)
            if rec:
                out[rec["pmid"]] = rec
        time.sleep(PAUSE)
    return out


def is_preprint(paper: dict) -> bool:
    journal = paper["journal"].lower()
    return any(s in journal for s in PREPRINT_SERVERS) or (
        "Preprint" in paper["pub_types"] and not journal
    )


def select(papers: list[dict]) -> list[dict]:
    """Drop errata and preprints superseded by their journal version."""
    kept = [p for p in papers if "Published Erratum" not in p["pub_types"]]
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for paper in kept:
        groups[norm_title(paper["title"])].append(paper)

    out: list[dict] = []
    for group in groups.values():
        if len(group) > 1:
            published = [p for p in group if not is_preprint(p)]
            if published:
                group = published
        out.extend(group)
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _prose(node, out: list[str]) -> None:
    if _local(node.tag) in _DROP_TAGS:
        return
    if node.text:
        out.append(node.text)
    for child in node:
        _prose(child, out)
        if child.tail:
            out.append(child.tail)


def extract_pmc_body(root) -> str:
    """Pull section-titled prose out of a JATS full-text article."""
    body = next((el for el in root.iter() if _local(el.tag) == "body"), None)
    if body is None:
        return ""
    chunks: list[str] = []

    def walk(node, depth: int) -> None:
        for child in node:
            name = _local(child.tag)
            if name in _DROP_TAGS:
                continue
            if name == "sec":
                title_el = next(
                    (gc for gc in child if _local(gc.tag) == "title"), None
                )
                if title_el is not None:
                    parts: list[str] = []
                    _prose(title_el, parts)
                    heading = " ".join("".join(parts).split())
                    if heading:
                        hashes = "#" * min(depth + 2, 6)
                        chunks.append(f"\n{hashes} {heading}\n")
                walk(child, depth + 1)
            elif name == "p":
                parts = []
                _prose(child, parts)
                para = " ".join("".join(parts).split())
                if len(para) > 40:
                    chunks.append(para)
            else:
                walk(child, depth)

    walk(body, 0)
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(chunks)).strip()


def fetch_pmc_text(pmcid: str) -> str:
    params = urllib.parse.urlencode(
        {"db": "pmc", "id": pmcid.replace("PMC", ""), "retmode": "xml"}
    )
    try:
        xml = _get(f"{EUTILS}/efetch.fcgi?{params}")
        body = extract_pmc_body(DET.fromstring(xml))
    except Exception as exc:  # noqa: BLE001
        print(f"  {pmcid}: {exc}", file=sys.stderr)
        return ""
    return body if len(body) > 1500 else ""


def write_paper(paper: dict, body: str) -> None:
    title = clean_title(paper["title"])
    where = ", ".join(x for x in (paper["journal"], paper["year"]) if x)
    ids = [f"PMID: {paper['pmid']}"]
    if paper["doi"]:
        ids.append(f"DOI: {paper['doi']}")
    lines = [f"# {title}", "", f"*{where}.* {'. '.join(ids)}.", ""]
    if paper["abstract"]:
        lines += ["## Abstract", "", paper["abstract"], ""]
    if body:
        lines += [body, ""]
    (CORPUS / f"{slugify(title)}.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def main() -> int:
    CORPUS.mkdir(parents=True, exist_ok=True)
    existing_titles = {
        norm_title(path.read_text(encoding="utf-8").splitlines()[0][2:])
        for path in CORPUS.glob("*.md")
        if path.read_text(encoding="utf-8").startswith("# ")
    }

    papers: dict[str, dict] = {}
    for display, term, constrain in MEMBERS:
        query = f"{term} AND {GROUP_CLAUSE}" if constrain else term
        print(f"searching {display} ...")
        pmids = esearch(query)
        print(f"  {len(pmids)} hits")
        for pmid, rec in efetch(pmids).items():
            papers.setdefault(pmid, rec)

    group = [
        p for p in papers.values()
        if set(p["author_keys"]) & ANCHORS
    ]
    selected = select(group)
    print(f"\n{len(papers)} unique across all members, "
          f"{len(group)} by a PI, {len(selected)} after dedup")

    written = skipped = 0
    for paper in sorted(selected, key=lambda p: (p["year"], p["pmid"])):
        title = clean_title(paper["title"])
        slug = slugify(title)
        if not title:
            continue
        already_have = (CORPUS / f"{slug}.md").exists()
        if already_have or norm_title(title) in existing_titles:
            skipped += 1
            continue
        body = fetch_pmc_text(paper["pmc"]) if paper["pmc"] else ""
        write_paper(paper, body)
        written += 1

    print(f"wrote {written} papers, skipped {skipped} already present")
    print("run dev/build_catalog.py to rebuild the catalog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
