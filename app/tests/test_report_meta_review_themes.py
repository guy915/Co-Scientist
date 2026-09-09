"""MO-2: the "Emerging themes" section renders the full theme taxonomy.

Google's published meta-review critique
(``meta-review-critiques/als-meta-review-critique.md``) organizes the
recurring critiques as five themes, three levels deep: a theme, the named
critique points under it, and the guidance sub-points under several of
those. Our schema flattened all of that to ``{theme, description,
frequency}``; both halves of that loss are now closed -- ``meta_review.py``
used to drop ``description``/``frequency`` before the state dict reached
the app (so the section printed bare theme names for fields the model was
paid to compute), and the schema itself carried no nesting to render.

These pin the three levels of real markdown hierarchy, and the three input
shapes that must all render: the nested taxonomy, the flat entry a run
checkpointed before ``sub_themes`` existed still carries, and the
bare-name ``emerging_themes`` fallback of a demo/seed report.
"""

from app import report_markdown


def _markdown(meta_review: dict[str, object]) -> str:
    """Render a minimal report carrying only the given meta-review."""
    hypothesis: dict[str, object] = {
        "id": "h1",
        "title": "NHE1 coupling",
        "statement": "NHE1 couples to the RSK axis in HFpEF.",
    }
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[hypothesis],
            meta_review=meta_review,
        )
    )


def test_a_structured_theme_renders_its_description_and_frequency() -> None:
    """A recurring_themes entry prints its description and frequency."""
    markdown = _markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Motor neuron specificity",
                    "description": (
                        "Ideas rarely explain why the mechanism would"
                        " preferentially affect motor neurons."
                    ),
                    "frequency": "common",
                }
            ]
        }
    )

    assert "### Emerging themes" in markdown
    assert "Motor neuron specificity" in markdown
    assert "preferentially affect motor neurons" in markdown
    assert "common" in markdown


def test_a_bare_theme_name_falls_back_to_a_plain_bullet() -> None:
    """A report with only the flattened list still renders, bare-named.

    Covers demo/seed reports and any report persisted before
    ``recurring_themes`` existed -- ``emerging_themes`` alone must not
    regress to a missing section.
    """
    markdown = _markdown(
        {"emerging_themes": ["Time-resolved state measurements"]}
    )

    assert "### Emerging themes" in markdown
    assert "- Time-resolved state measurements" in markdown


def test_an_entry_with_no_theme_name_is_skipped() -> None:
    """A malformed entry with an empty theme does not render a bare '****:'.

    ``**:`` alone is too loose a check -- R14-13's per-hypothesis disclaimer
    ("**About**: ...") legitimately contains it. The bug this guards is an
    empty name reaching ``f"**{name}**: {description}"`` and rendering the
    doubled-asterisk ``****:`` that produces.
    """
    markdown = _markdown(
        {
            "recurring_themes": [
                {"theme": "", "description": "orphaned text", "frequency": ""}
            ]
        }
    )

    assert "orphaned text" not in markdown
    assert "****:" not in markdown


def test_a_theme_renders_its_sub_themes_and_their_points() -> None:
    """MO-2: three real levels of hierarchy, not a flattened dump.

    The published critique nests a named critique point under each theme
    and guidance sub-points under several of those points; the renderer
    must show that as a heading, a bullet, and a sub-bullet rather than
    running them together.
    """
    markdown = _markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Core Hypothesis and Mechanism",
                    "description": "How the mechanism itself is argued.",
                    "frequency": "very common",
                    "sub_themes": [
                        {
                            "theme": "Primary Driver vs. Consequence",
                            "description": "Whether it initiates or follows.",
                            "points": [
                                "Provide evidence for the temporal sequence.",
                                "Knock the driver down to show necessity.",
                            ],
                        }
                    ],
                }
            ]
        }
    )

    assert "#### Core Hypothesis and Mechanism" in markdown
    assert "- **Primary Driver vs. Consequence**: Whether it" in markdown
    assert "  - Provide evidence for the temporal sequence." in markdown
    assert "  - Knock the driver down to show necessity." in markdown


def test_a_flat_theme_from_an_older_checkpoint_still_renders() -> None:
    """A resumed run persisted before sub-themes existed must not crash.

    ``meta_review`` is checkpointed state, so the flat three-field entry
    outlives the schema change; it renders as a theme with no sub-list.
    """
    markdown = _markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Motor neuron specificity",
                    "description": "Rarely explained.",
                    "frequency": "common",
                }
            ]
        }
    )

    assert "#### Motor neuron specificity" in markdown
    assert "Rarely explained." in markdown


def test_a_sub_theme_with_no_points_renders_as_a_plain_bullet() -> None:
    """Two of the published themes carry points with no sub-points at all."""
    markdown = _markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Novelty and Impact",
                    "description": "",
                    "frequency": "",
                    "sub_themes": [
                        {
                            "theme": "Incremental vs. Groundbreaking",
                            "description": "Builds on existing knowledge.",
                            "points": [],
                        }
                    ],
                }
            ]
        }
    )

    assert "#### Novelty and Impact" in markdown
    assert (
        "- **Incremental vs. Groundbreaking**: Builds on existing knowledge."
        in markdown
    )


def test_a_bare_string_sub_theme_still_renders() -> None:
    """json_object mode enforces nothing, so a sub-theme may be a string."""
    markdown = _markdown(
        {
            "recurring_themes": [
                {
                    "theme": "Assumptions and Validation",
                    "sub_themes": ["State every assumption explicitly."],
                }
            ]
        }
    )

    assert "- State every assumption explicitly." in markdown
