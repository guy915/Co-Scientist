"""Test generate node in isolation.

Depends on supervisor node output (will run supervisor first).
Optionally can test with literature review results.
"""

import asyncio
from collections.abc import Sequence
from typing import Any

from absl import app, flags
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from state_helpers import (
    DEFAULT_MODEL_NAME,
    DEFAULT_RESEARCH_GOAL,
    make_generate_state,
)

from co_scientist.models import Hypothesis
from co_scientist.nodes.generate import generate_node

console = Console()

FLAGS = flags.FLAGS

flags.DEFINE_bool(
    "with_literature", False, "Include mocked literature review data."
)


def _prepare_generate_state(with_literature: bool) -> dict:
    """Build state for the generate node, optionally with mocked literature.

    Args:
        with_literature: if True, includes mocked literature review data.

    Returns:
        Workflow state ready for the generate node.
    """
    console.print(
        "[yellow]Preparing state (running supervisor first)...[/yellow]"
    )
    state = make_generate_state(
        research_goal=DEFAULT_RESEARCH_GOAL,
        model_name=DEFAULT_MODEL_NAME,
        with_literature=with_literature,
    )

    if with_literature:
        console.print("[green]Using mocked literature review data[/green]")
    else:
        console.print("[yellow]No literature review data[/yellow]")

    return state


def _render_hypotheses_table(hypotheses: list[Hypothesis]) -> None:
    """Print a table summarizing the generated hypotheses.

    Args:
        hypotheses: hypotheses returned by the generate node.
    """
    hyp_table = Table(title=f"generated hypotheses ({len(hypotheses)} total)")
    hyp_table.add_column("id", style="cyan", width=10)
    hyp_table.add_column("hypothesis", style="white", max_width=60)
    hyp_table.add_column("generation_method", style="yellow", width=20)

    for hyp in hypotheses:
        hyp_table.add_row(
            hyp.id,
            hyp.text[:60] + "..." if len(hyp.text) > 60 else hyp.text,
            hyp.generation_method or "standard",
        )

    console.print(hyp_table)


def _show_first_hypothesis(hypotheses: list[Hypothesis]) -> None:
    """Print full detail for the first generated hypothesis, if any.

    Args:
        hypotheses: hypotheses returned by the generate node.
    """
    if not hypotheses:
        return

    first = hypotheses[0]
    console.print(
        Panel(
            Markdown(f"""
**hypothesis text:**
{first.text}

**rationale:**
{first.rationale}

**generation method:** {first.generation_method or "standard"}
"""),
            title="[bold green]first hypothesis details[/bold green]",
            border_style="green",
        )
    )


def _print_debate_info(debate_transcripts: list[dict[str, Any]]) -> None:
    """Print debate transcript counts, if any debates were recorded.

    Args:
        debate_transcripts: debate transcripts returned by the generate node.
    """
    if not debate_transcripts:
        return

    n_debates = len(debate_transcripts)
    n_turns = len(debate_transcripts[0].get("debate_turns", []))
    console.print(
        f"\n[bold]debate transcripts:[/bold] {n_debates} debates recorded"
    )
    console.print(f"  example debate turns: {n_turns} turns")


def _is_standard_method(hyp: Hypothesis) -> bool:
    """Check whether a hypothesis used the standard generation method.

    Args:
        hyp: a generated hypothesis.

    Returns:
        True if the hypothesis has no generation method or is 'standard'.
    """
    return not hyp.generation_method or hyp.generation_method == "standard"


def _tally_generation_methods(
    hypotheses: list[Hypothesis],
) -> tuple[int, int, int]:
    """Count hypotheses by generation method.

    Args:
        hypotheses: hypotheses returned by the generate node.

    Returns:
        Tuple of (debate_count, literature_count, standard_count).
    """
    n_debate = 0
    n_lit = 0
    n_std = 0
    for h in hypotheses:
        if h.generation_method == "debate":
            n_debate += 1
        if h.generation_method == "literature":
            n_lit += 1
        if _is_standard_method(h):
            n_std += 1
    return n_debate, n_lit, n_std


def _print_summary_stats(hypotheses: list[Hypothesis]) -> None:
    """Print aggregate hypothesis-generation stats.

    Args:
        hypotheses: hypotheses returned by the generate node.
    """
    n_debate, n_lit, n_std = _tally_generation_methods(hypotheses)
    console.print("\n[bold]summary stats:[/bold]")
    console.print(f"  hypotheses generated: {len(hypotheses)}")
    console.print(f"  debate-based: {n_debate}")
    console.print(f"  literature-based: {n_lit}")
    console.print(f"  standard: {n_std}")


async def test_generate(with_literature: bool = False):
    """Run generate node with minimal state.

    Args:
        with_literature: if True, includes mocked literature review data
    """
    console.print("\n[bold cyan]Testing generate node[/bold cyan]\n")

    state = _prepare_generate_state(with_literature)

    console.print(f"\n[yellow]research goal:[/yellow] {state['research_goal']}")
    n_hyps = state["initial_hypotheses_count"]
    console.print(f"[yellow]hypotheses to generate:[/yellow] {n_hyps}\n")

    # run node
    console.print(
        "[yellow]calling generate node"
        " (this may take 1-2 minutes)...[/yellow]\n"
    )
    result = await generate_node(state)

    hypotheses = result.get("hypotheses", [])
    debate_transcripts = result.get("debate_transcripts", [])

    _render_hypotheses_table(hypotheses)
    _show_first_hypothesis(hypotheses)
    _print_debate_info(debate_transcripts)
    _print_summary_stats(hypotheses)


def main(argv: Sequence[str]) -> None:
    del argv  # Unused.
    asyncio.run(test_generate(with_literature=FLAGS.with_literature))


if __name__ == "__main__":
    app.run(main)
