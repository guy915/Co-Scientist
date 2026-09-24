"""Admission for campaign calls to a qualified reference MCP deployment."""

import copy
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from co_scientist.llm_free_policy import campaign_free_mode
from co_scientist.mcp_client_helpers import (
    MCP_AUTH_HEADER,
    MCP_CAMPAIGN_HEADER,
    MCP_SHARED_SECRET_ENV,
)

POLICY = "coscientist-public-retrieval-v1"
# Protocol surface implemented by the independently packaged reference server.
PUBLIC_TOOLS = frozenset(
    {
        "check_pubmed_available",
        "search_pubmed",
        "pubmed_search_with_fulltext",
        "search_openalex",
        "get_opencitations_citation_edges",
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
        "search_gwas_catalog_associations",
    }
)
_M10_PUBLIC_TOOLS = PUBLIC_TOOLS - {"search_gwas_catalog_associations"}
_PRE_CITATION_ROLLBACK_TOOLS = _M10_PUBLIC_TOOLS - {
    "get_opencitations_citation_edges"
}


def _qualified_url(configs: dict[str, dict[str, Any]]) -> str:
    expected = os.getenv("COSCIENTIST_CAMPAIGN_MCP_URL", "")
    if not expected or len(configs) != 1:
        raise RuntimeError(
            "campaign MCP requires one explicitly qualified endpoint"
        )
    config = next(iter(configs.values()))
    secret = os.getenv(MCP_SHARED_SECRET_ENV)
    if not secret:
        raise RuntimeError("campaign MCP requires shared-secret authentication")
    headers = {
        MCP_AUTH_HEADER: secret,
        MCP_CAMPAIGN_HEADER: "1",
    }
    if (
        set(config) - {"transport", "url", "headers"}
        or config.get("transport") != "streamable_http"
        or config.get("url") != expected
        or (config.get("headers") or {}) != headers
    ):
        raise RuntimeError("campaign MCP configuration is not qualified")
    url = urlsplit(expected)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != "/mcp"
    ):
        raise RuntimeError("campaign MCP endpoint must be a plain /mcp URL")
    return expected


def campaign_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    """Prevent redirects and proxies from changing the qualified route."""
    del follow_redirects
    if auth is not None:
        raise RuntimeError("campaign MCP custom authentication is unavailable")
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout or httpx.Timeout(30),
        follow_redirects=False,
        trust_env=False,
    )


class CampaignAdmission:
    """Bind tools to one configuration and recheck its serving policy."""

    def __init__(self, configs: dict[str, dict[str, Any]]) -> None:
        """Snapshot the qualified configuration before discovery."""
        self.configs = copy.deepcopy(configs)
        self.url = _qualified_url(configs)

    async def verify(self, configs: dict[str, dict[str, Any]]) -> None:
        """Require the bound route and a current reference-server policy."""
        if configs != self.configs or _qualified_url(configs) != self.url:
            raise RuntimeError(
                "campaign MCP binding changed; initialize a new client"
            )
        url = urlsplit(self.url)
        root = urlunsplit((url.scheme, url.netloc, "/", "", ""))
        headers = next(iter(self.configs.values())).get("headers")
        async with campaign_http_client(headers=headers) as client:
            response = await client.get(root)
            response.raise_for_status()
            data = response.json()
        expected_policy = {
            "version": POLICY,
            "enabled": True,
            "anonymous_openalex": True,
        }
        # M10 added citation edges; M11 added GWAS after it. Accept those
        # exact rollout states plus the known pre-citation rollback target.
        # Reject hybrids and every unreviewed tool addition.
        accepted_policies = [
            {**expected_policy, "tools": sorted(tools)}
            for tools in (
                PUBLIC_TOOLS,
                _M10_PUBLIC_TOOLS,
                _PRE_CITATION_ROLLBACK_TOOLS,
            )
        ]
        if (
            not isinstance(data, dict)
            or data.get("campaign_policy") not in accepted_policies
            or data.get("service") != "coscientist-lit-review"
        ):
            raise RuntimeError(
                "campaign MCP server policy is unavailable or unqualified"
            )

    async def require_tool(
        self, name: str, configs: dict[str, dict[str, Any]]
    ) -> None:
        """Admit only reviewed tools on the qualified serving deployment."""
        if name not in PUBLIC_TOOLS:
            raise RuntimeError("tool is unavailable under campaign MCP policy")
        await self.verify(configs)

    def transport_configs(self) -> dict[str, dict[str, Any]]:
        """Use the fixed transport factory for the captured configuration."""
        return {
            name: {**config, "httpx_client_factory": campaign_http_client}
            for name, config in copy.deepcopy(self.configs).items()
        }


def require_bound_mode(admission: CampaignAdmission | None) -> None:
    """Reject clients discovered before campaign qualification."""
    if campaign_free_mode() and admission is None:
        raise RuntimeError(
            "campaign MCP client was not qualified at initialization"
        )


async def prepare_admission(
    configs: dict[str, dict[str, Any]],
) -> CampaignAdmission | None:
    """Qualify campaign transport before the MCP SDK opens a connection."""
    if not campaign_free_mode():
        return None
    admission = CampaignAdmission(configs)
    await admission.verify(configs)
    return admission
