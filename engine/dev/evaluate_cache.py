"""Test LLM caching functionality.

This script runs the same workflow twice to demonstrate cache speedup.
"""
# pylint: disable=inconsistent-quotes

import os
import sys
import time

# Allow running example without installing the package
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")),
)

# pylint: disable=wrong-import-position
import asyncio
from collections.abc import Sequence

from absl import app
from co_scientist import HypothesisGenerator, clear_cache, get_cache_stats


# pylint: enable=wrong-import-position
async def run_generation():
    """Run a simple generation to test caching."""
    generator = HypothesisGenerator(
        model_name="gemini/gemini-2.5-flash",
        max_iterations=0,  # No iterations for faster testing
        initial_hypotheses_count=3,
        evolution_max_count=2,
        enable_cache=True,  # Explicitly enable cache
    )

    research_goal = (
        "Develop novel approaches for early detection of Alzheimer's disease")

    print(f"Research goal: {research_goal}\n")

    start = time.time()
    result = await generator.generate_hypotheses(research_goal=research_goal)
    elapsed = time.time() - start

    print(f"Generated {len(result['hypotheses'])} hypotheses in {elapsed:.2f}s")
    print(f"LLM calls: {result['metrics']['llm_calls']}")

    return elapsed


async def _run() -> None:
    print("=" * 70)
    print("Testing LLM Cache Performance")
    print("=" * 70)
    print()

    # Clear cache to start fresh
    cleared = clear_cache()
    print(f"Cleared {cleared} cached responses\n")

    # First run (cold cache)
    print("RUN 1: Cold cache (all LLM calls)")
    print("-" * 70)
    time1 = await run_generation()
    stats1 = get_cache_stats()
    n1 = stats1['cache_files']
    mb1 = stats1['total_size_mb']
    print(f"Cache after run 1: {n1} files ({mb1:.2f} MB)")
    print()

    # Second run (warm cache)
    print("RUN 2: Warm cache (should be much faster)")
    print("-" * 70)
    time2 = await run_generation()
    stats2 = get_cache_stats()
    n2 = stats2['cache_files']
    mb2 = stats2['total_size_mb']
    print(f"Cache after run 2: {n2} files ({mb2:.2f} MB)")
    print()

    # Results
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    speedup = time1 / time2 if time2 > 0 else 1
    print(f"First run:  {time1:.2f}s (cold cache)")
    print(f"Second run: {time2:.2f}s (warm cache)")
    print(f"Speedup:    {speedup:.1f}x faster")
    print()
    print(f"Cache directory: {stats2['cache_dir']}")
    print(f"Cache size:      {mb2:.2f} MB ({n2} files)")


def main(argv: Sequence[str]) -> None:
    del argv  # Unused.
    asyncio.run(_run())


if __name__ == "__main__":
    app.run(main)
