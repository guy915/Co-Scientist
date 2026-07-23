"""Advanced constructor options for :class:`HypothesisGenerator`.

The generator's four run-size knobs (``model_name``, ``max_iterations``,
``initial_hypotheses_count``, ``evolution_max_count``) stay as top-level
constructor arguments because almost every caller sets them and they are
what the app's run tiers scale. Every other knob -- the supervisor model,
Elo/tournament/literature tuning, caching, tool configuration, and the
scheduler budget -- is set only occasionally, so those are grouped here to
keep the constructor signature small without making the common call verbose.
"""

from dataclasses import dataclass, field
from typing import Any

from co_scientist.constants import ELO_K_FACTOR


@dataclass(frozen=True)
class GeneratorOptions:
    """Optional generator configuration beyond the core run-size knobs.

    Every field defaults to the generator's historical default, so
    ``GeneratorOptions()`` reproduces the old all-defaults constructor.

    Attributes:
        supervisor_model_name: Model for the supervisor and meta-review
            steps (None = use the generator's ``model_name``).
        tournament_pairs: Number of Elo tournament comparisons per ranking.
        elo_k_factor: Rating sensitivity applied to every committed match.
        literature_review_papers_count: Number of papers to read/analyze.
        enable_cache: Enable/disable LLM response caching for this
            generator's own calls (None = the process default from
            ``COSCIENTIST_CACHE_ENABLED``). Scoped to this generator's own
            execution via ``cache.scoped_cache_override`` rather than
            mutating that env var, so it never disables caching for another
            generator running in the same process.
        cache_dir: Directory for cache files (None = use default).
        tools_config: Path to custom tools YAML config file (None =
            use defaults).
        disable_tools: Tool IDs to disable (None = use all enabled tools).
        budget: Optional serialized ``scheduling.Budget`` (keys
            ``max_iterations``/``max_llm_calls``/``max_tasks``/
            ``max_wall_clock_s``) giving the adaptive scheduler hard
            termination ceilings beyond ``max_iterations``. None derives a
            budget from ``max_iterations`` alone.
    """

    supervisor_model_name: str | None = None
    tournament_pairs: int = 12
    elo_k_factor: int = ELO_K_FACTOR
    literature_review_papers_count: int = 8
    enable_cache: bool | None = None
    cache_dir: str | None = None
    tools_config: str | None = None
    disable_tools: list[str] | None = None
    budget: dict[str, Any] | None = field(default=None)
