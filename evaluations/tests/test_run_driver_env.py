"""An offline sweep must be unable to spend money.

``configure_environment`` is what every driver calls before importing the
app, so it is the one place that can make "offline" mean offline for call
sites that never consult the flag. It did not, and the bill was invisible:
the claim assessor falls back to its deterministic twin on any provider
error, so a single offline ``make parity`` run made 177 real provider calls
and reported nothing until the account ran out of credit.
"""

from __future__ import annotations

import os

import pytest

from evaluations._run_driver import configure_environment


def test_an_offline_invocation_leaves_no_credential_to_spend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Credentials are removed, not merely unused.

    Asserted by suffix rather than against a list of provider names, the
    same way the code removes them: a hand-kept list of credentials is the
    thing that fell behind once already.
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-would-be-billed")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-would-be-billed")

    configure_environment("/tmp/db.sqlite", "/tmp/cache", live=False)

    assert [name for name in os.environ if name.endswith("_API_KEY")] == []
    assert os.environ["COSCIENTIST_FORCE_OFFLINE"] == "1"


def test_an_offline_invocation_disables_literature_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline evidence blocks every idea, so the node is switched off.

    Generated passages cannot support a generated claim under the
    deterministic assessor, so every idea is withheld and the run ends
    blocked before the report -- the stages a sweep exists to exercise. The
    app suite disables the node for the same reason.
    """
    monkeypatch.delenv("FORCE_LITERATURE_REVIEW", raising=False)

    configure_environment("/tmp/db.sqlite", "/tmp/cache", live=False)

    assert os.environ["FORCE_LITERATURE_REVIEW"] == "0"
