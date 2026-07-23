"""Test LLM caching functionality.

This script runs the same workflow twice to demonstrate cache speedup.
"""

import os
import sys
import time

# Allow running example without installing the package
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")),
)

import asyncio
from collections.abc import Sequence

from absl import app

from co_scientist import (
    GeneratorOptions,
    HypothesisGenerator,
    clear_cache,
    get_cache_stats,
)


async def run_generation():
    """Run a simple generation to test caching."""
    generator = HypothesisGenerator(
        model_name="gemini/gemini-2.5-flash",
        max_iterations=0,
        # No iterations for faster testing
        initial_hypotheses_count=3,
        evolution_max_count=2,
        # Explicitly enable cache,
        options=GeneratorOptions(
            enable_cache=True,
        ),
    )

    research_goal = (
        "Develop novel approaches for early detection of Alzheimer's disease"
    )

    print(f"Research goal: {research_goal}\n")

    start = time.time()
    result = await generator.generate_hypotheses(research_goal=research_goal)
    elapsed = time.time() - start

    print(f"Generated {len(result['hypotheses'])} hypotheses in {elapsed:.2f}s")
    print(f"LLM calls: {result['metrics']['llm_calls']}")

    return elapsed


async def _timed_generation_run(label: str) -> tuple[float, dict]:
    """Run one generation, print its cache use, return timing and stats."""
    print(label)
    print("-" * 70)
    elapsed = await run_generation()
    stats = get_cache_stats()
    n = stats["cache_files"]
    mb = stats["total_size_mb"]
    print(f"Cache now: {n} files ({mb:.2f} MB)\n")
    return elapsed, stats


async def _run() -> None:
    """Run the cold/warm cache benchmark and print timing results."""
    print("=" * 70)
    print("Testing LLM Cache Performance")
    print("=" * 70)
    print()

    cleared = clear_cache()
    print(f"Cleared {cleared} cached responses\n")

    time1, _ = await _timed_generation_run("RUN 1: Cold cache (all LLM calls)")
    time2, stats2 = await _timed_generation_run(
        "RUN 2: Warm cache (should be much faster)"
    )

    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    speedup = time1 / time2 if time2 > 0 else 1
    print(f"First run:  {time1:.2f}s (cold cache)")
    print(f"Second run: {time2:.2f}s (warm cache)")
    print(f"Speedup:    {speedup:.1f}x faster")
    print()
    print(f"Cache directory: {stats2['cache_dir']}")
    print(
        f"Cache size:      {stats2['total_size_mb']:.2f} MB "
        f"({stats2['cache_files']} files)"
    )


def main(argv: Sequence[str]) -> None:
    del argv  # Unused.
    asyncio.run(_run())


if __name__ == "__main__":
    app.run(main)
