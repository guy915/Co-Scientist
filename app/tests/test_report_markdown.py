from typing import Any

from app.report import markdown as report_markdown
from app.report.markdown import document as report_markdown_toc
from app.report.markdown.overview import render_research_overview_markdown


def _hypothesis() -> dict[str, Any]:
    return {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }


def _evidence(evidence_id: str, **overrides: Any) -> dict[str, Any]:
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
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[_hypothesis()],
            evidence=evidence,
        )
    )


def test_a_retrieved_source_prints_title_authors_year_and_link() -> None:
    markdown = _overview_markdown([_evidence("ev-1")])

    section = markdown.split("## References", 1)[1]
    assert "Kim et al., 2022" in section
    assert "RSK1 drives NHE1 phosphorylation" in section
    assert "[" in section and "](https://example.org/rsk1)" in section


def test_a_source_with_no_url_renders_unlinked() -> None:
    markdown = _overview_markdown(
        [_evidence("ev-1", url="", authors=[], year=None)]
    )

    section = markdown.split("## References", 1)[1]
    assert "RSK1 drives NHE1 phosphorylation" in section
    assert "](" not in section.split("\n\n", 1)[0]


def test_a_doi_or_pmid_prints_as_the_identifier() -> None:
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
    markdown = _overview_markdown([_evidence("ev-1", retracted=True)])

    section = markdown.split("## References", 1)[1]
    assert "(retracted)" in section


def test_the_same_paper_from_two_sources_collapses_to_one_entry() -> None:
    # DOI identifies repeated captures even when source searches word their
    # titles differently.
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
    markdown = _overview_markdown(
        [
            _evidence("ev-1", title="Paper A", pmid="111"),
            _evidence("ev-2", title="Paper A (variant)", pmid="111"),
            _evidence("ev-3", title="Paper B", url="https://x.example/b"),
            _evidence(
                "ev-4", title="Paper B (variant)", url="https://x.example/b"
            ),
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
    assert forward == reversed_order


def test_a_run_with_no_retrieved_sources_renders_no_heading() -> None:
    assert "## References" not in _overview_markdown([])
    assert "## References" not in _overview_markdown(None)


def test_a_preprint_is_labelled_rather_than_read_as_peer_reviewed() -> None:
    # Preprints resolve like reviewed papers; omitting their type hides that
    # distinction from readers.
    markdown = _overview_markdown([_evidence("ev-1", source_type="preprint")])

    section = markdown.split("## References", 1)[1]
    assert "(preprint)" in section


def test_a_peer_reviewed_source_carries_no_type_suffix() -> None:
    markdown = _overview_markdown(
        [_evidence("ev-1", source_type="peer_reviewed")]
    )

    section = markdown.split("## References", 1)[1]
    assert "(peer" not in section
    assert "(preprint)" not in section


def test_an_unclassified_row_is_classified_from_what_it_carries() -> None:
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
    # Title-only formatting cannot otherwise distinguish an undated paper from a
    # complete reference.
    markdown = _overview_markdown(
        [_evidence("ev-1", year=None, source_type="peer_reviewed")]
    )

    section = markdown.split("## References", 1)[1]
    assert "(no date)" in section


def test_a_source_that_never_had_a_date_is_not_flagged_as_missing_one() -> None:
    # Attachments and database records have no publication date to lose.
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
    markdown = _overview_markdown(
        [_evidence("ev-1", year=9999, source_type="peer_reviewed")]
    )

    section = markdown.split("## References", 1)[1]
    assert "(date not verifiable)" in section


def _referenced_hypothesis(hyp_id: str, mechanism: str) -> dict[str, object]:
    return {
        "id": hyp_id,
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
        "mechanism": mechanism,
    }


def _citation_row(
    hyp_id: str, key: str, evidence_id: str, state: str = "verified"
) -> dict[str, object]:
    return {
        "run_id": "run-1",
        "hypothesis_id": hyp_id,
        "evidence_id": evidence_id,
        "claim": f"[{key}] cited in hypothesis",
        "state": state,
    }


def _paper_evidence(evidence_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": evidence_id,
        "title": "RSK1 drives NHE1 phosphorylation",
        "url": "https://example.org/rsk1",
        "authors": ["Kim"],
        "year": 2022,
    }
    row.update(overrides)
    return row


def _bibliography_markdown(
    hypotheses: list[dict[str, object]],
    citations: list[dict[str, object]] | None = None,
    evidence: list[dict[str, object]] | None = None,
) -> str:
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
    markdown = _bibliography_markdown(
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
    markdown = _bibliography_markdown(
        [
            _referenced_hypothesis(
                "h1", "RSK1 acts on NHE1 [C1], confirmed in vivo [C2]."
            )
        ],
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
    markdown = _bibliography_markdown(
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
    assert "](" not in section.split("\n\n", 1)[0]


def test_old_run_with_keys_but_no_data_shows_no_references_heading() -> None:
    # Legacy citation markers cannot reconstruct references when no supporting
    # rows were persisted.
    markdown = _bibliography_markdown(
        [_referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=None,
        evidence=None,
    )

    assert "#### References" not in markdown
    assert "[C1]" in markdown


def test_a_run_with_neither_keys_nor_citations_renders_cleanly() -> None:
    markdown = _bibliography_markdown(
        [_referenced_hypothesis("h1", "RSK1 phosphorylates NHE1.")],
        citations=[],
        evidence=[],
    )

    assert "#### References" not in markdown


def test_a_citation_row_with_an_unparseable_claim_is_skipped() -> None:
    # Unkeyable citation rows must not fabricate plausible references.
    markdown = _bibliography_markdown(
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
    markdown = _bibliography_markdown(
        [_referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=[_citation_row("h1", "C1", "ev-missing")],
        evidence=[],
    )

    assert "#### References" not in markdown


def test_only_hypotheses_with_resolvable_citations_get_a_heading() -> None:
    markdown = _bibliography_markdown(
        [
            _referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1]."),
            _referenced_hypothesis("h2", "A second, uncited idea."),
        ],
        citations=[_citation_row("h1", "C1", "ev-1")],
        evidence=[_paper_evidence("ev-1")],
    )

    assert markdown.count("#### References") == 1


def test_citation_state_never_appears_as_a_verdict_tag() -> None:
    markdown = _bibliography_markdown(
        [_referenced_hypothesis("h1", "RSK1 acts on NHE1 [C1].")],
        citations=[_citation_row("h1", "C1", "ev-1", state="unsupported")],
        evidence=[_paper_evidence("ev-1")],
    )

    section = markdown.split("#### References", 1)[1]
    assert "unsupported" not in section.lower()


# json_object mode permits object or serialized-JSON values where the schema
# requests strings.


def _render_overview_payload(payload: dict[str, Any]) -> str:
    return "\n".join(render_research_overview_markdown(payload))


def test_json_string_importance_is_flattened() -> None:
    payload = {
        "overview": {
            "summary": "A coherent program emerges.",
            "research_directions": [
                {
                    "title": "Validate in an orthogonal model",
                    "importance": (
                        '{"significance": "Guards against artefacts", '
                        '"gap": "None known"}'
                    ),
                    "suggested_experiments": ["Run a perturbation series."],
                }
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "Guards against artefacts - None known" in text
    assert '{"significance"' not in text
    assert "Run a perturbation series." in text


def test_object_and_json_array_experiments_are_flattened() -> None:
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Probe pathway redundancy",
                    "importance": "Determines whether routes compensate.",
                    "suggested_experiments": [
                        {"experiment": "Delete relA", "rationale": "tolerance"}
                    ],
                },
                {
                    "title": "Establish causality",
                    "importance": "Confirms the shared assumption.",
                    "suggested_experiments": '["Assay A", "Assay B"]',
                },
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "- Delete relA - tolerance" in text
    assert "- Assay A" in text and "- Assay B" in text
    assert '{"experiment"' not in text
    assert '["Assay A"' not in text


def test_malformed_aims_and_contacts_are_flattened() -> None:
    payload = {
        "nih_specific_aims": {
            "disease_description": (
                '{"context": "Targets tolerance", "scope": "in vitro"}'
            ),
            "aims": [
                {
                    "overarching_goal": "Aim 1: Delete relA",
                    "hypothesis": {"why": "Guards against artefacts"},
                    "reasoning": "Static and flow-cell assays.",
                }
            ],
            "pilot_evaluation": (
                "Converts the lead hypothesis into a research program."
            ),
        },
        "research_contacts": [
            {
                "name": "Ada Researcher",
                "expertise": '{"field": "Biofilm metabolism"}',
                "justification": "Authored an analyzed paper.",
                "source_title": "A biofilm study",
                "source_url": "https://example.org/paper",
            }
        ],
    }

    text = _render_overview_payload(payload)

    assert "Targets tolerance - in vitro" in text
    assert "Guards against artefacts" in text
    assert "Biofilm metabolism" in text
    assert '{"context"' not in text
    assert '{"field"' not in text
    assert '{"why"' not in text
    assert "https://example.org/paper" in text


def test_well_formed_overview_is_unchanged() -> None:
    payload = {
        "overview": {
            "summary": "Top hypotheses converge on cross-pathway interference.",
            "research_directions": [
                {
                    "title": "Validate in an orthogonal model",
                    "importance": "Guards against assay-specific artefacts.",
                    "suggested_experiments": [
                        "Run a controlled perturbation series.",
                        "Quantify the readout against baseline.",
                    ],
                }
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "Guards against assay-specific artefacts." in text
    assert "- Run a controlled perturbation series." in text
    assert "- Quantify the readout against baseline." in text
    assert "converge on cross-pathway interference" in text


def test_sub_topics_render() -> None:
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Mitochondrial dysfunction",
                    "importance": "Central to the disease's early stages.",
                    "suggested_experiments": ["Profile ROS in patient iPSCs."],
                    "sub_topics": [
                        {
                            "title": "Mitochondrial DNA repair defects",
                            "why": "A deficiency could be a primary driver.",
                            "what": "Assay BER activity in iPSC neurons.",
                            "example_idea": "Knock down OGG1 in iPSC neurons.",
                            "specific_questions": [
                                "Does OGG1 activity correlate with damage?",
                                "Does release activate cGAS-STING?",
                            ],
                        }
                    ],
                }
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "#### Mitochondrial DNA repair defects" in text
    assert "A deficiency could be a primary driver." in text
    assert "Assay BER activity in iPSC neurons." in text
    assert "**Example idea:** Knock down OGG1 in iPSC neurons." in text
    assert "- Does OGG1 activity correlate with damage?" in text
    assert "- Does release activate cGAS-STING?" in text


def test_malformed_sub_topics_are_flattened() -> None:
    # json_object mode does not enforce field types; persisted overviews may
    # carry objects or serialized JSON.
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Direction",
                    "importance": "I",
                    "suggested_experiments": ["E"],
                    "sub_topics": [
                        {
                            "title": "Sub-topic",
                            "why": '["stress", "damage"]',
                            "what": "Investigate.",
                            "specific_questions": "not a list",
                        },
                        "not a dict",
                    ],
                }
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "stress damage" in text
    assert '["stress"' not in text
    assert "#### Sub-topic" in text


def test_recent_findings_renders() -> None:
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Mitochondrial dysfunction",
                    "importance": "Central to the disease's early stages.",
                    "recent_findings": (
                        "mtDNA repair defects are already implicated."
                    ),
                    "suggested_experiments": ["Profile ROS in patient iPSCs."],
                }
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "mtDNA repair defects are already implicated." in text


def test_malformed_recent_findings_is_flattened() -> None:
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Direction",
                    "importance": "I",
                    "recent_findings": {"gap": "None known"},
                    "suggested_experiments": ["E"],
                }
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "None known" in text
    assert '{"gap"' not in text


def test_two_or_more_directions_get_a_preview_list() -> None:
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Mitochondrial dysfunction",
                    "importance": "Central to the disease's early stages.",
                },
                {
                    "title": "RNA processing defects",
                    "importance": "Implicated across ALS subtypes.",
                },
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "We will be focusing on these research directions:" in text
    assert "- Mitochondrial dysfunction" in text
    assert "- RNA processing defects" in text
    preview_at = text.index("We will be focusing")
    detail_at = text.index("### Mitochondrial dysfunction")
    assert preview_at < detail_at


def test_a_single_direction_gets_no_preview_list() -> None:
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {
                    "title": "Mitochondrial dysfunction",
                    "importance": "Central to the disease's early stages.",
                }
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "We will be focusing on these research directions:" not in text
    assert "### Mitochondrial dysfunction" in text


def test_an_untitled_direction_is_dropped_from_the_preview_count() -> None:
    payload = {
        "overview": {
            "summary": "",
            "research_directions": [
                {"title": "Mitochondrial dysfunction", "importance": "I"},
                {"title": "", "importance": "No name given"},
                "not a dict",
            ],
        }
    }

    text = _render_overview_payload(payload)

    assert "We will be focusing on these research directions:" not in text
    assert "### Mitochondrial dysfunction" in text


def test_published_aims_vocabulary_renders_every_block() -> None:
    payload = {
        "nih_specific_aims": {
            "disease_description": "An aggressive malignancy.",
            "unmet_need": "Current therapies relapse.",
            "proposed_solution": "Repurpose an approved inhibitor.",
            "aims": [
                {
                    "overarching_goal": "Determine anti-tumour activity.",
                    "hypothesis": "Treatment reduces viability.",
                    "reasoning": "The pathway is upregulated.",
                }
            ],
            "pilot_evaluation": "A xenograft study measures tumour growth.",
        }
    }

    text = _render_overview_payload(payload)

    assert "### Disease Description" in text
    assert "### Unmet Need" in text
    assert "### Proposed Solution" in text
    assert "### Specific Aims 1" in text
    assert "**Overarching goal:** Determine anti-tumour activity." in text
    assert "**Hypothesis:** Treatment reduces viability." in text
    assert "**Reasoning:** The pathway is upregulated." in text
    assert "### Pilot Evaluation" in text


def _contents_markdown(**overrides: Any) -> str:
    hypothesis: dict[str, Any] = overrides.pop(
        "hypothesis",
        {
            "id": "h1",
            "title": "NHE1 coupling",
            "statement": "NHE1 couples to the RSK axis in HFpEF.",
        },
    )
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis] if hypothesis else [],
            **overrides,
        )
    )


def test_table_of_contents_lists_only_the_sections_this_render_produced() -> (
    None
):
    markdown = _contents_markdown(
        attributes=[{"name": "Human Relevance", "rubric": "1-5 scale."}],
        meta_review={"summary": "Ideas converge on a shared mechanism."},
        knowledge_base=[{"title": "NHE1", "summary": "Background."}],
    )

    lines = markdown.splitlines()
    toc_at = lines.index("#### Table of contents:")
    assert lines[toc_at + 1] == ""
    assert lines[toc_at + 2] == "- Stratification Attributes"
    assert lines[toc_at + 3] == "- Meta-review insights"
    assert lines[toc_at + 4] == "- Top hypotheses"
    assert lines[toc_at + 5] == "- Knowledge Base"
    assert "- Research Goal Details" not in markdown
    assert "- Open questions" not in markdown
    assert "- Research Contacts" not in markdown


def test_table_of_contents_opens_the_report_before_any_section() -> None:
    markdown = _contents_markdown(
        meta_review={"summary": "Ideas converge on a shared mechanism."}
    )

    lines = markdown.splitlines()
    assert lines[0] == "# Research Report — Explain the cardiac benefit."
    toc_at = lines.index("#### Table of contents:")
    goal_at = markdown.find("## Research Goal Details")
    hypotheses_at = markdown.find("## Top hypotheses")
    assert toc_at < 8
    assert goal_at == -1
    assert markdown.index("#### Table of contents:") < hypotheses_at


def test_table_of_contents_still_lists_the_lone_populated_section() -> None:
    markdown = _contents_markdown()

    lines = markdown.splitlines()
    toc_at = lines.index("#### Table of contents:")
    assert lines[toc_at + 2] == "- Top hypotheses"
    assert lines[toc_at + 3] == ""


def test_table_of_contents_omitted_with_nothing_to_navigate() -> None:
    assert report_markdown_toc._render_table_of_contents([]) == []
    assert report_markdown_toc._render_table_of_contents([[], [], []]) == []


def test_table_of_contents_ignores_a_bogus_heading_inside_body_prose() -> None:
    # Model-authored bodies can contain headings; navigation may scan only
    # section-leading headings.
    sections = [
        ["## Real heading", "", "some prose", "## Fake heading in the body"],
    ]

    toc = report_markdown_toc._render_table_of_contents(sections)

    assert toc == ["#### Table of contents:", "", "- Real heading", ""]
    assert "Fake heading" not in "\n".join(toc)


def test_table_of_contents_degrades_when_research_overview_is_malformed() -> (
    None
):
    markdown = _contents_markdown(research_overview="not a dict")

    lines = markdown.splitlines()
    toc_at = lines.index("#### Table of contents:")
    assert lines[toc_at + 2] == "- Top hypotheses"
    assert lines[toc_at + 3] == ""
