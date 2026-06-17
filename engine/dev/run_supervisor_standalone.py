"""Test supervisor node in isolation.

Simplest node to test - no dependencies, just creates research plan.
"""
# pylint: disable=inconsistent-quotes

import asyncio
import json
from collections.abc import Sequence

from absl import app
from rich.console import Console
from rich.panel import Panel
from rich.json import JSON

from state_helpers import make_base_state
from co_scientist.nodes.supervisor import supervisor_node

console = Console()


async def test_supervisor() -> None:
    """Run supervisor node with minimal state."""

    console.print("\n[bold cyan]Testing supervisor node[/bold cyan]\n")

    # Create minimal state
    state = make_base_state(
        research_goal=
        "How can we detect Alzheimer's disease earlier using retinal imaging?",
        model_name="gemini/gemini-2.5-flash",
    )

    console.print(f"[yellow]Research goal:[/yellow] {state['research_goal']}\n")

    # Run node
    console.print("[yellow]Calling supervisor node...[/yellow]\n")
    result = await supervisor_node(state)

    # Display results
    guidance = result.get("supervisor_guidance", {})

    console.print(
        Panel(JSON(json.dumps(guidance, indent=2)),
              title="[bold green]Supervisor guidance output[/bold green]",
              border_style="green"))

    # Show what would be passed to next nodes
    console.print("\n[bold]Key fields for downstream nodes:[/bold]")
    n_approach = len(guidance.get('approach_description', ''))
    n_considerations = len(guidance.get('key_considerations', []))
    console.print(f"  approach_description: {n_approach} chars")
    console.print(f"  key_considerations: {n_considerations} items")
    console.print(
        f"  search_strategy: {len(guidance.get('search_strategy', {}))} keys")


def main(argv: Sequence[str]) -> None:
    del argv  # Unused.
    asyncio.run(test_supervisor())


if __name__ == "__main__":
    app.run(main)
