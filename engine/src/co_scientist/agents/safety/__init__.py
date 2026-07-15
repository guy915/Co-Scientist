"""Safety screen (cross-cutting).

Safety is not one of Google's six agents but a cross-cutting concern that
screens research goals and hypotheses at intake, per hypothesis, and at final
output. In this engine the per-hypothesis screen runs as the durable graph node
``safety_screen`` (the intake and final-output gates live in the app viewer's
``safety`` module); its key string is preserved. See ``co_scientist.agents``
for the six-agent model it complements.
"""

from co_scientist.agents.safety.safety_screen import safety_screen_node

__all__ = ["safety_screen_node"]
