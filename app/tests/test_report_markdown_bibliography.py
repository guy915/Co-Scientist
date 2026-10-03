"""The run-wide 'References' section (R12-12): every source a run retrieved.

Google's published MASH report ends with a flat, deduplicated bibliography
(docs/CORPUS-EXTRACTION.md R12-12) -- these tests pin the aggregate section
this repo adds for that: dedup across sources on a stable identity, stable
alphabetical ordering, placement last in the document, and a clean degrade
when a run retrieved nothing.
"""

from typing import Any

from app.report import markdown as report_markdown


def _hypothesis() -> dict[str, Any]:
    """A minimal report-ready hypothesis; content is irrelevant here."""
    return {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }


def _evidence(evidence_id: str, **overrides: Any) -> dict[str, Any]:
    """One evidence row in the shape ``store.list_evidence`` returns."""
    row: dict[str, Any] = {
        "id": evidence_id,
        "title": "RSK1 drives NHE1 phosphorylation",
        "url": "https://example.org/rsk1",
        "authors": ["Kim"],
        "year": 2022,
        "doi": None,
        "pmid": None,
        "retracted": False,
    }
    row.update(overrides)
    return row


def _overview_markdown(evidence: list[dict[str, Any]] | None) -> str:
    """Render the report with the given evidence."""
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[_hypothesis()],
            evidence=evidence,
        )
    )


def test_a_retrieved_source_prints_title_authors_year_and_link() -> None:
    """A normal paper renders as an author/year/title bullet, linked."""
    markdown = _overview_markdown([_evidence("ev-1")])

    section = markdown.split("## References", 1)[1]
    assert "Kim et al., 2022" in section
    assert "RSK1 drives NHE1 phosphorylation" in section
    assert "[" in section and "](https://example.org/rsk1)" in section


def test_a_source_with_no_url_renders_unlinked() -> None:
    """A source with no url (an uploaded doc, a directly fetched paper)."""
    markdown = _overview_markdown(
        [_evidence("ev-1", url="", authors=[], year=None)]
    )

    section = markdown.split("## References", 1)[1]
    assert "RSK1 drives NHE1 phosphorylation" in section
    assert "](" not in section.split("\n\n", 1)[0]


def test_a_doi_or_pmid_prints_as_the_identifier() -> None:
    """The persisted identifier is shown, DOI in preference to PMID."""
    markdown = _overview_markdown(
        [
            _evidence("ev-1", doi="10.1038/example"),
            _evidence("ev-2", title="Second paper", pmid="12345678"),
        ]
    )

    section = markdown.split("## References", 1)[1]
    assert "DOI: 10.1038/example" in section
    assert "PMID: 12345678" in section


def test_a_retracted_source_is_flagged_not_silently_listed() -> None:
    """A withdrawn paper is not shown as a plain, current reference."""
    markdown = _overview_markdown([_evidence("ev-1", retracted=True)])

    section = markdown.split("## References", 1)[1]
    assert "(retracted)" in section


def test_the_same_paper_from_two_sources_collapses_to_one_entry() -> None:
    """A run can retrieve one paper via two searches -- one entry, not two.

    DOI is the strongest identity: two rows that only share a DOI (a
    different capture of the record from a different search) still
    collapse, even with a differently worded title.
    """
    markdown = _overview_markdown(
        [
            _evidence(
                "ev-1",
                title="NHE1 in heart failure",
                doi="10.1000/shared",
                url="https://pubmed.example/shared",
            ),
            _evidence(
                "ev-2",
                title="NHE1 in heart failure (preprint)",
                doi="10.1000/shared",
                url="https://biorxiv.example/shared",
            ),
        ]
    )

    section = markdown.split("## References", 1)[1]
    assert section.count("NHE1 in heart failure") == 1


def test_dedup_falls_back_through_pmid_url_then_title() -> None:
    """Each identity tier collapses a duplicate the tier above it misses."""
    markdown = _overview_markdown(
        [
            # Same PMID, no DOI on either row.
            _evidence("ev-1", title="Paper A", pmid="111"),
            _evidence("ev-2", title="Paper A (variant)", pmid="111"),
            # Same URL, no DOI/PMID on either row.
            _evidence("ev-3", title="Paper B", url="https://x.example/b"),
            _evidence(
                "ev-4", title="Paper B (variant)", url="https://x.example/b"
            ),
            # Same normalized title, no DOI/PMID/URL on either row.
            _evidence("ev-5", title="Paper C", url="", authors=[], year=None),
            _evidence(
                "ev-6", title="  paper c  ", url="", authors=[], year=None
            ),
        ]
    )

    section = markdown.split("## References", 1)[1]
    assert section.count("Paper A") == 1
    assert section.count("Paper B") == 1
    assert section.lower().count("paper c") == 1


def test_two_distinct_papers_both_survive() -> None:
    """Dedup never merges rows that are actually different sources."""
    markdown = _overview_markdown(
        [
            _evidence("ev-1", title="Paper One", doi="10.1/one"),
            _evidence("ev-2", title="Paper Two", doi="10.1/two"),
        ]
    )

    section = markdown.split("## References", 1)[1]
    assert "Paper One" in section
    assert "Paper Two" in section


def test_ordering_is_alphabetical_by_rendered_label_and_stable() -> None:
    """Entries sort by the same text they render, independent of input order."""
    evidence = [
        _evidence("ev-1", title="Zebra study", url="", authors=[], year=None),
        _evidence("ev-2", title="Alpha study", url="", authors=[], year=None),
        _evidence("ev-3", title="Mango study", url="", authors=[], year=None),
    ]

    forward = _overview_markdown(evidence)
    reversed_order = _overview_markdown(list(reversed(evidence)))

    section = forward.split("## References", 1)[1]
    assert (
        section.index("Alpha study")
        < section.index("Mango study")
        < section.index("Zebra study")
    )
    # Rendering the identical rows in a different input order produces the
    # identical document -- the sort key is the render, not arrival order.
    assert forward == reversed_order


def test_a_run_with_no_retrieved_sources_renders_no_heading() -> None:
    """No evidence at all: omit the heading along with the body.

    Matches this renderer's own convention (R14-23) -- a heading with
    nothing under it is never printed.
    """
    assert "## References" not in _overview_markdown([])
    assert "## References" not in _overview_markdown(None)


def test_a_preprint_is_labelled_rather_than_read_as_peer_reviewed() -> None:
    """A reader is told which references have not been reviewed.

    A preprint resolves as well as a journal article and is listed
    alongside one, so the type has to be printed or the two are
    indistinguishable in the only place a reader sees the run's sources.
    """
    markdown = _overview_markdown([_evidence("ev-1", source_type="preprint")])

    section = markdown.split("## References", 1)[1]
    assert "(preprint)" in section


def test_a_peer_reviewed_source_carries_no_type_suffix() -> None:
    """The expected case prints nothing; only the exceptions are labelled."""
    markdown = _overview_markdown(
        [_evidence("ev-1", source_type="peer_reviewed")]
    )

    section = markdown.split("## References", 1)[1]
    assert "(peer" not in section
    assert "(preprint)" not in section


def test_an_unclassified_row_is_classified_from_what_it_carries() -> None:
    """A row predating the column still classifies, from source and URL.

    ``source_type`` is NULL for every row persisted before it existed and
    for evidence that never went through the drain; falling back to the
    same classifier over the row's own source/URL keeps those readable
    rather than showing them as an unlabelled gap.
    """
    markdown = _overview_markdown(
        [
            _evidence(
                "ev-1",
                source_type=None,
                source="biorxiv",
                url="https://www.biorxiv.org/content/10.1101/1v1",
            )
        ]
    )

    section = markdown.split("## References", 1)[1]
    assert "(preprint)" in section


def test_a_paper_with_no_date_says_so() -> None:
    """An undated paper is flagged, not silently printed title-only.

    Without authors *and* a year the label falls back to the bare title,
    which is exactly what a normal title-only entry looks like -- so the
    absence of a date is invisible unless it is stated.
    """
    markdown = _overview_markdown(
        [_evidence("ev-1", year=None, source_type="peer_reviewed")]
    )

    section = markdown.split("## References", 1)[1]
    assert "(no date)" in section


def test_a_source_that_never_had_a_date_is_not_flagged_as_missing_one() -> None:
    """An attachment or database record has no publication date to lose.

    Reporting one as undated invents a metadata defect on every row of a
    kind that never carries a year.
    """
    markdown = _overview_markdown(
        [
            _evidence("ev-1", year=None, source_type="document"),
            _evidence(
                "ev-2", title="A record", year=None, source_type="database"
            ),
        ]
    )

    section = markdown.split("## References", 1)[1]
    assert "(no date)" not in section
    assert "(attached document)" in section


def test_an_impossible_date_is_flagged_rather_than_printed_as_fact() -> None:
    """A year outside the range a paper can hold is bad metadata."""
    markdown = _overview_markdown(
        [_evidence("ev-1", year=9999, source_type="peer_reviewed")]
    )

    section = markdown.split("## References", 1)[1]
    assert "(date not verifiable)" in section


def _referenced_hypothesis(hyp_id: str, mechanism: str) -> dict[str, object]:
    """Build a minimal report-ready hypothesis carrying [C*] keys in prose."""
    return {
        "id": hyp_id,
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
        "mechanism": mechanism,
    }


def _citation_row(
    hyp_id: str, key: str, evidence_id: str, state: str = "verified"
) -> dict[str, object]:
    """Build one citation row in the shape ``store.list_citations`` returns."""
    return {
        "run_id": "run-1",
        "hypothesis_id": hyp_id,
        "evidence_id": evidence_id,
        "claim": f"[{key}] cited in hypothesis",
        "state": state,
    }


def _paper_evidence(evidence_id: str, **overrides: object) -> dict[str, object]:
    """Build one evidence row in the shape ``store.list_evidence`` returns."""
    row: dict[str, object] = {
        "id": evidence_id,
        "title": "RSK1 drives NHE1 phosphorylation",
        "url": "https://example.org/rsk1",
        "authors": ["Kim"],
        "year": 2022,
    }
    row.update(overrides)
    return row


def _markdown(
    hypotheses: list[dict[str, object]],
    citations: list[dict[str, object]] | None = None,
    evidence: list[dict[str, object]] | None = None,
) -> str:
    """Render a minimal report carrying the given hypotheses/citations."""
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=hypotheses,
            citations=citations,
            evidence=evidence,
        )
    )


def test_a_resolvable_key_prints_its_reference_entry() -> None:
    """A [C1] key with a matching citation+evidence row resolves to a line."""
    markdown = _markdown(
        [
            _referenced_hypothesis(
                "h1", "RSK1 phosphorylates NHE1 directly [C1]."
            )
        ],
        citations=[_citation_row("h1", "C1", "ev-1")],
        evidence=[_paper_evidence("ev-1")],
    )

    assert "#### References" in markdown
    assert "[C1]" in markdown.split("#### References", 1)[1]
    assert "Kim et al., 2022" in markdown
    assert "RSK1 drives NHE1 phosphorylation" in markdown
    assert "https://example.org/rsk1" in markdown


def test_multiple_keys_render_in_numeric_order() -> None:
    """C1 and C2 both resolve, C1 printed before C2 regardless of row order."""
    markdown = _markdown(
        [
            _referenced_hypothesis(
                "h1", "RSK1 acts on NHE1 [C1], confirmed in vivo [C2]."
            )
        ],
        # Rows deliberately out of key order.
        citations=[
            _citation_row("h1", "C2", "ev-2"),
            _citation_row("h1", "C1", "ev-1"),
        ],
        evidence=[
            _paper_evidence("ev-1", title="Paper one"),
            _paper_evidence("ev-2", title="Paper two"),
        ],
    )

    section = markdown.split("#### References", 1)[1]
    assert section.index("[C1]") < section.index("[C2]")
    assert "Paper one" in section
    assert "Paper two" in section


def test_a_knowledge_graph_citation_has_no_url_and_no_author_year() -> None:
    """A non-paper source renders its title alone, unlinked (no URL)."""
    markdown = _markdown(
        [_referenced_hypothesis("h1", "KRAS activates RAF1 [C1].")],
        citations=[_citation_row("h1", "C1", "ev-1")],
        evidence=[
            {
                "id": "ev-1",
                "title": "INDRA: KRAS -> RAF1 [Activation]",
                "url": "",
                "authors": [],
                "year": None,
            }
        ],
    )

    section = markdown.split("#### References", 1)[1]
    assert "INDRA: KRAS -> RAF1 [Activation]" in section
    # No markdown link syntax for a source with no URL.
    assert "](" not in section.split("\n\n", 1)[0]


def test_old_run_with_keys_but_no_data_shows_no_references_heading() -> None:
    """A run persisted before this fix has [C*] keys, nothing to resolve them.

    The [C*] markers stay literally in the mechanism prose -- there is no
    data to reconstruct a reference list from -- but the report must not
    crash, and must not print an empty 'References' heading.
    """
    markdown = _markdown(
        [_referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=None,
        evidence=None,
    )

    assert "#### References" not in markdown
    # The unresolved key is still visible in the prose -- not silently
    # deleted, just not fabricated into a reference.
    assert "[C1]" in markdown


def test_a_run_with_neither_keys_nor_citations_renders_cleanly() -> None:
    """No [C*] keys, no citation rows: no heading, no crash."""
    markdown = _markdown(
        [_referenced_hypothesis("h1", "RSK1 phosphorylates NHE1.")],
        citations=[],
        evidence=[],
    )

    assert "#### References" not in markdown


def test_a_citation_row_with_an_unparseable_claim_is_skipped() -> None:
    """A citation row whose claim isn't the '[Ck] ...' format resolves nothing.

    Never invent a plausible-looking entry for a row this renderer cannot
    positively key -- it is dropped instead of guessed at.
    """
    markdown = _markdown(
        [_referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=[
            {
                "run_id": "run-1",
                "hypothesis_id": "h1",
                "evidence_id": "ev-1",
                "claim": "NHE1 couples to the RSK axis.",
                "state": "verified",
            }
        ],
        evidence=[_paper_evidence("ev-1")],
    )

    assert "#### References" not in markdown


def test_a_dangling_evidence_id_is_skipped_not_fabricated() -> None:
    """A citation row pointing at an evidence id the run never persisted."""
    markdown = _markdown(
        [_referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=[_citation_row("h1", "C1", "ev-missing")],
        evidence=[],
    )

    assert "#### References" not in markdown


def test_only_hypotheses_with_resolvable_citations_get_a_heading() -> None:
    """Heading omission is per-hypothesis, not all-or-nothing for the report."""
    markdown = _markdown(
        [
            _referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1]."),
            _referenced_hypothesis("h2", "A second, uncited idea."),
        ],
        citations=[_citation_row("h1", "C1", "ev-1")],
        evidence=[_paper_evidence("ev-1")],
    )

    assert markdown.count("#### References") == 1


def test_citation_state_never_appears_as_a_verdict_tag() -> None:
    """No inline parenthetical verdict tags (e.g. '[C1 (unsupported)]').

    Google's corpus carries exactly two such markers across every published
    document -- not a format to mirror. The reference line names the source,
    never the citation's classification state.
    """
    markdown = _markdown(
        [_referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=[_citation_row("h1", "C1", "ev-1", state="unsupported")],
        evidence=[_paper_evidence("ev-1")],
    )

    section = markdown.split("#### References", 1)[1]
    assert "unsupported" not in section.lower()
