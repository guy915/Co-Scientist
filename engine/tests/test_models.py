"""Regression tests for the ``co_scientist.models.Hypothesis`` dataclass.

These tests lock in the *current* construction defaults, computed properties,
serialization shape, and equality semantics of ``Hypothesis``, giving upcoming
refactors a safety net. The supporting dataclasses (``HypothesisReview``,
``ExecutionMetrics``, ``Article``) are covered in ``test_models_supporting.py``.
"""

import pytest

from co_scientist.models import (
    GenerationMethod,
    Hypothesis,
    HypothesisOrigin,
    HypothesisReview,
)
from tests._state import make_review

# Exact serialized key sets are part of the contract this net pins.
_HYPOTHESIS_DICT_KEYS = {
    "id",
    "parent_id",
    "parent_ids",
    "generation",
    "origin",
    "creation_iteration",
    "text",
    "title",
    "category",
    "introduction",
    "recent_findings",
    "safety_and_toxicity",
    "explanation",
    "literature_grounding",
    "experiment",
    "novelty_validation",
    "enrichments",
    "citation_map",
    "score",
    "elo_rating",
    "reviews",
    "similarity_cluster_id",
    "evolution_history",
    "reflection_notes",
    "deep_verification_probes",
    "deep_verification_verdict",
    "deep_verification_fingerprint",
    "review_disposition",
    "safety_status",
    "generation_method",
    "debate_id",
    "win_count",
    "loss_count",
    "total_matches",
    "win_rate",
}

# --- Hypothesis: construction and defaults ----------------------------------


def test_hypothesis_minimal_construction_defaults() -> None:
    """Only ``text`` is required; other fields use documented defaults."""
    hyp = Hypothesis(text="A hypothesis")
    assert hyp.text == "A hypothesis"
    assert hyp.category is None
    assert hyp.explanation is None
    assert hyp.literature_grounding is None
    assert hyp.experiment is None
    assert hyp.novelty_validation is None
    assert hyp.enrichments == {}
    assert hyp.citation_map == {}
    assert hyp.score == 0.0
    assert hyp.elo_rating == 1200
    assert hyp.reviews == []
    assert hyp.similarity_cluster_id is None
    assert hyp.similarity_degree is None
    assert hyp.evolution_history == []
    assert hyp.reflection_notes is None
    assert hyp.generation_method is None
    assert hyp.debate_id is None
    assert hyp.win_count == 0
    assert hyp.loss_count == 0


def test_hypothesis_mutable_defaults_not_shared() -> None:
    """``default_factory`` fields are independent per instance (no sharing)."""
    a = Hypothesis(text="a")
    b = Hypothesis(text="b")
    a.evolution_history.append("step 1")
    a.enrichments["k"] = "v"
    a.reviews.append(make_review())
    assert b.evolution_history == []
    assert b.enrichments == {}
    assert b.reviews == []


# --- Hypothesis: lineage / evolution ----------------------------------------


def test_gen_zero_hypothesis_has_no_lineage() -> None:
    """A fresh (gen-0) hypothesis carries no parent lineage.

    The explicit lineage fields default to a root: ``parent_id`` None,
    ``generation`` 0, ``origin`` GENERATION. ``evolution_history`` (empty),
    ``debate_id`` (None), and ``generation_method`` (None) are also root
    defaults.
    """
    hyp = Hypothesis(text="origin")
    assert hyp.parent_id is None
    assert hyp.generation == 0
    assert hyp.origin is HypothesisOrigin.GENERATION
    assert hyp.creation_iteration is None
    assert hyp.evolution_history == []
    assert hyp.debate_id is None
    assert hyp.generation_method is None


def test_evolved_hypothesis_records_lineage() -> None:
    """An evolved child references its parent via explicit lineage fields."""
    parent = Hypothesis(text="origin")
    evolved = Hypothesis(
        text="refined",
        parent_id=parent.id,
        generation=1,
        origin=HypothesisOrigin.EVOLUTION,
        creation_iteration=2,
        evolution_history=["origin"],
    )
    assert evolved.parent_id == parent.id
    assert evolved.generation == 1
    assert evolved.origin is HypothesisOrigin.EVOLUTION
    assert evolved.creation_iteration == 2
    # The child has a distinct id from its parent.
    assert evolved.id != parent.id


def test_multi_parent_lineage_records_every_parent() -> None:
    """A combination child keeps parent_id primary and parent_ids all."""
    primary = Hypothesis(text="primary parent")
    partner = Hypothesis(text="partner parent")
    child = Hypothesis(
        text="combined child",
        parent_id=primary.id,
        parent_ids=[primary.id, partner.id],
        generation=1,
        origin=HypothesisOrigin.EVOLUTION,
    )
    assert child.parent_id == primary.id
    assert child.parent_ids == [primary.id, partner.id]
    # The full parent list survives serialization round-trips (checkpoints).
    restored = Hypothesis.from_dict(child.to_dict())
    assert restored.parent_id == primary.id
    assert restored.parent_ids == [primary.id, partner.id]


def test_parent_ids_default_empty_and_legacy_payloads_load() -> None:
    """parent_ids defaults to empty; pre-lineage payloads still load."""
    assert Hypothesis(text="x").parent_ids == []
    legacy = Hypothesis(text="x").to_dict()
    legacy.pop("parent_ids")  # a cached payload from before the field
    assert Hypothesis.from_dict(legacy).parent_ids == []


# --- Hypothesis: computed properties ----------------------------------------


def test_total_matches_sums_wins_and_losses() -> None:
    """``total_matches`` is ``win_count + loss_count``."""
    hyp = Hypothesis(text="x", win_count=3, loss_count=2)
    assert hyp.total_matches == 5


def test_win_rate_with_matches() -> None:
    """``win_rate`` is a 0-100 percentage of wins over total matches."""
    hyp = Hypothesis(text="x", win_count=3, loss_count=1)
    assert hyp.win_rate == 75.0


def test_win_rate_zero_matches_guard() -> None:
    """No matches yields ``0.0`` win rate (no ZeroDivisionError)."""
    hyp = Hypothesis(text="x")
    assert hyp.total_matches == 0
    assert hyp.win_rate == 0.0


# --- Hypothesis: serialization ----------------------------------------------


def test_hypothesis_to_dict_shape_and_computed_fields() -> None:
    """``to_dict`` adds computed fields and omits ``similarity_degree``.

    The computed ``total_matches``/``win_rate`` properties are serialized while
    the ``similarity_degree`` field is intentionally left out.
    """
    hyp = Hypothesis(text="x", win_count=2, loss_count=2)
    d = hyp.to_dict()
    # Computed fields are serialized even though they are properties.
    assert d["total_matches"] == 4
    assert d["win_rate"] == 50.0
    # similarity_degree is a real field but is intentionally NOT serialized.
    assert "similarity_degree" not in d
    # Exact key set is part of the contract this regression net pins.
    assert set(d.keys()) == _HYPOTHESIS_DICT_KEYS


def test_hypothesis_to_dict_serializes_reviews() -> None:
    """Nested reviews are flattened to plain dicts inside ``to_dict``."""
    review = make_review()
    hyp = Hypothesis(text="x", reviews=[review])
    d = hyp.to_dict()
    assert len(d["reviews"]) == 1
    serialized = d["reviews"][0]
    assert serialized["review_summary"] == review.review_summary
    assert serialized["overall_score"] == review.overall_score
    assert serialized["scores"] == review.scores


# --- Hypothesis: equality and hashing ---------------------------------------


def test_hypothesis_equality_is_field_based() -> None:
    """Dataclass equality compares all fields; identical fields are equal."""
    a = Hypothesis(text="same", score=5.0)
    b = Hypothesis(text="same", score=5.0)
    c = Hypothesis(text="same", score=6.0)
    assert a == b
    assert a != c


def test_hypothesis_is_unhashable() -> None:
    """The dataclass is unhashable (eq=True, not frozen): ``hash`` raises."""
    with pytest.raises(TypeError):
        hash(Hypothesis(text="x"))


# --- Hypothesis: stable id --------------------------------------------------


def test_hypothesis_id_present_and_unique() -> None:
    """Each hypothesis gets a distinct, non-empty id on construction."""
    a = Hypothesis(text="x")
    b = Hypothesis(text="x")
    assert a.id
    assert b.id
    assert a.id != b.id


def test_hypothesis_id_excluded_from_equality() -> None:
    """``id`` is ``compare=False`` so it never affects dataclass equality.

    Two hypotheses with identical content but distinct ids remain equal, which
    keeps the text-based dedup heuristics unperturbed.
    """
    a = Hypothesis(text="same", score=5.0)
    b = Hypothesis(text="same", score=5.0)
    assert a.id != b.id
    assert a == b


def test_hypothesis_to_dict_includes_id() -> None:
    """``to_dict`` serializes the stable id."""
    hyp = Hypothesis(text="x")
    assert hyp.to_dict()["id"] == hyp.id


def test_hypothesis_from_dict_preserves_id() -> None:
    """``from_dict`` round-trips a provided id verbatim.

    Equality ignores id (``compare=False``), so the round-trip is asserted on
    the id value directly rather than via ``==``.
    """
    original = Hypothesis(text="x", win_count=2, loss_count=1)
    restored = Hypothesis.from_dict(original.to_dict())
    assert restored.id == original.id
    assert restored.text == original.text
    assert restored.win_count == 2
    assert restored.loss_count == 1


def test_hypothesis_category_round_trips() -> None:
    """``category`` serializes and reconstructs through to_dict/from_dict."""
    hyp = Hypothesis(text="x", category="Metabolic reprogramming")
    d = hyp.to_dict()
    assert d["category"] == "Metabolic reprogramming"
    restored = Hypothesis.from_dict(d)
    assert restored.category == "Metabolic reprogramming"


def test_hypothesis_lineage_round_trips() -> None:
    """Lineage fields serialize and reconstruct, with origin as its enum."""
    child = Hypothesis(
        text="child",
        parent_id="parent-123",
        generation=2,
        origin=HypothesisOrigin.EVOLUTION,
        creation_iteration=3,
    )
    d = child.to_dict()
    assert d["parent_id"] == "parent-123"
    assert d["generation"] == 2
    assert d["origin"] == "evolution"  # serialized as the enum value
    assert d["creation_iteration"] == 3
    restored = Hypothesis.from_dict(d)
    assert restored.parent_id == "parent-123"
    assert restored.generation == 2
    assert restored.origin is HypothesisOrigin.EVOLUTION
    assert restored.creation_iteration == 3


def test_hypothesis_from_dict_pre_lineage_payload_defaults() -> None:
    """A legacy cached payload without lineage keys deserializes to a root.

    Backward-compatibility guard: older caches predate the lineage fields, so
    ``from_dict`` must fill the generation-0 defaults rather than raising.
    """
    payload = Hypothesis(text="legacy").to_dict()
    for key in ("parent_id", "generation", "origin", "creation_iteration"):
        del payload[key]
    restored = Hypothesis.from_dict(payload)
    assert restored.parent_id is None
    assert restored.generation == 0
    assert restored.origin is HypothesisOrigin.GENERATION
    assert restored.creation_iteration is None


def test_hypothesis_from_dict_generates_id_when_absent() -> None:
    """A pre-id payload (no ``id`` key) reconstructs with a fresh id."""
    payload = Hypothesis(text="legacy").to_dict()
    del payload["id"]
    restored = Hypothesis.from_dict(payload)
    assert restored.id
    assert restored.text == "legacy"


def test_hypothesis_from_dict_restores_enum_and_reviews() -> None:
    """``from_dict`` rebuilds the enum and nested reviews so to_dict re-runs.

    A naive ``cls(**data)`` would leave ``generation_method`` as a str and
    ``reviews`` as dicts, crashing a subsequent ``to_dict``. This pins the
    round-trip through ``to_dict -> from_dict -> to_dict``.
    """
    hyp = Hypothesis(
        text="x",
        generation_method=GenerationMethod.DEBATE,
        reviews=[make_review()],
    )
    restored = Hypothesis.from_dict(hyp.to_dict())
    assert restored.generation_method == GenerationMethod.DEBATE
    assert isinstance(restored.reviews[0], HypothesisReview)
    # to_dict must not raise on the reconstructed object.
    assert restored.to_dict()["generation_method"] == "debate"


# --- Hypothesis: deep-verification fields -----------------------------------


def test_hypothesis_deep_verification_fields_default_empty() -> None:
    """A fresh hypothesis has no deep-verification probes or verdict."""
    h = Hypothesis(text="X inhibits Y")
    assert h.deep_verification_probes == []
    assert h.deep_verification_verdict is None


def test_hypothesis_to_dict_includes_deep_verification() -> None:
    """``to_dict`` serializes the deep-verification probes and verdict."""
    h = Hypothesis(text="X inhibits Y")
    h.deep_verification_probes = [
        {
            "question": "q",
            "answer": "a",
            "reasoning": "r",
            "assumption_is_fundamental": True,
        }
    ]
    h.deep_verification_verdict = "weakened"
    d = h.to_dict()
    assert d["deep_verification_probes"][0]["question"] == "q"
    assert d["deep_verification_verdict"] == "weakened"


# --- Hypothesis: review/verification summaries -------------------------------
#
# Prompt-ready projections shared by the ranking-matchup and evolution
# prompts (agents/ranking/ranking_debate_turns.py,
# agents/evolution/evolve_prompt.py, agents/evolution/evolve_context.py),
# which each read only the subset of
# fields they need from the result.


def test_review_summary_none_when_no_reviews() -> None:
    """A hypothesis with no reviews yields None, not a hollow dict."""
    hyp = Hypothesis(text="x")
    assert hyp.review_summary() is None


def test_review_summary_projects_latest_review() -> None:
    """The most recent review's fields are projected into a summary dict."""
    review = make_review(
        review_summary="Solid mechanism, weak controls.",
        scores={"novelty": 7, "rigor": 5},
        constructive_feedback="Add a dose-response arm.",
        overall_score=6.5,
    )
    hyp = Hypothesis(text="x", reviews=[review])
    assert hyp.review_summary() == {
        "overall_score": 6.5,
        "review_summary": "Solid mechanism, weak controls.",
        "constructive_feedback": "Add a dose-response arm.",
        "scores": {"novelty": 7, "rigor": 5},
    }


def test_review_summary_uses_the_latest_of_several_reviews() -> None:
    """With multiple reviews, only the most recent one is projected."""
    first = make_review(overall_score=3.0)
    second = make_review(overall_score=8.0)
    hyp = Hypothesis(text="x", reviews=[first, second])
    summary = hyp.review_summary()
    assert summary is not None
    assert summary["overall_score"] == 8.0


def test_deep_verification_summary_none_when_no_probes() -> None:
    """A hypothesis with no deep-verification probes yields None.

    None (rather than a dict of Nones/empties) lets a prompt builder drop
    the block entirely instead of shipping a hollow one -- the drift that
    used to separate this projection from evolution's own inline copy.
    """
    hyp = Hypothesis(text="x")
    assert hyp.deep_verification_summary() is None


def test_deep_verification_summary_returns_probes_and_verdict() -> None:
    """Populated probes/verdict are returned as a summary dict."""
    probes = [
        {
            "question": "does it hold under X?",
            "answer": "yes",
            "reasoning": "because Y",
            "assumption_is_fundamental": True,
        }
    ]
    hyp = Hypothesis(
        text="x",
        deep_verification_probes=probes,
        deep_verification_verdict="holds",
    )
    assert hyp.deep_verification_summary() == {
        "probes": probes,
        "verdict": "holds",
    }
