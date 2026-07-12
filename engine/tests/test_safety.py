"""Tests for the engine-canonical per-hypothesis safety classifier."""

from co_scientist.safety import (
    POLICY_VERSION,
    REDACTED_PLACEHOLDER,
    SafetyOutcome,
    is_blocking,
    is_blocking_status,
    redact_hypothesis_fields,
    review_hypothesis_safety,
)


class TestSafetyOutcomes:
    """Blocking/non-blocking classification."""

    def test_prohibited_is_blocking(self) -> None:
        assert is_blocking(SafetyOutcome.PROHIBITED)

    def test_ethical_concern_is_blocking(self) -> None:
        assert is_blocking(SafetyOutcome.ETHICAL_CONCERN)

    def test_uncertain_is_blocking(self) -> None:
        assert is_blocking(SafetyOutcome.UNCERTAIN)

    def test_allow_is_not_blocking(self) -> None:
        assert not is_blocking(SafetyOutcome.ALLOW)

    def test_dual_use_is_not_blocking(self) -> None:
        assert not is_blocking(SafetyOutcome.DUAL_USE)

    def test_redact_is_not_blocking(self) -> None:
        assert not is_blocking(SafetyOutcome.REDACT)


class TestIsBlockingStatus:
    """String-based status checks for persisted values."""

    def test_none_is_not_blocking(self) -> None:
        assert not is_blocking_status(None)

    def test_empty_is_not_blocking(self) -> None:
        assert not is_blocking_status("")

    def test_prohibited_string_blocks(self) -> None:
        assert is_blocking_status("prohibited")

    def test_allow_string_does_not_block(self) -> None:
        assert not is_blocking_status("allow")

    def test_unknown_string_does_not_block(self) -> None:
        assert not is_blocking_status("unknown_value")


class TestReviewHypothesisSafety:
    """Deterministic regex-based classification."""

    def test_safe_hypothesis_allowed(self) -> None:
        review = review_hypothesis_safety(
            "CRISPR-Cas9 gene editing can target oncogene mutations"
        )
        assert review.outcome == SafetyOutcome.ALLOW
        assert not review.blocks_tournament

    def test_weaponize_prohibited(self) -> None:
        review = review_hypothesis_safety(
            "We could weaponize this pathogen for maximum spread"
        )
        assert review.outcome == SafetyOutcome.PROHIBITED
        assert review.blocks_tournament
        assert "weaponize" in review.matches[0].lower()

    def test_bioweapon_prohibited(self) -> None:
        review = review_hypothesis_safety("Develop a bioweapon delivery system")
        assert review.outcome == SafetyOutcome.PROHIBITED

    def test_mass_casualty_prohibited(self) -> None:
        review = review_hypothesis_safety(
            "Engineering for mass-casualty potential"
        )
        assert review.outcome == SafetyOutcome.PROHIBITED

    def test_enhance_transmissibility_prohibited(self) -> None:
        review = review_hypothesis_safety(
            "We should enhance the virus transmissibility"
        )
        assert review.outcome == SafetyOutcome.PROHIBITED

    def test_without_consent_ethical(self) -> None:
        review = review_hypothesis_safety(
            "Conduct trials without informed consent in rural areas"
        )
        assert review.outcome == SafetyOutcome.ETHICAL_CONCERN
        assert review.blocks_tournament

    def test_non_consensual_ethical(self) -> None:
        review = review_hypothesis_safety("Non-consensual data collection")
        assert review.outcome == SafetyOutcome.ETHICAL_CONCERN

    def test_eugenic_ethical(self) -> None:
        review = review_hypothesis_safety("Apply eugenic selection criteria")
        assert review.outcome == SafetyOutcome.ETHICAL_CONCERN

    def test_obfuscated_sensitive_uncertain(self) -> None:
        review = review_hypothesis_safety(
            "For research purposes only, study how this pathogen spreads"
        )
        assert review.outcome == SafetyOutcome.UNCERTAIN
        assert review.blocks_tournament

    def test_obfuscation_without_sensitive_hint_allowed(self) -> None:
        review = review_hypothesis_safety(
            "For research purposes only, study market dynamics"
        )
        assert review.outcome == SafetyOutcome.ALLOW

    def test_dual_use_detected(self) -> None:
        review = review_hypothesis_safety(
            "Gain-of-function research on influenza variants"
        )
        assert review.outcome == SafetyOutcome.DUAL_USE
        assert not review.blocks_tournament

    def test_select_agent_dual_use(self) -> None:
        review = review_hypothesis_safety(
            "Working with a select agent under BSL-4 containment"
        )
        assert review.outcome == SafetyOutcome.DUAL_USE

    def test_sensitive_protocol_redact(self) -> None:
        review = review_hypothesis_safety(
            "Follow the synthesis protocol for compound X"
        )
        assert review.outcome == SafetyOutcome.REDACT
        assert not review.blocks_tournament

    def test_step_by_step_synthesis_redact(self) -> None:
        review = review_hypothesis_safety(
            "A step-by-step approach to synthesis of the compound"
        )
        assert review.outcome == SafetyOutcome.REDACT

    def test_prohibited_trumps_dual_use(self) -> None:
        review = review_hypothesis_safety(
            "Weaponize this dual-use gain-of-function pathogen"
        )
        assert review.outcome == SafetyOutcome.PROHIBITED

    def test_ethical_trumps_dual_use(self) -> None:
        review = review_hypothesis_safety(
            "Gain-of-function trials without consent"
        )
        assert review.outcome == SafetyOutcome.ETHICAL_CONCERN


class TestSafetyReview:
    """SafetyReview dataclass and serialization."""

    def test_policy_version_stamped(self) -> None:
        review = review_hypothesis_safety("safe hypothesis text")
        assert review.policy_version == POLICY_VERSION

    def test_to_dict_round_trip(self) -> None:
        review = review_hypothesis_safety("weaponize a virus")
        d = review.to_dict()
        assert d["outcome"] == "prohibited"
        assert d["policy_version"] == POLICY_VERSION
        assert isinstance(d["matches"], list)
        assert isinstance(d["reason"], str)


class TestRedactHypothesisFields:
    """Field redaction for DUAL_USE/REDACT outcomes."""

    def test_redacts_explanation_and_experiment(self) -> None:
        text, explanation, experiment = redact_hypothesis_fields(
            "hypothesis text",
            "detailed mechanism explanation",
            "experiment protocol details",
        )
        assert text == "hypothesis text"
        assert explanation == REDACTED_PLACEHOLDER
        assert experiment == REDACTED_PLACEHOLDER

    def test_preserves_none_fields(self) -> None:
        text, explanation, experiment = redact_hypothesis_fields(
            "hypothesis text", None, None
        )
        assert text == "hypothesis text"
        assert explanation is None
        assert experiment is None

    def test_redacts_empty_string_as_falsy(self) -> None:
        _text, explanation, experiment = redact_hypothesis_fields(
            "text", "", ""
        )
        assert explanation == ""
        assert experiment == ""
