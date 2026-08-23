"""``run_setup._resolve_overview_review`` gates the overview review.

Opt-in, and refused for the offline backend: the offline responder
answers every schema-constrained call deterministically, so reviewing
its output would check nothing real. Mirrors
``test_reflection_simulation_execution.py``'s resolution tests for
``_resolve_simulation_execution``.
"""

from co_scientist.generator import run_setup


def test_offline_backend_runs_no_review_at_all() -> None:
    assert (
        run_setup._resolve_overview_review(
            {"enable_overview_review": True}, "offline/deterministic"
        )
        is False
    )


def test_a_real_model_asked_for_may_review() -> None:
    assert (
        run_setup._resolve_overview_review(
            {"enable_overview_review": True}, "deepseek/some-model"
        )
        is True
    )


def test_an_omitted_option_is_not_a_request() -> None:
    assert (
        run_setup._resolve_overview_review({}, "deepseek/some-model") is False
    )
