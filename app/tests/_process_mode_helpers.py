"""The test adapter for ``app.process_mode``.

``conftest.fake_process_mode`` installs one of these so a test states the
process fact it needs -- offline, or a credential for the model about to be
called -- once, instead of patching a wrapper in each consumer module.
"""

from __future__ import annotations

from collections.abc import Callable


class FakeProcessMode:
    """A process mode a test states outright, in place of the env-derived one.

    Starts as the suite's own posture (offline, no credential); a test lifts
    it with :meth:`online`. The facts are independent knobs, not derived from
    each other the way the production adapter derives them: a test can ask for
    "online, but nothing credentialed for this model", the shape of a
    partially configured deployment.
    """

    def __init__(self) -> None:
        self.offline = True
        self.credential: bool | Callable[[str], bool] = False

    def online(
        self, *, credential: bool | Callable[[str], bool] = True
    ) -> None:
        """Lift the offline pin, optionally choosing what is credentialed.

        Args:
            credential: ``True``/``False`` answers every model alike; a
                callable is asked per model, which lets a test record or vary
                the models the code under test checks.
        """
        self.offline = False
        self.credential = credential

    def is_offline(self) -> bool:
        return self.offline

    def credential_available(self, model: str) -> bool:
        if callable(self.credential):
            return self.credential(model)
        return self.credential
