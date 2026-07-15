"""Safety screen (cross-cutting).

Safety is not one of Google's six agents but a cross-cutting concern that
screens research goals and hypotheses at intake, per hypothesis, and at final
output. In this engine the per-hypothesis screen runs as the durable graph node
``safety_screen`` (the intake and final-output gates live in the app viewer's
``safety`` module). This module exposes the node for completeness; see
``co_scientist.agents`` for the six-agent model it complements.
"""

from co_scientist.nodes.safety_screen import safety_screen_node

__all__ = ["safety_screen_node"]
