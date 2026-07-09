"""Test generate node with lit tools in isolation mode.

this script enables dev isolation mode which:
1. forces cache on lit review node (fast, no mcp calls)
2. allocates all hypotheses to lit tools generation (no debate)
3. skips generate node cache (see real tool-based output)

useful for debugging the two-phase tool-based generation without
distraction from debate output or slow lit review calls.
"""
# pylint: disable=inconsistent-quotes

import asyncio
import os
from collections.abc import Sequence

from absl import app
from absl import flags
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from state_helpers import (make_supervisor_state, DEFAULT_RESEARCH_GOAL,
                           DEFAULT_MODEL_NAME)
from co_scientist.models import Hypothesis
from co_scientist.nodes.literature_review import literature_review_node
from co_scientist.nodes.generate import generate_node

console = Console()

FLAGS = flags.FLAGS

flags.DEFINE_string("model", DEFAULT_MODEL_NAME, "LLM model to use.")
flags.DEFINE_integer("count", 3, "Number of hypotheses to generate.")


def _prepare_isolation_state(research_goal: str, model_name: str,
                             hypotheses_count: int) -> dict:
    """Build supervisor state configured for lit-tools isolation testing.

    Args:
        research_goal: research question.
        model_name: llm model to use.
        hypotheses_count: number of hypotheses to generate.

    Returns:
        Workflow state ready for the literature review and generate nodes.
    """
    # disable global cache so we see fresh generate output
    os.environ["COSCIENTIST_CACHE_ENABLED"] = "false"
    console.print("[yellow]global cache disabled"
                  " (will see fresh generate output)[/yellow]")

    # create base state with supervisor
    console.print(
        "[yellow]preparing state (running supervisor first)...[/yellow]")
    state = make_supervisor_state(research_goal=research_goal,
                                  model_name=model_name)
    state["initial_hypotheses_count"] = hypotheses_count

    # enable lit tools generation
    state["enable_tool_calling_generation"] = True
    console.print("[green]enabled: tool_calling_generation=True[/green]")

    # enable dev isolation mode (force lit review cache + no debate)
    state["dev_test_lit_tools_isolation"] = True
    console.print("[green]enabled: dev_test_lit_tools_isolation=True[/green]")
    console.print("  - lit review will use cache (fast)")
    console.print("  - all hypotheses allocated to lit tools (no debate)\n")

    return state


async def _run_lit_review_phase(state: dict) -> bool:
    """Run the literature review node and report whether it produced data.

    Args:
        state: workflow state, updated in place with the node's output.

    Returns:
        True if literature review data is available, False otherwise.
    """
    console.print(
        "[yellow]running literature review node (with forced cache)...[/yellow]"
    )
    lit_result = await literature_review_node(state)
    state.update(lit_result)

    if not state.get("articles_with_reasoning"):
        console.print("[red]error: no literature review data available[/red]")
        return False

    n_arts = len(state.get('articles', []))
    console.print(f"[green]literature review complete:"
                  f" {n_arts} articles found[/green]")
    return True


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
            hyp.generation_method or "unknown",
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
        Panel(Markdown(f"""
**hypothesis text:**
{first.text}

**justification:**
{first.justification or 'none'}

**literature review used:**
{first.literature_review_used or 'none'}

**novelty validation:**
{first.novelty_validation or 'none'}

**generation method:** {first.generation_method or 'unknown'}
"""),
              title="[bold green]first hypothesis details[/bold green]",
              border_style="green"))


def _tally_generation_methods(hypotheses: list[Hypothesis]) -> tuple[int, int]:
    """Count hypotheses generated via lit tools vs. via debate.

    Args:
        hypotheses: hypotheses returned by the generate node.

    Returns:
        Tuple of (lit_tools_count, debate_count).
    """
    lit_tools_count = sum(
        1 for h in hypotheses if h.generation_method == "literature_tools")
    debate_count = sum(1 for h in hypotheses if h.generation_method == "debate")
    return lit_tools_count, debate_count


def _print_lit_tools_summary(hypotheses: list[Hypothesis]) -> None:
    """Print summary stats and validate all hypotheses used lit tools.

    Args:
        hypotheses: hypotheses returned by the generate node.
    """
    lit_tools_count, debate_count = _tally_generation_methods(hypotheses)

    console.print("\n[bold]summary stats:[/bold]")
    console.print(f"  hypotheses generated: {len(hypotheses)}")
    console.print(f"  lit tools: {lit_tools_count}")
    console.print(f"  debate: {debate_count}")

    if debate_count > 0:
        console.print(f"\n[red]warning: expected 0 debate hypotheses in"
                      f" isolation mode, got {debate_count}[/red]")
    if lit_tools_count != len(hypotheses):
        n_total = len(hypotheses)
        console.print(f"[red]warning: expected all hypotheses to be lit_tools,"
                      f" got {lit_tools_count}/{n_total}[/red]")

    if lit_tools_count == len(hypotheses):
        console.print("\n[bold green]success: all hypotheses generated"
                      " with lit tools![/bold green]")


async def test_lit_tools_isolation(research_goal: str,
                                   model_name: str,
                                   hypotheses_count: int = 3):
    """Run generate node with lit tools in isolation mode.

    args:
        research_goal: research question
        model_name: llm model to use
        hypotheses_count: number of hypotheses to generate
    """

    console.print("\n[bold cyan]testing generate node with lit tools"
                  " (isolation mode)[/bold cyan]\n")

    state = _prepare_isolation_state(research_goal, model_name,
                                     hypotheses_count)

    if not await _run_lit_review_phase(state):
        return

    console.print(f"\n[yellow]research goal:[/yellow] {state['research_goal']}")
    n_hyps = state['initial_hypotheses_count']
    console.print(f"[yellow]hypotheses to generate:[/yellow] {n_hyps}")
    console.print(f"[yellow]model:[/yellow] {state['model_name']}\n")

    # run generate node with lit tools
    console.print("[yellow]calling generate node with lit tools"
                  " (this may take 2-3 minutes)...[/yellow]")
    console.print("[dim]phase 1: draft hypotheses by reading papers[/dim]")
    console.print(
        "[dim]phase 2: validate novelty by searching literature[/dim]\n")

    result = await generate_node(state)
    hypotheses = result.get("hypotheses", [])

    _render_hypotheses_table(hypotheses)
    _show_first_hypothesis(hypotheses)
    _print_lit_tools_summary(hypotheses)


def main(argv: Sequence[str]) -> None:
    # absl strips flags, leaving the program name plus any positional args.
    # An optional positional argument overrides the default research goal.
    research_goal = argv[1] if len(argv) > 1 else DEFAULT_RESEARCH_GOAL

    asyncio.run(
        test_lit_tools_isolation(research_goal=research_goal,
                                 model_name=FLAGS.model,
                                 hypotheses_count=FLAGS.count))


if __name__ == "__main__":
    app.run(main)
