"""The report resolves a hypothesis's [C*] citation keys against References.

The generation prompt (``prompts/generation_debate.py``) instructs the model
to cite ``[C1]``/``[C2]``/... keys inline in ``literature_grounding``
(persisted as ``mechanism``), keyed against a per-hypothesis reference index
the engine builds and resolves onto each hypothesis's own ``citation_map``
(``co_scientist.agents.generation.citations``). The drain already persists
that map into the ``citations``/``evidence`` tables, but nothing rendered it
back out, so the report printed bare ``[C1]`` markers with nothing to
resolve them against. These tests pin the fix at the render layer, in
isolation from the drain/store.
"""

from app.report import markdown as report_markdown


def _hypothesis(hyp_id: str, mechanism: str) -> dict[str, object]:
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
        [_hypothesis("h1", "RSK1 phosphorylates NHE1 directly [C1].")],
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
        [_hypothesis("h1", "RSK1 acts on NHE1 [C1], confirmed in vivo [C2].")],
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
        [_hypothesis("h1", "KRAS activates RAF1 [C1].")],
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
        [_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
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
        [_hypothesis("h1", "RSK1 phosphorylates NHE1.")],
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
        [_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
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
        [_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=[_citation_row("h1", "C1", "ev-missing")],
        evidence=[],
    )

    assert "#### References" not in markdown


def test_only_hypotheses_with_resolvable_citations_get_a_heading() -> None:
    """Heading omission is per-hypothesis, not all-or-nothing for the report."""
    markdown = _markdown(
        [
            _hypothesis("h1", "RSK1 acts on NHE1 [C1]."),
            _hypothesis("h2", "A second, uncited idea."),
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
        [_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=[_citation_row("h1", "C1", "ev-1", state="unsupported")],
        evidence=[_paper_evidence("ev-1")],
    )

    section = markdown.split("#### References", 1)[1]
    assert "unsupported" not in section.lower()
