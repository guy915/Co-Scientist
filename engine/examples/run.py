"""Minimal interactive demo for the Co-Scientist hypothesis generator.

Prompts for a research goal, runs ``HypothesisGenerator`` with literature
review and tool-calling generation enabled, then prints the ranked
hypotheses and the synthesized research overview using plain ``print``.

Prerequisites:
    - An MCP server running (default http://localhost:8888/mcp) for the
      literature review and tool-calling generation steps. Without one
      the engine falls back to LLM-only mode.
    - The provider API key for ``MODEL_NAME`` set in the environment (for
      example GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY).
"""
import asyncio
from typing import Any

from co_scientist import HypothesisGenerator

MODEL_NAME = "gemini/gemini-2.5-flash"


async def _report_progress(phase: str, data: dict[str, Any]) -> None:
    """Print a one-line progress update for a workflow phase.

    Args:
        phase: Name of the workflow phase emitting the update.
        data: Payload dict; a human-readable string is read from
            ``data['message']`` when present.
    """
    message = data.get("message", "")
    if message:
        print(f"  [{phase}] {message}")


async def _run() -> None:
    """Prompt for a research goal, run the workflow, and print results."""
    research_goal = input("Enter a research goal: ").strip()
    if not research_goal:
        print("Error: research goal cannot be empty.")
        return

    generator = HypothesisGenerator(
        model_name=MODEL_NAME,
        max_iterations=2,
        initial_hypotheses_count=7,
        evolution_max_count=4,
    )

    result = await generator.generate_hypotheses(
        research_goal=research_goal,
        progress_callback=_report_progress,
        opts={
            "enable_literature_review_node": True,
            "enable_tool_calling_generation": True,
        },
    )

    hypotheses = sorted(
        result.get("hypotheses", []),
        key=lambda h: h.get("elo_rating", 1200),
        reverse=True,
    )

    print()
    print("Ranked hypotheses")
    print("=================")
    for rank, hyp in enumerate(hypotheses, start=1):
        elo = hyp.get("elo_rating", 1200)
        print(f"\n{rank}. [Elo {elo}] {hyp.get('text', '')}")
        explanation = hyp.get("explanation")
        if explanation:
            print(f"   Summary: {explanation}")

    overview = result.get("research_overview", {}).get("overview", {})
    summary = overview.get("summary")
    if summary:
        print()
        print("Research overview")
        print("=================")
        print(summary)
        for direction in overview.get("research_directions", []):
            print(f"- {direction.get('title', '')}")


if __name__ == "__main__":
    asyncio.run(_run())
