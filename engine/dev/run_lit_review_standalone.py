"""Test literature review node in isolation.

Requires:
- MCP server running (provides PubMed and other tools)
- GEMINI_API_KEY env var (for LLM calls)

Set COSCIENTIST_DEV_MODE=true for faster testing with reduced paper counts.

Create a .env file in this directory (dev/) with your API keys:
  GEMINI_API_KEY=your_key
  MCP_SERVER_URL=http://localhost:8888/mcp  (or your MCP server URL)
"""
# pylint: disable=inconsistent-quotes

import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

from absl import app
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Load .env file from dev/ directory if it exists
console = Console()

try:
    from dotenv import load_dotenv

    dev_dir = Path(__file__).parent
    env_file = dev_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        console.print(f"[dim]Loaded environment from {env_file}[/dim]")
    else:
        console.print(
            f"[dim]No .env file found at {env_file},"
            " using system environment variables[/dim]"
        )
except ImportError:
    console.print(
        "[dim]python-dotenv not installed,"
        " using system environment variables only[/dim]"
    )

# pylint: disable=wrong-import-position
from state_helpers import (
    DEFAULT_MODEL_NAME,
    DEFAULT_RESEARCH_GOAL,
    make_base_state,
)

from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.mcp_client import (
    check_mcp_available,
    check_pubmed_available_via_mcp,
)
from co_scientist.models import Article
from co_scientist.nodes.literature_review import literature_review_node


# pylint: enable=wrong-import-position
async def _gather_prereqs() -> tuple[list[str], list[str], bool, bool]:
    """Check API key, MCP server, and PubMed availability.

    Returns:
        Tuple of (errors, warnings, mcp_ok, pubmed_ok).
    """
    errors = []
    warnings = []

    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        errors.append("GEMINI_API_KEY not set - required for LLM calls")
    else:
        console.print("[green]GEMINI_API_KEY found[/green]")

    mcp_ok = await check_mcp_available()
    if not mcp_ok:
        errors.append("MCP server not available")
    else:
        console.print("[green]MCP server available[/green]")

    pubmed_ok = await check_pubmed_available_via_mcp()
    if not pubmed_ok:
        warnings.append(
            "PubMed not available via MCP - PubMed search will be disabled"
        )
        console.print(
            "[yellow]PubMed not available via MCP - will be disabled[/yellow]"
        )
    else:
        console.print("[green]PubMed available via MCP[/green]")

    return errors, warnings, mcp_ok, pubmed_ok


def _report_prerequisite_issues(errors: list[str], warnings: list[str]) -> bool:
    """Print prerequisite errors/warnings and report whether to proceed.

    Args:
        errors: critical errors that should abort the run.
        warnings: non-fatal warnings to surface before proceeding.

    Returns:
        True if there are no critical errors, False otherwise.
    """
    if errors:
        console.print("\n[bold red]Critical errors detected:[/bold red]")
        for error in errors:
            console.print(f"  [red]{error}[/red]")
        console.print("\n[yellow]Fix these issues and try again[/yellow]")
        console.print(
            "[dim]Tip: create a .env file in dev/ directory"
            " with your API keys[/dim]"
        )
        return False

    if warnings:
        console.print("\n[bold yellow]Warnings:[/bold yellow]")
        for warning in warnings:
            console.print(f"  [yellow]{warning}[/yellow]")

    return True


async def _check_prerequisites() -> tuple[bool, bool] | None:
    """Verify required API keys, MCP server, and PubMed availability.

    Returns:
        Tuple of (mcp_ok, pubmed_ok) if the run may proceed, or None if a
        critical error should abort it.
    """
    console.print("[yellow]Checking prerequisites...[/yellow]\n")

    errors, warnings, mcp_ok, pubmed_ok = await _gather_prereqs()
    if not _report_prerequisite_issues(errors, warnings):
        return None

    return mcp_ok, pubmed_ok


def _render_queries_table(queries: list[str]) -> None:
    """Print a table of the search queries generated.

    Args:
        queries: search queries returned by the literature review node.
    """
    query_table = Table(title="Search queries generated")
    query_table.add_column("Query", style="cyan")
    for q in queries:
        query_table.add_row(q)
    console.print(query_table)


def _render_articles_table(articles: list[Article]) -> None:
    """Print a table of the first 10 articles found.

    Args:
        articles: articles returned by the literature review node.
    """
    article_table = Table(title=f"Articles found ({len(articles)} total)")
    article_table.add_column("Title", style="cyan", max_width=50)
    article_table.add_column("Year", style="yellow")
    article_table.add_column("Citations", style="green")

    for article in articles[:10]:  # Show first 10
        article_table.add_row(
            article.title[:50] + "..."
            if len(article.title) > 50
            else article.title,
            str(article.year) if article.year else "n/a",
            str(article.citations) if article.citations else "n/a",
        )

    console.print(article_table)


def _print_summary_panel(summary: str) -> None:
    """Print the literature review summary, truncated to 500 chars.

    Args:
        summary: literature review summary text.
    """
    console.print(
        Panel(
            summary[:500] + "..." if len(summary) > 500 else summary,
            title="[bold green]Literature review summary"
            " (first 500 chars)[/bold green]",
            border_style="green",
        )
    )


def _print_review_stats(
    queries: list[str], articles: list[Article], summary: str
) -> None:
    """Print aggregate literature review stats.

    Args:
        queries: search queries returned by the literature review node.
        articles: articles returned by the literature review node.
        summary: literature review summary text.
    """
    console.print("\n[bold]Summary stats:[/bold]")
    console.print(f"  Queries generated: {len(queries)}")
    console.print(f"  Articles found: {len(articles)}")
    console.print(f"  Summary length: {len(summary)} chars")
    console.print(f"  Articles with reasoning available: {bool(summary)}")


def _display_literature_results(
    articles: list[Article], queries: list[str], summary: str
) -> None:
    """Print the article breakdown, tables, summary, and stats.

    Args:
        articles: articles returned by the literature review node.
        queries: search queries returned by the literature review node.
        summary: literature review summary text.
    """
    # Show article breakdown by source (PubMed-only now)
    pm_articles = [a for a in articles if a.source == "pubmed"]
    console.print("\n[bold yellow]Article breakdown:[/bold yellow]")
    console.print(f"  PubMed: {len(pm_articles)} total")

    _render_queries_table(queries)
    _render_articles_table(articles)
    _print_summary_panel(summary)
    _print_review_stats(queries, articles, summary)


async def test_literature_review() -> None:
    """Run literature review node with minimal state."""
    console.print("\n[bold cyan]Testing literature review node[/bold cyan]\n")

    prerequisites = await _check_prerequisites()
    if prerequisites is None:
        return
    mcp_ok, pubmed_ok = prerequisites

    dev_mode = os.getenv("COSCIENTIST_DEV_MODE", "").lower() == "true"
    if dev_mode:
        console.print(
            "\n[yellow]Dev mode enabled - using reduced paper counts[/yellow]"
        )

    # Create minimal state
    state = make_base_state(
        research_goal=DEFAULT_RESEARCH_GOAL,
        model_name=DEFAULT_MODEL_NAME,
    )
    state["mcp_available"] = mcp_ok
    state["pubmed_available"] = pubmed_ok

    console.print(
        f"\n[yellow]Research goal:[/yellow] {state['research_goal']}\n"
    )

    # Run node
    console.print(
        "[yellow]Calling literature review node"
        " (this may take a couple of minutes)...[/yellow]\n"
    )
    result = await literature_review_node(state)

    # Display results
    articles = result.get("articles", [])
    queries = result.get("literature_review_queries", [])
    summary = result.get("articles_with_reasoning", "")

    # Check if literature review failed
    if summary == LITERATURE_REVIEW_FAILED:
        console.print("\n[bold red]Literature review failed![/bold red]")
        console.print(
            "[yellow]The system will fall back to standard generation"
            " without literature context[/yellow]"
        )
        return

    _display_literature_results(articles, queries, summary)


def main(argv: Sequence[str]) -> None:
    del argv  # Unused.
    asyncio.run(test_literature_review())


if __name__ == "__main__":
    app.run(main)
