"""Safety screen and monitor (cross-cutting).

Safety is not one of Google's six agents but a cross-cutting concern that
screens research goals and hypotheses at intake, per hypothesis, and at final
output. In this engine the per-hypothesis screen runs as the durable graph node
``safety_screen`` (the intake and final-output gates live in the app viewer's
``safety`` module); its key string is preserved. See ``co_scientist.agents``
for the six-agent model it complements.

Alongside the screen, ``safety_monitor`` watches the run itself: it reads
each meta-review synthesis and halts a run whose direction reaches
prohibited content, rather than letting it work to the end and be withheld
at the final gate. It is a helper of the meta-review node, not a node.
"""

from co_scientist.agents.safety.safety_monitor import (
    monitor_research_direction,
)
from co_scientist.agents.safety.safety_screen import safety_screen_node

__all__ = ["monitor_research_direction", "safety_screen_node"]
