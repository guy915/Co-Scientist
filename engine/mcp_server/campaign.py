"""Campaign cost policy for the independently packaged reference server."""

import os


def campaign_free_mode() -> bool:
    """Read the same strict mode contract as the engine without importing it."""
    configured = (
        os.getenv("COSCIENTIST_REQUIRE_FREE_MODELS", "0").strip().lower()
    )
    if configured not in {"0", "false", "", "1", "true"}:
        raise RuntimeError("zero-cost campaign mode setting is invalid")
    return configured in {"1", "true"}


def require_metered_search_allowed() -> None:
    """Refuse account-backed search before any request or fallback."""
    if campaign_free_mode():
        raise RuntimeError("metered web search is unavailable in campaign mode")


POLICY = "coscientist-public-retrieval-v1"
# Protocol surface implemented by the independently packaged reference server.
PUBLIC_TOOLS = frozenset(
    {
        "check_pubmed_available",
        "search_pubmed",
        "pubmed_search_with_fulltext",
        "search_openalex",
        "search_chembl",
        "search_uniprot",
        "search_string_interactions",
        "search_reactome_pathways",
        "search_open_targets",
        "search_europepmc",
        "search_preprints",
        "search_arxiv",
        "search_biorxiv",
        "search_ensembl_gene",
        "search_gnomad_constraint",
        "search_clinical_trials",
    }
)


def campaign_policy() -> dict[str, object]:
    """Describe the campaign contract without exposing credentials."""
    return {
        "version": POLICY,
        "enabled": campaign_free_mode(),
        "anonymous_openalex": True,
        "tools": sorted(PUBLIC_TOOLS),
    }


def require_tool_allowed(name: str) -> None:
    """Check registered calls even when mode changed after tool registration."""
    if campaign_free_mode() and name not in PUBLIC_TOOLS:
        raise RuntimeError("tool is unavailable under campaign MCP policy")
