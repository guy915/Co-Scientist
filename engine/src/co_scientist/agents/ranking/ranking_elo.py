"""Elo rating math and match-tier classification for the ranking node."""

from co_scientist.constants import (
    # ELO_K_FACTOR bounds how much a single matchup can move a rating;
    # ELO_UPSET_MARGIN is the pre-match gap that makes a win an "upset".
    ELO_K_FACTOR,
    ELO_UPSET_MARGIN,
)

# The K-annealing and margin-scaling knobs are local reconstruction choices
# (paper-unspecified; see constants.tournament for each one's rationale).
# Imported from their home module rather than the constants re-export so the
# tournament-shaping values stay the sole subject of that file.
from co_scientist.constants.tournament import (
    ELO_K_ANNEALED_MINIMUM,
    ELO_K_ANNEALING_HALF_LIFE,
    ELO_MARGIN_MULTIPLIER_CAP,
    ELO_MARGIN_VICTORY_SCALE,
)

# Judge confidence levels mapped to a fraction of a full victory margin.
# The judge reports a verdict plus confidence rather than scores, so this is
# the margin-of-victory reconstruction's signal (see ELO_MARGIN_VICTORY_SCALE
# in constants.tournament). Unrecognized values score no margin at all.
_CONFIDENCE_MARGINS = {"high": 1.0, "medium": 0.5}


def annealed_k_factor(
    base_k_factor: int,
    matches_played: int,
    half_life: int | None = None,
) -> int:
    """Return a hypothesis's annealed K-factor from its career match count.

    Local reconstruction choice (paper-unspecified): the reference corpus
    documents a per-hypothesis phase schedule in which K shrinks as a
    hypothesis accumulates matches. This reconstruction halves K once per
    ``half_life`` matches already played, floored so a rating never fully
    freezes. Defaults to the fixed ``base_k_factor`` -- 0 (or a negative)
    half-life disables annealing entirely, preserving historical ratings.

    Args:
        base_k_factor: The run's configured K-factor (the value annealing
            decays from).
        matches_played: Career matches the hypothesis played before this
            match (its win + loss record).
        half_life: Matches per halving; None reads the module constant.

    Returns:
        The effective K-factor for this side of the matchup, at least
        ``ELO_K_ANNEALED_MINIMUM`` when annealing is active.
    """
    if half_life is None:
        half_life = ELO_K_ANNEALING_HALF_LIFE
    if half_life <= 0 or matches_played <= 0:
        return base_k_factor
    halvings = matches_played // half_life
    annealed = base_k_factor / (2**halvings)
    return max(ELO_K_ANNEALED_MINIMUM, int(annealed))


def margin_scaled_k_factor(
    base_k_factor: int,
    confidence: str | None,
    scale: float | None = None,
) -> int:
    """Scale a K-factor by how decisive the judge called its verdict.

    Local reconstruction choice (paper-unspecified): the reference corpus
    scales K by the victory margin between the sides. This tournament's
    judge reports confidence instead of scores, so the margin is mapped from
    confidence (High full, Medium half, otherwise none) and K grows by
    ``scale * margin`` times the base, capped at ``ELO_MARGIN_MULTIPLIER_CAP``
    times it. Defaults to the fixed ``base_k_factor`` -- a 0.0 (or negative)
    scale disables the scaling entirely, preserving historical ratings.

    Args:
        base_k_factor: The K-factor to scale (typically the annealed one).
        confidence: The judge's confidence level for the verdict, if any.
        scale: Margin-of-victory sensitivity; None reads the module
            constant.

    Returns:
        The margin-scaled K-factor, never below ``base_k_factor``.
    """
    if scale is None:
        scale = ELO_MARGIN_VICTORY_SCALE
    if scale <= 0 or not confidence:
        return base_k_factor
    margin = _CONFIDENCE_MARGINS.get(confidence.strip().lower(), 0.0)
    if margin <= 0:
        return base_k_factor
    multiplier = min(ELO_MARGIN_MULTIPLIER_CAP, 1.0 + scale * margin)
    return int(base_k_factor * multiplier)


def effective_k_factor(
    base_k_factor: int,
    matches_played: int,
    confidence: str | None = None,
) -> int:
    """Return one side's effective K for a match: annealed, then scaled.

    Composes the two local reconstruction knobs (both off by default, so the
    result is exactly ``base_k_factor`` unless a deployment opts in).
    Annealing goes first: it models how calibrated the hypothesis's rating
    already is; the margin multiplier then expresses how decisive this
    particular verdict was.

    Args:
        base_k_factor: The run's configured K-factor.
        matches_played: Career matches this side played before the match.
        confidence: The judge's confidence level for the verdict, if any.

    Returns:
        The K-factor this side's rating update is scaled by.
    """
    annealed = annealed_k_factor(base_k_factor, matches_played)
    return margin_scaled_k_factor(annealed, confidence)


def calculate_elo_update(
    winner_elo: int,
    loser_elo: int,
    k_factor: int = ELO_K_FACTOR,
    *,
    loser_k_factor: int | None = None,
) -> tuple[int, int]:
    """Calculates updated Elo ratings for winner and loser.

    Args:
        winner_elo: Current Elo rating of winner
        loser_elo: Current Elo rating of loser
        k_factor: K-factor for Elo calculation (default 24)
        loser_k_factor: Optional distinct K-factor for the loser's update.
            Defaults to ``k_factor``: one shared K is the historical
            behavior. A distinct value lets a per-side schedule (K-factor
            annealing) weight the two updates differently; with the two
            K-factors apart, the update is no longer exactly point-
            conserving before truncation.

    Returns:
        Tuple of (new_winner_elo, new_loser_elo)
    """
    loser_k = k_factor if loser_k_factor is None else loser_k_factor
    # Calculate expected scores
    # Standard Elo expected-score formula: each side's probability of
    # winning given the current rating gap, on the logistic curve with a
    # 400-point scale (a 400-point gap implies a 10x win-odds ratio). The
    # two expected scores always sum to 1.
    expected_winner = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_elo - loser_elo) / 400))

    # Calculate new ratings
    # Rating update: actual score (1 for the winner, 0 for the loser) minus
    # expected score, scaled by k_factor. An upset (low-rated hypothesis
    # beats a high-rated one) has expected_winner near 0, so the winner
    # gains close to the full k_factor; an expected win moves ratings only
    # slightly.
    new_winner_elo = winner_elo + k_factor * (1 - expected_winner)
    new_loser_elo = loser_elo + loser_k * (0 - expected_loser)

    return int(new_winner_elo), int(new_loser_elo)


def match_tier(
    winner_elo_before: int, loser_elo_before: int, confidence: str
) -> str:
    """Classifies how decisive a judged matchup was.

    Derived deterministically (no extra LLM call) from the pre-match Elo gap
    and the judge's stated confidence, mirroring the reference product's
    per-match ``tier`` label in "Performance against other ideas".

    Args:
        winner_elo_before: Winner's Elo rating before the match.
        loser_elo_before: Loser's Elo rating before the match.
        confidence: Judge confidence level ("High"/"Medium"/"Low").

    Returns:
        One of "upset" (a lower-rated hypothesis won), "decisive",
        "clear", or "narrow".
    """
    # "upset" takes priority over the confidence-based tiers below: if the
    # loser was already rated at least ELO_UPSET_MARGIN points above the
    # winner, the outcome is surprising regardless of how confident the
    # judge was.
    if loser_elo_before - winner_elo_before >= ELO_UPSET_MARGIN:
        return "upset"
    # Otherwise the tier reflects how confident the LLM judge was in its
    # verdict; unrecognized/missing confidence values fall through to
    # "narrow" (the least decisive tier) rather than erroring.
    normalized = confidence.strip().lower()
    if normalized == "high":
        return "decisive"
    if normalized == "medium":
        return "clear"
    return "narrow"
