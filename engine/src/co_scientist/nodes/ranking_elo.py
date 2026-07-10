"""Elo rating math and match-tier classification for the ranking node."""

from co_scientist.constants import (
    # ELO_K_FACTOR bounds how much a single matchup can move a rating;
    # ELO_UPSET_MARGIN is the pre-match gap that makes a win an "upset".
    ELO_K_FACTOR,
    ELO_UPSET_MARGIN,
)


def calculate_elo_update(
    winner_elo: int, loser_elo: int, k_factor: int = ELO_K_FACTOR
) -> tuple[int, int]:
    """Calculates updated Elo ratings for winner and loser.

    Args:
        winner_elo: Current Elo rating of winner
        loser_elo: Current Elo rating of loser
        k_factor: K-factor for Elo calculation (default 24)

    Returns:
        Tuple of (new_winner_elo, new_loser_elo)
    """
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
    new_loser_elo = loser_elo + k_factor * (0 - expected_loser)

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
