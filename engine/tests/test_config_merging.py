"""Tests for the raw-dict merge-strategy helpers in ``config.merging``.

``registry.py``'s ``ConfigRegistry`` exercises these helpers indirectly
while merging default/user/custom YAML overlays, but not every branch
(e.g. a "settings" block present without a nested "merge_strategy" key, or
a "settings" block on the user config only) is reached through that path.
These tests call the three pure classification helpers directly.
"""

from co_scientist.config.registry import (
    _both_dicts,
    _both_lists_to_extend,
    _determine_merge_strategy,
)

# --- _both_dicts -------------------------------------------------------


def test_both_dicts_true_when_both_are_dicts() -> None:
    """Two dict values are mergeable."""
    assert _both_dicts({"a": 1}, {"b": 2}) is True


def test_both_dicts_false_when_existing_is_not_a_dict() -> None:
    """A non-dict existing value is never mergeable, even with a dict."""
    assert _both_dicts([1, 2], {"a": 1}) is False


def test_both_dicts_false_when_value_is_not_a_dict() -> None:
    """A non-dict overlay value is never mergeable, even with a dict."""
    assert _both_dicts({"a": 1}, [1, 2]) is False


def test_both_dicts_false_when_neither_is_a_dict() -> None:
    """Two non-dict values are not mergeable."""
    assert _both_dicts("x", "y") is False


# --- _both_lists_to_extend -----------------------------------------------


def test_both_lists_to_extend_true_for_extend_strategy_and_lists() -> None:
    """Both lists under the "extend" strategy should be concatenated."""
    assert _both_lists_to_extend([1], [2], "extend") is True


def test_both_lists_to_extend_false_for_non_extend_strategy() -> None:
    """Lists under any other strategy are not extended by this helper."""
    assert _both_lists_to_extend([1], [2], "override") is False


def test_both_lists_to_extend_false_when_existing_is_not_a_list() -> None:
    """A non-list existing value blocks extension even under "extend"."""
    assert _both_lists_to_extend("a", [2], "extend") is False


def test_both_lists_to_extend_false_when_value_is_not_a_list() -> None:
    """A non-list overlay value blocks extension even under "extend"."""
    assert _both_lists_to_extend([1], "b", "extend") is False


# --- _determine_merge_strategy --------------------------------------------


def test_determine_merge_strategy_defaults_to_override_with_no_configs() -> (
    None
):
    """Absent user and custom configs fall back to "override"."""
    assert _determine_merge_strategy(None, None) == "override"


def test_determine_merge_strategy_neither_has_settings_key() -> None:
    """Configs present but without a "settings" key default to "override"."""
    assert _determine_merge_strategy({"foo": 1}, {"bar": 2}) == "override"


def test_determine_merge_strategy_uses_custom_settings_when_present() -> None:
    """A custom-only "settings" block sets the strategy."""
    custom = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(None, custom) == "extend"


def test_determine_merge_strategy_custom_wins_over_user() -> None:
    """When both declare a strategy, the custom config's choice wins."""
    user = {"settings": {"merge_strategy": "replace"}}
    custom = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(user, custom) == "extend"


def test_determine_merge_strategy_falls_back_to_user_settings() -> None:
    """With no custom config, the user config's "settings" block is used."""
    user = {"settings": {"merge_strategy": "extend"}}
    assert _determine_merge_strategy(user, None) == "extend"


def test_determine_merge_strategy_custom_without_settings_falls_to_user() -> (
    None
):
    """A custom config lacking "settings" falls through to the user's."""
    user = {"settings": {"merge_strategy": "extend"}}
    custom = {"other_key": True}
    assert _determine_merge_strategy(user, custom) == "extend"


def test_determine_merge_strategy_settings_present_without_merge_key() -> None:
    """A "settings" block with no "merge_strategy" key defaults to override."""
    custom: dict[str, dict[str, str]] = {"settings": {}}
    assert _determine_merge_strategy(None, custom) == "override"
